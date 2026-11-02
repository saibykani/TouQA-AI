"""Integration configuration, credential storage and connection testing."""
from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.integrations.http import IntegrationError, IntegrationValidationError
from app.integrations.jira.client import JiraClient
from app.integrations.spira.client import API_VERSION, SpiraClient
from app.models import CredentialSecret, IntegrationConfig, Project
from app.security.crypto import decrypt_secret, encrypt_secret, secret_fingerprint
from app.security.netguard import UnsafeUrlError, validate_outbound_url
from app.services import audit

# Tests inject mock transports here: {"spira": httpx.MockTransport(...), "jira": ...}
TEST_TRANSPORTS: dict[str, httpx.BaseTransport] = {}

SPIRA_CAPABILITIES = {
    "auth": "username + api-key headers (RSS token)",
    "requirements": True, "requirement_coverage": True, "requirement_steps": True,
    "test_cases": True, "test_steps": True, "test_case_folders": True, "create_test_case_folder": True,
    "test_sets": True, "test_set_folders": True, "test_set_membership": True,
    "incidents": True, "create_incident": True, "attachments_upload": True, "attachments_list": True,
    "releases_and_iterations": True, "workflow_fields": True, "custom_property_definitions": True,
    "create_test_set_folder": False,  # not used by TouQA (test case folders only)
}


class IntegrationNotConfigured(IntegrationError):
    pass


def get_config(db: Session, platform: str) -> IntegrationConfig | None:
    return db.query(IntegrationConfig).filter_by(platform=platform).one_or_none()


def public_view(cfg: IntegrationConfig | None, platform: str) -> dict[str, Any]:
    """Safe representation for the browser. Never includes secret material."""
    if cfg is None:
        return {"platform": platform, "configured": False, "status": "unconfigured"}
    return {
        "platform": platform,
        "configured": bool(cfg.base_url and cfg.secret_id),
        "base_url": cfg.base_url,
        "username": cfg.username,
        "auth_type": cfg.auth_type,
        "flavor": cfg.flavor,
        "has_secret": cfg.secret_id is not None,
        "secret_fingerprint": cfg.secret.fingerprint if cfg.secret else None,
        "settings": cfg.settings or {},
        "status": cfg.status,
        "last_success_at": cfg.last_success_at,
        "last_checked_at": cfg.last_checked_at,
        "last_error": cfg.last_error,
        "api_version": cfg.api_version,
        "capabilities": cfg.capabilities or {},
    }


def save_config(db: Session, platform: str, *, base_url: str, username: str, secret: str | None,
                flavor: str = "cloud", auth_type: str = "api_key", settings: dict | None = None,
                user_id: int | None = None) -> IntegrationConfig:
    try:
        url = validate_outbound_url(base_url)
    except UnsafeUrlError as exc:
        raise IntegrationValidationError(str(exc)) from exc
    cfg = get_config(db, platform)
    if cfg is None:
        cfg = IntegrationConfig(platform=platform)
        db.add(cfg)
    changed_target = cfg.base_url and cfg.base_url != url
    cfg.base_url, cfg.username, cfg.flavor, cfg.auth_type = url, username.strip(), flavor, auth_type
    if settings is not None:
        cfg.settings = {**(cfg.settings or {}), **settings}
    if secret:
        old = cfg.secret
        cs = CredentialSecret(ciphertext=encrypt_secret(secret), fingerprint=secret_fingerprint(secret))
        db.add(cs)
        db.flush()
        cfg.secret_id = cs.id
        if old is not None:
            db.delete(old)
    elif changed_target:
        raise IntegrationValidationError("Re-enter the API key/token when changing the instance URL.")
    cfg.status = "configured" if cfg.secret_id else "unconfigured"
    cfg.last_error = None
    audit.record(db, action=f"{platform}.config.saved", category="config", outcome="success",
                 user_id=user_id, platform=platform,
                 summary=f"{platform} configuration saved for {url}" + (" (credential updated)" if secret else ""),
                 details={"base_url": url, "username": username, "flavor": flavor})
    db.commit()
    db.refresh(cfg)
    return cfg


def disconnect(db: Session, platform: str, user_id: int | None = None) -> None:
    cfg = get_config(db, platform)
    if cfg is None:
        return
    secret = cfg.secret
    cfg.secret_id = None
    cfg.status = "disconnected"
    cfg.last_error = None
    if secret is not None:
        db.delete(secret)
    audit.record(db, action=f"{platform}.disconnected", category="config", outcome="success", user_id=user_id,
                 platform=platform, summary=f"{platform} credentials removed. Imported data is retained.")
    db.commit()


def _secret(cfg: IntegrationConfig) -> str:
    if cfg.secret is None:
        raise IntegrationNotConfigured(f"{cfg.platform.capitalize()} credentials are not configured.")
    return decrypt_secret(cfg.secret.ciphertext)


def spira_client(db: Session) -> SpiraClient:
    cfg = get_config(db, "spira")
    if cfg is None or not cfg.base_url:
        raise IntegrationNotConfigured("Spira is not configured. Open Settings → Integrations → Spira.")
    return SpiraClient(cfg.base_url, cfg.username, _secret(cfg), transport=TEST_TRANSPORTS.get("spira"),
                       sleep=(lambda _s: None) if "spira" in TEST_TRANSPORTS else None)


