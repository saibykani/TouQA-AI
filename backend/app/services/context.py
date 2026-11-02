"""Build grounded AI context from locally synchronised records."""
from __future__ import annotations

import re

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import Incident, Project, ProjectMetadata, Requirement, RequirementTestCase, TestCase

_WORD = re.compile(r"[a-z0-9]{3,}")
STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "will", "should", "must", "shall",
    "can", "not", "user", "users", "when", "then", "given", "into", "have", "has", "been", "able", "system",
    "verify", "test", "case", "page", "able", "which", "their", "there", "they", "also", "all", "any",
}


def tokens(text: str | None) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in STOPWORDS}


def _cp_value(cp: dict):
    for key in ("StringValue", "IntegerValue", "DecimalValue", "BooleanValue", "DateTimeValue", "IntegerListValue"):
        v = cp.get(key)
        if v not in (None, "", []):
            return v
    return None


def resolve_custom_properties(db: Session, project_id: int, artifact: str, cps: list) -> list[dict]:
    """Return [{name, value}] for custom properties that have a value. List values resolve to names."""
    defs = {m.external_id: m for m in db.query(ProjectMetadata).filter_by(project_id=project_id, kind=f"custom_property:{artifact}")}
    out = []
    for cp in cps or []:
        if not isinstance(cp, dict):
            continue
        value = _cp_value(cp)
        if value is None:
            continue
        num = str(cp.get("PropertyNumber"))
        d = defs.get(num)
        name = (cp.get("Definition") or {}).get("Name") if isinstance(cp.get("Definition"), dict) else None
        name = name or (d.name if d else f"Custom {num}")
        if d and d.data.get("list_values"):
            lookup = {str(v["id"]): v["name"] for v in d.data["list_values"]}
            if isinstance(value, list):
                value = [lookup.get(str(v), v) for v in value]
            else:
                value = lookup.get(str(value), value)
        if isinstance(value, str):
            from app.integrations.spira.mapper import html_to_text

            value = html_to_text(value) if "<" in value else value
        out.append({"name": name, "value": value})
    return out


def acceptance_criteria_text(db: Session, req: Requirement, project: Project) -> tuple[str | None, str | None]:
    """If the project maps a custom property as 'Acceptance Criteria', return (field_label, text)."""
    field = (project.settings or {}).get("acceptance_criteria_field")
    candidates = resolve_custom_properties(db, project.id, "Requirement", req.custom_properties)
    for cp in candidates:
        if (field and cp["name"].lower() == field.lower()) or (not field and "acceptance" in cp["name"].lower()):
            v = cp["value"]
            return f"custom:{cp['name']}", "\n".join(map(str, v)) if isinstance(v, list) else str(v)
    return None, None


def test_case_summary(tc: TestCase, max_steps: int = 12) -> dict:
    return {
        "external_id": tc.external_id, "name": tc.name, "description": (tc.description_text or "")[:600],
        "steps": [{"n": s.position, "action": s.description[:300], "expected": (s.expected_result or "")[:300]}
                  for s in tc.steps[:max_steps]],
    }


def linked_test_cases(db: Session, req: Requirement) -> list[TestCase]:
    ext_ids = [l.test_case_external_id for l in db.query(RequirementTestCase).filter_by(
        project_id=req.project_id, requirement_external_id=req.external_id)]
    if not ext_ids:
        return []
    return db.query(TestCase).filter(TestCase.project_id == req.project_id, TestCase.external_id.in_(ext_ids)).all()


def related_incidents(db: Session, req: Requirement, limit: int = 5) -> list[dict]:
    """Incidents that explicitly reference the requirement ID, then keyword-similar ones (labelled)."""
    marker = f"RQ:{req.external_id}"
    explicit = db.query(Incident).filter(Incident.project_id == req.project_id, or_(
        Incident.description_text.contains(marker), Incident.name.contains(marker))).limit(limit).all()
    out = [{"external_id": i.external_id, "name": i.name, "status": i.status_name,
            "relation": "explicit reference", "description": (i.description_text or "")[:500]} for i in explicit]
    if len(out) < limit:
        rt = tokens(f"{req.name} {req.description_text}")
        if rt:
            scored = []
            for i in db.query(Incident).filter(Incident.project_id == req.project_id, Incident.is_deleted_externally.is_(False)).limit(2000):
                if any(o["external_id"] == i.external_id for o in out):
                    continue
                it = tokens(f"{i.name} {(i.description_text or '')[:1000]}")
                if not it:
                    continue
                score = len(rt & it) / max(1, len(rt | it))
                if score >= 0.12:
                    scored.append((score, i))
            for score, i in sorted(scored, key=lambda x: -x[0])[: limit - len(out)]:
                out.append({"external_id": i.external_id, "name": i.name, "status": i.status_name,
                            "relation": f"keyword similarity {score:.2f} (possibly related)",
                            "description": (i.description_text or "")[:400]})
    return out


def similar_test_cases(db: Session, project_id: int, text: str, exclude: set[str], limit: int = 15) -> list[TestCase]:
    qt = tokens(text)
    if not qt:
        return []
    scored = []
    for tc in db.query(TestCase).filter(TestCase.project_id == project_id, TestCase.is_deleted_externally.is_(False)).limit(5000):
        if tc.external_id in exclude:
            continue
        t = tokens(f"{tc.name} {(tc.description_text or '')[:500]}")
        if not t:
            continue
        score = len(qt & t) / max(1, len(qt | t))
        if score >= 0.08:
            scored.append((score, tc))
    return [tc for _, tc in sorted(scored, key=lambda x: -x[0])[:limit]]


def requirement_context(db: Session, req: Requirement) -> dict:
    project = db.get(Project, req.project_id)
    ac_field, ac_text = acceptance_criteria_text(db, req, project)
    parent = db.get(Requirement, req.parent_id) if req.parent_id else None
    children = db.query(Requirement).filter_by(parent_id=req.id).limit(30).all()
    linked = linked_test_cases(db, req)
    conventions = [tc.name for tc in db.query(TestCase).filter_by(project_id=req.project_id)
                   .order_by(TestCase.external_updated_at.desc().nullslast()).limit(8)]
    return {
        "requirement": {
            "external_id": req.external_id, "name": req.name,
            "description": (req.description_text or "")[:12000],
            "acceptance_criteria_field": ac_field, "acceptance_criteria_text": ac_text,
            "type": req.type_name, "status": req.status_name, "importance": req.importance_name,
            "release": req.release_version, "owner": req.owner_name, "tags": req.tags,
            "steps": req.steps or [],
            "custom_properties": resolve_custom_properties(db, req.project_id, "Requirement", req.custom_properties),
        },
        "parent": {"external_id": parent.external_id, "name": parent.name,
                   "description": (parent.description_text or "")[:3000]} if parent else None,
        "children": [{"external_id": c.external_id, "name": c.name} for c in children],
        "linked_test_cases": [test_case_summary(tc) for tc in linked[:25]],
        "related_incidents": related_incidents(db, req),
        "project": {"name": project.name, "existing_test_case_name_examples": conventions},
        "unsupported_or_missing": [k for k, v in {
            "description": req.description_text, "acceptance_criteria_custom_field": ac_text}.items() if not v],
    }
