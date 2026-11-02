"""In-memory sliding-window rate limiter (per client IP). Suitable for a single-instance
deployment; use a shared store (e.g. Redis) when running several replicas."""
from __future__ import annotations

import threading
import time
from collections import deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import get_settings

AI_PATH_MARKERS = ("/analyses", "/generation", "/analyze")


class RateLimiter:
    def __init__(self):
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window: float = 60.0) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True


limiter = RateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and not path.endswith(("/health", "/ready")):
            s = get_settings()
            ip = request.client.host if request.client else "unknown"
            if not limiter.allow(f"all:{ip}", s.rate_limit_per_minute):
                return JSONResponse(status_code=429, content={"error": {"code": "rate_limited", "message": "Too many requests. Slow down."}})
            if request.method == "POST" and any(m in path for m in AI_PATH_MARKERS):
                if not limiter.allow(f"ai:{ip}", s.ai_rate_limit_per_minute):
                    return JSONResponse(status_code=429, content={"error": {"code": "rate_limited", "message": "Too many AI requests. Try again in a minute."}})
            if path.endswith("/auth/login") and not limiter.allow(f"login:{ip}", 10):
                return JSONResponse(status_code=429, content={"error": {"code": "rate_limited", "message": "Too many sign-in attempts."}})
        return await call_next(request)
