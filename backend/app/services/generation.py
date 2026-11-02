"""AI test case generation. Produces local drafts only — never external records."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai import prompts
from app.ai.schemas import SCENARIO_CATEGORIES, GenerationOutput
from app.models import GenerationBatch, Requirement, RequirementAnalysis, TestCaseDraft
from app.services import audit
from app.services.ai_settings import provider_for
from app.services.context import linked_test_cases, requirement_context, similar_test_cases, test_case_summary
from app.services.duplicates import detect_for_batch
from app.services.jobs import JobContext
from app.services.validation import validate_test_case

MAX_TOTAL = 60


def normalise_config(config: dict) -> dict:
    counts = {k: int(v) for k, v in (config.get("counts") or {}).items() if k in SCENARIO_CATEGORIES and int(v or 0) > 0}
    if not counts:
        raise ValueError("Request at least one test case in at least one category.")
    total = sum(counts.values())
    if total > MAX_TOTAL:
        raise ValueError(f"At most {MAX_TOTAL} test cases can be generated per batch (requested {total}).")
    return {"counts": counts, "total": total, "max_steps": int(config.get("max_steps") or 0) or None,
            "avoid_existing_duplicates": bool(config.get("avoid_existing_duplicates", True))}


def pick_analysis(db: Session, req: Requirement) -> RequirementAnalysis | None:
    q = db.query(RequirementAnalysis).filter_by(requirement_id=req.id)
    return (q.filter_by(status="approved").order_by(RequirementAnalysis.approved_at.desc()).first()
            or q.filter_by(status="draft").order_by(RequirementAnalysis.created_at.desc()).first())


def build_generation_context(db: Session, reqs: list[Requirement], analyses: dict[int, RequirementAnalysis | None], config: dict) -> dict:
    items, exclude = [], set()
    for req in reqs:
        rc = requirement_context(db, req)
        a = analyses.get(req.id)
        acs = [{"id": ac["id"], "text": ac["text"], "origin": ac["origin"], "clarity": ac["clarity"]}
               for ac in (a.content.get("acceptance_criteria", []) if a else [])]
        items.append({
            "external_id": req.external_id, "name": req.name, "description": rc["requirement"]["description"],
            "acceptance_criteria_text": rc["requirement"]["acceptance_criteria_text"],
            "acceptance_criteria": acs, "analysis_status": a.status if a else "none",
            "gaps": [g["description"] for g in (a.content.get("gaps", []) if a else [])][:10],
            "test_objectives": (a.content.get("test_objectives", []) if a else [])[:30],
            "parent": rc["parent"], "custom_properties": rc["requirement"]["custom_properties"],
            "linked_test_cases": rc["linked_test_cases"],
        })
        exclude |= {t["external_id"] for t in rc["linked_test_cases"]}
    similar = []
    if config.get("avoid_existing_duplicates", True):
        text = " ".join(f"{r.name} {r.description_text or ''}" for r in reqs)
        similar = [test_case_summary(tc, 6) for tc in similar_test_cases(db, reqs[0].project_id, text, exclude, 15)]
    return {"requirements": items, "other_similar_existing_test_cases": similar, "config": config}


def run_generation(ctx: JobContext) -> dict:
    db = ctx.db
    job = ctx.job
    batch = db.get(GenerationBatch, job.params["batch_id"])
    reqs = [db.get(Requirement, rid) for rid in batch.requirement_ids]
    reqs = [r for r in reqs if r is not None]
    # Use the analyses pinned when the batch was created; fall back to the best available one.
    pinned = {a.requirement_id: a for a in db.query(RequirementAnalysis).filter(
        RequirementAnalysis.id.in_(batch.analysis_ids or [0]))}
    analyses = {r.id: pinned.get(r.id) or pick_analysis(db, r) for r in reqs}
    ctx.progress(10, "Collecting requirement, analysis and existing test context…")
    context = build_generation_context(db, reqs, analyses, batch.config)
    provider = provider_for(db)
    ctx.progress(25, f"Generating with {provider.name} ({provider.model})…")
    result = provider.generate(system=prompts.GENERATION_SYSTEM,
                               prompt=prompts.generation_prompt(context, batch.config, batch.instructions),
                               schema=GenerationOutput, task="generation", context=context)
    ctx.check_cancelled()
    out: GenerationOutput = result.output  # type: ignore[assignment]
    allowed = {r.external_id for r in reqs}
    req_by_ext = {r.external_id: r for r in reqs}
    crit_ids = {r.external_id: {ac["id"] for ac in (analyses[r.id].content.get("acceptance_criteria", []) if analyses.get(r.id) else [])}
                for r in reqs}
    ctx.progress(80, "Validating generated cases…")
    drafts: list[TestCaseDraft] = []
    for i, case in enumerate(out.test_cases):
        content = case.model_dump()
        known = crit_ids.get(content.get("requirement_id")) or None
        content, issues = validate_test_case(content, allowed_requirement_ids=allowed, known_criterion_ids=known)
        req = req_by_ext.get(content.get("requirement_id"))
        d = TestCaseDraft(batch_id=batch.id, project_id=batch.project_id, requirement_id=req.id if req else None,
                          position=i, status="draft", content=content, validation_errors=issues)
        db.add(d)
        drafts.append(d)
    db.flush()
    ctx.progress(90, "Checking for duplicates…")
    detect_for_batch(db, drafts)
    requested = batch.config.get("counts", {})
    produced: dict[str, int] = {}
    for d in drafts:
        produced[d.content.get("category", "other")] = produced.get(d.content.get("category", "other"), 0) + 1
    batch.provider, batch.model, batch.is_simulated = result.provider, result.model, result.simulated
    batch.summary = {
        "requested": requested, "produced": produced,
        "skipped_categories": [s.model_dump() for s in out.skipped_categories], "notes": out.notes,
        "analysis_used": {r.external_id: (analyses[r.id].status if analyses.get(r.id) else "none") for r in reqs},
        "usage": result.usage,
    }
    audit.record(db, action="ai.test_generation", category="ai", outcome="success", user_id=job.created_by_id,
                 project_id=batch.project_id, entity_type="generation_batch", entity_id=batch.id,
                 summary=f"Generated {len(drafts)} draft test case(s) for {', '.join('RQ:' + r.external_id for r in reqs)}"
                         + (" (simulated)" if result.simulated else ""),
                 details={"requested": requested, "produced": produced, "usage": result.usage})
    db.commit()
    return {"_status": "NEEDS_REVIEW", "batch_id": batch.id, "draft_count": len(drafts), "simulated": result.simulated}


def revalidate_draft(db: Session, draft: TestCaseDraft) -> list[dict]:
    batch = draft.batch
    allowed = {r.external_id for r in db.query(Requirement).filter(Requirement.id.in_(batch.requirement_ids))}
    known = None
    if draft.requirement_id:
        req = db.get(Requirement, draft.requirement_id)
        a = pick_analysis(db, req) if req else None
        if a:
            known = {ac["id"] for ac in a.content.get("acceptance_criteria", [])}
    content, issues = validate_test_case(draft.content, allowed_requirement_ids=allowed, known_criterion_ids=known)
    draft.content, draft.validation_errors = content, issues
    return issues


__all__ = ["normalise_config", "run_generation", "revalidate_draft", "pick_analysis", "linked_test_cases"]
