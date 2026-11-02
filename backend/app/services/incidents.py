"""Incident Studio: drafting, classification, preview and approved submission to Spira and/or Jira."""
from __future__ import annotations

import html
import logging

from sqlalchemy.orm import Session

from app.ai import prompts
from app.ai.providers import AIError, ImageInput
from app.ai.schemas import IncidentDraftContent, ScreenshotAnalysis
from app.db import utcnow
from app.integrations.http import IntegrationError, OutcomeUnknownError
from app.integrations.jira import adf
from app.integrations.spira.client import WORKFLOW_FIELD_STATES, spira_artifact_url
from app.models import (
    ApprovalEvent, Attachment, ExternalRecordRef, Incident, IncidentDraft, Project, ProjectMetadata,
    Release, Requirement, TestCase,
)
from app.services import attachments as files
from app.services import audit, operations
from app.services.ai_settings import load as load_ai, provider_for
from app.services.integrations import get_config, jira_client, spira_client
from app.services.jobs import JobContext
from app.services.mappings import resolve
from app.services.validation import has_errors, validate_incident

log = logging.getLogger("touqa.incidents")
DESTINATIONS = {"spira", "jira"}


# ------------------------------------------------------------------ serialisation
def attachment_dict(a: Attachment) -> dict:
    return {"id": a.id, "filename": a.original_filename, "content_type": a.content_type, "size_bytes": a.size_bytes,
            "width": a.width, "height": a.height, "sha256": a.sha256, "include_in_submission": a.include_in_submission,
            "analysis": a.analysis, "upload_results": a.upload_results, "created_at": a.created_at,
            "is_image": a.content_type.startswith("image/")}


def draft_dict(d: IncidentDraft) -> dict:
    return {"id": d.id, "project_id": d.project_id, "status": d.status, "title": d.title, "raw_notes": d.raw_notes,
            "evidence": d.evidence, "content": d.content, "classification": d.classification,
            "destinations": d.destinations, "ai_provider": d.ai_provider, "ai_model": d.ai_model,
            "is_simulated": d.is_simulated, "results": d.results,
            "validation": validate_incident(d.content)[1] if d.content else [],
            "attachments": [attachment_dict(a) for a in d.attachments],
            "created_at": d.created_at, "updated_at": d.updated_at}


