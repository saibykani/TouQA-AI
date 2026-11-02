"""Idempotent external write bookkeeping shared by test case, folder and incident submission."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ApiOperation
from app.security.redaction import redact


def payload_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def get_or_create(db: Session, key: str, *, platform: str, operation: str, project_id: int | None,
                  entity_type: str | None, entity_id: int | None, job_id: int | None = None,
                  summary: dict | None = None) -> ApiOperation:
    op = db.query(ApiOperation).filter_by(idempotency_key=key).one_or_none()
    if op is not None:
        if job_id:
            op.job_id = job_id
        return op
    op = ApiOperation(idempotency_key=key, platform=platform, operation=operation, project_id=project_id,
                      local_entity_type=entity_type, local_entity_id=entity_id, job_id=job_id,
                      request_summary=redact(summary or {}))
    db.add(op)
    try:
        db.commit()
    except IntegrityError:  # concurrent creation: reuse the winner
        db.rollback()
        op = db.query(ApiOperation).filter_by(idempotency_key=key).one()
    return op


def to_dict(op: ApiOperation) -> dict:
    return {
        "id": op.id, "idempotency_key": op.idempotency_key, "platform": op.platform, "operation": op.operation,
        "status": op.status, "attempts": op.attempts, "external_id": op.external_id, "external_key": op.external_key,
        "external_url": op.external_url, "error": op.error, "response_status": op.response_status,
        "local_entity_type": op.local_entity_type, "local_entity_id": op.local_entity_id,
        "request_summary": op.request_summary, "is_simulated": op.is_simulated,
        "created_at": op.created_at, "updated_at": op.updated_at,
    }
