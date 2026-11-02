"""Cookie session authentication with CSRF protection.

* Session token: random, stored hashed in ``app_sessions``; sent as an HttpOnly, SameSite=Lax
  cookie (Secure when COOKIE_SECURE=true).
* CSRF: unsafe methods must send ``X-CSRF-Token`` equal to the session's CSRF token, which the
  SPA reads from the non-HttpOnly ``touqa_csrf`` cookie (double-submit pattern).
* AUTH_ENABLED=false (local single-user mode) maps every request to a local admin user.
"""
from __future__ import annotations

import hmac
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db, utcnow
from app.models import AppSession, User
from app.security.crypto import hash_token, new_token
from app.security.passwords import hash_password, verify_password

SESSION_COOKIE = "touqa_session"
CSRF_COOKIE = "touqa_csrf"
LOCAL_EMAIL = "local@touqa.local"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def ensure_bootstrap_admin(db: Session) -> None:
    s = get_settings()
    if db.query(User).count() == 0 and s.admin_password and s.admin_password.get_secret_value():
        db.add(User(email=s.admin_email.lower(), display_name="Administrator",
                    password_hash=hash_password(s.admin_password.get_secret_value()), role="admin"))
        db.commit()


def _local_user(db: Session) -> User:
    u = db.query(User).filter_by(email=LOCAL_EMAIL).one_or_none()
    if u is None:
        u = User(email=LOCAL_EMAIL, display_name="Local user", password_hash="!", role="admin")
        db.add(u)
        db.commit()
        db.refresh(u)
    return u


def login(db: Session, response: Response, email: str, password: str) -> tuple[User, str]:
    user = db.query(User).filter_by(email=email.strip().lower()).one_or_none()
    if user is None or not user.is_active or not verify_password(user.password_hash, password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    s = get_settings()
    token, csrf = new_token(), new_token(24)
    db.add(AppSession(token_hash=hash_token(token), csrf_token=csrf, user_id=user.id,
                      expires_at=utcnow() + timedelta(hours=s.session_ttl_hours)))
    db.commit()
    max_age = s.session_ttl_hours * 3600
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=s.cookie_secure, samesite="lax", max_age=max_age, path="/")
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, secure=s.cookie_secure, samesite="lax", max_age=max_age, path="/")
    return user, csrf


def logout(db: Session, request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.query(AppSession).filter_by(token_hash=hash_token(token)).delete()
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    s = get_settings()
    if not s.auth_enabled:
        return _local_user(db)
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not signed in")
    sess = db.query(AppSession).filter_by(token_hash=hash_token(token)).one_or_none()
    if sess is None or sess.expires_at < utcnow() or not sess.user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    if request.method not in SAFE_METHODS:
        header = request.headers.get("X-CSRF-Token", "")
        if not header or not hmac.compare_digest(header, sess.csrf_token):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="CSRF token missing or invalid")
    sess.last_seen_at = utcnow()
    db.commit()
    request.state.user_id = sess.user_id
    return sess.user


def require_writer(user: User = Depends(current_user)) -> User:
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Your role does not allow this action")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Administrator role required")
    return user
