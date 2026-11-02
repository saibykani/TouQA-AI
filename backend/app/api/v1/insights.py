from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuditLog, User
from app.security.auth import current_user
from app.services import dashboard

router = APIRouter(tags=["insights"])


@router.get("/dashboard")
def get_dashboard(project_id: int | None = None, days: int = 30, release: str | None = None,
                  db: Session = Depends(get_db), _: User = Depends(current_user)):
    return dashboard.metrics(db, project_id, days=max(1, min(days, 365)), release_external_id=release)


@router.get("/audit")
def audit_log(project_id: int | None = None, category: str | None = None, outcome: str | None = None,
              platform: str | None = None, q: str | None = None, since: datetime | None = None, until: datetime | None = None,
              page: int = 1, page_size: int = 50, db: Session = Depends(get_db), _: User = Depends(current_user)):
    query = db.query(AuditLog)
    if project_id:
        query = query.filter(or_(AuditLog.project_id == project_id, AuditLog.project_id.is_(None)))
    for col, val in ((AuditLog.category, category), (AuditLog.outcome, outcome), (AuditLog.platform, platform)):
        if val:
            query = query.filter(col == val)
    if q:
        query = query.filter(or_(AuditLog.summary.ilike(f"%{q}%"), AuditLog.action.ilike(f"%{q}%")))
    if since:
        query = query.filter(AuditLog.created_at >= since)
    if until:
        query = query.filter(AuditLog.created_at <= until)
    page_size = max(1, min(page_size, 200))
    total = query.count()
    rows = query.order_by(AuditLog.created_at.desc()).offset((max(1, page) - 1) * page_size).limit(page_size).all()
    users = {u.id: u.email for u in db.query(User)}
    return {"items": [{"id": a.id, "created_at": a.created_at, "user": users.get(a.user_id), "project_id": a.project_id,
                       "action": a.action, "category": a.category, "entity_type": a.entity_type, "entity_id": a.entity_id,
                       "platform": a.platform, "outcome": a.outcome, "summary": a.summary, "details": a.details,
                       "is_demo": a.is_demo} for a in rows],
            "total": total, "page": page, "page_size": page_size}