# --------------------------------------------------------------------- drafting
def run_incident_analysis(ctx: JobContext) -> dict:
    db = ctx.db
    job = ctx.job
    draft = db.get(IncidentDraft, job.params["draft_id"])
    ev = draft.evidence or {}
    ai_cfg = load_ai(db)
    screenshot_findings = []
    images = [a for a in draft.attachments if a.content_type.startswith("image/")]
    if images and ai_cfg.get("vision_enabled", True):
        vprov = provider_for(db, vision=True)
        for i, a in enumerate(images):
            ctx.check_cancelled()
            ctx.progress(10 + int(30 * i / len(images)), f"Inspecting screenshot {a.original_filename}…")
            try:
                r = vprov.generate(system=prompts.SCREENSHOT_SYSTEM, prompt=prompts.screenshot_prompt(a.original_filename, draft.raw_notes),
                                   schema=ScreenshotAnalysis, images=[ImageInput(a.content_type, files.read(a.stored_name), a.original_filename)],
                                   task="screenshot", context={})
                a.analysis = {**r.output.model_dump(), "provider": r.provider, "model": r.model, "simulated": r.simulated}
            except AIError as exc:
                a.analysis = {"error": exc.user_message}
            db.commit()
            if "error" not in a.analysis:
                screenshot_findings.append({"filename": a.original_filename, **{k: v for k, v in a.analysis.items()
                                            if k in ("visible_ui_state", "displayed_errors", "validation_messages", "contextual_details", "uncertainty_notes")}})
    ctx.progress(50, "Drafting incident…")
    related = []
    for rid in ev.get("related_requirement_ids") or []:
        r = db.query(Requirement).filter_by(project_id=draft.project_id, external_id=str(rid)).first()
        if r:
            related.append({"type": "requirement", "external_id": r.external_id, "name": r.name,
                            "description": (r.description_text or "")[:2000]})
    for tid in ev.get("related_test_case_ids") or []:
        t = db.query(TestCase).filter_by(project_id=draft.project_id, external_id=str(tid)).first()
        if t:
            related.append({"type": "test_case", "external_id": t.external_id, "name": t.name,
                            "steps": [{"n": s.position, "action": s.description, "expected": s.expected_result} for s in t.steps[:15]]})
    context = {
        "notes": draft.raw_notes, "environment": ev.get("environment") or {},
        "expected_behavior": ev.get("expected_behavior"), "actual_behavior": ev.get("actual_behavior"),
        "reproduction_notes": ev.get("reproduction_notes"), "logs": (ev.get("logs") or "")[:15000],
        "api_details": (ev.get("api_details") or "")[:15000],
        "attachments": [{"filename": a.original_filename, "content_type": a.content_type} for a in draft.attachments],
        "screenshot_findings": screenshot_findings, "linked_records": related,
        "related_requirement_ids": ev.get("related_requirement_ids") or [],
        "related_test_case_ids": ev.get("related_test_case_ids") or [],
    }
    provider = provider_for(db)
    result = provider.generate(system=prompts.INCIDENT_SYSTEM, prompt=prompts.incident_prompt(context),
                               schema=IncidentDraftContent, task="incident", context=context)
    ctx.check_cancelled()
    content = result.output.model_dump()
    draft.content = content
    draft.title = content["title"]
    draft.status = "analyzed"
    draft.ai_provider, draft.ai_model, draft.is_simulated = result.provider, result.model, result.simulated
    suggest_classification(db, draft)
    audit.record(db, action="ai.incident_draft", category="ai", outcome="success", user_id=job.created_by_id,
                 project_id=draft.project_id, entity_type="incident_draft", entity_id=draft.id,
                 summary=f"Drafted incident '{content['title'][:80]}' with {result.provider}" + (" (simulated)" if result.simulated else ""),
                 details={"screenshots_analysed": len(screenshot_findings), "usage": result.usage})
    db.commit()
    return {"_status": "NEEDS_REVIEW", "draft_id": draft.id, "simulated": result.simulated}


def suggest_classification(db: Session, draft: IncidentDraft) -> None:
    """Pre-fill classification only from resolvable values; never invent external IDs."""
    c = draft.content or {}
    cls = dict(draft.classification or {})
    sp = dict(cls.get("spira") or {})
    for field, canonical in (("incident_priority", c.get("priority")), ("incident_severity", c.get("severity"))):
        key = "priority_id" if field == "incident_priority" else "severity_id"
        if not sp.get(key):
            r = resolve(db, "spira", draft.project_id, field, canonical)
            if r["id"]:
                sp[key] = r["id"]
    if not sp.get("type_id"):
        d = db.query(ProjectMetadata).filter_by(project_id=draft.project_id, kind="incident_type_default").first()
        if d:
            sp["type_id"] = d.external_id
    if not sp.get("detected_release_id"):
        rel = (c.get("environment") or {}).get("release") or ""
        if rel and rel != "unknown":
            hits = db.query(Release).filter(Release.project_id == draft.project_id,
                                            (Release.version_number == rel) | (Release.name == rel)).all()
            if len(hits) == 1:
                sp["detected_release_id"] = hits[0].external_id
    cls["spira"] = sp
    jr = dict(cls.get("jira") or {})
    jira_cfg = get_config(db, "jira")
    if jira_cfg and not jr.get("issue_type_id"):
        jr["issue_type_id"] = (jira_cfg.settings or {}).get("issue_type_id")
    cls["jira"] = jr
    draft.classification = cls


