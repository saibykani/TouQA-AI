"""Read APIs for synchronised records: requirements, test cases, test sets, incidents, releases, folders, search."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, desc, or_
from sqlalchemy.orm import Session

from app.api.v1.projects import get_project
from app.db import get_db
from app.integrations.spira.client import spira_artifact_url
from app.models import (
    ExternalAttachment, Folder, Incident, Release, Requirement, RequirementAnalysis, RequirementTestCase,
    TestCase, TestSet, TestSetTestCase, User,
)
from app.security.auth import current_user
from app.services import folders as fsvc
from app.services.context import linked_test_cases, related_incidents, resolve_custom_properties
from app.services.integrations import get_config

router = APIRouter(tags=["records"])


def _page(q, page: int, page_size: int, mapper):
    page_size = max(1, min(page_size, 200))
    total = q.count()
    rows = q.offset((max(page, 1) - 1) * page_size).limit(page_size).all()
    return {"items": [mapper(r) for r in rows], "total": total, "page": page, "page_size": page_size}


def _sort(q, model, sort: str | None, default: str):
    field = (sort or default).lstrip("-")
    col = getattr(model, field, None)
    if col is None:
        col = getattr(model, default.lstrip("-"))
    return q.order_by(desc(col) if (sort or default).startswith("-") else asc(col))


def _url(db: Session, project, artifact: str, ext: str) -> str | None:
    if project.is_demo:
        return None
    cfg = get_config(db, "spira")
    return spira_artifact_url(cfg.base_url, project.external_id, artifact, ext) if cfg and cfg.base_url else None


# ------------------------------------------------------------------ requirements
def req_row(r: Requirement) -> dict:
    return {"id": r.id, "external_id": r.external_id, "name": r.name, "status": r.status_name, "type": r.type_name,
            "importance": r.importance_name, "owner": r.owner_name, "release": r.release_version,
            "release_external_id": r.release_external_id, "indent_level": r.indent_level, "is_summary": r.is_summary,
            "parent_id": r.parent_id, "coverage": r.coverage, "updated_at": r.external_updated_at,
            "is_deleted_externally": r.is_deleted_externally}


@router.get("/requirements")
def list_requirements(project_id: int, q: str | None = None, status: str | None = None, release: str | None = None,
                      owner: str | None = None, importance: str | None = None, parent_id: int | None = None,
                      include_summary: bool = True, sort: str | None = None, page: int = 1, page_size: int = 50,
                      db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_project(db, project_id)
    query = db.query(Requirement).filter(Requirement.project_id == project_id)
    if q:
        term = f"%{q.strip()}%"
        idq = q.strip().upper().removeprefix("RQ:").strip()
        query = query.filter(or_(Requirement.name.ilike(term), Requirement.description_text.ilike(term), Requirement.external_id == idq))
    for col, val in ((Requirement.status_name, status), (Requirement.release_external_id, release),
                     (Requirement.owner_name, owner), (Requirement.importance_name, importance)):
        if val:
            query = query.filter(col == val)
    if parent_id is not None:
        query = query.filter(Requirement.parent_id == parent_id)
    if not include_summary:
        query = query.filter(Requirement.is_summary.is_(False))
    query = _sort(query, Requirement, sort, "indent_level")
    return _page(query, page, page_size, req_row)


@router.get("/requirements/facets")
def requirement_facets(project_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_project(db, project_id)
    base = db.query(Requirement).filter(Requirement.project_id == project_id)

    def distinct(col):
        return sorted({v for (v,) in base.with_entities(col).distinct() if v})

    releases = [{"external_id": r.external_id, "name": r.name, "version": r.version_number}
                for r in db.query(Release).filter_by(project_id=project_id).order_by(Release.indent_level)]
    return {"statuses": distinct(Requirement.status_name), "owners": distinct(Requirement.owner_name),
            "importances": distinct(Requirement.importance_name), "types": distinct(Requirement.type_name), "releases": releases}


@router.get("/requirements/tree")
def requirement_tree(project_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_project(db, project_id)
    rows = db.query(Requirement).filter_by(project_id=project_id, is_deleted_externally=False).order_by(Requirement.indent_level).all()
    nodes = {r.id: {"id": r.id, "external_id": r.external_id, "name": r.name, "is_summary": r.is_summary,
                    "status": r.status_name, "children": []} for r in rows}
    roots = []
    for r in rows:
        (nodes[r.parent_id]["children"] if r.parent_id in nodes else roots).append(nodes[r.id])
    return roots


@router.get("/requirements/{requirement_id}")
def requirement_detail(requirement_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    r = db.get(Requirement, requirement_id)
    if r is None:
        raise HTTPException(404, "Requirement not found")
    project = get_project(db, r.project_id)
    parent = db.get(Requirement, r.parent_id) if r.parent_id else None
    children = db.query(Requirement).filter_by(parent_id=r.id).order_by(Requirement.indent_level).all()
    tcs = linked_test_cases(db, r)
    linked_ext = {l.test_case_external_id for l in db.query(RequirementTestCase).filter_by(project_id=r.project_id, requirement_external_id=r.external_id)}
    analyses = db.query(RequirementAnalysis).filter_by(requirement_id=r.id).order_by(RequirementAnalysis.created_at.desc()).all()
    return {
        **req_row(r),
        "description_html": r.description_html, "description_text": r.description_text, "author": r.author_name,
        "tags": r.tags, "steps": r.steps,
        "custom_properties": resolve_custom_properties(db, r.project_id, "Requirement", r.custom_properties),
        "created_at": r.external_created_at, "synced_at": r.synced_at, "url": _url(db, project, "requirement", r.external_id),
        "parent": {"id": parent.id, "external_id": parent.external_id, "name": parent.name} if parent else None,
        "children": [req_row(c) for c in children],
        "linked_test_cases": [{"id": t.id, "external_id": t.external_id, "name": t.name, "status": t.status_name,
                               "execution_status": t.execution_status_name, "step_count": len(t.steps)} for t in tcs],
        "unresolved_test_case_links": sorted(linked_ext - {t.external_id for t in tcs}),
        "related_incidents": related_incidents(db, r, limit=8),
        "analyses": [{"id": a.id, "status": a.status, "provider": a.provider, "model": a.model, "is_simulated": a.is_simulated,
                      "created_at": a.created_at, "approved_at": a.approved_at} for a in analyses],
        "sync": {"external_updated_at": r.external_updated_at, "synced_at": r.synced_at, "content_hash": r.content_hash[:12]},
    }


# -------------------------------------------------------------------- test cases
def tc_row(t: TestCase) -> dict:
    return {"id": t.id, "external_id": t.external_id, "name": t.name, "status": t.status_name, "type": t.type_name,
            "priority": t.priority_name, "owner": t.owner_name, "execution_status": t.execution_status_name,
            "folder_external_id": t.folder_external_id, "origin": t.origin, "updated_at": t.external_updated_at,
            "is_deleted_externally": t.is_deleted_externally}


@router.get("/test-cases")
def list_test_cases(project_id: int, q: str | None = None, folder_external_id: str | None = None, status: str | None = None,
                    priority: str | None = None, origin: str | None = None, sort: str | None = None, page: int = 1,
                    page_size: int = 50, db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_project(db, project_id)
    query = db.query(TestCase).filter(TestCase.project_id == project_id)
    if q:
        idq = q.strip().upper().removeprefix("TC:").strip()
        query = query.filter(or_(TestCase.name.ilike(f"%{q}%"), TestCase.description_text.ilike(f"%{q}%"), TestCase.external_id == idq))
    for col, val in ((TestCase.folder_external_id, folder_external_id), (TestCase.status_name, status),
                     (TestCase.priority_name, priority), (TestCase.origin, origin)):
        if val:
            query = query.filter(col == val)
    return _page(_sort(query, TestCase, sort, "name"), page, page_size, tc_row)


@router.get("/test-cases/{test_case_id}")
def test_case_detail(test_case_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    t = db.get(TestCase, test_case_id)
    if t is None:
        raise HTTPException(404, "Test case not found")
    project = get_project(db, t.project_id)
    req_ext = [l.requirement_external_id for l in db.query(RequirementTestCase).filter_by(project_id=t.project_id, test_case_external_id=t.external_id)]
    reqs = db.query(Requirement).filter(Requirement.project_id == t.project_id, Requirement.external_id.in_(req_ext or ["-"])).all()
    sets = (db.query(TestSet).join(TestSetTestCase, TestSetTestCase.test_set_id == TestSet.id)
            .filter(TestSet.project_id == t.project_id, TestSetTestCase.test_case_external_id == t.external_id).all())
    return {**tc_row(t), "description_html": t.description_html, "description_text": t.description_text, "tags": t.tags,
            "author": t.author_name, "folder_path": fsvc.path_of(db, t.project_id, t.folder_external_id),
            "custom_properties": resolve_custom_properties(db, t.project_id, "TestCase", t.custom_properties),
            "steps": [{"position": s.position, "description": s.description, "expected_result": s.expected_result,
                       "sample_data": s.sample_data, "precondition": s.precondition,
                       "linked_test_case_external_id": s.linked_test_case_external_id} for s in t.steps],
            "requirements": [{"id": r.id, "external_id": r.external_id, "name": r.name} for r in reqs],
            "test_sets": [{"id": s.id, "external_id": s.external_id, "name": s.name} for s in sets],
            "url": _url(db, project, "test_case", t.external_id), "synced_at": t.synced_at}


# --------------------------------------------------------------------- test sets
@router.get("/test-sets")
def list_test_sets(project_id: int, q: str | None = None, release: str | None = None, status: str | None = None,
                   sort: str | None = None, page: int = 1, page_size: int = 50, db: Session = Depends(get_db),
                   _: User = Depends(current_user)):
    get_project(db, project_id)
    query = db.query(TestSet).filter(TestSet.project_id == project_id)
    if q:
        query = query.filter(or_(TestSet.name.ilike(f"%{q}%"), TestSet.external_id == q.strip().upper().removeprefix("TX:")))
    if release:
        query = query.filter(TestSet.release_external_id == release)
    if status:
        query = query.filter(TestSet.status_name == status)

    def row(s: TestSet):
        return {"id": s.id, "external_id": s.external_id, "name": s.name, "status": s.status_name, "owner": s.owner_name,
                "release": s.release_version, "planned_date": s.planned_date, "counts": s.counts,
                "folder_external_id": s.folder_external_id,
                "test_case_count": db.query(TestSetTestCase).filter_by(test_set_id=s.id).count()}
    return _page(_sort(query, TestSet, sort, "name"), page, page_size, row)


@router.get("/test-sets/{test_set_id}")
def test_set_detail(test_set_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    s = db.get(TestSet, test_set_id)
    if s is None:
        raise HTTPException(404, "Test set not found")
    project = get_project(db, s.project_id)
    members = db.query(TestSetTestCase).filter_by(test_set_id=s.id).order_by(TestSetTestCase.position).all()
    tcs = {t.external_id: t for t in db.query(TestCase).filter(TestCase.project_id == s.project_id,
                                                              TestCase.external_id.in_([m.test_case_external_id for m in members] or ["-"]))}
    return {"id": s.id, "external_id": s.external_id, "name": s.name, "status": s.status_name, "owner": s.owner_name,
            "release": s.release_version, "planned_date": s.planned_date, "counts": s.counts,
            "description_text": s.description_text, "folder_path": fsvc.path_of(db, s.project_id, s.folder_external_id, "test_set"),
            "test_cases": [{"position": m.position, "test_case_external_id": m.test_case_external_id,
                            "id": tcs[m.test_case_external_id].id if m.test_case_external_id in tcs else None,
                            "name": tcs[m.test_case_external_id].name if m.test_case_external_id in tcs else None} for m in members],
            "url": _url(db, project, "test_set", s.external_id)}


# --------------------------------------------------------------------- incidents
def inc_row(i: Incident) -> dict:
    return {"id": i.id, "external_id": i.external_id, "platform": i.platform, "external_key": i.external_key, "name": i.name,
            "status": i.status_name, "is_open": i.is_open, "type": i.type_name, "priority": i.priority_name,
            "severity": i.severity_name, "owner": i.owner_name, "detected_release": i.detected_release_version,
            "updated_at": i.external_updated_at, "url": i.url}


@router.get("/incidents")
def list_incidents(project_id: int, q: str | None = None, status: str | None = None, priority: str | None = None,
                   severity: str | None = None, open_only: bool = False, release: str | None = None, sort: str | None = None,
                   page: int = 1, page_size: int = 50, db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_project(db, project_id)
    query = db.query(Incident).filter(Incident.project_id == project_id)
    if q:
        query = query.filter(or_(Incident.name.ilike(f"%{q}%"), Incident.description_text.ilike(f"%{q}%"),
                                 Incident.external_id == q.strip().upper().removeprefix("IN:")))
    for col, val in ((Incident.status_name, status), (Incident.priority_name, priority), (Incident.severity_name, severity),
                     (Incident.detected_release_external_id, release)):
        if val:
            query = query.filter(col == val)
    if open_only:
        query = query.filter(Incident.is_open.is_(True))
    return _page(_sort(query, Incident, sort, "-external_updated_at"), page, page_size, inc_row)


@router.get("/incidents/{incident_id}")
def incident_detail(incident_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    i = db.get(Incident, incident_id)
    if i is None:
        raise HTTPException(404, "Incident not found")
    get_project(db, i.project_id)
    atts = db.query(ExternalAttachment).filter_by(project_id=i.project_id, artifact_type="incident", artifact_external_id=i.external_id).all()
    return {**inc_row(i), "description_html": i.description_html, "description_text": i.description_text,
            "opener": i.opener_name, "resolved_release": i.resolved_release_version, "components": i.component_external_ids,
            "custom_properties": resolve_custom_properties(db, i.project_id, "Incident", i.custom_properties),
            "attachments": [{"external_id": a.external_id, "filename": a.filename, "size_bytes": a.size_bytes,
                             "author": a.author_name, "uploaded_at": a.uploaded_at} for a in atts],
            "created_at": i.external_created_at, "synced_at": i.synced_at}


# ----------------------------------------------------------- releases & folders
@router.get("/releases")
def list_releases(project_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_project(db, project_id)
    rows = db.query(Release).filter_by(project_id=project_id).order_by(Release.indent_level).all()
    out = []
    for r in rows:
        out.append({"id": r.id, "external_id": r.external_id, "name": r.name, "version": r.version_number,
                    "indent_level": r.indent_level, "is_iteration": r.is_iteration, "type": r.type_name, "status": r.status_name,
                    "active": r.active, "start_date": r.start_date, "end_date": r.end_date,
                    "requirements": db.query(Requirement).filter_by(project_id=project_id, release_external_id=r.external_id).count(),
                    "incidents_detected": db.query(Incident).filter_by(project_id=project_id, detected_release_external_id=r.external_id).count(),
                    "is_deleted_externally": r.is_deleted_externally})
    return out


@router.get("/folders")
def folder_tree(project_id: int, folder_type: str = Query("test_case", pattern="^(test_case|test_set)$"),
                db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_project(db, project_id)
    last = db.query(Folder).filter_by(project_id=project_id, folder_type=folder_type).order_by(Folder.synced_at.desc()).first()
    return {"tree": fsvc.tree(db, project_id, folder_type), "synced_at": last.synced_at if last else None}


# ------------------------------------------------------------------ global search
@router.get("/search")
def search(project_id: int, q: str = Query(min_length=1, max_length=200), db: Session = Depends(get_db),
           _: User = Depends(current_user)):
    get_project(db, project_id)
    term = f"%{q.strip()}%"
    raw = q.strip().upper()
    num = raw.split(":")[-1].strip()
    out = []
    for model, kind, prefix in ((Requirement, "requirement", "RQ"), (TestCase, "test_case", "TC"),
                                (TestSet, "test_set", "TX"), (Incident, "incident", "IN")):
        rows = (db.query(model).filter(model.project_id == project_id, or_(model.name.ilike(term), model.external_id == num))
                .limit(8).all())
        out += [{"kind": kind, "id": r.id, "external_id": r.external_id, "label": f"{prefix}:{r.external_id}", "name": r.name} for r in rows]
    return out
