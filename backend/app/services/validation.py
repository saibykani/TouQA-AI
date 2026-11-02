"""Deterministic validation of AI-generated (and user-edited) drafts before review/submission."""
from __future__ import annotations

import re

from pydantic import ValidationError

from app.ai.schemas import GeneratedTestCase, IncidentDraftContent

VAGUE_PATTERNS = [
    r"^\s*verify (that )?(the )?(system|application|app|it|feature) (works|is working|behaves)\b",
    r"^\s*(check|ensure|verify) (that )?(everything|it) (works|is (fine|ok|correct))",
    r"^\s*(works|working) (as expected|correctly|fine)\.?\s*$",
    r"^\s*as expected\.?\s*$",
    r"^\s*(ok|pass|passes|success|successful)\.?\s*$",
    r"^\s*(the )?(system|application) (works|behaves) (correctly|as expected|properly)\.?\s*$",
]
_VAGUE = [re.compile(p, re.IGNORECASE) for p in VAGUE_PATTERNS]
SPIRA_NAME_MAX = 255


def is_vague(text: str) -> bool:
    return any(p.search(text or "") for p in _VAGUE)


def issue(field: str, message: str, severity: str = "error") -> dict:
    return {"field": field, "message": message, "severity": severity}


def validate_test_case(content: dict, *, allowed_requirement_ids: set[str] | None = None,
                       known_criterion_ids: set[str] | None = None) -> tuple[dict, list[dict]]:
    """Returns (normalised_content, issues). Errors block submission; warnings need review."""
    issues: list[dict] = []
    try:
        tc = GeneratedTestCase.model_validate(content)
    except ValidationError as exc:
        return content, [issue(".".join(map(str, e["loc"])) or "content", e["msg"]) for e in exc.errors()]

    data = tc.model_dump()
    if not tc.name.strip():
        issues.append(issue("name", "Name is required."))
    elif len(tc.name) > SPIRA_NAME_MAX:
        issues.append(issue("name", f"Name exceeds {SPIRA_NAME_MAX} characters."))
    if not tc.steps:
        issues.append(issue("steps", "At least one test step is required."))
    # Renumber steps sequentially so positions are always 1..n
    for i, step in enumerate(data["steps"], 1):
        step["step_number"] = i
        if not step["action"].strip():
            issues.append(issue(f"steps.{i}.action", f"Step {i} has no action."))
        elif is_vague(step["action"]):
            issues.append(issue(f"steps.{i}.action", f"Step {i} action is vague; describe a concrete action.", "warning"))
        if not step["expected_result"].strip():
            issues.append(issue(f"steps.{i}.expected_result", f"Step {i} has no expected result."))
        elif is_vague(step["expected_result"]):
            issues.append(issue(f"steps.{i}.expected_result",
                                f"Step {i} expected result is not verifiable; state the observable outcome."))
    if allowed_requirement_ids is not None and tc.requirement_id not in allowed_requirement_ids:
        issues.append(issue("requirement_id", f"Requirement '{tc.requirement_id}' is not one of the selected requirements."))
    if known_criterion_ids is not None:
        unknown = [c for c in tc.acceptance_criterion_ids if c not in known_criterion_ids]
        if unknown:
            issues.append(issue("acceptance_criterion_ids",
                                f"Unknown acceptance criterion reference(s): {', '.join(unknown)}.", "warning"))
    if not tc.acceptance_criterion_ids:
        issues.append(issue("acceptance_criterion_ids", "No acceptance criterion referenced (traceability gap).", "warning"))
    if tc.confidence == "low":
        issues.append(issue("confidence", "Model reported low confidence; review carefully.", "warning"))
    return data, issues


def has_errors(issues: list[dict]) -> bool:
    return any(i["severity"] == "error" for i in issues)


def validate_incident(content: dict) -> tuple[dict, list[dict]]:
    issues: list[dict] = []
    try:
        inc = IncidentDraftContent.model_validate(content)
    except ValidationError as exc:
        return content, [issue(".".join(map(str, e["loc"])) or "content", e["msg"]) for e in exc.errors()]
    if not inc.title.strip():
        issues.append(issue("title", "Title is required."))
    elif len(inc.title) > SPIRA_NAME_MAX:
        issues.append(issue("title", f"Title exceeds {SPIRA_NAME_MAX} characters."))
    if not inc.description.strip() and not inc.actual_result.strip():
        issues.append(issue("description", "Provide a description or actual result."))
    if not inc.steps_to_reproduce:
        issues.append(issue("steps_to_reproduce", "No reproduction steps; the incident may not be reproducible.", "warning"))
    if inc.expected_result.lower().startswith("unknown"):
        issues.append(issue("expected_result", "Expected result is unknown; confirm with the reporter.", "warning"))
    for m in inc.missing_information:
        issues.append(issue("missing_information", f"Missing: {m}", "warning"))
    return inc.model_dump(), issues
