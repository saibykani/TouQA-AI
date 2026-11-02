"""Dashboard metrics. Every number is computed from stored rows; nothing is estimated."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    ApiOperation, AuditLog, IncidentDraft, Incident, IntegrationConfig, Job, Project, Requirement,
    RequirementTestCase, SyncEntityResult, TestCase, TestCaseDraft, TestSet,
)


def _range(days: int) -> tuple[datetime, datetime]:
    end = datetime.now(timezone.utc)
    return end - timedelta(days=days), end


def metrics(db: Session, project_id: int | None, *, days: int = 30, release_external_id: str | None = None) -> dict:
    start, end = _range(days)
    proj = db.get(Project, project_id) if project_id else None

    def scoped(q, model):
        if project_id:
            q = q.filter(model.project_id == project_id)
        return q

    req_q = scoped(db.query(Requirement), Requirement).filter(Requirement.is_deleted_externally.is_(False))
    if release_external_id:
        req_q = req_q.filter(Requirement.release_external_id == release_external_id)
    total_reqs = req_q.count()
    leaf_reqs = req_q.filter(Requirement.is_summary.is_(False))
    leaf_count = leaf_reqs.count()
    covered = 0
    if project_id and leaf_count:
        linked = {r for (r,) in db.query(RequirementTestCase.requirement_external_id).filter_by(project_id=project_id).distinct()}
        covered = sum(1 for (ext,) in leaf_reqs.with_entities(Requirement.external_id) if ext in linked)
    coverage_reliable = False
    if project_id:
        last_req_sync = (db.query(SyncEntityResult).join(Job, Job.id == SyncEntityResult.job_id)
                         .filter(Job.project_id == project_id, SyncEntityResult.entity_type == "requirements",
                                 SyncEntityResult.status == "COMPLETED")
                         .order_by(SyncEntityResult.finished_at.desc()).first())
        coverage_reliable = bool(last_req_sync) and bool(
            (db.get(Job, last_req_sync.job_id).params.get("options") or {}).get("include_requirement_coverage", True))

    tc_count = scoped(db.query(TestCase), TestCase).filter(TestCase.is_deleted_externally.is_(False)).count()
    ts_q = scoped(db.query(TestSet), TestSet).filter(TestSet.is_deleted_externally.is_(False))
    if release_external_id:
        ts_q = ts_q.filter(TestSet.release_external_id == release_external_id)
    inc_q = scoped(db.query(Incident), Incident).filter(Incident.is_deleted_externally.is_(False))
    if release_external_id:
        inc_q = inc_q.filter(Incident.detected_release_external_id == release_external_id)
    open_incidents = inc_q.filter(Incident.is_open.is_(True)).count()

    drafts_q = scoped(db.query(TestCaseDraft), TestCaseDraft)
    generated = drafts_q.filter(TestCaseDraft.created_at >= start).count()
    pending = drafts_q.filter(TestCaseDraft.status.in_(["draft", "approved"])).count()
    pending_inc = scoped(db.query(IncidentDraft), IncidentDraft).filter(IncidentDraft.status.in_(["draft", "analyzed", "approved"])).count()

    ops_q = scoped(db.query(ApiOperation), ApiOperation).filter(ApiOperation.status == "succeeded", ApiOperation.updated_at >= start)
    tc_created = ops_q.filter(ApiOperation.operation == "create_test_case").count()
    inc_created = ops_q.filter(ApiOperation.operation.in_(["create_incident", "create_issue"])).count()
    failed_jobs = scoped(db.query(Job), Job).filter(Job.status == "FAILED", Job.created_at >= start).count()

    # Trends per day
    trend: dict[str, dict] = defaultdict(lambda: {"generated": 0, "test_cases_created": 0, "incidents_created": 0, "ai_runs": 0})
    for (ts,) in drafts_q.filter(TestCaseDraft.created_at >= start).with_entities(TestCaseDraft.created_at):
        trend[ts.date().isoformat()]["generated"] += 1
    for op, ts in ops_q.with_entities(ApiOperation.operation, ApiOperation.updated_at):
        k = "test_cases_created" if op == "create_test_case" else "incidents_created"
        trend[ts.date().isoformat()][k] += 1
    ai_q = db.query(AuditLog.created_at).filter(AuditLog.category == "ai", AuditLog.created_at >= start)
    if project_id:
        ai_q = ai_q.filter(AuditLog.project_id == project_id)
    for (ts,) in ai_q:
        trend[ts.date().isoformat()]["ai_runs"] += 1
    series = []
    for i in range(days + 1):
        d = (start + timedelta(days=i)).date().isoformat()
        series.append({"date": d, **trend.get(d, {"generated": 0, "test_cases_created": 0, "incidents_created": 0, "ai_runs": 0})})

    status_breakdown = dict(inc_q.with_entities(Incident.status_name, func.count()).group_by(Incident.status_name).all())
    req_status = dict(req_q.with_entities(Requirement.status_name, func.count()).group_by(Requirement.status_name).all())

    recent = db.query(AuditLog).order_by(AuditLog.created_at.desc())
    if project_id:
        recent = recent.filter((AuditLog.project_id == project_id) | (AuditLog.project_id.is_(None)))
    syncs = scoped(db.query(Job), Job).filter(Job.kind == "sync").order_by(Job.created_at.desc()).limit(5).all()
    integrations = {c.platform: {"status": c.status, "last_success_at": c.last_success_at} for c in db.query(IntegrationConfig)}

    return {
        "project": {"id": proj.id, "name": proj.name, "is_demo": proj.is_demo, "last_synced_at": proj.last_synced_at} if proj else None,
        "period_days": days,
        "integrations": integrations,
        "counts": {
            "requirements": total_reqs, "test_cases": tc_count, "test_sets": ts_q.count(), "incidents": inc_q.count(),
            "open_incidents": open_incidents, "test_cases_generated": generated, "test_cases_created": tc_created,
            "incidents_created": inc_created, "pending_drafts": pending, "pending_incident_drafts": pending_inc,
            "failed_jobs": failed_jobs,
        },
        "coverage": {"leaf_requirements": leaf_count, "covered": covered,
                     "percent": round(100 * covered / leaf_count, 1) if leaf_count else None,
                     "reliable": coverage_reliable,
                     "note": None if coverage_reliable else "Coverage links are only reliable after a completed requirements sync with coverage enabled."},
        "incident_status": [{"name": k or "Unknown", "count": v} for k, v in status_breakdown.items()],
        "requirement_status": [{"name": k or "Unknown", "count": v} for k, v in req_status.items()],
        "trend": series,
        "recent_activity": [{"id": a.id, "created_at": a.created_at, "action": a.action, "category": a.category,
                             "outcome": a.outcome, "summary": a.summary, "platform": a.platform} for a in recent.limit(12)],
        "recent_syncs": [{"id": j.id, "status": j.status, "created_at": j.created_at, "finished_at": j.finished_at,
                          "entities": (j.result or {}).get("entities", {})} for j in syncs],
    }