def update_draft(db: Session, draft: IncidentDraft, data: dict, user_id: int | None) -> IncidentDraft:
    if draft.status in ("submitting",):
        raise ValueError("The draft is being submitted and cannot be edited.")
    if "content" in data and data["content"] is not None:
        content, issues = validate_incident(data["content"])
        if any(i["severity"] == "error" and i["field"] not in ("title", "description") for i in issues):
            raise ValueError("; ".join(i["message"] for i in issues if i["severity"] == "error"))
        draft.content = content
        draft.title = content.get("title", draft.title)
    for key in ("raw_notes", "evidence", "classification"):
        if key in data and data[key] is not None:
            setattr(draft, key, data[key])
    if "destinations" in data and data["destinations"] is not None:
        bad = set(data["destinations"]) - DESTINATIONS
        if bad:
            raise ValueError(f"Unknown destination(s): {', '.join(bad)}")
        draft.destinations = list(dict.fromkeys(data["destinations"]))
    if "title" in data and data["title"] is not None and "content" not in data:
        draft.title = data["title"]
    if draft.status in ("approved", "failed") and draft.status != "submitted":
        draft.status = "analyzed" if draft.content else "draft"
    db.commit()
    return draft


# ---------------------------------------------------------------------- payloads
def _sections(c: dict, draft: IncidentDraft) -> list[tuple[str, object]]:
    env = c.get("environment") or {}
    env_lines = "\n".join(f"{k.replace('_', ' ').title()}: {v}" for k, v in env.items() if v and v != "unknown") or "Not provided"
    facts = [f"{f['statement']} (source: {f['source']})" for f in c.get("observed_facts", [])]
    hyps = [f"{h['statement']} — {h['rationale']}" for h in c.get("hypotheses", [])]
    rel = [f"RQ:{r}" for r in c.get("related_requirement_ids", [])] + [f"TC:{t}" for t in c.get("related_test_case_ids", [])]
    ev = draft.evidence or {}
    return [
        ("Summary", c.get("summary")),
        ("Description", c.get("description")),
        ("Environment", env_lines),
        ("Preconditions", c.get("preconditions") or None),
        ("Steps to reproduce", c.get("steps_to_reproduce") or None),
        ("Expected result", c.get("expected_result")),
        ("Actual result", c.get("actual_result")),
        ("Reproducibility", c.get("reproducibility")),
        ("Impact", c.get("impact")),
        ("Observed facts", ("bullets", facts) if facts else None),
        ("Hypotheses (unverified)", ("bullets", hyps) if hyps else None),
        ("Suggested diagnostics", ("bullets", c.get("suggested_diagnostics")) if c.get("suggested_diagnostics") else None),
        ("API request/response", ("code", ev["api_details"][:8000]) if ev.get("api_details") else None),
        ("Logs", ("code", ev["logs"][:8000]) if ev.get("logs") else None),
        ("Related records", ("bullets", rel) if rel else None),
        ("Open questions", ("bullets", c.get("clarification_questions")) if c.get("clarification_questions") else None),
    ]


def sections_to_html(sections: list[tuple[str, object]], simulated: bool) -> str:
    out = []
    for title, value in sections:
        if value in (None, "", []):
            continue
        out.append(f"<h3>{html.escape(title)}</h3>")
        if isinstance(value, list):
            out.append("<ol>" + "".join(f"<li>{html.escape(str(v))}</li>" for v in value) + "</ol>")
        elif isinstance(value, tuple) and value[0] == "bullets":
            out.append("<ul>" + "".join(f"<li>{html.escape(str(v))}</li>" for v in value[1]) + "</ul>")
        elif isinstance(value, tuple) and value[0] == "code":
            out.append(f"<pre>{html.escape(str(value[1]))}</pre>")
        else:
            out.append("".join(f"<p>{html.escape(p).replace(chr(10), '<br />')}</p>" for p in str(value).split("\n\n")))
    out.append(f"<p><em>Drafted with TouQA AI{' (simulated provider)' if simulated else ''}; reviewed and approved by the reporter.</em></p>")
    return "".join(out)


