"""Consistent JSON error format: {"error": {"code", "message", "detail"}}."""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.ai.providers import AIError, AINotConfigured, AIRefusal
from app.integrations import http as ih
from app.security.crypto import EncryptionNotConfigured
from app.services.attachments import UploadRejected
from app.services.folders import FolderError
from app.services.integrations import IntegrationNotConfigured

log = logging.getLogger("touqa.api")


def error(status: int, code: str, message: str, detail=None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "detail": detail}})


INTEGRATION_STATUS = [
    (IntegrationNotConfigured, 409, "integration_not_configured"),
    (ih.IntegrationAuthError, 502, "integration_auth_failed"),
    (ih.IntegrationPermissionError, 502, "integration_forbidden"),
    (ih.IntegrationNotFoundError, 502, "integration_not_found"),
    (ih.IntegrationRateLimitError, 503, "integration_rate_limited"),
    (ih.IntegrationValidationError, 422, "integration_rejected"),
    (ih.OutcomeUnknownError, 504, "integration_outcome_unknown"),
    (ih.IntegrationNetworkError, 504, "integration_unreachable"),
    (ih.IntegrationServerError, 502, "integration_server_error"),
]


def install(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exc(_: Request, exc: HTTPException):
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 409: "conflict", 429: "rate_limited"}.get(exc.status_code, "error")
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
        extra = exc.detail if not isinstance(exc.detail, str) else None
        return error(exc.status_code, code, detail, extra)

    @app.exception_handler(RequestValidationError)
    async def validation_exc(_: Request, exc: RequestValidationError):
        errs = [{"field": ".".join(str(x) for x in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
        return error(422, "validation_error", "The request is invalid.", errs)

    @app.exception_handler(ih.IntegrationError)
    async def integration_exc(_: Request, exc: ih.IntegrationError):
        for cls, status, code in INTEGRATION_STATUS:
            if isinstance(exc, cls):
                return error(status, code, exc.user_message, {"upstream_status": exc.status_code})
        return error(502, "integration_error", exc.user_message)

    @app.exception_handler(FolderError)
    async def folder_exc(_: Request, exc: FolderError):
        status = {"duplicate": 409, "writes_disabled": 403, "unknown_outcome": 504}.get(exc.code, 422)
        return error(status, f"folder_{exc.code}", exc.message, {"existing": exc.existing} if exc.existing else None)

    @app.exception_handler(AIError)
    async def ai_exc(_: Request, exc: AIError):
        if isinstance(exc, AINotConfigured):
            return error(409, "ai_not_configured", exc.user_message)
        if isinstance(exc, AIRefusal):
            return error(422, "ai_refusal", exc.user_message)
        return error(502, "ai_error", exc.user_message)

    @app.exception_handler(UploadRejected)
    async def upload_exc(_: Request, exc: UploadRejected):
        return error(422, "upload_rejected", str(exc))

    @app.exception_handler(EncryptionNotConfigured)
    async def enc_exc(_: Request, exc: EncryptionNotConfigured):
        return error(500, "encryption_not_configured", str(exc))

    @app.exception_handler(ValueError)
    async def value_exc(_: Request, exc: ValueError):
        return error(422, "invalid", str(exc))
