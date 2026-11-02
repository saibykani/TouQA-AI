"""Duplicate / overlap detection for generated test cases.

Similarity is a weighted combination of title terms, step content and requirement/criterion
overlap. Title similarity alone never classifies a case as a likely duplicate; it is reported
as "title only" so the user can judge.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import RequirementTestCase, TestCase, TestCaseDraft
from app.services.context import tokens

LIKELY = 0.62
POSSIBLE = 0.40


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class Candidate:
    name: str
    title_terms: set[str]
    step_terms: set[str]
    step_list: list[set[str]]
    requirement_id: str | None
    criteria: set[str]


def from_draft_content(c: dict) -> Candidate:
    steps = c.get("steps") or []
    step_list = [tokens(f"{s.get('action', '')} {s.get('expected_result', '')}") for s in steps]
    return Candidate(
        name=c.get("name", ""), title_terms=tokens(f"{c.get('name', '')} {c.get('objective', '')}"),
        step_terms=set().union(*step_list) if step_list else set(), step_list=step_list,
        requirement_id=str(c.get("requirement_id")) if c.get("requirement_id") else None,
        criteria=set(c.get("acceptance_criterion_ids") or []),
    )


def from_test_case(tc: TestCase) -> Candidate:
    step_list = [tokens(f"{s.description} {s.expected_result or ''}") for s in tc.steps]
    return Candidate(
        name=tc.name, title_terms=tokens(f"{tc.name} {(tc.description_text or '')[:300]}"),
        step_terms=set().union(*step_list) if step_list else set(), step_list=step_list,
        requirement_id=None, criteria=set(),
    )


def compare(a: Candidate, b: Candidate, *, b_requirements: set[str] | None = None) -> dict:
    title = _jaccard(a.title_terms, b.title_terms)
    steps = _jaccard(a.step_terms, b.step_terms)
    matched_steps = 0
    for sa in a.step_list:
        if any(_jaccard(sa, sb) >= 0.5 for sb in b.step_list):
            matched_steps += 1
    same_req = bool(a.requirement_id and (a.requirement_id == b.requirement_id or a.requirement_id in (b_requirements or set())))
    crit = _jaccard(a.criteria, b.criteria) if a.criteria and b.criteria else 0.0
    has_steps = bool(a.step_list and b.step_list)
    score = 0.35 * title + (0.45 * steps if has_steps else 0) + 0.2 * (1.0 if same_req else crit)
    if not has_steps:
        score = min(score, 0.55)  # without steps we cannot be confident
    reasons = []
    if title >= 0.3:
        reasons.append(f"titles/objectives share {title:.0%} of key terms")
    if has_steps:
        reasons.append(f"{matched_steps} of {len(a.step_list)} steps have closely matching action/expected text")
    else:
        reasons.append("existing case has no imported steps to compare")
    if same_req:
        reasons.append("both trace to the same requirement")
    if crit:
        reasons.append(f"acceptance criteria overlap {crit:.0%}")
    title_only = title >= 0.5 and (not has_steps or steps < 0.25) and not same_req
    level = "likely" if score >= LIKELY and not title_only else ("possible" if score >= POSSIBLE or title_only else "none")
    return {"score": round(score, 3), "level": level, "title_only": title_only,
            "explanation": "; ".join(reasons) + (" — title similarity only, steps differ; review before removing" if title_only else "")}


def detect_for_batch(db: Session, drafts: list[TestCaseDraft]) -> None:
    """Populate ``duplicate_info`` for each draft against existing test cases and other drafts."""
    if not drafts:
        return
    project_id = drafts[0].project_id
    existing = db.query(TestCase).filter(TestCase.project_id == project_id, TestCase.is_deleted_externally.is_(False)).limit(5000).all()
    links: dict[str, set[str]] = {}
    for l in db.query(RequirementTestCase).filter_by(project_id=project_id):
        links.setdefault(l.test_case_external_id, set()).add(l.requirement_external_id)
    existing_c = [(tc, from_test_case(tc)) for tc in existing]
    draft_c = [(d, from_draft_content(d.content)) for d in drafts]
    for d, dc in draft_c:
        matches = []
        for tc, ec in existing_c:
            if not (dc.title_terms & ec.title_terms) and not (dc.step_terms & ec.step_terms):
                continue
            r = compare(dc, ec, b_requirements=links.get(tc.external_id, set()))
            if r["level"] != "none":
                matches.append({"kind": "existing", "external_id": tc.external_id, "name": tc.name, **r})
        for other, oc in draft_c:
            if other.id == d.id:
                continue
            r = compare(dc, oc)
            if r["level"] != "none":
                matches.append({"kind": "draft", "draft_id": other.id, "name": other.content.get("name"), **r})
        matches.sort(key=lambda m: -m["score"])
        top = matches[:5]
        d.duplicate_info = {
            "checked": True,
            "level": top[0]["level"] if top else "none",
            "matches": top,
        }
