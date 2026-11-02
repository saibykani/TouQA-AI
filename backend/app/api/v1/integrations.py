from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.integrations.http import IntegrationError
from app.models import User
from app.schemas.api import AISettingsIn, JiraConfigIn, Ok, SpiraConfigIn
from app.security.auth import current_user, require_admin
from app.services import ai_settings, audit
from app.services import integrations as svc

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("")
def list_integrations(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return {
        "spira": svc.public_view(svc.get_config(db, "spira"), "spira"),
        "jira": svc.public_view(svc.get_config(db, "jira"), "jira"),
        "ai": ai_settings.effective(db),
    }


@router.put("/spira")
def save_spira(body: SpiraConfigIn, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    cfg = svc.save_config(db, "spira", base_url=body.base_url, username=body.username, secret=body.api_key, user_id=user.id)
    return svc.public_view(cfg, "spira")


@router.post("/spira/test")
def test_spira(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return svc.test_spira(db, user.id)


@router.get("/spira/projects")
def spira_projects(db: Session = Depends(get_db), _: User = Depends(current_user)):
    with svc.spira_client(db) as client:
        projects = client.list_projects()
    return [{"external_id": str(p["ProjectId"]), "name": p.get("Name"), "description": p.get("Description"),
             "template_id": p.get("ProjectTemplateId"), "active": p.get("Active", True)}
            for p in projects if p.get("ProjectId") is not None]


@router.delete("/spira", response_model=Ok)
def disconnect_spira(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    svc.disconnect(db, "spira", user.id)
    return Ok()


@router.put("/jira")
def save_jira(body: JiraConfigIn, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    settings = {k: v for k, v in {"project_key": body.project_key, "issue_type_id": body.issue_type_id}.items() if v is not None}
    cfg = svc.save_config(db, "jira", base_url=body.base_url, username=body.email, secret=body.api_token,
                          flavor=body.flavor, auth_type="api_token" if body.flavor == "cloud" else "pat",
                          settings=settings, user_id=user.id)
    return svc.public_view(cfg, "jira")


@router.post("/jira/test")
def test_jira(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return svc.test_jira(db, user.id)


@router.delete("/jira", response_model=Ok)
def disconnect_jira(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    svc.disconnect(db, "jira", user.id)
    return Ok()


@router.get("/jira/projects")
def jira_projects(db: Session = Depends(get_db), _: User = Depends(current_user)):
    with svc.jira_client(db) as client:
        return [{"key": p.get("key"), "name": p.get("name"), "id": p.get("id")} for p in client.list_projects()]


@router.get("/jira/issue-types")
def jira_issue_types(project_key: str | None = None, db: Session = Depends(get_db), _: User = Depends(current_user)):
    cfg = svc.get_config(db, "jira")
    key = project_key or ((cfg.settings or {}).get("project_key") if cfg else None)
    if not key:
        raise ValueError("Set a Jira project key first.")
    with svc.jira_client(db) as client:
        return [{"id": t.get("id"), "name": t.get("name"), "subtask": t.get("subtask", False)} for t in client.create_issue_types(key)]


@router.get("/jira/fields")
def jira_fields(issue_type_id: str, project_key: str | None = None, db: Session = Depends(get_db), _: User = Depends(current_user)):
    """Create-screen fields for an issue type, including requirements and allowed values (for mapping)."""
    cfg = svc.get_config(db, "jira")
    key = project_key or ((cfg.settings or {}).get("project_key") if cfg else None)
    if not key:
        raise ValueError("Set a Jira project key first.")
    with svc.jira_client(db) as client:
        fields = client.create_fields(key, issue_type_id)
    out = []
    for f in fields:
        out.append({
            "id": f.get("fieldId") or f.get("key"), "name": f.get("name"), "required": bool(f.get("required")),
            "has_default": bool(f.get("hasDefaultValue")), "schema": f.get("schema") or {},
            "allowed_values": [{"id": v.get("id"), "name": v.get("name") or v.get("value")} for v in (f.get("allowedValues") or [])
                               if isinstance(v, dict)][:200],
        })
    return out


@router.put("/ai")
def save_ai(body: AISettingsIn, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    values = body.model_dump(exclude_none=True)
    if values.get("base_url"):
        from app.security.netguard import UnsafeUrlError, validate_outbound_url

        try:
            values["base_url"] = validate_outbound_url(values["base_url"], allow_loopback_http=True)
        except UnsafeUrlError as exc:
            raise ValueError(str(exc)) from exc
    ai_settings.save(db, values)
    audit.record(db, action="ai.settings.saved", category="config", outcome="success", user_id=user.id,
                 summary=f"AI settings updated: {values}", commit=True)
    return ai_settings.effective(db)


@router.post("/ai/test")
def test_ai(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Round-trip a tiny structured request to verify provider, key and model."""
    from pydantic import BaseModel

    class Ping(BaseModel):
        ok: bool
        message: str

    try:
        provider = ai_settings.provider_for(db)
    except IntegrationError as exc:  # pragma: no cover
        raise exc
    if provider.simulated:
        return {"ok": True, "provider": "simulated", "model": provider.model, "simulated": True,
                "message": "Simulated provider active (demo mode or explicitly selected)."}
    r = provider.generate(system="Return the requested JSON only.", prompt='Return {"ok": true, "message": "pong"}.', schema=Ping, task="ping")
    return {"ok": bool(r.output.ok), "provider": r.provider, "model": r.model, "simulated": r.simulated}
