from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User
from app.schemas.api import LoginIn, Ok, SessionOut, UserOut
from app.security import auth
from app.services import audit

router = APIRouter()


@router.get("/health", tags=["system"])
def health():
    return {"status": "ok", "app": get_settings().app_name}


@router.get("/ready", tags=["system"])
def ready(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    s = get_settings()
    return {
        "status": "ready",
        "database": "ok",
        "encryption_configured": bool(s.encryption_key and s.encryption_key.get_secret_value()),
        "demo_mode": s.demo_mode,
    }


@router.get("/config", tags=["system"])
def public_config():
    """Non-secret runtime flags the UI needs before sign-in."""
    s = get_settings()
    return {"app_name": s.app_name, "auth_enabled": s.auth_enabled, "demo_mode": s.demo_mode,
            "demo_allow_external_writes": s.demo_allow_external_writes, "environment": s.environment,
            "max_upload_bytes": s.max_upload_bytes, "allowed_upload_types": s.allowed_upload_types}


@router.post("/auth/login", response_model=SessionOut, tags=["auth"])
def login(body: LoginIn, response: Response, request: Request, db: Session = Depends(get_db)):
    try:
        user, csrf = auth.login(db, response, body.email, body.password)
    except Exception:
        audit.record(db, action="auth.login", category="auth", outcome="failure", summary=f"Failed sign-in for {body.email[:100]}",
                     details={"ip": request.client.host if request.client else None}, commit=True)
        raise
    audit.record(db, action="auth.login", category="auth", outcome="success", user_id=user.id,
                 summary=f"{user.email} signed in", commit=True)
    return SessionOut(user=UserOut.model_validate(user), csrf_token=csrf, auth_enabled=True)


@router.post("/auth/logout", response_model=Ok, tags=["auth"])
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    auth.logout(db, request, response)
    return Ok()


@router.get("/auth/me", response_model=SessionOut, tags=["auth"])
def me(request: Request, user: User = Depends(auth.current_user)):
    return SessionOut(user=UserOut.model_validate(user), csrf_token=request.cookies.get(auth.CSRF_COOKIE),
                      auth_enabled=get_settings().auth_enabled)