def spira_required_fields(db: Session, project: Project, type_id: str | None) -> dict:
    """Discover required/hidden fields for the incident type's initial status from the workflow."""
    if not project.template_id or not type_id:
        return {"available": False, "required": [], "hidden": [], "note": "Select an incident type to load workflow rules."}
    default_status = db.query(ProjectMetadata).filter_by(project_id=project.id, kind="incident_status_default").first()
    try:
        with spira_client(db) as client:
            fields = client.incident_type_workflow_fields(int(project.template_id), int(type_id))
    except (IntegrationError, ValueError) as exc:
        return {"available": False, "required": [], "hidden": [], "note": f"Workflow rules unavailable: {getattr(exc, 'user_message', exc)}"}
    status_id = int(default_status.external_id) if default_status else None
    rel = [f for f in fields if status_id is None or f.get("ArtifactStatusId") == status_id]
    req = sorted({f.get("FieldName") for f in rel if WORKFLOW_FIELD_STATES.get(f.get("FieldStateId")) == "required" and f.get("FieldName")})
    hid = sorted({f.get("FieldName") for f in rel if WORKFLOW_FIELD_STATES.get(f.get("FieldStateId")) == "hidden" and f.get("FieldName")})
    return {"available": True, "required": req, "hidden": hid, "status_id": status_id,
            "note": None if default_status else "Default incident status unknown; rules shown for all statuses."}


SPIRA_FIELD_KEYS = {
    "priorityid": "PriorityId", "severityid": "SeverityId", "incidenttypeid": "IncidentTypeId",
    "incidentstatusid": "IncidentStatusId", "ownerid": "OwnerId", "detectedreleaseid": "DetectedReleaseId",
    "resolvedreleaseid": "ResolvedReleaseId", "componentids": "ComponentIds", "name": "Name", "description": "Description",
}


def build_spira_payload(db: Session, project: Project, draft: IncidentDraft, check_workflow: bool = True) -> dict:
    c = draft.content or {}
    sp = (draft.classification or {}).get("spira") or {}
    issues: list[dict] = []
    body: dict = {"Name": (c.get("title") or draft.title or "")[:255],
                  "Description": sections_to_html(_sections(c, draft), draft.is_simulated)}
    pairs = [("priority_id", "PriorityId", "incident_priority"), ("severity_id", "SeverityId", "incident_severity"),
             ("type_id", "IncidentTypeId", "incident_type"), ("status_id", "IncidentStatusId", "incident_status"),
             ("owner_id", "OwnerId", "user"), ("detected_release_id", "DetectedReleaseId", None),
             ("resolved_release_id", "ResolvedReleaseId", None)]
    for key, field, kind in pairs:
        v = sp.get(key)
        if v in (None, ""):
            continue
        if kind:
            ok = db.query(ProjectMetadata).filter_by(project_id=project.id, kind=kind, external_id=str(v)).first()
        else:
            ok = db.query(Release).filter_by(project_id=project.id, external_id=str(v)).first()
        if not ok:
            issues.append({"field": field, "severity": "error", "message": f"{field} {v} is not a known value for this project. Re-sync metadata or reselect."})
            continue
        body[field] = int(v)
    if sp.get("component_ids"):
        body["ComponentIds"] = [int(x) for x in sp["component_ids"]]
    workflow = {"available": False, "required": [], "hidden": []}
    if check_workflow:
        workflow = spira_required_fields(db, project, sp.get("type_id"))
        present = {k.lower() for k in body}
        for f in workflow.get("required", []):
            key = SPIRA_FIELD_KEYS.get(f.lower(), f)
            if key.lower() not in present and f.lower() not in present:
                issues.append({"field": key, "severity": "error",
                               "message": f"Spira workflow requires '{f}' for new incidents of this type."})
    _, content_issues = validate_incident(c) if c else ({}, [{"field": "content", "severity": "error", "message": "Generate or write the incident first."}])
    issues = content_issues + issues
    atts = [a for a in draft.attachments if a.include_in_submission]
    return {"destination": "spira", "endpoint": "POST /projects/{project_id}/incidents", "payload": body,
            "attachments": [{"id": a.id, "filename": a.original_filename, "size_bytes": a.size_bytes,
                             "endpoint": "POST /projects/{project_id}/documents/file"} for a in atts],
            "workflow": workflow, "issues": issues, "blocking": has_errors(issues)}


