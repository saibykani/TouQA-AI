"""Approved test case submission to Spira.

Generation never writes externally. Submission requires an explicit confirmation carrying the
hash of the previewed payloads, so exactly what the user reviewed is what gets created.

Per draft, an ApiOperation with key ``spira:create_test_case:draft:{id}`` tracks progress:
  pending → in_flight → (test case created) → steps → coverage link → succeeded
A retry resumes from the last confirmed sub-step and never re-creates a test case whose ID
is already recorded. If a create timed out (outcome unknown), the next attempt first searches
Spira for a test case with the exact name before creating anything.
"""
from __future__ import annotations

import html

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db import utcnow
from app.integrations.http import IntegrationError, OutcomeUnknownError
from app.integrations.spira.client import spira_artifact_url
from app.models import (
    ApprovalEvent, ExternalRecordRef, Folder, Project, Requirement, RequirementTestCase,
    TestCase, TestCaseDraft, TestStep,
)
from app.services import audit, operations
from app.services.folders import path_of
from app.services.integrations import get_config, spira_client
from app.services.jobs import JobContext
from app.services.mappings import allowed_values, resolve
from app.services.validation import has_errors

DEFAULT_STATUS_NAMES = ["draft", "ready for review", "new"]
DEFAULT_TYPE_NAMES = ["functional", "acceptance", "manual"]


def _esc(t: str) -> str:
    return html.escape(t or "").replace("\n", "<br />")


def description_html(c: dict, requirement: Requirement | None, simulated: bool) -> str:
    parts = [f"<p>{_esc(c.get('description', ''))}</p>"]
    if c.get("objective"):
        parts.append(f"<p><strong>Objective:</strong> {_esc(c['objective'])}</p>")
    if c.get("preconditions"):
        parts.append("<p><strong>Preconditions:</strong></p><ul>" + "".join(f"<li>{_esc(p)}</li>" for p in c["preconditions"]) + "</ul>")
    if c.get("test_data"):
        parts.append("<p><strong>Test data:</strong></p><ul>" + "".join(f"<li>{_esc(p)}</li>" for p in c["test_data"]) + "</ul>")
    if c.get("expected_outcome"):
        parts.append(f"<p><strong>Overall expected outcome:</strong> {_esc(c['expected_outcome'])}</p>")
    trace = f"RQ:{requirement.external_id} {requirement.name}" if requirement else c.get("requirement_id", "")
    acs = ", ".join(c.get("acceptance_criterion_ids") or []) or "none"
    parts.append(f"<p><strong>Traceability:</strong> {_esc(trace)} · Criteria: {_esc(acs)} · Category: {_esc(c.get('category', ''))}</p>")
    parts.append(f"<p><strong>Risk:</strong> {_esc(c.get('risk_level', ''))} · <strong>Automation suitability:</strong> "
                 f"{_esc(c.get('automation_suitability', ''))}</p>")
    if c.get("assumptions"):
        parts.append("<p><strong>Assumptions:</strong></p><ul>" + "".join(f"<li>{_esc(a)}</li>" for a in c["assumptions"]) + "</ul>")
    parts.append(f"<p><em>Drafted with TouQA AI{' (simulated provider)' if simulated else ''} and approved by a reviewer.</em></p>")
    return "".join(parts)


def _default_id(values: list[dict], preferred: list[str], configured: str | None) -> dict | None:
    if configured:
        hit = next((v for v in values if v["id"] == str(configured)), None)
        if hit:
            return hit
    for name in preferred:
        hit = next((v for v in values if v["name"].strip().lower() == name), None)
        if hit:
            return hit
    return values[0] if len(values) == 1 else None


