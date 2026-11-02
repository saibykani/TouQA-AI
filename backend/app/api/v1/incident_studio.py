from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.v1.projects import get_project
from app.config import get_settings
from app.db import get_db
from app.models import Attachment, IncidentDraft, User
from app.schemas.api import AttachmentUpdateIn, IncidentDraftCreateIn, IncidentDraftUpdateIn, IncidentSubmitIn, JobOut
from app.security.auth import current_user, require_writer
from app.services import attachments as files
from app.services import audit, incidents as isvc, jobs
from app.services.ai_settings import provider_for
from app.services.integrations import external_writes_allowed

router = APIRouter(prefix="/incident-drafts", tags=["incident studio"])


def _draft(db: Session, draft_id: int) -> IncidentDraft:
    d = db.get(IncidentDraft, draft_id)
    if d is None:
        raise HTTPException(404, "Incident draft not found")
    get_project(db, d.project_id)
    return d


@router.get("")
def list_drafts(project_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_project(db, project_id)
    rows = db.query(IncidentDraft).filter_by(project_id=project_id).order_by(IncidentDraft.updated_at.desc()).limit(100).all()
    return [{"id": d.id, "title": d.title or (d.raw_notes[:80] if d.raw_notes else "Untitled"), "status": d.status,
             "destinations": d.destinations, "is_simulated": d.is_simulated, "attachment_count": len(d.attachments),
             "results": d.results, "updated_at": d.updated_at} for d in rows]


@router.post("")
def create_draft(body: IncidentDraftCreateIn, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    get_project(db, body.project_id)
    d = IncidentDraft(project_id=body.project_id, created_by_id=user.id, raw_notes=body.raw_notes,
                      evidence=body.evidence.model_dump(), destinations=list(dict.fromkeys(body.destinations)),
                      title=(body.raw_notes.strip().splitlines() or [""])[0][:120])
    db.add(d)
    db.commit()
    return isvc.draft_dict(d)


@router.get("/{draft_id}")
def get_draft(draft_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return isvc.draft_dict(_draft(db, draft_id))


@router.put("/{draft_id}")
def update_draft(draft_id: int, body: IncidentDraftUpdateIn, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    d = _draft(db, draft_id)
    data = body.model_dump(exclude_unset=True)
    if body.evidence is not None:
        data["evidence"] = body.evidence.model_dump()
    return isvc.draft_dict(isvc.update_draft(db, d, data, user.id))


@router.delete("/{draft_id}")
def delete_draft(draft_id: int, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    d = _draft(db, draft_id)
    if d.status in ("submitted", "partially_submitted", "submitting"):
        raise HTTPException(409, "Submitted incident drafts are kept for traceability.")
    for a in d.attachments:
        files.delete(a.stored_name)
    db.delete(d)
    audit.record(db, action="incident_draft.deleted", category="draft", outcome="success", user_id=user.id,
                 project_id=d.project_id, entity_type="incident_draft", entity_id=draft_id, summary="Incident draft deleted")
    db.commit()
    return {"ok": True}


@router.post("/{draft_id}/attachments")
async def upload(draft_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), _: User = Depends(require_writer)):
    d = _draft(db, draft_id)
    limit = get_settings().max_upload_bytes
    data = await file.read(limit + 1)
    if len(d.attachments) >= 20:
        raise HTTPException(422, "At most 20 attachments per incident draft.")
    meta = files.store(data, file.filename or "upload", file.content_type)
    a = Attachment(incident_draft_id=d.id, **meta)
    db.add(a)
    db.commit()
    return isvc.attachment_dict(a)


@router.get("/{draft_id}/attachments/{attachment_id}/content")
def attachment_content(draft_id: int, attachment_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    d = _draft(db, draft_id)
    a = db.get(Attachment, attachment_id)
    if a is None or a.incident_draft_id != d.id:
        raise HTTPException(404, "Attachment not found")
    headers = {"Content-Disposition": f'inline; filename="{a.original_filename}"', "X-Content-Type-Options": "nosniff",
               "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'", "Cache-Control": "private, max-age=300"}
    return Response(files.read(a.stored_name), media_type=a.content_type, headers=headers)


@router.patch("/{draft_id}/attachments/{attachment_id}")
def update_attachment(draft_id: int, attachment_id: int, body: AttachmentUpdateIn, db: Session = Depends(get_db),
                      _: User = Depends(require_writer)):
    d = _draft(db, draft_id)
    a = db.get(Attachment, attachment_id)
    if a is None or a.incident_draft_id != d.id:
        raise HTTPException(404, "Attachment not found")
    a.include_in_submission = body.include_in_submission
    db.commit()
    return isvc.attachment_dict(a)


@router.delete("/{draft_id}/attachments/{attachment_id}")
def delete_attachment(draft_id: int, attachment_id: int, db: Session = Depends(get_db), _: User = Depends(require_writer)):
    d = _draft(db, draft_id)
    a = db.get(Attachment, attachment_id)
    if a is None or a.incident_draft_id != d.id:
        raise HTTPException(404, "Attachment not found")
    if any(v.get("status") == "uploaded" for v in (a.upload_results or {}).values()):
        raise HTTPException(409, "This attachment was already uploaded externally and is kept for traceability.")
    files.delete(a.stored_name)
    db.delete(a)
    db.commit()
    return {"ok": True}


@router.post("/{draft_id}/analyze", response_model=JobOut)
def analyze(draft_id: int, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    d = _draft(db, draft_id)
    if not d.raw_notes.strip() and not d.attachments:
        raise HTTPException(422, "Add a description or evidence before drafting the incident.")
    provider_for(db)
    job = jobs.create_job(db, "incident_analysis", project_id=d.project_id, params={"draft_id": d.id}, user_id=user.id,
                          message="Drafting incident")
    jobs.submit(job.id, isvc.run_incident_analysis)
    db.refresh(job)
    return jobs.job_to_dict(job)


@router.get("/{draft_id}/preview")
def preview(draft_id: int, verify: bool = True, db: Session = Depends(get_db), _: User = Depends(current_user)):
    d = _draft(db, draft_id)
    project = get_project(db, d.project_id)
    result = isvc.preview(db, d, fetch_meta=verify and not project.is_demo)
    allowed, reason = external_writes_allowed()
    result["writes_allowed"] = allowed and not project.is_demo
    result["writes_disabled_reason"] = reason or ("The demo project is synthetic; submission is preview-only." if project.is_demo else None)
    return result


@router.post("/{draft_id}/submit", response_model=JobOut)
def submit(draft_id: int, body: IncidentSubmitIn, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    if not body.confirm:
        raise HTTPException(400, "Submission must be explicitly confirmed.")
    d = _draft(db, draft_id)
    project = get_project(db, d.project_id)
    allowed, reason = external_writes_allowed()
    if not allowed or project.is_demo:
        raise HTTPException(403, reason or "The synthetic demo project cannot be submitted externally.")
    if d.status == "submitting":
        raise HTTPException(409, "This incident is already being submitted.")
    current = isvc.preview(db, d, fetch_meta=False)
    if current["payload_hash"] != body.payload_hash:
        raise HTTPException(409, "The incident changed since you reviewed the preview. Review it again.")
    dests = body.destinations or d.destinations or ["spira"]
    blocking = [k for k in dests if (isvc.preview(db, d, fetch_meta=True)["destinations"].get(k) or {}).get("blocking")]
    # Destinations that already succeeded are skipped by the idempotent submit; only block if a pending one is invalid.
    pending = [k for k in blocking if not str((d.results or {}).get(k, {}).get("status", "")).startswith("created")]
    if pending:
        raise HTTPException(422, f"Resolve blocking issues for: {', '.join(pending)}")
    isvc.record_approval(db, user.id, d, body.payload_hash)
    d.status = "submitting"
    db.commit()
    job = jobs.create_job(db, "incident_submission", project_id=d.project_id, user_id=user.id,
                          params={"draft_id": d.id, "destinations": dests, "payload_hash": body.payload_hash},
                          message=f"Submitting incident to {', '.join(dests)}")
    jobs.submit(job.id, isvc.run_incident_submission)
    db.refresh(job)
    return jobs.job_to_dict(job)