def build_jira_payload(db: Session, draft: IncidentDraft, fetch_meta: bool = True) -> dict:
    cfg = get_config(db, "jira")
    issues: list[dict] = []
    c = draft.content or {}
    jr = (draft.classification or {}).get("jira") or {}
    if cfg is None or not cfg.base_url:
        return {"destination": "jira", "payload": None, "attachments": [], "issues": [
            {"field": "jira", "severity": "error", "message": "Jira is not configured."}], "blocking": True}
    key = (cfg.settings or {}).get("project_key")
    issue_type = jr.get("issue_type_id") or (cfg.settings or {}).get("issue_type_id")
    if not key:
        issues.append({"field": "project", "severity": "error", "message": "Set the Jira project key in Settings → Integrations → Jira."})
    if not issue_type:
        issues.append({"field": "issuetype", "severity": "error", "message": "Select a Jira issue type."})
    sections = _sections(c, draft)
    description = adf.sections_to_adf(sections) if cfg.flavor == "cloud" else adf.sections_to_wiki(sections)
    fields: dict = {"project": {"key": key}, "summary": (c.get("title") or draft.title or "")[:250],
                    "issuetype": {"id": str(issue_type)} if issue_type else None, "description": description}
    if jr.get("priority_id"):
        fields["priority"] = {"id": str(jr["priority_id"])}
    labels = [l for l in (jr.get("labels") or ["touqa-ai"]) if l and " " not in l]
    if labels:
        fields["labels"] = labels
    for fid, value in (jr.get("fields") or {}).items():
        if value not in (None, "", []):
            fields[fid] = value
    meta = {"available": False, "required": []}
    if fetch_meta and key and issue_type:
        try:
            with jira_client(db) as client:
                cm = client.create_fields(key, str(issue_type))
            allowed_ids = {f.get("fieldId") or f.get("key") for f in cm}
            required = [f for f in cm if f.get("required") and not f.get("hasDefaultValue")]
            meta = {"available": True, "required": [{"id": f.get("fieldId"), "name": f.get("name")} for f in required]}
            for f in required:
                fid = f.get("fieldId") or f.get("key")
                if fid not in fields or fields.get(fid) in (None, "", []):
                    issues.append({"field": fid, "severity": "error", "message": f"Jira requires '{f.get('name')}' ({fid})."})
            for fid in list(fields):
                if fid not in allowed_ids and fid not in ("project", "issuetype", "summary"):
                    issues.append({"field": fid, "severity": "warning" if fid == "labels" else "error",
                                   "message": f"Field '{fid}' is not on the create screen for this issue type."})
                    if fid == "labels":
                        fields.pop("labels")
        except IntegrationError as exc:
            meta = {"available": False, "required": [], "note": exc.user_message}
            issues.append({"field": "metadata", "severity": "warning", "message": f"Could not verify Jira field requirements: {exc.user_message}"})
    fields = {k: v for k, v in fields.items() if v is not None}
    if c:
        issues = validate_incident(c)[1] + issues
    else:
        issues.insert(0, {"field": "content", "severity": "error", "message": "Generate or write the incident first."})
    atts = [a for a in draft.attachments if a.include_in_submission]
    return {"destination": "jira", "endpoint": f"POST {'/rest/api/3' if cfg.flavor == 'cloud' else '/rest/api/2'}/issue",
            "payload": {"fields": fields}, "metadata": meta,
            "attachments": [{"id": a.id, "filename": a.original_filename, "size_bytes": a.size_bytes,
                             "endpoint": "POST /issue/{key}/attachments"} for a in atts],
            "issues": issues, "blocking": has_errors(issues)}


