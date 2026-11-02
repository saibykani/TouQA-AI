from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuditLog
from app.security.redaction import redact, redact_text

log = logging.getLogger("touqa.audit")


def record(
    db: Session,
    *,
    action: str,
    category: str,
    outcome: str,
    summary: str = "",
    user_id: int | None = None,
    project_id: int | None = None,
    entity_type: str | None = None,
    entity_id: Any = None,
    platform: str | None = None,
    details: dict | None = None,
    commit: bool = False,
) -> AuditLog:
    entry = AuditLog(
        action=action, category=category, outcome=outcome, summary=redact_text(summary)[:4000],
        user_id=user_id, project_id=project_id, entity_type=entity_type,
        entity_id=None if entity_id is None else str(entity_id), platform=platform,
        details=redact(details or {}), is_demo=get_settings().demo_mode,
    )
    db.add(entry)
    if commit:
        db.commit()
    log.info("audit %s %s %s %s", category, action, outcome, entry.entity_id or "")
    return entry
