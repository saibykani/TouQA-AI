from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Project, ProjectMetadata, User
from app.schemas.api import MappingIn, ProjectImportIn, ProjectOut, ProjectSettingsIn
from app.security.auth import current_user, require_writer
from app.services import audit, demo, mappings
from app.services import integrations as isvc

router = APIRouter(prefix="/projects", tags=["projects"])


def get_project(db: Session, project_id: int) -> Project:
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(404, "Project not found")
    if p.is_demo != get_settings().demo_mode and p.is_demo:
        raise HTTPException(404, "Demo projects are only available in demo mode")
    return p


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), _: User = Depends(current_user)):
    q = db.query(Project).filter(Project.is_active.is_(True))
    if not get_settings().demo_mode:
        q = q.filter(Project.is_demo.is_(False))
    return q.order_by(Project.is_demo.desc(), Project.name).all()


@router.post("/import", response_model=ProjectOut)
def import_project(body: ProjectImportIn, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    p = isvc.ensure_spira_project(db, body.external_id)
    audit.record(db, action="project.added", category="import", outcome="success", user_id=user.id, project_id=p.id,
                 platform="spira", summary=f"Added Spira project PR:{p.external_id} {p.name}", commit=True)
    return p


@router.post("/demo/seed", response_model=ProjectOut)
def seed_demo(db: Session = Depends(get_db), user: User = Depends(require_writer)):
    if not get_settings().demo_mode:
        raise HTTPException(403, "Demo data can only be loaded when DEMO_MODE=true")
    p = demo.seed(db)
    audit.record(db, action="demo.seeded", category="import", outcome="info", user_id=user.id, project_id=p.id,
                 summary="Synthetic demo project loaded", commit=True)
    return p


@router.get("/{project_id}", response_model=ProjectOut)
def project_detail(project_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    return get_project(db, project_id)


@router.put("/{project_id}/settings", response_model=ProjectOut)
def update_settings(project_id: int, body: ProjectSettingsIn, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    p = get_project(db, project_id)
    p.settings = {**(p.settings or {}), **body.model_dump(exclude_unset=True)}
    audit.record(db, action="project.settings", category="config", outcome="success", user_id=user.id, project_id=p.id,
                 summary="Project settings updated", details=body.model_dump(exclude_unset=True))
    db.commit()
    return p


@router.get("/{project_id}/metadata")
def metadata(project_id: int, kind: str | None = None, db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_project(db, project_id)
    q = db.query(ProjectMetadata).filter_by(project_id=project_id)
    if kind:
        q = q.filter(ProjectMetadata.kind == kind)
    out: dict[str, list] = {}
    for m in q.order_by(ProjectMetadata.kind, ProjectMetadata.name):
        out.setdefault(m.kind, []).append({"id": m.external_id, "name": m.name, "active": m.active, "data": m.data})
    return out


@router.get("/{project_id}/mappings")
def get_mappings(project_id: int, platform: str | None = None, db: Session = Depends(get_db), _: User = Depends(current_user)):
    get_project(db, project_id)
    fields = {}
    for field in ("test_case_priority", "incident_priority", "incident_severity"):
        values = mappings.allowed_values(db, project_id, field)
        fields[field] = {
            "allowed": [{"id": v["id"], "name": v["name"]} for v in values],
            "resolution": {c: mappings.resolve(db, "spira", project_id, field, c, values) for c in mappings.CANONICAL_VALUES[field]},
        }
    return {"mappings": mappings.list_mappings(db, project_id, platform), "spira_fields": fields,
            "canonical_values": mappings.CANONICAL_VALUES}


@router.put("/{project_id}/mappings")
def put_mapping(project_id: int, body: MappingIn, db: Session = Depends(get_db), user: User = Depends(require_writer)):
    get_project(db, project_id)
    if body.platform == "spira" and body.external_value_id:
        kind = mappings.SPIRA_FIELD_KINDS.get(body.field, body.field)
        if not db.query(ProjectMetadata).filter_by(project_id=project_id, kind=kind, external_id=body.external_value_id).first():
            raise ValueError(f"{body.external_value_id} is not an allowed {body.field} value for this project. Sync metadata first.")
    m = mappings.set_mapping(db, body.platform, project_id, body.field, body.canonical_value, body.external_value_id, body.external_value_name)
    audit.record(db, action="mapping.saved", category="config", outcome="success", user_id=user.id, project_id=project_id,
                 summary=f"{body.platform} {body.field}: {body.canonical_value} → {body.external_value_name or body.external_value_id}", commit=True)
    return {"id": m.id, "field": m.field, "canonical_value": m.canonical_value, "external_value_id": m.external_value_id,
            "external_value_name": m.external_value_name}