def preview(db: Session, draft: IncidentDraft, *, fetch_meta: bool = True) -> dict:
    project = db.get(Project, draft.project_id)
    dests = draft.destinations or ["spira"]
    out = {}
    if "spira" in dests:
        out["spira"] = build_spira_payload(db, project, draft, check_workflow=fetch_meta)
    if "jira" in dests:
        out["jira"] = build_jira_payload(db, draft, fetch_meta=fetch_meta)
    exact = {k: {"payload": v.get("payload"), "attachments": [a["id"] for a in v.get("attachments", [])]} for k, v in out.items()}
    return {"destinations": out, "payload_hash": operations.payload_hash(exact),
            "blocking": any(v["blocking"] for v in out.values()),
            "rendered_html": sections_to_html(_sections(draft.content or {}, draft), draft.is_simulated) if draft.content else "",
            "previous_results": draft.results or {}}


# -------------------------------------------------------------------- submission
def _upload_attachments(db, draft, dest, upload_fn, ext_id, job_id, user_id, project_id) -> list[dict]:
    results = []
    for a in [a for a in draft.attachments if a.include_in_submission]:
        key = f"{dest}:upload_attachment:{a.id}:{ext_id}"
        op = operations.get_or_create(db, key, platform=dest, operation="upload_attachment", project_id=project_id,
                                      entity_type="attachment", entity_id=a.id, job_id=job_id,
                                      summary={"filename": a.original_filename, "size": a.size_bytes, "target": ext_id})
        if op.status == "succeeded":
            results.append({"attachment_id": a.id, "status": "already_uploaded", "external_id": op.external_id})
            continue
        op.status, op.attempts = "in_flight", op.attempts + 1
        db.commit()
        try:
            data = files.read(a.stored_name)
            ref = upload_fn(a, data)
            op.status, op.external_id, op.error = "succeeded", ref, None
            a.upload_results = {**(a.upload_results or {}), dest: {"status": "uploaded", "external_id": ref}}
            results.append({"attachment_id": a.id, "status": "uploaded", "external_id": ref})
        except OutcomeUnknownError as exc:
            op.status, op.error = "unknown", exc.user_message
            a.upload_results = {**(a.upload_results or {}), dest: {"status": "unknown", "error": exc.user_message}}
            results.append({"attachment_id": a.id, "status": "unknown", "error": exc.user_message})
        except (IntegrationError, files.UploadRejected) as exc:
            msg = getattr(exc, "user_message", str(exc))
            op.status, op.error = "failed", msg
            a.upload_results = {**(a.upload_results or {}), dest: {"status": "failed", "error": msg}}
            results.append({"attachment_id": a.id, "status": "failed", "error": msg})
        audit.record(db, action=f"{dest}.attachment.upload", category="external_write",
                     outcome="success" if op.status == "succeeded" else "failure", user_id=user_id, project_id=project_id,
                     platform=dest, entity_type="attachment", entity_id=a.id,
                     summary=f"{a.original_filename} → {ext_id}: {op.status}")
        db.commit()
    return results