def build_payload(db: Session, project: Project, draft: TestCaseDraft, folder_external_id: str | None,
                  options: dict | None = None) -> dict:
    """The exact request bodies that will be sent, plus resolution issues."""
    options = options or {}
    c = draft.content
    req = db.get(Requirement, draft.requirement_id) if draft.requirement_id else None
    issues: list[dict] = [i for i in (draft.validation_errors or [])]
    statuses = allowed_values(db, project.id, "test_case_status")
    types = allowed_values(db, project.id, "test_case_type")
    settings = project.settings or {}
    status = _default_id(statuses, DEFAULT_STATUS_NAMES, options.get("status_id") or settings.get("default_test_case_status_id"))
    ttype = _default_id(types, DEFAULT_TYPE_NAMES, options.get("type_id") or settings.get("default_test_case_type_id"))
    if not status:
        issues.append({"field": "TestCaseStatusId", "severity": "error",
                       "message": "Test case status is required by Spira. Select a default status (sync metadata first)."})
    if not ttype:
        issues.append({"field": "TestCaseTypeId", "severity": "error",
                       "message": "Test case type is required by Spira. Select a default type (sync metadata first)."})
    prio = resolve(db, "spira", project.id, "test_case_priority", c.get("priority"))
    if prio["source"] == "unresolved":
        issues.append({"field": "TestCasePriorityId", "severity": "warning",
                       "message": f"Priority '{c.get('priority')}' has no Spira mapping; it will be left unset. Configure it in Field Mapping."})
    body: dict = {
        "Name": c.get("name", "")[:255],
        "Description": description_html(c, req, draft.batch.is_simulated if draft.batch else False),
    }
    if status:
        body["TestCaseStatusId"] = int(status["id"])
    if ttype:
        body["TestCaseTypeId"] = int(ttype["id"])
    if prio["id"]:
        body["TestCasePriorityId"] = int(prio["id"])
    if folder_external_id:
        body["TestCaseFolderId"] = int(folder_external_id)
    tags = [t for t in (c.get("tags") or []) if t]
    if options.get("include_tags", True) and tags:
        body["Tags"] = ", ".join(dict.fromkeys(tags))[:1000]
    steps = [{"Position": s["step_number"], "Description": _esc(s["action"]), "ExpectedResult": _esc(s["expected_result"]),
              **({"SampleData": _esc(s["test_data"])} if s.get("test_data") else {})} for s in c.get("steps", [])]
    link = {"RequirementId": int(req.external_id)} if req and req.external_id.isdigit() else None
    if not req:
        issues.append({"field": "requirement", "severity": "warning", "message": "No requirement linked; coverage will not be created."})
    return {
        "draft_id": draft.id,
        "name": body["Name"],
        "test_case": body,
        "test_steps": steps,
        "coverage_link": link,
        "resolved": {"status": status, "type": ttype, "priority": prio},
        "issues": issues,
        "blocking": has_errors(issues),
    }


def preview(db: Session, project: Project, draft_ids: list[int], folder_external_id: str | None, options: dict | None = None) -> dict:
    drafts = db.query(TestCaseDraft).filter(TestCaseDraft.id.in_(draft_ids), TestCaseDraft.project_id == project.id).order_by(TestCaseDraft.position).all()
    if folder_external_id and not db.query(Folder).filter_by(project_id=project.id, folder_type="test_case", external_id=str(folder_external_id)).first():
        raise ValueError("Destination folder not found. Refresh the folder tree.")
    payloads = [build_payload(db, project, d, folder_external_id, options) for d in drafts]
    already = []
    for d in drafts:
        op = db.query(operations.ApiOperation).filter_by(idempotency_key=f"spira:create_test_case:draft:{d.id}").one_or_none()
        if op and op.status == "succeeded":
            already.append({"draft_id": d.id, "external_id": op.external_id})
    exact = [{k: p[k] for k in ("draft_id", "test_case", "test_steps", "coverage_link")} for p in payloads]
    return {
        "project_external_id": project.external_id,
        "folder_external_id": folder_external_id,
        "folder_path": path_of(db, project.id, folder_external_id) or ["(project root)"],
        "payloads": payloads,
        "payload_hash": operations.payload_hash({"folder": folder_external_id, "payloads": exact}),
        "blocking": any(p["blocking"] for p in payloads),
        "already_created": already,
        "endpoints": {
            "test_case": "POST /projects/{project_id}/test-cases",
            "test_step": "POST /projects/{project_id}/test-cases/{test_case_id}/test-steps",
            "coverage": "POST /projects/{project_id}/requirements/test-cases",
        },
    }


def _save_progress(op, progress: dict) -> None:
    """Assign a fresh copy and flag it so in-place mutations of ``progress`` are always persisted."""
    op.request_summary = dict(progress)
    flag_modified(op, "request_summary")


