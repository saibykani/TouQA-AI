"""FastAPI application entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import errors
from app.api.v1 import ai, incident_studio, insights, integrations, jobs, projects, records, submissions, system
from app.config import get_settings
from app.db import session_factory
from app.security.ratelimit import RateLimitMiddleware
from app.security.redaction import RedactingFilter


def configure_logging() -> None:
    s = get_settings()
    logging.basicConfig(level=s.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for h in logging.getLogger().handlers:
        h.addFilter(RedactingFilter())
    logging.getLogger("httpx").setLevel(logging.WARNING)  # never log request URLs/headers at INFO


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.security.auth import ensure_bootstrap_admin
    from app.services import jobs as job_svc

    s = get_settings()
    if s.is_production and not s.verify_tls:
        raise RuntimeError("VERIFY_TLS=false is not permitted in production")
    with session_factory()() as db:
        ensure_bootstrap_admin(db)
        n = job_svc.recover_interrupted_jobs(db)
        if n:
            logging.getLogger("touqa").warning("Marked %s interrupted job(s) as FAILED", n)
    yield
    job_svc.shutdown()


def create_app() -> FastAPI:
    configure_logging()
    s = get_settings()
    app = FastAPI(title="TouQA AI API", version="1.0.0", lifespan=lifespan,
                  docs_url="/api/docs", redoc_url="/api/redoc", openapi_url="/api/openapi.json")
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Content-Type", "X-CSRF-Token"])

    @app.middleware("http")
    async def security_headers(request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        return resp

    errors.install(app)
    for r in (system, integrations, projects, jobs, records, ai, submissions, incident_studio, insights):
        app.include_router(r.router, prefix="/api/v1")
    return app


app = create_app()
