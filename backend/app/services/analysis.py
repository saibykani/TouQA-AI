"""AI requirement analysis: run, verify grounding, edit, approve, export."""
from __future__ import annotations

import re

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.ai import prompts
from app.ai.schemas import RequirementAnalysisContent
from app.db import utcnow
from app.models import ApprovalEvent, Requirement, RequirementAnalysis
from app.services import audit
from app.services.ai_settings import provider_for
from app.services.context import requirement_context
from app.services.jobs import JobContext

_WS = re.compile(r"\s+")


def _norm(t: str) -> str:
    return _WS.sub(" ", (t or "").strip().lower())


def verify_grounding(content: dict, context: dict) -> dict:
    """Check model claims against the source. Returns a verification report stored with the analysis."""
    req = context["requirement"]
    source = _norm(" ".join(filter(None, [
        req.get("description"), req.get("acceptance_criteria_text"),
        " ".join(s.get("description") or "" for s in req.get("steps") or []),
        " ".join(str(cp.get("value")) for cp in req.get("custom_properties") or []),
        (context.get("parent") or {}).get("description"),
    ])))
    unverified, fixed_ids = [], []
    for ac in content.get("acceptance_criteria", []):
        if ac.get("origin") == "imported":
            q = _norm(ac.get("source_quote", ""))
            if not q or q not in source:
                # Allow minor punctuation differences: compare alphanumerics only
                strip = lambda s: re.sub(r"[^a-z0-9 ]", "", s)  # noqa: E731
                if not q or strip(q) not in strip(source):
                    unverified.append(ac.get("id"))
    linked = {str(t["external_id"]) for t in context.get("linked_test_cases", [])}
    for row in content.get("coverage_matrix", []):
        bad = [i for i in row.get("existing_test_case_ids", []) if str(i) not in linked]
        if bad:
            row["existing_test_case_ids"] = [i for i in row["existing_test_case_ids"] if str(i) in linked]
            fixed_ids.extend(bad)
    id_ok = str(content.get("requirement_id")) == str(req.get("external_id"))
    if not id_ok:
        content["requirement_id"] = str(req.get("external_id"))
    return {
        "unverified_criteria": unverified,
        "removed_unknown_test_case_ids": sorted(set(map(str, fixed_ids))),
        "requirement_id_corrected": not id_ok,
        "missing_source_fields": context.get("unsupported_or_missing", []),
    }


def run_analysis(ctx: JobContext) -> dict:
    db = ctx.db
    job = ctx.job
    req = db.get(Requirement, job.params["requirement_id"])
    ctx.progress(10, "Collecting requirement context…")
    context = requirement_context(db, req)
    provider = provider_for(db)
    ctx.progress(30, f"Analysing with {provider.name} ({provider.model})…")
    result = provider.generate(system=prompts.ANALYSIS_SYSTEM, prompt=prompts.analysis_prompt(context),
                               schema=RequirementAnalysisContent, task="analysis", context=context)
    ctx.check_cancelled()
    content = result.output.model_dump()
    verification = verify_grounding(content, context)
    content["_verification"] = verification
    content["_context_summary"] = {
        "linked_test_cases": [t["external_id"] for t in context["linked_test_cases"]],
        "related_incidents": [{"external_id": i["external_id"], "relation": i["relation"]} for i in context["related_incidents"]],
        "parent": (context.get("parent") or {}).get("external_id"),
        "acceptance_criteria_field": context["requirement"].get("acceptance_criteria_field"),
    }
    analysis = RequirementAnalysis(
        requirement_id=req.id, job_id=job.id, status="draft", content=content,
        provider=result.provider, model=result.model, prompt_version=prompts.PROMPT_VERSION,
        is_simulated=result.simulated,
    )
    db.add(analysis)
    audit.record(db, action="ai.requirement_analysis", category="ai", outcome="success", user_id=job.created_by_id,
                 project_id=req.project_id, entity_type="requirement", entity_id=req.external_id,
                 summary=f"Analysed RQ:{req.external_id} with {result.provider}/{result.model}"
                         + (" (simulated)" if result.simulated else ""),
                 details={"usage": result.usage, "verification": verification})
    db.commit()
    return {"_status": "NEEDS_REVIEW", "analysis_id": analysis.id, "simulated": result.simulated}


