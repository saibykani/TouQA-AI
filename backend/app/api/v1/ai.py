"""Requirement analysis, test generation and draft review. Nothing here writes to Spira/Jira."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.v1.projects import get_project
from app.db import get_db
from app.models import GenerationBatch, Requirement, RequirementAnalysis, TestCaseDraft, User
from app.schemas.api import AnalysisUpdateIn, DraftUpdateIn, GenerationStartIn, JobOut
from app.security.auth import current_user, require_writer
from app.services import analysis as asvc
from app.services import audit, generation as gsvc, jobs
from app.services.ai_settings import provider_for
from app.services.duplicates import detect_for_batch

router = APIRouter(tags=["ai"])


def analysis_dict(a: RequirementAnalysis) -> dict:
    return {"id": a.id, "requirement_id": a.requirement_id, "job_id": a.job_id, "status": a.status, "content": a.content,
            "is_edited": a.is_edited, "provider": a.provider, "model": a.model, "prompt_version": a.prompt_version,
            "is_simulated": a.is_simulated, "approved_at": a.approved_at, "created_at": a.created_at, "updated_at": a.updated_at}


def _analysis(db: Session, analysis_id: int) -> RequirementAnalysis:
    a = db.get(RequirementAnalysis, analysis_id)
    if a is None:
        raise HTTPException(404, "Analysis not found")
    return a


@router.post("/requirements/{requirement_id}/analyses", response_model=JobOut)
def start_analysis(requirement_id: int, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    req = db.get(Requirement, requirement_id)
    if req is None:
        raise HTTPException(404, "Requirement not found")
    get_project(db, req.project_id)
    provider_for(db)  # fail fast if the AI provider is not configured
    job = jobs.create_job(db, "analysis", project_id=req.project_id, params={"requirement_id": req.id},
                          user_id=user.id, message=f"Analysing RQ:{req.external_id}")
    jobs.submit(job.id, asvc.run_analysis)
    db.refresh(job)
    return jobs.job_to_dict(job)


@router.get("/requirements/{requirement_id}/analyses")
def list_analyses(requirement_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    rows = db.query(RequirementAnalysis).filter_by(requirement_id=requirement_id).order_by(RequirementAnalysis.created_at.desc()).all()
    return [analysis_dict(a) for a in rows]


@router.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return analysis_dict(_analysis(db, analysis_id))


@router.put("/analyses/{analysis_id}")
def update_analysis(analysis_id: int, body: AnalysisUpdateIn, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    return analysis_dict(asvc.update_content(db, _analysis(db, analysis_id), body.content, user.id))


@router.post("/analyses/{analysis_id}/approve")
def approve_analysis(analysis_id: int, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    return analysis_dict(asvc.approve(db, _analysis(db, analysis_id), user.id))


@router.get("/analyses/{analysis_id}/export")
def export_analysis(analysis_id: int, format: str = "markdown", db: Session = Depends(get_db), _: User = Depends(current_user)):
    a = _analysis(db, analysis_id)
    req = db.get(Requirement, a.requirement_id)
    if format == "json":
        return PlainTextResponse(json.dumps(analysis_dict(a), default=str, indent=2), media_type="application/json",
                                 headers={"Content-Disposition": f'attachment; filename="analysis-RQ{req.external_id}.json"'})
    return PlainTextResponse(asvc.to_markdown(a, req), media_type="text/markdown",
                             headers={"Content-Disposition": f'attachment; filename="analysis-RQ{req.external_id}.md"'})


# ------------------------------------------------------------------- generation
def draft_dict(d: TestCaseDraft) -> dict:
    return {"id": d.id, "batch_id": d.batch_id, "requirement_id": d.requirement_id, "position": d.position, "status": d.status,
            "content": d.content, "is_edited": d.is_edited, "duplicate_info": d.duplicate_info,
            "duplicate_decision": d.duplicate_decision, "validation_errors": d.validation_errors,
            "external_test_case_id": d.external_test_case_id, "external_url": d.external_url, "updated_at": d.updated_at}


def batch_dict(b: GenerationBatch) -> dict:
    return {"id": b.id, "project_id": b.project_id, "job_id": b.job_id, "requirement_ids": b.requirement_ids,
            "analysis_ids": b.analysis_ids, "config": b.config, "instructions": b.instructions, "provider": b.provider,
            "model": b.model, "is_simulated": b.is_simulated, "summary": b.summary, "created_at": b.created_at,
            "drafts": [draft_dict(d) for d in b.drafts]}


@router.post("/generation", response_model=JobOut)
def start_generation(body: GenerationStartIn, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    get_project(db, body.project_id)
    reqs = db.query(Requirement).filter(Requirement.id.in_(body.requirement_ids), Requirement.project_id == body.project_id).all()
    if len(reqs) != len(set(body.requirement_ids)):
        raise HTTPException(404, "One or more requirements were not found in this project")
    config = gsvc.normalise_config(body.config.model_dump())
    analyses = {r.id: gsvc.pick_analysis(db, r) for r in reqs}
    if body.require_approved_analysis:
        missing = [f"RQ:{r.external_id}" for r in reqs if not analyses[r.id] or analyses[r.id].status != "approved"]
        if missing:
            raise HTTPException(409, f"Approve the analysis first for: {', '.join(missing)}")
    provider = provider_for(db)
    batch = GenerationBatch(project_id=body.project_id, requirement_ids=[r.id for r in reqs],
                            analysis_ids=[a.id for a in analyses.values() if a], config=config,
                            instructions=body.instructions, provider=provider.name, model=provider.model,
                            is_simulated=provider.simulated)
    db.add(batch)
    db.commit()
    job = jobs.create_job(db, "generation", project_id=body.project_id, params={"batch_id": batch.id},
                          user_id=user.id, message=f"Generating {config['total']} test case(s)")
    batch.job_id = job.id
    db.commit()
    jobs.submit(job.id, gsvc.run_generation)
    db.refresh(job)
    return jobs.job_to_dict(job)


@router.get("/generation/batches")
def list_batches(project_id: int, requirement_id: int | None = None, limit: int = 20, db: Session = Depends(get_db),
                 _: User = Depends(current_user)):
    rows = db.query(GenerationBatch).filter_by(project_id=project_id).order_by(GenerationBatch.created_at.desc()).limit(min(limit, 100)).all()
    if requirement_id:
        rows = [b for b in rows if requirement_id in (b.requirement_ids or [])]
    return [{k: v for k, v in batch_dict(b).items() if k != "drafts"} | {"draft_count": len(b.drafts)} for b in rows]


@router.get("/generation/batches/{batch_id}")
def get_batch(batch_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    b = db.get(GenerationBatch, batch_id)
    if b is None:
        raise HTTPException(404, "Batch not found")
    return batch_dict(b)


@router.post("/generation/batches/{batch_id}/duplicates")
def rerun_duplicates(batch_id: int, db: Session = Depends(get_db), _: User = Depends(require_writer)):
    b = db.get(GenerationBatch, batch_id)
    if b is None:
        raise HTTPException(404, "Batch not found")
    active = [d for d in b.drafts if d.status not in ("rejected",)]
    detect_for_batch(db, active)
    db.commit()
    return batch_dict(b)


def _draft(db: Session, draft_id: int) -> TestCaseDraft:
    d = db.get(TestCaseDraft, draft_id)
    if d is None:
        raise HTTPException(404, "Draft not found")
    return d


@router.put("/drafts/{draft_id}")
def update_draft(draft_id: int, body: DraftUpdateIn, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    d = _draft(db, draft_id)
    if d.status in ("submitted", "submitting"):
        raise HTTPException(409, "This draft has already been submitted to Spira and can no longer be edited.")
    if body.content is not None:
        d.content = body.content
        d.is_edited = True
        gsvc.revalidate_draft(db, d)
    if body.duplicate_decision is not None:
        d.duplicate_decision = body.duplicate_decision
        if body.duplicate_decision == "remove":
            d.status = "rejected"
    if body.status is not None:
        if body.status == "approved" and any(i["severity"] == "error" for i in d.validation_errors or []):
            raise HTTPException(422, "Resolve validation errors before approving this draft.")
        d.status = body.status
    audit.record(db, action="draft.updated", category="draft", outcome="success", user_id=user.id, project_id=d.project_id,
                 entity_type="test_case_draft", entity_id=d.id,
                 summary=f"Draft {d.id} {'edited' if body.content is not None else ''} {('→ ' + d.status) if body.status else ''}".strip())
    db.commit()
    return draft_dict(d)


@router.post("/drafts/{draft_id}/validate")
def validate_draft(draft_id: int, db: Session = Depends(get_db), _: User = Depends(require_writer)):
    d = _draft(db, draft_id)
    issues = gsvc.revalidate_draft(db, d)
    db.commit()
    return {"draft_id": d.id, "issues": issues}


@router.delete("/drafts/{draft_id}")
def delete_draft(draft_id: int, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    d = _draft(db, draft_id)
    if d.status in ("submitted", "submitting"):
        raise HTTPException(409, "Submitted drafts are kept for traceability.")
    db.delete(d)
    audit.record(db, action="draft.deleted", category="draft", outcome="success", user_id=user.id, project_id=d.project_id,
                 entity_type="test_case_draft", entity_id=draft_id, summary=f"Draft {draft_id} deleted")
    db.commit()
    return {"ok": True}
