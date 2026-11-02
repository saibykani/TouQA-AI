"""Deterministic, offline 'simulated AI' used in demo mode and automated tests.

It derives output only from the supplied record text using simple heuristics. Results are
always flagged ``simulated=True`` and shown in the UI as simulated. It never fabricates IDs:
it only reuses IDs present in the input context.
"""
from __future__ import annotations

import re

from app.ai import schemas as s
from app.ai.providers import AIResult, LLMProvider

_AC_LINE = re.compile(r"(?i)^\s*(?:[-*•]|\d+[.)]|ac\s*\d+[:.)-]?|given\b|when\b|then\b)?\s*(.*\b(must|should|shall|can|cannot|will|given|when|then)\b.*)$")


def _sentences(text: str) -> list[str]:
    lines = [ln.strip(" -*•\t") for ln in (text or "").splitlines()]
    out: list[str] = []
    for ln in lines:
        if not ln:
            continue
        out.extend(p.strip() for p in re.split(r"(?<=[.!?])\s+", ln) if p.strip())
    return out


def _criteria_from(context: dict) -> list[tuple[str, str]]:
    req = context.get("requirement", {})
    found: list[tuple[str, str]] = []
    for field in ("acceptance_criteria_text", "description"):
        for sent in _sentences(req.get(field) or ""):
            if _AC_LINE.match(sent) and (field, sent) not in found:
                found.append((field, sent))
    for step in req.get("steps") or []:
        if step.get("description"):
            found.append(("steps", step["description"]))
    seen, uniq = set(), []
    for f, t in found:
        if t.lower() not in seen:
            seen.add(t.lower())
            uniq.append((f, t))
    return uniq[:12]


