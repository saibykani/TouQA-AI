"""Background job runner.

Jobs are persisted in the ``jobs`` table so status, progress and results survive restarts
and are visible in the UI. Work runs in a bounded thread pool; each job gets its own DB
session. Cancellation is cooperative: workers call ``ctx.check_cancelled()`` between safe
points (e.g. between pages or between external writes, never mid-write).
"""
from __future__ import annotations

import logging
import threading
import traceback
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_factory, utcnow
from app.integrations.http import IntegrationError, OperationCancelled
from app.models import Job
from app.security.redaction import redact_text

log = logging.getLogger("touqa.jobs")

_executor: ThreadPoolExecutor | None = None
_lock = threading.Lock()
_futures: dict[int, Future] = {}
# Tests set this to True to run jobs inline (deterministic, no threads).
RUN_INLINE = False


class JobContext:
    def __init__(self, job_id: int, db: Session):
        self.job_id = job_id
        self.db = db

    @property
    def job(self) -> Job:
        return self.db.get(Job, self.job_id)

    def progress(self, pct: int, message: str | None = None) -> None:
        job = self.job
        job.progress = max(0, min(100, int(pct)))
        if message is not None:
            job.message = message[:2000]
        self.db.commit()

    def is_cancel_requested(self) -> bool:
        # Read the flag from a fresh session so a cancel issued by the API is observed.
        with session_factory()() as s:
            j = s.get(Job, self.job_id)
            return bool(j and j.cancel_requested)

    def check_cancelled(self) -> None:
        if self.is_cancel_requested():
            raise OperationCancelled()


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=get_settings().job_workers, thread_name_prefix="touqa-job")
        return _executor


def create_job(db: Session, kind: str, *, project_id: int | None, params: dict | None = None,
               user_id: int | None = None, message: str | None = None) -> Job:
    job = Job(kind=kind, project_id=project_id, params=params or {}, created_by_id=user_id,
              message=message, is_demo=get_settings().demo_mode)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def submit(job_id: int, fn: Callable[[JobContext], dict | None], *, final_status: Callable[[dict], str] | None = None) -> None:
    """Run ``fn(ctx)`` in the background. ``fn`` returns the job result dict."""

    def runner():
        db = session_factory()()
        try:
            job = db.get(Job, job_id)
            if job is None:
                return
            if job.cancel_requested:
                job.status, job.finished_at = "CANCELLED", utcnow()
                db.commit()
                return
            job.status, job.started_at = "RUNNING", utcnow()
            db.commit()
            ctx = JobContext(job_id, db)
            result = fn(ctx) or {}
            job = db.get(Job, job_id)
            job.result = {**(job.result or {}), **result}
            job.status = final_status(result) if final_status else result.get("_status", "COMPLETED")
            job.result.pop("_status", None)
            job.progress = 100 if job.status in {"COMPLETED", "NEEDS_REVIEW", "PARTIALLY_COMPLETED"} else job.progress
            job.finished_at = utcnow()
            db.commit()
        except OperationCancelled:
            db.rollback()
            job = db.get(Job, job_id)
            job.status, job.finished_at = "CANCELLED", utcnow()
            job.message = (job.message or "") + " Cancelled by user."
            db.commit()
        except IntegrationError as exc:
            db.rollback()
            _fail(db, job_id, exc.user_message)
        except Exception as exc:  # noqa: BLE001 - job boundary
            db.rollback()
            msg = getattr(exc, "user_message", None) or f"{exc.__class__.__name__}: {exc}"
            log.error("Job %s failed: %s", job_id, redact_text(traceback.format_exc()))
            _fail(db, job_id, msg)
        finally:
            db.close()
            _futures.pop(job_id, None)

    if RUN_INLINE:
        runner()
        return
    _futures[job_id] = _get_executor().submit(runner)


def _fail(db: Session, job_id: int, message: str) -> None:
    job = db.get(Job, job_id)
    if job is None:
        return
    job.status, job.error, job.finished_at = "FAILED", redact_text(message)[:4000], utcnow()
    db.commit()


def request_cancel(db: Session, job: Job) -> Job:
    if job.status in {"QUEUED", "RUNNING"}:
        job.cancel_requested = True
        if job.status == "QUEUED" and job.id not in _futures:
            job.status, job.finished_at = "CANCELLED", utcnow()
        db.commit()
    return job


def recover_interrupted_jobs(db: Session) -> int:
    """Mark jobs left RUNNING/QUEUED by a previous process as FAILED (they cannot resume safely)."""
    stale = db.query(Job).filter(Job.status.in_(["RUNNING", "QUEUED"])).all()
    for job in stale:
        job.status = "FAILED"
        job.error = "Interrupted by an application restart. Review partial results and retry."
        job.finished_at = utcnow()
    db.commit()
    return len(stale)


def shutdown() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None


def job_to_dict(job: Job) -> dict[str, Any]:
    return {
        "id": job.id, "kind": job.kind, "status": job.status, "project_id": job.project_id,
        "progress": job.progress, "message": job.message, "params": job.params, "result": job.result,
        "error": job.error, "cancel_requested": job.cancel_requested, "is_demo": job.is_demo,
        "created_at": job.created_at, "started_at": job.started_at, "finished_at": job.finished_at,
    }