def update_content(db: Session, analysis: RequirementAnalysis, content: dict, user_id: int | None) -> RequirementAnalysis:
    meta = {k: v for k, v in analysis.content.items() if k.startswith("_")}
    body = {k: v for k, v in content.items() if not k.startswith("_")}
    try:
        validated = RequirementAnalysisContent.model_validate(body).model_dump()
    except ValidationError as exc:
        raise ValueError("; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:10])) from exc
    analysis.content = {**validated, **meta}
    analysis.is_edited = True
    if analysis.status == "approved":
        analysis.status = "draft"  # edits after approval require re-approval
        analysis.approved_at = None
    audit.record(db, action="analysis.edited", category="draft", outcome="success", user_id=user_id,
                 entity_type="requirement_analysis", entity_id=analysis.id, summary="Analysis edited")
    db.commit()
    return analysis


def approve(db: Session, analysis: RequirementAnalysis, user_id: int | None) -> RequirementAnalysis:
    for other in db.query(RequirementAnalysis).filter(
            RequirementAnalysis.requirement_id == analysis.requirement_id, RequirementAnalysis.id != analysis.id,
            RequirementAnalysis.status == "approved"):
        other.status = "superseded"
    analysis.status, analysis.approved_by_id, analysis.approved_at = "approved", user_id, utcnow()
    db.add(ApprovalEvent(user_id=user_id, entity_type="requirement_analysis", entity_id=analysis.id, action="approve"))
    audit.record(db, action="analysis.approved", category="draft", outcome="success", user_id=user_id,
                 entity_type="requirement_analysis", entity_id=analysis.id, summary="Analysis approved")
    db.commit()
    return analysis


def to_markdown(analysis: RequirementAnalysis, req: Requirement) -> str:
    c = analysis.content
    lines = [f"# Requirement analysis — RQ:{req.external_id} {req.name}", "",
             f"*Provider:* {analysis.provider} / {analysis.model}{' (simulated)' if analysis.is_simulated else ''}  ",
             f"*Status:* {analysis.status}  ", f"*Generated:* {analysis.created_at:%Y-%m-%d %H:%M} UTC", "",
             "## Summary", c.get("summary", ""), ""]

    def stmts(title, items):
        if items:
            lines.append(f"## {title}")
            for s in items:
                tag = "" if s.get("basis") == "grounded" else " _(AI inference)_"
                lines.append(f"- {s.get('text')}{tag}")
            lines.append("")

    bo = c.get("business_objective")
    if bo:
        lines += ["## Business objective", bo.get("text", "") + ("" if bo.get("basis") == "grounded" else " _(AI inference)_"), ""]
    for key, title in [("actors", "Actors"), ("dependencies", "Dependencies"), ("functional_behavior", "Functional behaviour"),
                       ("inputs", "Inputs"), ("outputs", "Outputs"), ("business_rules", "Business rules"),
                       ("preconditions", "Preconditions"), ("postconditions", "Postconditions"), ("failure_modes", "Failure modes")]:
        stmts(title, c.get(key))
    if c.get("acceptance_criteria"):
        lines += ["## Acceptance criteria", "| ID | Criterion | Origin | Clarity | Source |", "|---|---|---|---|---|"]
        for ac in c["acceptance_criteria"]:
            lines.append(f"| {ac['id']} | {ac['text']} | {ac['origin']} | {ac['clarity']} | {ac['source_field']} |")
        lines.append("")
    if c.get("gaps"):
        lines.append("## Gaps and ambiguities")
        lines += [f"- **{g['category']}** — {g['description']} _Q: {g['suggested_question']}_" for g in c["gaps"]]
        lines.append("")
    lines += [f"## Testability: {c.get('testability')} · Complexity: {c.get('complexity')}", c.get("testability_rationale", ""), ""]
    if c.get("risks"):
        lines.append("## Risks")
        lines += [f"- [{r['severity']}] {r['kind']}: {r['description']}" for r in c["risks"]]
        lines.append("")
    if c.get("clarification_questions"):
        lines.append("## Questions for the product owner")
        lines += [f"{i}. {q}" for i, q in enumerate(c["clarification_questions"], 1)]
        lines.append("")
    if c.get("coverage_matrix"):
        lines += ["## Coverage matrix", "| Criterion | Status | Existing tests | Proposed objectives |", "|---|---|---|---|"]
        for r in c["coverage_matrix"]:
            lines.append(f"| {r['criterion_id']} | {r['status']} | {', '.join('TC:' + str(x) for x in r['existing_test_case_ids'])} | {', '.join(r['proposed_objective_ids'])} |")
    return "\n".join(lines)