def _submit_spira(db: Session, project: Project, draft: IncidentDraft, job_id: int, user_id: int | None) -> dict:
    built = build_spira_payload(db, project, draft)
    if built["blocking"]:
        return {"status": "skipped_invalid", "issues": [i for i in built["issues"] if i["severity"] == "error"]}
    cfg = get_config(db, "spira")
    pid = int(project.external_id)
    key = f"spira:create_incident:draft:{draft.id}"
    op = operations.get_or_create(db, key, platform="spira", operation="create_incident", project_id=project.id,
                                  entity_type="incident_draft", entity_id=draft.id, job_id=job_id,
                                  summary={"name": built["payload"]["Name"]})
    with spira_client(db) as client:
        inc_id = op.external_id
        if op.status != "succeeded" or not inc_id:
            if not inc_id and op.status in ("in_flight", "unknown"):
                matches = client.search_incidents_by_name(pid, built["payload"]["Name"])
                if len(matches) == 1:
                    inc_id = str(matches[0]["IncidentId"])
                elif len(matches) > 1:
                    op.status, op.error = "unknown", f"{len(matches)} incidents with this name exist; resolve manually."
                    db.commit()
                    return {"status": "needs_attention", "error": op.error}
            if not inc_id:
                op.status, op.attempts = "in_flight", op.attempts + 1
                db.commit()
                try:
                    created = client.create_incident(pid, built["payload"])
                except OutcomeUnknownError as exc:
                    op.status, op.error = "unknown", exc.user_message
                    db.commit()
                    return {"status": "unknown", "error": exc.user_message}
                except IntegrationError as exc:
                    op.status, op.error, op.response_status = "failed", exc.user_message, exc.status_code
                    audit.record(db, action="spira.incident.create", category="external_write", outcome="failure",
                                 user_id=user_id, project_id=project.id, platform="spira", entity_type="incident_draft",
                                 entity_id=draft.id, summary=exc.user_message)
                    db.commit()
                    return {"status": "failed", "error": exc.user_message}
                inc_id = str((created or {}).get("IncidentId") or "")
                if not inc_id:
                    op.status, op.error = "unknown", "Spira did not return an IncidentId"
                    db.commit()
                    return {"status": "unknown", "error": op.error}
            url = spira_artifact_url(cfg.base_url, pid, "incident", inc_id)
            op.status, op.external_id, op.external_url, op.error = "succeeded", inc_id, url, None
            if not db.query(ExternalRecordRef).filter_by(platform="spira", record_type="incident", external_id=inc_id, project_id=project.id).first():
                db.add(ExternalRecordRef(project_id=project.id, platform="spira", record_type="incident", external_id=inc_id,
                                         url=url, local_entity_type="incident_draft", local_entity_id=draft.id))
            if not db.query(Incident).filter_by(project_id=project.id, platform="spira", external_id=inc_id).first():
                db.add(Incident(project_id=project.id, platform="spira", external_id=inc_id, name=built["payload"]["Name"],
                                description_html=built["payload"]["Description"], url=url, raw={}))
            audit.record(db, action="spira.incident.create", category="external_write", outcome="success", user_id=user_id,
                         project_id=project.id, platform="spira", entity_type="incident", entity_id=inc_id,
                         summary=f"Created IN:{inc_id} '{built['payload']['Name'][:80]}'")
            db.commit()

        def up(a: Attachment, data: bytes) -> str:
            doc = client.upload_document(pid, a.original_filename, data, description="Evidence attached via TouQA AI",
                                         artifact="incident", artifact_id=int(inc_id))
            return str((doc or {}).get("AttachmentId") or "")

        att = _upload_attachments(db, draft, "spira", up, inc_id, job_id, user_id, project.id)
    failed_att = [a for a in att if a["status"] not in ("uploaded", "already_uploaded")]
    return {"status": "created_with_attachment_failures" if failed_att else "created", "external_id": inc_id,
            "url": op.external_url, "attachments": att}