def _record_local(db: Session, project: Project, draft: TestCaseDraft, payload: dict, created: dict, tc_id: str,
                  base_url: str) -> None:
    tc = db.query(TestCase).filter_by(project_id=project.id, external_id=tc_id).one_or_none()
    if tc is None:
        tc = TestCase(project_id=project.id, external_id=tc_id, name=payload["test_case"]["Name"], origin="touqa", raw={})
        db.add(tc)
    tc.folder_external_id = str(payload["test_case"].get("TestCaseFolderId") or "") or None
    tc.description_html = payload["test_case"]["Description"]
    from app.integrations.spira.mapper import html_to_text

    tc.description_text = html_to_text(tc.description_html)
    tc.status_name = (payload["resolved"]["status"] or {}).get("name")
    tc.type_name = (payload["resolved"]["type"] or {}).get("name")
    tc.priority_name = payload["resolved"]["priority"].get("name")
    tc.synced_at = utcnow()
    db.flush()
    if not tc.steps:
        for s in draft.content.get("steps", []):
            tc.steps.append(TestStep(external_id=f"pending-{draft.id}-{s['step_number']}", position=s["step_number"],
                                     description=s["action"], expected_result=s["expected_result"], sample_data=s.get("test_data") or None))
    if payload.get("coverage_link"):
        rid = str(payload["coverage_link"]["RequirementId"])
        if not db.query(RequirementTestCase).filter_by(project_id=project.id, requirement_external_id=rid, test_case_external_id=tc_id).first():
            db.add(RequirementTestCase(project_id=project.id, requirement_external_id=rid, test_case_external_id=tc_id))
    url = spira_artifact_url(base_url, project.external_id, "test_case", tc_id)
    if not db.query(ExternalRecordRef).filter_by(platform="spira", record_type="test_case", external_id=tc_id, project_id=project.id).first():
        db.add(ExternalRecordRef(project_id=project.id, platform="spira", record_type="test_case", external_id=tc_id, url=url,
                                 local_entity_type="test_case_draft", local_entity_id=draft.id))
    draft.status, draft.external_test_case_id, draft.external_url = "submitted", tc_id, url


