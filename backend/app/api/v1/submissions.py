"""Folder creation and approved test case submission to Spira (external writes)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.projects import get_project
from app.db import get_db
from app.models import ApiOperation, User
from app.schemas.api import FolderCreateIn, FolderPreviewIn, JobOut, SubmissionIn, SubmissionPreviewIn
from app.security.auth import current_user, require_writer
from app.services import folders as fsvc
from app.services import jobs, operations, submission
from app.services.integrations import external_writes_allowed

router = APIRouter(tags=["submissions"])


@router.post("/folders/refresh")
def refresh_folders(project_id: int, db: Session = Depends(get_db), _: User = Depends(require_writer)):
    project = get_project(db, project_id)
    if project.is_demo:
        return {"tree": fsvc.tree(db, project.id), "note": "Demo project: folders are synthetic and not refreshed from Spira."}
    return {"tree": fsvc.refresh(db, project)}


@router.post("/folders/preview")
def preview_folder(body: FolderPreviewIn, db: Session = Depends(get_db), _: User = Depends(require_writer)):
    project = get_project(db, body.project_id)
    allowed, reason = external_writes_allowed()
    return {**fsvc.preview(db, project, body.name, body.parent_external_id), "writes_allowed": allowed and not project.is_demo,
            "writes_disabled_reason": reason or ("The demo project is synthetic." if project.is_demo else None)}


@router.post("/folders")
def create_folder(body: FolderCreateIn, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    if not body.confirm:
        raise HTTPException(400, "Folder creation must be explicitly confirmed (confirm=true).")
    project = get_project(db, body.project_id)
    if project.is_demo:
        raise HTTPException(403, "Folders cannot be created in Spira for the synthetic demo project.")
    return fsvc.create(db, project, body.name, body.parent_external_id, user_id=user.id, description=body.description)


@router.post("/submissions/test-cases/preview")
def preview_submission(body: SubmissionPreviewIn, db: Session = Depends(get_db), _: User = Depends(require_writer)):
    project = get_project(db, body.project_id)
    result = submission.preview(db, project, body.draft_ids, body.folder_external_id, body.options.model_dump())
    allowed, reason = external_writes_allowed()
    result["writes_allowed"] = allowed and not project.is_demo
    result["writes_disabled_reason"] = reason or ("The demo project is synthetic; submission is preview-only." if project.is_demo else None)
    return result


@router.post("/submissions/test-cases", response_model=JobOut)
def submit_test_cases(body: SubmissionIn, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    if not body.confirm:
        raise HTTPException(400, "Submission must be explicitly confirmed.")
    project = get_project(db, body.project_id)
    allowed, reason = external_writes_allowed()
    if not allowed or project.is_demo:
        raise HTTPException(403, reason or "The synthetic demo project cannot be submitted to Spira.")
    current = submission.preview(db, project, body.draft_ids, body.folder_external_id, body.options.model_dump())
    if current["payload_hash"] != body.payload_hash:
        raise HTTPException(409, "The drafts or destination changed since you reviewed the preview. Review the preview again.")
    if current["blocking"]:
        raise HTTPException(422, "Some drafts have blocking validation errors. Fix or deselect them.")
    running = db.query(ApiOperation).filter(ApiOperation.local_entity_type == "test_case_draft",
                                            ApiOperation.local_entity_id.in_(body.draft_ids),
                                            ApiOperation.status == "in_flight").first()
    active_job = running and running.job_id and db.get(jobs.Job, running.job_id)
    if active_job and active_job.status in ("QUEUED", "RUNNING"):
        raise HTTPException(409, f"Draft {running.local_entity_id} is already being submitted (job {active_job.id}).")
    submission.record_approval(db, user.id, body.draft_ids, body.payload_hash)
    job = jobs.create_job(db, "test_case_submission", project_id=project.id, user_id=user.id,
                          params={"draft_ids": body.draft_ids, "folder_external_id": body.folder_external_id,
                                  "options": body.options.model_dump(), "payload_hash": body.payload_hash},
                          message=f"Creating {len(body.draft_ids)} test case(s) in Spira")
    jobs.submit(job.id, submission.run_submission)
    db.refresh(job)
    return jobs.job_to_dict(job)


@router.get("/operations")
def list_operations(project_id: int | None = None, entity_type: str | None = None, entity_id: int | None = None,
                    status: str | None = None, limit: int = 100, db: Session = Depends(get_db), _: User = Depends(current_user)):
    q = db.query(ApiOperation)
    if project_id:
        q = q.filter(ApiOperation.project_id == project_id)
    if entity_type:
        q = q.filter(ApiOperation.local_entity_type == entity_type)
    if entity_id:
        q = q.filter(ApiOperation.local_entity_id == entity_id)
    if status:
        q = q.filter(ApiOperation.status == status)
    return [operations.to_dict(o) for o in q.order_by(ApiOperation.updated_at.desc()).limit(min(limit, 500))]