def jira_client(db: Session) -> JiraClient:
    cfg = get_config(db, "jira")
    if cfg is None or not cfg.base_url:
        raise IntegrationNotConfigured("Jira is not configured. Open Settings → Integrations → Jira.")
    return JiraClient(cfg.base_url, flavor=cfg.flavor, email=cfg.username, api_token=_secret(cfg),
                      transport=TEST_TRANSPORTS.get("jira"),
                      sleep=(lambda _s: None) if "jira" in TEST_TRANSPORTS else None)


def _mark(db: Session, cfg: IntegrationConfig, ok: bool, error: str | None = None) -> None:
    cfg.last_checked_at = utcnow()
    if ok:
        cfg.status, cfg.last_success_at, cfg.last_error = "connected", utcnow(), None
    else:
        cfg.status, cfg.last_error = "error", error
    db.commit()


def test_spira(db: Session, user_id: int | None = None) -> dict:
    cfg = get_config(db, "spira")
    if cfg is None:
        raise IntegrationNotConfigured("Spira is not configured.")
    try:
        with spira_client(db) as client:
            user = client.current_user() or {}
            try:
                version = client.product_version()
            except IntegrationError:
                version = None
            projects = client.list_projects()
    except IntegrationError as exc:
        _mark(db, cfg, False, exc.user_message)
        audit.record(db, action="spira.connection_test", category="config", outcome="failure", user_id=user_id,
                     platform="spira", summary=exc.user_message, commit=True)
        raise
    version_str = version if isinstance(version, str) else (version or {}).get("Version") if isinstance(version, dict) else None
    cfg.api_version = f"REST {API_VERSION}" + (f" · Spira {version_str}" if version_str else "")
    cfg.capabilities = SPIRA_CAPABILITIES
    _mark(db, cfg, True)
    audit.record(db, action="spira.connection_test", category="config", outcome="success", user_id=user_id,
                 platform="spira", summary=f"Connected as {user.get('UserName') or cfg.username}; {len(projects)} projects visible",
                 commit=True)
    return {
        "ok": True,
        "user": {"username": user.get("UserName"), "full_name": user.get("FullName"), "id": user.get("UserId")},
        "api_version": cfg.api_version,
        "project_count": len(projects),
        "projects": [{"external_id": str(p["ProjectId"]), "name": p.get("Name"), "template_id": p.get("ProjectTemplateId")}
                     for p in projects if p.get("ProjectId") is not None],
    }


def test_jira(db: Session, user_id: int | None = None) -> dict:
    cfg = get_config(db, "jira")
    if cfg is None:
        raise IntegrationNotConfigured("Jira is not configured.")
    try:
        with jira_client(db) as client:
            me = client.myself() or {}
            info = client.server_info() or {}
            project = None
            key = (cfg.settings or {}).get("project_key")
            if key:
                project = client.get_project(key)
    except IntegrationError as exc:
        _mark(db, cfg, False, exc.user_message)
        audit.record(db, action="jira.connection_test", category="config", outcome="failure", user_id=user_id,
                     platform="jira", summary=exc.user_message, commit=True)
        raise
    deployment = info.get("deploymentType") or ("Cloud" if cfg.flavor == "cloud" else "Server/Data Center")
    cfg.api_version = f"REST {'v3' if cfg.flavor == 'cloud' else 'v2'} · {deployment} {info.get('version', '')}".strip()
    cfg.capabilities = {"search": True, "create_issue": True, "attachments_upload": True, "create_metadata": True,
                        "bidirectional_sync": False}
    _mark(db, cfg, True)
    audit.record(db, action="jira.connection_test", category="config", outcome="success", user_id=user_id,
                 platform="jira", summary=f"Connected as {me.get('displayName') or me.get('name') or cfg.username}", commit=True)
    return {
        "ok": True,
        "user": {"display_name": me.get("displayName"), "account_id": me.get("accountId") or me.get("name")},
        "api_version": cfg.api_version,
        "project": {"key": project.get("key"), "name": project.get("name"), "id": project.get("id")} if project else None,
    }


def ensure_spira_project(db: Session, external_id: str) -> Project:
    """Create/refresh the local project row for a Spira project the user selected."""
    from app.integrations.spira.mapper import map_project

    with spira_client(db) as client:
        raw = client.get_project(int(external_id))
    data = map_project(raw)
    proj = db.query(Project).filter_by(platform="spira", external_id=data["external_id"], is_demo=False).one_or_none()
    if proj is None:
        proj = Project(platform="spira", raw={}, settings={}, **data)
        db.add(proj)
    else:
        for k, v in data.items():
            setattr(proj, k, v)
    proj.raw = {k: v for k, v in raw.items() if k != "CustomProperties"}
    db.commit()
    db.refresh(proj)
    return proj


def external_writes_allowed() -> tuple[bool, str | None]:
    s = get_settings()
    if s.demo_mode and not s.demo_allow_external_writes:
        return False, "External writes are disabled in demo mode. Submissions are shown as previews only."
    return True, None