def submit_one(db: Session, client, project: Project, draft: TestCaseDraft, payload: dict, job_id: int | None,
               base_url: str, user_id: int | None) -> dict:
    key = f"spira:create_test_case:draft:{draft.id}"
    op = operations.get_or_create(db, key, platform="spira", operation="create_test_case", project_id=project.id,
                                  entity_type="test_case_draft", entity_id=draft.id, job_id=job_id,
                                  summary={"name": payload["name"], "folder": payload["test_case"].get("TestCaseFolderId"),
                                           "steps": len(payload["test_steps"])})
    pid = int(project.external_id)
    if op.status == "succeeded":
        return {"draft_id": draft.id, "status": "already_created", "external_id": op.external_id, "url": op.external_url}

    progress = dict(op.request_summary or {})
    tc_id = op.external_id
    if not tc_id and op.status in ("in_flight", "unknown"):
        # A previous create may have succeeded without us receiving the response: reconcile first.
        matches = client.search_test_cases_by_name(pid, payload["name"])
        if len(matches) == 1:
            tc_id = str(matches[0]["TestCaseId"])
            op.external_id = tc_id
            progress["reconciled"] = True
        elif len(matches) > 1:
            op.status, op.error = "unknown", (f"{len(matches)} test cases named '{payload['name']}' exist in Spira; "
                                              "resolve manually before retrying.")
            db.commit()
            return {"draft_id": draft.id, "status": "needs_attention", "error": op.error}

    op.status, op.attempts = "in_flight", op.attempts + 1
    draft.status = "submitting"
    db.commit()
    try:
        if not tc_id:
            created = client.create_test_case(pid, payload["test_case"])
            tc_id = str((created or {}).get("TestCaseId") or "")
            if not tc_id:
                raise OutcomeUnknownError("Spira did not return a TestCaseId for the created test case.")
            op.external_id = tc_id
            progress["steps_created"] = 0
            _save_progress(op, progress)
            db.commit()
        done = int(progress.get("steps_created") or 0)
        if progress.get("reconciled") and done == 0:
            existing_steps = client.test_steps(pid, int(tc_id))
            done = len(existing_steps)
        for step in payload["test_steps"][done:]:
            client.add_test_step(pid, int(tc_id), {**step, "TestCaseId": int(tc_id)})
            done += 1
            progress["steps_created"] = done
            _save_progress(op, progress)
            db.commit()
        if payload.get("coverage_link") and not progress.get("coverage_linked"):
            client.link_requirement_test_case(pid, payload["coverage_link"]["RequirementId"], int(tc_id))
            progress["coverage_linked"] = True
            _save_progress(op, progress)
        op.status, op.error = "succeeded", None
        op.external_url = spira_artifact_url(base_url, pid, "test_case", tc_id)
        _record_local(db, project, draft, payload, {}, tc_id, base_url)
        audit.record(db, action="spira.test_case.create", category="external_write", outcome="success", user_id=user_id,
                     project_id=project.id, platform="spira", entity_type="test_case", entity_id=tc_id,
                     summary=f"Created TC:{tc_id} '{payload['name']}' with {done} step(s)",
                     details={"draft_id": draft.id, "attempt": op.attempts, "reconciled": bool(progress.get("reconciled"))})
        db.commit()
        return {"draft_id": draft.id, "status": "created", "external_id": tc_id, "url": op.external_url}
    except OutcomeUnknownError as exc:
        op.status, op.error = "unknown", exc.user_message
        _save_progress(op, progress)
        draft.status = "failed"
        audit.record(db, action="spira.test_case.create", category="external_write", outcome="failure", user_id=user_id,
                     project_id=project.id, platform="spira", entity_type="test_case_draft", entity_id=draft.id,
                     summary=f"Outcome unknown for '{payload['name']}': {exc.user_message}")
        db.commit()
        return {"draft_id": draft.id, "status": "unknown", "error": exc.user_message, "external_id": tc_id or None}
    except IntegrationError as exc:
        op.status = "partial" if tc_id else "failed"
        op.error, op.response_status = exc.user_message, exc.status_code
        _save_progress(op, progress)
        draft.status = "failed"
        audit.record(db, action="spira.test_case.create", category="external_write",
                     outcome="partial" if tc_id else "failure", user_id=user_id, project_id=project.id, platform="spira",
                     entity_type="test_case_draft", entity_id=draft.id,
                     summary=(f"TC:{tc_id} created but incomplete ({progress.get('steps_created', 0)}/{len(payload['test_steps'])} steps): "
                              if tc_id else f"Failed to create '{payload['name']}': ") + exc.user_message)
        db.commit()
        return {"draft_id": draft.id, "status": "partial" if tc_id else "failed", "error": exc.user_message,
                "external_id": tc_id or None, "steps_created": progress.get("steps_created", 0)}


def run_submission(ctx: JobContext) -> dict:
    db = ctx.db
    job = ctx.job
    project = db.get(Project, job.project_id)
    params = job.params
    cfg = get_config(db, "spira")
    drafts = db.query(TestCaseDraft).filter(TestCaseDraft.id.in_(params["draft_ids"])).order_by(TestCaseDraft.position).all()
    results = []
    with spira_client(db) as client:
        for i, draft in enumerate(drafts):
            ctx.check_cancelled()  # safe point: between test cases, never mid-write
            ctx.progress(int(i * 100 / max(1, len(drafts))), f"Creating {i + 1}/{len(drafts)}: {draft.content.get('name', '')[:80]}")
            payload = build_payload(db, project, draft, params.get("folder_external_id"), params.get("options"))
            if payload["blocking"]:
                results.append({"draft_id": draft.id, "status": "skipped_invalid",
                                "error": "; ".join(i["message"] for i in payload["issues"] if i["severity"] == "error")})
                continue
            results.append(submit_one(db, client, project, draft, payload, job.id, cfg.base_url, job.created_by_id))
    ok = [r for r in results if r["status"] in ("created", "already_created")]
    if len(ok) == len(results):
        status = "COMPLETED"
    elif ok:
        status = "PARTIALLY_COMPLETED"
    else:
        status = "FAILED"
    if status == "FAILED":
        ctx.job.error = "No test cases were created. See per-case results."
    return {"_status": status, "results": results, "created": len(ok), "total": len(results)}


def record_approval(db: Session, user_id: int | None, draft_ids: list[int], phash: str) -> None:
    for did in draft_ids:
        db.add(ApprovalEvent(user_id=user_id, entity_type="test_case_draft", entity_id=did,
                             action="confirm_submission", payload_hash=phash))
    db.commit()