def _submit_jira(db: Session, project: Project, draft: IncidentDraft, job_id: int, user_id: int | None) -> dict:
    built = build_jira_payload(db, draft)
    if built["blocking"]:
        return {"status": "skipped_invalid", "issues": [i for i in built["issues"] if i["severity"] == "error"]}
    cfg = get_config(db, "jira")
    project_key = (cfg.settings or {}).get("project_key")
    key = f"jira:create_issue:draft:{draft.id}"
    summary = built["payload"]["fields"]["summary"]
    op = operations.get_or_create(db, key, platform="jira", operation="create_issue", project_id=project.id,
                                  entity_type="incident_draft", entity_id=draft.id, job_id=job_id, summary={"summary": summary})
    with jira_client(db) as client:
        issue_key = op.external_key
        if op.status != "succeeded" or not issue_key:
            if not issue_key and op.status in ("in_flight", "unknown"):
                matches = client.search_by_summary(project_key, summary)
                if len(matches) == 1:
                    issue_key = matches[0].get("key")
                    op.external_id = matches[0].get("id")
                elif len(matches) > 1:
                    op.status, op.error = "unknown", f"{len(matches)} issues with this summary exist; resolve manually."
                    db.commit()
                    return {"status": "needs_attention", "error": op.error}
            if not issue_key:
                op.status, op.attempts = "in_flight", op.attempts + 1
                db.commit()
                try:
                    created = client.create_issue(built["payload"]["fields"])
                except OutcomeUnknownError as exc:
                    op.status, op.error = "unknown", exc.user_message
                    db.commit()
                    return {"status": "unknown", "error": exc.user_message}
                except IntegrationError as exc:
                    op.status, op.error, op.response_status = "failed", exc.user_message, exc.status_code
                    audit.record(db, action="jira.issue.create", category="external_write", outcome="failure", user_id=user_id,
                                 project_id=project.id, platform="jira", entity_type="incident_draft", entity_id=draft.id,
                                 summary=exc.user_message)
                    db.commit()
                    return {"status": "failed", "error": exc.user_message}
                issue_key, op.external_id = (created or {}).get("key"), (created or {}).get("id")
                if not issue_key:
                    op.status, op.error = "unknown", "Jira did not return an issue key"
                    db.commit()
                    return {"status": "unknown", "error": op.error}
            url = client.browse_url(issue_key)
            op.status, op.external_key, op.external_url, op.error = "succeeded", issue_key, url, None
            if not db.query(ExternalRecordRef).filter_by(platform="jira", record_type="issue", external_id=str(op.external_id or issue_key), project_id=project.id).first():
                db.add(ExternalRecordRef(project_id=project.id, platform="jira", record_type="issue",
                                         external_id=str(op.external_id or issue_key), external_key=issue_key, url=url,
                                         local_entity_type="incident_draft", local_entity_id=draft.id))
            audit.record(db, action="jira.issue.create", category="external_write", outcome="success", user_id=user_id,
                         project_id=project.id, platform="jira", entity_type="issue", entity_id=issue_key,
                         summary=f"Created {issue_key} '{summary[:80]}'")
            db.commit()

        def up(a: Attachment, data: bytes) -> str:
            res = client.add_attachment(issue_key, a.original_filename, data, a.content_type)
            return str((res[0] if res else {}).get("id") or "")

        att = _upload_attachments(db, draft, "jira", up, issue_key, job_id, user_id, project.id)
    failed_att = [a for a in att if a["status"] not in ("uploaded", "already_uploaded")]
    return {"status": "created_with_attachment_failures" if failed_att else "created", "external_key": issue_key,
            "external_id": op.external_id, "url": op.external_url, "attachments": att}


def run_incident_submission(ctx: JobContext) -> dict:
    db = ctx.db
    job = ctx.job
    draft = db.get(IncidentDraft, job.params["draft_id"])
    project = db.get(Project, draft.project_id)
    results = dict(draft.results or {})
    for i, dest in enumerate(job.params["destinations"]):
        ctx.check_cancelled()
        ctx.progress(int(i * 100 / len(job.params["destinations"])), f"Submitting to {dest.capitalize()}…")
        try:
            r = _submit_spira(db, project, draft, job.id, job.created_by_id) if dest == "spira" else \
                _submit_jira(db, project, draft, job.id, job.created_by_id)
        except IntegrationError as exc:
            r = {"status": "failed", "error": exc.user_message}
        r["at"] = utcnow().isoformat()
        results[dest] = r
        draft.results = dict(results)
        db.commit()
    created = [d for d in job.params["destinations"] if results.get(d, {}).get("status", "").startswith("created")]
    clean = [d for d in job.params["destinations"] if results.get(d, {}).get("status") == "created"]
    if len(clean) == len(job.params["destinations"]):
        draft.status, status = "submitted", "COMPLETED"
    elif created:
        draft.status, status = "partially_submitted", "PARTIALLY_COMPLETED"
    else:
        draft.status, status = "failed", "FAILED"
        ctx.job.error = "Incident was not created in any destination. See per-destination results."
    db.commit()
    return {"_status": status, "results": results}


def record_approval(db: Session, user_id: int | None, draft: IncidentDraft, phash: str) -> None:
    db.add(ApprovalEvent(user_id=user_id, entity_type="incident_draft", entity_id=draft.id, action="confirm_submission",
                         payload_hash=phash))
    draft.status = "approved"
    db.commit()
