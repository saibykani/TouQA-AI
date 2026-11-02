"""Canonical ↔ external value mapping.

Resolution order: explicit FieldMapping row → unambiguous name match against values
discovered from the external project → unresolved. Unresolved values are reported to the
user; an external ID is never guessed.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models import FieldMapping, ProjectMetadata

# field -> ProjectMetadata.kind (Spira)
SPIRA_FIELD_KINDS = {
    "test_case_priority": "test_case_priority", "test_case_status": "test_case_status",
    "test_case_type": "test_case_type", "incident_priority": "incident_priority",
    "incident_severity": "incident_severity", "incident_type": "incident_type",
    "incident_status": "incident_status", "owner": "user", "component": "component",
}
CANONICAL_VALUES = {
    "test_case_priority": ["critical", "high", "medium", "low"],
    "incident_priority": ["critical", "high", "medium", "low"],
    "incident_severity": ["critical", "high", "medium", "low"],
    "priority": ["critical", "high", "medium", "low"],
}
SYNONYMS = {
    "critical": ["critical", "blocker", "highest", "urgent", "1"],
    "high": ["high", "major", "2"],
    "medium": ["medium", "normal", "moderate", "3"],
    "low": ["low", "minor", "trivial", "lowest", "4"],
}


def _words(name: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", name.lower()))


def allowed_values(db: Session, project_id: int, field: str) -> list[dict]:
    kind = SPIRA_FIELD_KINDS.get(field, field)
    rows = db.query(ProjectMetadata).filter_by(project_id=project_id, kind=kind, active=True).order_by(ProjectMetadata.name).all()
    return [{"id": r.external_id, "name": r.name, "data": r.data} for r in rows]


def resolve(db: Session, platform: str, project_id: int, field: str, canonical: str | None,
            values: list[dict] | None = None) -> dict:
    """Return {"id", "name", "source"} with id None when unresolved."""
    if canonical in (None, "", "unknown"):
        return {"id": None, "name": None, "source": "unset", "canonical": canonical}
    m = db.query(FieldMapping).filter_by(platform=platform, project_id=project_id, field=field,
                                         canonical_value=str(canonical).lower()).one_or_none()
    if m and m.external_value_id:
        return {"id": m.external_value_id, "name": m.external_value_name, "source": "mapping", "canonical": canonical}
    options = values if values is not None else allowed_values(db, project_id, field)
    c = str(canonical).lower()
    exact = [o for o in options if o["name"].strip().lower() == c]
    if len(exact) == 1:
        return {"id": exact[0]["id"], "name": exact[0]["name"], "source": "name_match", "canonical": canonical}
    syn = SYNONYMS.get(c)
    if syn:
        hits = [o for o in options if _words(o["name"]) & set(syn)]
        # Disambiguate e.g. "1 - Critical" vs "2 - High" by preferring the non-numeric synonym match
        word_hits = [o for o in hits if _words(o["name"]) & {s for s in syn if not s.isdigit()}]
        pick = word_hits if word_hits else hits
        if len(pick) == 1:
            return {"id": pick[0]["id"], "name": pick[0]["name"], "source": "name_match", "canonical": canonical}
    return {"id": None, "name": None, "source": "unresolved", "canonical": canonical,
            "allowed": [o["name"] for o in options][:50]}


def set_mapping(db: Session, platform: str, project_id: int, field: str, canonical: str,
                external_id: str | None, external_name: str | None) -> FieldMapping:
    m = db.query(FieldMapping).filter_by(platform=platform, project_id=project_id, field=field,
                                         canonical_value=canonical.lower()).one_or_none()
    if m is None:
        m = FieldMapping(platform=platform, project_id=project_id, field=field, canonical_value=canonical.lower())
        db.add(m)
    m.external_value_id, m.external_value_name = external_id, external_name
    db.commit()
    return m


def list_mappings(db: Session, project_id: int, platform: str | None = None) -> list[dict]:
    q = db.query(FieldMapping).filter_by(project_id=project_id)
    if platform:
        q = q.filter_by(platform=platform)
    return [{"id": m.id, "platform": m.platform, "field": m.field, "canonical_value": m.canonical_value,
             "external_value_id": m.external_value_id, "external_value_name": m.external_value_name} for m in q]
