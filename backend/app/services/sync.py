"""Spira → TouQA import and synchronisation.

* Records are upserted by (project_id, external_id); Spira remains authoritative.
* A content hash detects unchanged records; their expensive sub-resources (test steps,
  coverage, test-set membership, attachment lists) are not re-fetched — this is the
  incremental part of the sync, since Spira's list endpoints have no "changed since" filter
  for every entity.
* Each entity type reports discovered / imported / new / updated / skipped / failed counts
  and individual errors. One entity failing does not abort the others.
* Records missing from a complete, error-free entity pass are flagged
  ``is_deleted_externally`` (never hard-deleted locally).
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from sqlalchemy.orm import Session

from app.db import utcnow
from app.integrations.http import IntegrationError, OperationCancelled
from app.integrations.spira import mapper
from app.integrations.spira.client import SpiraClient
from app.models import (
    ExternalAttachment, Folder, Incident, Project, ProjectMetadata, Release, Requirement,
    RequirementTestCase, SyncEntityResult, TestCase, TestSet, TestSetTestCase, TestStep,
)
from app.services import audit
from app.services.integrations import spira_client
from app.services.jobs import JobContext

log = logging.getLogger("touqa.sync")

ENTITY_ORDER = ["metadata", "releases", "folders", "requirements", "test_cases", "test_sets", "incidents"]
DEFAULT_OPTIONS = {
    "include_test_steps": True,
    "include_requirement_coverage": True,
    "include_requirement_steps": False,
    "include_test_set_membership": True,
    "include_incident_attachments": False,
}


class EntitySync:
    """Accumulates per-entity counters and persists them to SyncEntityResult."""

    def __init__(self, db: Session, row: SyncEntityResult):
        self.db, self.row = db, row
        self.errors: list[dict] = []
        self.notes: list[str] = []

    def start(self):
        self.row.status, self.row.started_at = "RUNNING", utcnow()
        self.db.commit()

    def fail_record(self, external_id: Any, message: str):
        self.row.failed += 1
        if len(self.errors) < 200:
            self.errors.append({"external_id": str(external_id), "error": message[:500]})

    def note(self, text: str):
        self.notes.append(text)

    def flush(self):
        self.row.errors = list(self.errors)
        self.row.notes = list(self.notes)
        self.db.commit()

    def finish(self, status: str | None = None):
        if status is None:
            status = "PARTIALLY_COMPLETED" if self.row.failed else "COMPLETED"
        self.row.status, self.row.finished_at = status, utcnow()
        self.flush()


def _upsert(db: Session, model, existing: dict[str, Any], data: dict, raw: dict, project_id: int,
            es: EntitySync, extra_filter: dict | None = None) -> tuple[Any, bool]:
    """Returns (row, changed)."""
    h = mapper.content_hash(raw)
    ext = data["external_id"]
    row = existing.get(ext)
    clean_raw = {k: v for k, v in raw.items() if k not in ("CustomProperties", "TestSteps", "Steps")}
    if row is None:
        row = model(project_id=project_id, raw=clean_raw, content_hash=h, **(extra_filter or {}), **data)
        db.add(row)
        existing[ext] = row
        es.row.created += 1
        changed = True
    elif row.content_hash == h and not row.is_deleted_externally:
        es.row.skipped += 1
        changed = False
    else:
        for k, v in data.items():
            setattr(row, k, v)
        row.raw, row.content_hash, row.is_deleted_externally = clean_raw, h, False
        es.row.updated += 1
        changed = True
    row.synced_at = utcnow()
    es.row.imported += 1
    return row, changed


def _flag_missing(existing: dict[str, Any], seen: set[str], es: EntitySync, complete: bool) -> None:
    if not complete:
        return
    missing = [r for ext, r in existing.items() if ext not in seen and not r.is_deleted_externally]
    for r in missing:
        r.is_deleted_externally = True
    if missing:
        es.note(f"{len(missing)} previously imported record(s) no longer returned by Spira; flagged as deleted externally.")


def _iter_pages(pages: Iterable[list[dict]], es: EntitySync, ctx: JobContext) -> Iterable[dict]:
    for page in pages:
        ctx.check_cancelled()
        es.row.discovered += len(page)
        yield from page


# ----------------------------------------------------------------------- entities
def sync_metadata(db: Session, client: SpiraClient, project: Project, es: EntitySync, ctx: JobContext, opts: dict) -> None:
    pid = int(project.external_id)
    tid = int(project.template_id) if project.template_id else None
    existing = {(m.kind, m.external_id): m for m in db.query(ProjectMetadata).filter_by(project_id=project.id)}

    def put(kind: str, ext_id: Any, name: str, data: dict | None = None, active: bool = True):
        key = (kind, str(ext_id))
        es.row.discovered += 1
        row = existing.get(key)
        if row is None:
            row = ProjectMetadata(project_id=project.id, kind=kind, external_id=str(ext_id), name=name or "", data=data or {}, active=active)
            db.add(row)
            existing[key] = row
            es.row.created += 1
        else:
            row.name, row.data, row.active, row.synced_at = name or "", data or {}, active, utcnow()
            es.row.updated += 1
        es.row.imported += 1

    def attempt(label: str, fn: Callable[[], None]):
        try:
            ctx.check_cancelled()
            fn()
        except OperationCancelled:
            raise
        except IntegrationError as exc:
            es.fail_record(label, exc.user_message)

    def users():
        for u in client.project_users(pid):
            uid, name, data = mapper.map_user(u)
            put("user", uid, name, data, bool(u.get("Active", True)))

    def components():
        for c in client.components(pid):
            put("component", c["ComponentId"], c.get("Name"), {}, bool(c.get("IsActive", True)) and not c.get("IsDeleted"))

    attempt("users", users)
    attempt("components", components)
    if tid is None:
        es.note("Project template ID unknown; template-level lists (priorities, statuses, types) were skipped.")
    else:
        lists = [
            ("incidents", "priorities", "incident_priority", "PriorityId"),
            ("incidents", "severities", "incident_severity", "SeverityId"),
            ("incidents", "types", "incident_type", "IncidentTypeId"),
            ("incidents", "statuses", "incident_status", "IncidentStatusId"),
            ("test-cases", "priorities", "test_case_priority", "TestCasePriorityId"),
            ("test-cases", "statuses", "test_case_status", "TestCaseStatusId"),
            ("test-cases", "types", "test_case_type", "TestCaseTypeId"),
            ("requirements", "statuses", "requirement_status", "RequirementStatusId"),
            ("requirements", "types", "requirement_type", "RequirementTypeId"),
            ("requirements", "importances", "requirement_importance", "ImportanceId"),
        ]
        for artifact, kind, local_kind, id_key in lists:
            def load(artifact=artifact, kind=kind, local_kind=local_kind, id_key=id_key):
                for item in client.template_list(tid, artifact, kind):
                    ext = item.get(id_key)
                    if ext is None:
                        ext = next((v for k, v in item.items() if k.endswith("Id") and isinstance(v, int)), None)
                    if ext is None:
                        continue
                    put(local_kind, ext, item.get("Name"), {k: v for k, v in item.items() if k in
                        ("Open", "Default", "Score", "Color", "IsDefault", "Issue", "Risk", "WorkflowId", "Position")},
                        bool(item.get("Active", True)))
            attempt(f"{artifact}/{kind}", load)

        def defaults():
            st = client.default_incident_status(tid)
            if st and st.get("IncidentStatusId") is not None:
                put("incident_status_default", st["IncidentStatusId"], st.get("Name"))
            ty = client.default_incident_type(tid)
            if ty and ty.get("IncidentTypeId") is not None:
                put("incident_type_default", ty["IncidentTypeId"], ty.get("Name"))
        attempt("incident defaults", defaults)

        for art in ("Requirement", "TestCase", "Incident"):
            def cps(art=art):
                for cp in client.custom_property_definitions(tid, art):
                    if cp.get("IsDeleted"):
                        continue
                    put(f"custom_property:{art}", cp.get("PropertyNumber") or cp.get("CustomPropertyId"), cp.get("Name"), {
                        "field_name": cp.get("CustomPropertyFieldName"), "type": cp.get("CustomPropertyTypeName"),
                        "property_number": cp.get("PropertyNumber"),
                        "options": [{"name": (o or {}).get("Name"), "value": (o or {}).get("Value")} for o in (cp.get("Options") or []) if isinstance(o, dict)],
                        "list_values": [{"id": v.get("CustomPropertyValueId"), "name": v.get("Name")}
                                        for v in ((cp.get("CustomList") or {}).get("Values") or []) if isinstance(v, dict)],
                    })
            attempt(f"custom properties {art}", cps)
    es.flush()


def sync_releases(db, client: SpiraClient, project: Project, es: EntitySync, ctx: JobContext, opts) -> None:
    existing = {r.external_id: r for r in db.query(Release).filter_by(project_id=project.id)}
    seen: set[str] = set()
    records = client.releases(int(project.external_id), cancel_check=ctx.is_cancel_requested)
    es.row.discovered = len(records)
    for r in records:
        try:
            data = mapper.map_release(r)
            _upsert(db, Release, existing, data, r, project.id, es)
            seen.add(data["external_id"])
        except (KeyError, TypeError, ValueError) as exc:
            es.fail_record(r.get("ReleaseId"), f"Could not map release: {exc}")
    _flag_missing(existing, seen, es, es.row.failed == 0)
    es.flush()


def sync_folders(db, client: SpiraClient, project: Project, es: EntitySync, ctx: JobContext, opts) -> None:
    pid = int(project.external_id)
    for ftype, loader in (("test_case", client.test_case_folders), ("test_set", client.test_set_folders)):
        ctx.check_cancelled()
        existing = {f.external_id: f for f in db.query(Folder).filter_by(project_id=project.id, folder_type=ftype)}
        seen: set[str] = set()
        try:
            records = loader(pid)
        except IntegrationError as exc:
            es.fail_record(f"{ftype}_folders", exc.user_message)
            continue
        es.row.discovered += len(records)
        for r in records:
            try:
                data = mapper.map_folder(r, ftype)
                data.pop("folder_type")
                _upsert(db, Folder, existing, data, r, project.id, es, extra_filter={"folder_type": ftype})
                seen.add(data["external_id"])
            except (KeyError, TypeError, ValueError) as exc:
                es.fail_record(r.get("TestCaseFolderId") or r.get("TestSetFolderId"), f"Could not map folder: {exc}")
        _flag_missing(existing, seen, es, True)
    es.flush()


def sync_requirements(db, client: SpiraClient, project: Project, es: EntitySync, ctx: JobContext, opts) -> None:
    pid = int(project.external_id)
    existing = {r.external_id: r for r in db.query(Requirement).filter_by(project_id=project.id)}
    seen: set[str] = set()
    changed_with_coverage: list[Requirement] = []
    changed_rows: list[Requirement] = []
    for r in _iter_pages(client.iter_requirements(pid, cancel_check=ctx.is_cancel_requested), es, ctx):
        try:
            data = mapper.map_requirement(r)
            row, changed = _upsert(db, Requirement, existing, data, r, project.id, es)
            seen.add(data["external_id"])
            if changed:
                changed_rows.append(row)
                if (r.get("CoverageCountTotal") or 0) > 0:
                    changed_with_coverage.append(row)
        except (KeyError, TypeError, ValueError) as exc:
            es.fail_record(r.get("RequirementId"), f"Could not map requirement: {exc}")
        if es.row.imported % 250 == 0:
            es.flush()
    db.flush()

    # Hierarchy: Spira IndentLevel encodes the tree in 3-character segments.
    by_indent = {r.indent_level: r for r in existing.values() if r.indent_level and not r.is_deleted_externally}
    for r in existing.values():
        parent = by_indent.get(r.indent_level[:-3]) if r.indent_level and len(r.indent_level) > 3 else None
        r.parent_id = parent.id if parent else None

    try:
        expected = client.count_requirements(pid)
        if expected is not None and expected != len(seen):
            es.note(f"Spira reports {expected} requirements; {len(seen)} were returned by the list endpoint.")
    except IntegrationError:
        pass

    if opts.get("include_requirement_coverage"):
        for i, row in enumerate(changed_with_coverage):
            ctx.check_cancelled()
            try:
                links = client.requirement_coverage(pid, int(row.external_id), cancel_check=ctx.is_cancel_requested)
                current = {l.test_case_external_id: l for l in db.query(RequirementTestCase).filter_by(
                    project_id=project.id, requirement_external_id=row.external_id)}
                remote = {str(l["TestCaseId"]) for l in links if l.get("TestCaseId") is not None}
                for tc in remote - set(current):
                    db.add(RequirementTestCase(project_id=project.id, requirement_external_id=row.external_id, test_case_external_id=tc))
                for tc in set(current) - remote:
                    db.delete(current[tc])
            except IntegrationError as exc:
                es.fail_record(row.external_id, f"Coverage: {exc.user_message}")
            if i % 50 == 0:
                ctx.progress(ctx.job.progress, f"Requirements: coverage {i + 1}/{len(changed_with_coverage)}")
        # Requirements whose coverage count dropped to zero lose their links.
        for row in changed_rows:
            if (row.coverage or {}).get("total") in (0, None) and row not in changed_with_coverage:
                db.query(RequirementTestCase).filter_by(project_id=project.id, requirement_external_id=row.external_id).delete()
    if opts.get("include_requirement_steps"):
        for row in changed_rows:
            ctx.check_cancelled()
            try:
                steps = client.requirement_steps(pid, int(row.external_id), cancel_check=ctx.is_cancel_requested)
                row.steps = [{"position": s.get("Position"), "description": mapper.html_to_text(s.get("Description"))} for s in steps]
            except IntegrationError as exc:
                es.fail_record(row.external_id, f"Steps: {exc.user_message}")
    _flag_missing(existing, seen, es, es.row.failed == 0)
    es.flush()


def sync_test_cases(db, client: SpiraClient, project: Project, es: EntitySync, ctx: JobContext, opts) -> None:
    pid = int(project.external_id)
    existing = {t.external_id: t for t in db.query(TestCase).filter_by(project_id=project.id)}
    seen: set[str] = set()
    needs_steps: list[tuple[TestCase, dict]] = []

    def consume(records: Iterable[dict]):
        for r in records:
            try:
                data = mapper.map_test_case(r)
                if data["external_id"] in seen:
                    es.row.discovered -= 1
                    continue
                row, changed = _upsert(db, TestCase, existing, data, r, project.id, es)
                seen.add(data["external_id"])
                if changed and r.get("IsTestSteps", True):
                    needs_steps.append((row, r))
            except (KeyError, TypeError, ValueError) as exc:
                es.fail_record(r.get("TestCaseId"), f"Could not map test case: {exc}")
            if es.row.imported % 250 == 0:
                es.flush()

    consume(_iter_pages(client.iter_test_cases(pid, cancel_check=ctx.is_cancel_requested), es, ctx))
    complete = True
    try:
        expected = client.count_test_cases(pid)
    except IntegrationError:
        expected = None
    if expected is not None and len(seen) < expected:
        es.note(f"Project list returned {len(seen)} of {expected} test cases; scanning folders for the rest.")
        folders = db.query(Folder).filter_by(project_id=project.id, folder_type="test_case", is_deleted_externally=False).all()
        for f in folders:
            ctx.check_cancelled()
            try:
                consume(_iter_pages(client.iter_test_cases_in_folder(pid, int(f.external_id), cancel_check=ctx.is_cancel_requested), es, ctx))
            except IntegrationError as exc:
                complete = False
                es.fail_record(f"folder {f.external_id}", exc.user_message)
        if len(seen) < expected:
            complete = False
            es.note(f"{expected - len(seen)} test case(s) reported by Spira could not be retrieved (possibly permissions).")
    db.flush()

    if opts.get("include_test_steps"):
        for i, (row, raw) in enumerate(needs_steps):
            ctx.check_cancelled()
            try:
                steps = client.test_steps(pid, int(row.external_id), cancel_check=ctx.is_cancel_requested)
                current = {s.external_id: s for s in row.steps}
                remote_ids = set()
                for s in steps:
                    sd = mapper.map_test_step(s)
                    remote_ids.add(sd["external_id"])
                    st = current.get(sd["external_id"])
                    if st is None:
                        row.steps.append(TestStep(**sd))
                    else:
                        for k, v in sd.items():
                            setattr(st, k, v)
                for ext, st in current.items():
                    if ext not in remote_ids:
                        row.steps.remove(st)
            except IntegrationError as exc:
                es.fail_record(row.external_id, f"Test steps: {exc.user_message}")
            if i % 50 == 0:
                es.flush()
                ctx.progress(ctx.job.progress, f"Test cases: steps {i + 1}/{len(needs_steps)}")
    _flag_missing(existing, seen, es, complete and es.row.failed == 0)
    es.flush()


def sync_test_sets(db, client: SpiraClient, project: Project, es: EntitySync, ctx: JobContext, opts) -> None:
    pid = int(project.external_id)
    existing = {t.external_id: t for t in db.query(TestSet).filter_by(project_id=project.id)}
    seen: set[str] = set()
    changed: list[TestSet] = []
    for r in _iter_pages(client.iter_test_sets(pid, cancel_check=ctx.is_cancel_requested), es, ctx):
        try:
            data = mapper.map_test_set(r)
            row, ch = _upsert(db, TestSet, existing, data, r, project.id, es)
            seen.add(data["external_id"])
            if ch:
                changed.append(row)
        except (KeyError, TypeError, ValueError) as exc:
            es.fail_record(r.get("TestSetId"), f"Could not map test set: {exc}")
    db.flush()
    if opts.get("include_test_set_membership"):
        for row in changed:
            ctx.check_cancelled()
            try:
                maps = client.test_set_mappings(pid, int(row.external_id), cancel_check=ctx.is_cancel_requested)
                db.query(TestSetTestCase).filter_by(test_set_id=row.id).delete()
                for m in maps:
                    if m.get("TestSetTestCaseId") is None:
                        continue
                    db.add(TestSetTestCase(test_set_id=row.id, external_id=str(m["TestSetTestCaseId"]),
                                           test_case_external_id=str(m.get("TestCaseId")), position=m.get("Position"),
                                           owner_external_id=str(m["OwnerId"]) if m.get("OwnerId") else None))
            except IntegrationError as exc:
                es.fail_record(row.external_id, f"Membership: {exc.user_message}")
    _flag_missing(existing, seen, es, es.row.failed == 0)
    es.flush()


def sync_incidents(db, client: SpiraClient, project: Project, es: EntitySync, ctx: JobContext, opts) -> None:
    pid = int(project.external_id)
    existing = {i.external_id: i for i in db.query(Incident).filter_by(project_id=project.id, platform="spira")}
    seen: set[str] = set()
    changed: list[Incident] = []
    from app.integrations.spira.client import spira_artifact_url
    from app.services.integrations import get_config

    cfg = get_config(db, "spira")
    for r in _iter_pages(client.iter_incidents(pid, cancel_check=ctx.is_cancel_requested), es, ctx):
        try:
            data = mapper.map_incident(r)
            if cfg:
                data["url"] = spira_artifact_url(cfg.base_url, pid, "incident", data["external_id"])
            row, ch = _upsert(db, Incident, existing, data, r, project.id, es, extra_filter={"platform": "spira"})
            seen.add(data["external_id"])
            if ch and r.get("IsAttachments"):
                changed.append(row)
        except (KeyError, TypeError, ValueError) as exc:
            es.fail_record(r.get("IncidentId"), f"Could not map incident: {exc}")
        if es.row.imported % 250 == 0:
            es.flush()
    try:
        expected = client.count_incidents(pid)
        if expected is not None and expected != len(seen):
            es.note(f"Spira reports {expected} incidents; {len(seen)} were returned by the search endpoint.")
    except IntegrationError:
        pass
    db.flush()
    if opts.get("include_incident_attachments"):
        for row in changed:
            ctx.check_cancelled()
            try:
                docs = client.artifact_documents(pid, "incident", int(row.external_id), cancel_check=ctx.is_cancel_requested)
                for d in docs:
                    if d.get("AttachmentId") is None:
                        continue
                    key = dict(project_id=project.id, artifact_type="incident", artifact_external_id=row.external_id,
                               external_id=str(d["AttachmentId"]))
                    att = db.query(ExternalAttachment).filter_by(**key).one_or_none() or ExternalAttachment(**key, filename="")
                    att.filename = d.get("FilenameOrUrl") or ""
                    att.size_bytes = d.get("Size")
                    att.author_name = d.get("AuthorName")
                    att.uploaded_at = mapper.parse_date(d.get("UploadDate"))
                    att.synced_at = utcnow()
                    db.add(att)
            except IntegrationError as exc:
                es.fail_record(row.external_id, f"Attachments: {exc.user_message}")
    _flag_missing(existing, seen, es, es.row.failed == 0)
    es.flush()


HANDLERS = {
    "metadata": sync_metadata, "releases": sync_releases, "folders": sync_folders,
    "requirements": sync_requirements, "test_cases": sync_test_cases,
    "test_sets": sync_test_sets, "incidents": sync_incidents,
}


def create_entity_rows(db: Session, job_id: int, entities: list[str]) -> None:
    for e in entities:
        db.add(SyncEntityResult(job_id=job_id, entity_type=e))
    db.commit()


def run_sync(ctx: JobContext) -> dict:
    db = ctx.db
    job = ctx.job
    project = db.get(Project, job.project_id)
    entities = [e for e in ENTITY_ORDER if e in (job.params.get("entities") or ENTITY_ORDER)]
    opts = {**DEFAULT_OPTIONS, **(job.params.get("options") or {})}
    rows = {r.entity_type: r for r in db.query(SyncEntityResult).filter_by(job_id=job.id)}
    summary: dict[str, dict] = {}
    with spira_client(db) as client:
        for idx, entity in enumerate(entities):
            ctx.check_cancelled()
            ctx.progress(int(idx * 100 / len(entities)), f"Importing {entity.replace('_', ' ')}…")
            es = EntitySync(db, rows[entity])
            es.start()
            try:
                HANDLERS[entity](db, client, project, es, ctx, opts)
                db.commit()
                es.finish()
            except OperationCancelled:
                db.commit()
                es.finish("CANCELLED")
                raise
            except IntegrationError as exc:
                db.rollback()
                es = EntitySync(db, db.get(SyncEntityResult, rows[entity].id))
                es.errors.append({"external_id": None, "error": exc.user_message})
                es.finish("FAILED")
            except Exception as exc:  # noqa: BLE001 - isolate entity failures
                log.exception("Sync of %s failed", entity)
                db.rollback()
                es = EntitySync(db, db.get(SyncEntityResult, rows[entity].id))
                es.errors.append({"external_id": None, "error": f"Unexpected error: {exc.__class__.__name__}: {exc}"})
                es.finish("FAILED")
            r = db.get(SyncEntityResult, rows[entity].id)
            summary[entity] = {"status": r.status, "discovered": r.discovered, "imported": r.imported, "created": r.created,
                               "updated": r.updated, "skipped": r.skipped, "failed": r.failed}
    project = db.get(Project, job.project_id)
    project.last_synced_at = utcnow()
    statuses = {v["status"] for v in summary.values()}
    if statuses == {"COMPLETED"}:
        overall = "COMPLETED"
    elif statuses <= {"FAILED"}:
        overall = "FAILED"
    else:
        overall = "PARTIALLY_COMPLETED"
    audit.record(db, action="spira.sync", category="import", outcome={"COMPLETED": "success", "FAILED": "failure"}.get(overall, "partial"),
                 user_id=job.created_by_id, project_id=project.id, platform="spira", entity_type="job", entity_id=job.id,
                 summary=f"Sync {overall.lower().replace('_', ' ')}: " + ", ".join(f"{k} {v['imported']}" for k, v in summary.items()),
                 details=summary)
    db.commit()
    if overall == "FAILED":
        job = ctx.job
        job.error = "All selected entity imports failed. See entity details."
    return {"_status": overall, "entities": summary}
