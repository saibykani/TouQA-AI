from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Job, SyncEntityResult, User
from app.schemas.api import JobOut, SyncStartIn
from app.security.auth import current_user, require_writer
from app.services import jobs, sync
from app.api.v1.projects import get_project

router = APIRouter(tags=["jobs"])


def _job_or_404(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


def start_sync(db: Session, project_id: int, entities: list[str] | None, options: dict, user_id: int) -> Job:
    project = get_project(db, project_id)
    if project.is_demo:
        raise HTTPException(409, "The synthetic demo project cannot be synchronised with Spira.")
    running = db.query(Job).filter(Job.kind == "sync", Job.project_id == project_id, Job.status.in_(["QUEUED", "RUNNING"])).first()
    if running:
        raise HTTPException(409, f"A sync is already running for this project (job {running.id}).")
    ents = [e for e in sync.ENTITY_ORDER if e in (entities or sync.ENTITY_ORDER)]
    job = jobs.create_job(db, "sync", project_id=project_id, params={"entities": ents, "options": options},
                          user_id=user_id, message="Queued")
    sync.create_entity_rows(db, job.id, ents)
    jobs.submit(job.id, sync.run_sync)
    return job


@router.post("/sync/jobs", response_model=JobOut)
def create_sync(body: SyncStartIn, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    job = start_sync(db, body.project_id, body.entities, body.options.model_dump(), user.id)
    db.refresh(job)
    return jobs.job_to_dict(job)


@router.get("/sync/jobs")
def list_syncs(project_id: int | None = None, page: int = 1, page_size: int = 20,
               db: Session = Depends(get_db), _: User = Depends(current_user)):
    q = db.query(Job).filter(Job.kind == "sync")
    if project_id:
        q = q.filter(Job.project_id == project_id)
    total = q.count()
    rows = q.order_by(Job.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [{**jobs.job_to_dict(j), "entities": entity_rows(db, j.id)} for j in rows],
            "total": total, "page": page, "page_size": page_size}


def entity_rows(db: Session, job_id: int) -> list[dict]:
    rows = db.query(SyncEntityResult).filter_by(job_id=job_id).all()
    order = {e: i for i, e in enumerate(sync.ENTITY_ORDER)}
    return [{"entity_type": r.entity_type, "status": r.status, "discovered": r.discovered, "imported": r.imported,
             "created": r.created, "updated": r.updated, "skipped": r.skipped, "failed": r.failed,
             "errors": r.errors, "notes": r.notes, "started_at": r.started_at, "finished_at": r.finished_at}
            for r in sorted(rows, key=lambda r: order.get(r.entity_type, 99))]


@router.get("/sync/jobs/{job_id}")
def sync_detail(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    job = _job_or_404(db, job_id)
    return {**jobs.job_to_dict(job), "entities": entity_rows(db, job_id)}


@router.post("/sync/jobs/{job_id}/retry", response_model=JobOut)
def retry_sync(job_id: int, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    """Re-run only the entities that failed or were partial/cancelled."""
    job = _job_or_404(db, job_id)
    failed = [r["entity_type"] for r in entity_rows(db, job_id) if r["status"] not in ("COMPLETED",)]
    if not failed:
        raise HTTPException(409, "Nothing to retry: all entities completed.")
    new = start_sync(db, job.project_id, failed, job.params.get("options") or {}, user.id)
    db.refresh(new)
    return jobs.job_to_dict(new)


@router.get("/jobs")
def list_jobs(project_id: int | None = None, status: str | None = None, active: bool = False, limit: int = 30,
              db: Session = Depends(get_db), _: User = Depends(current_user)):
    q = db.query(Job)
    if project_id:
        q = q.filter(Job.project_id == project_id)
    if status:
        q = q.filter(Job.status == status)
    if active:
        q = q.filter(Job.status.in_(["QUEUED", "RUNNING"]))
    return [jobs.job_to_dict(j) for j in q.order_by(Job.created_at.desc()).limit(min(limit, 200))]


@router.get("/jobs/{job_id}", response_model=JobOut)
def job_detail(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return jobs.job_to_dict(_job_or_404(db, job_id))


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: int, db: Session = Depends(get_db), _: User = Depends(require_writer)):
    return jobs.job_to_dict(jobs.request_cancel(db, _job_or_404(db, job_id)))