class SimulatedProvider(LLMProvider):
    name = "simulated"
    simulated = True

    def __init__(self):
        super().__init__("touqa-simulated-v1")

    def generate(self, *, system, prompt, schema, images=None, task="", context=None):
        context = context or {}
        builder = {
            s.RequirementAnalysisContent: self._analysis,
            s.GenerationOutput: self._generation,
            s.IncidentDraftContent: self._incident,
            s.ScreenshotAnalysis: self._screenshot,
        }.get(schema)
        if builder is None:
            raise NotImplementedError(f"Simulated provider does not support {schema.__name__}")
        out = builder(context)
        return AIResult(schema.model_validate(out.model_dump()), self.name, self.model, simulated=True)

    # ------------------------------------------------------------------ analysis
    def _analysis(self, ctx: dict) -> s.RequirementAnalysisContent:
        req = ctx.get("requirement", {})
        rid, title = str(req.get("external_id", "")), req.get("name", "")
        crit = _criteria_from(ctx)
        acs = [
            s.AcceptanceCriterion(
                id=f"AC-{i}", text=t, origin="imported", source_field=f, source_quote=t,
                clarity="ambiguous" if re.search(r"(?i)\b(appropriate|quickly|user[- ]friendly|etc|as needed|fast)\b", t) else "clear",
                notes="Simulated extraction: sentence contains modal/BDD keywords.",
            )
            for i, (f, t) in enumerate(crit, 1)
        ]
        gaps: list[s.Gap] = []
        if not acs:
            gaps.append(s.Gap(category="missing_criterion", description="No acceptance criteria could be identified in the record.",
                              related_criteria=[], suggested_question="What are the acceptance criteria for this requirement?"))
        text = " ".join(t for _, t in crit).lower()
        if acs and not re.search(r"error|invalid|fail|reject", text):
            gaps.append(s.Gap(category="error_behavior", description="Error and failure behaviour is not specified.",
                              related_criteria=[a.id for a in acs], suggested_question="What should happen when input is invalid or a dependency fails?"))
        if acs and not re.search(r"\d", text):
            gaps.append(s.Gap(category="boundary_condition", description="No numeric limits or boundaries are stated.",
                              related_criteria=[a.id for a in acs], suggested_question="Are there minimum/maximum values or length limits?"))
        for a in acs:
            if a.clarity == "ambiguous":
                gaps.append(s.Gap(category="ambiguity", description=f"{a.id} uses subjective wording.", related_criteria=[a.id],
                                  suggested_question=f"How should '{a.text[:80]}' be measured?"))
        objectives = []
        for i, a in enumerate(acs, 1):
            objectives.append(s.TestObjective(id=f"TO-{2*i-1}", objective=f"Verify: {a.text}", criterion_ids=[a.id], category="positive", basis="grounded"))
            objectives.append(s.TestObjective(id=f"TO-{2*i}", objective=f"Verify rejection/handling when the condition in {a.id} is not met",
                                              criterion_ids=[a.id], category="negative", basis="inference"))
        linked = [str(t.get("external_id")) for t in ctx.get("linked_test_cases", [])]
        coverage = [
            s.CoverageEntry(
                criterion_id=a.id,
                status="needs_clarification" if a.clarity != "clear" else ("partially_covered" if linked else "not_covered"),
                existing_test_case_ids=linked[:3], proposed_objective_ids=[o.id for o in objectives if a.id in o.criterion_ids],
                rationale="Simulated: linked tests exist but are not mapped to individual criteria." if linked else "Simulated: no linked tests.",
            )
            for a in acs
        ]
        st = lambda t, b="grounded", f="description": s.Statement(text=t, basis=b, source_field=f)  # noqa: E731
        sentences = _sentences(req.get("description") or "")
        return s.RequirementAnalysisContent(
            requirement_id=rid, requirement_title=title,
            summary=(sentences[0] if sentences else title) + " (simulated analysis)",
            business_objective=st(sentences[0] if sentences else f"Deliver: {title}", "inference" if not sentences else "grounded"),
            actors=[st(m, "inference", "n/a") for m in sorted(set(re.findall(r"(?i)\b(user|admin|customer|operator|system)s?\b", req.get("description") or "")))][:4],
            dependencies=[st(f"Parent requirement: {ctx['parent']['name']}", "grounded", "parent")] if ctx.get("parent") else [],
            functional_behavior=[st(t, "grounded", f) for f, t in crit[:6]],
            inputs=[], outputs=[], business_rules=[st(t, "grounded", f) for f, t in crit if re.search(r"(?i)must|shall", t)][:5],
            preconditions=[], postconditions=[],
            acceptance_criteria=acs, gaps=gaps,
            testability="high" if acs and not gaps else ("medium" if acs else "low"),
            testability_rationale=f"{len(acs)} criteria identified; {len(gaps)} gaps found (simulated heuristic).",
            complexity="high" if len(acs) > 6 else ("medium" if len(acs) > 2 else "low"),
            failure_modes=[st(f"Condition in {a.id} is not enforced", "inference", "n/a") for a in acs[:4]],
            risks=[s.Risk(description="Unspecified error handling may lead to inconsistent behaviour", kind="functional", severity="medium", basis="inference")] if gaps else [],
            assumptions=["This analysis was produced by the offline simulated provider, not a language model."],
            clarification_questions=[g.suggested_question for g in gaps],
            test_objectives=objectives, coverage_matrix=coverage,
        )

    # ---------------------------------------------------------------- generation
    def _generation(self, ctx: dict) -> s.GenerationOutput:
        counts: dict = ctx.get("config", {}).get("counts", {}) or {"positive": 2, "negative": 2}
        reqs = ctx.get("requirements", [])
        cases: list[s.GeneratedTestCase] = []
        skipped: list[s.SkippedCategory] = []
        for req in reqs:
            acs = req.get("acceptance_criteria") or [{"id": "AC-1", "text": req.get("name", "requirement behaviour")}]
            for category, n in counts.items():
                n = int(n or 0)
                if n <= 0:
                    continue
                if category in ("accessibility", "concurrency") and not re.search(
                        r"(?i)screen|page|form|button|ui|concurren|simultaneous|parallel", (req.get("description") or "")):
                    skipped.append(s.SkippedCategory(category=category, reason=f"Not applicable to {req.get('external_id')} based on its description (simulated)."))
                    continue
                for i in range(n):
                    ac = acs[i % len(acs)]
                    cases.append(self._case(req, ac, category, i + 1))
        return s.GenerationOutput(test_cases=cases, skipped_categories=skipped,
                                  notes="Generated by the offline simulated provider for demonstration. Review every case.")

    def _case(self, req: dict, ac: dict, category: str, n: int) -> s.GeneratedTestCase:
        ac_text = ac.get("text", "")
        title = req.get("name", "Requirement")
        neg = category in ("negative", "validation", "error_handling", "security")
        verb = {"positive": "succeeds", "negative": "is rejected", "boundary": "is handled at the limit",
                "validation": "shows a validation error", "error_handling": "reports the failure",
                "security": "is denied for an unauthorised user", "data_integrity": "keeps data consistent",
                "integration": "propagates to the dependent system", "regression": "still works after change",
                "concurrency": "is consistent under simultaneous requests", "accessibility": "is operable by keyboard"}.get(category, "behaves as specified")
        steps = [
            s.GeneratedStep(step_number=1, action=f"Open the feature described by requirement {req.get('external_id')} ('{title[:60]}').",
                            expected_result="The feature screen or endpoint is available to the test user.", test_data=""),
            s.GeneratedStep(step_number=2, action=("Provide input that violates: " if neg else "Provide input that satisfies: ") + ac_text[:160],
                            expected_result="The input is accepted for submission." if not neg else "The input is entered without client-side crash.",
                            test_data="Valid data per criterion" if not neg else "Invalid data per criterion"),
            s.GeneratedStep(step_number=3, action="Submit the action.",
                            expected_result=(f"The system rejects the request and displays the specified error for {ac.get('id')}." if neg
                                             else f"The outcome required by {ac.get('id')} is observable."), test_data=""),
        ]
        return s.GeneratedTestCase(
            name=f"[{category}] {title[:70]} - {ac.get('id')} #{n} {verb}"[:200],
            description=f"Simulated {category} scenario for {ac.get('id')}: {ac_text[:200]}",
            requirement_id=str(req.get("external_id")), acceptance_criterion_ids=[ac.get("id", "AC-1")],
            category=category, objective=f"Verify that {ac_text[:150] or title} {verb}.",
            preconditions=["Test user has access to the feature."], test_data=[],
            steps=steps, expected_outcome=f"Behaviour matches {ac.get('id')}.",
            priority="high" if category in ("positive", "security") else "medium",
            risk_level="medium", automation_suitability="medium", automation_rationale="Deterministic inputs and outputs (simulated).",
            tags=[category, "touqa-simulated"], assumptions=["Expected error text is not specified in the requirement."] if neg else [],
            source_references=[f"{req.get('external_id')}:{ac.get('id')}"], confidence="low",
            review_warnings=["Simulated output - replace generic wording with application-specific detail before submission."],
        )

    # ------------------------------------------------------------------ incident
    def _incident(self, ctx: dict) -> s.IncidentDraftContent:
        notes = ctx.get("notes", "") or ""
        env_in = ctx.get("environment", {}) or {}
        sentences = _sentences(notes)
        title = (sentences[0] if sentences else "Untitled incident")[:115]
        env_match = re.search(r"(?i)\b(uat|qa|staging|production|prod|dev)\b", notes)
        steps = [t for t in sentences if re.match(r"(?i)^(when|i |click|open|submit|enter|go to|navigate|select)", t)]
        expected = ctx.get("expected_behavior") or "Unknown - not provided"
        actual = ctx.get("actual_behavior") or (sentences[1] if len(sentences) > 1 else (sentences[0] if sentences else "Unknown"))
        facts = [s.ObservedFact(statement=t, source="user_notes") for t in sentences[:6]]
        for shot in ctx.get("screenshot_findings", []):
            for err in shot.get("displayed_errors", []):
                facts.append(s.ObservedFact(statement=f"Screenshot shows: {err}", source="screenshot"))
        missing = []
        if expected.startswith("Unknown"):
            missing.append("Expected behaviour")
        if not steps:
            missing.append("Exact reproduction steps")
        if not env_in.get("browser"):
            missing.append("Browser and version")
        return s.IncidentDraftContent(
            title=title, summary=title, description=notes.strip()[:4000] or "No description provided.",
            environment=s.EnvironmentInfo(
                environment=env_in.get("environment") or (env_match.group(1).upper() if env_match else "unknown"),
                browser=env_in.get("browser") or "unknown", operating_system=env_in.get("operating_system") or "unknown",
                device=env_in.get("device") or "unknown", application_version=env_in.get("application_version") or "unknown",
                release=env_in.get("release") or "unknown"),
            preconditions=[], steps_to_reproduce=steps or ([sentences[0]] if sentences else []),
            expected_result=expected, actual_result=actual,
            reproducibility="unknown", impact="Impact not stated by the reporter (simulated).",
            severity="unknown", priority="unknown", affected_component="unknown",
            observed_facts=facts, hypotheses=[],
            evidence_summary=[f"{a.get('filename')}" for a in ctx.get("attachments", [])],
            suggested_diagnostics=["Collect application and server logs for the time of the failure."],
            missing_information=missing, clarification_questions=[f"Please provide: {m}" for m in missing],
            related_requirement_ids=[str(x) for x in ctx.get("related_requirement_ids", [])],
            related_test_case_ids=[str(x) for x in ctx.get("related_test_case_ids", [])],
        )

    def _screenshot(self, ctx: dict) -> s.ScreenshotAnalysis:
        return s.ScreenshotAnalysis(
            visible_ui_state="Not analysed: the simulated provider cannot inspect images.",
            displayed_errors=[], validation_messages=[], contextual_details=[],
            uncertainty_notes="Configure a vision-capable AI provider to analyse screenshots.",
        )
