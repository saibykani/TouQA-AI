"""Non-secret AI provider settings editable in the UI (provider, model, base URL).

API keys stay in the environment. Values here override env defaults at runtime.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai.providers import LLMProvider, get_provider
from app.config import get_settings
from app.models import AppSetting

KEY = "ai"


def load(db: Session) -> dict:
    row = db.get(AppSetting, KEY)
    return dict(row.value) if row else {}


def save(db: Session, values: dict) -> dict:
    allowed = {"provider", "model", "vision_model", "base_url", "vision_enabled"}
    clean = {k: v for k, v in values.items() if k in allowed}
    row = db.get(AppSetting, KEY)
    if row is None:
        row = AppSetting(key=KEY, value=clean)
        db.add(row)
    else:
        row.value = {**row.value, **clean}
    db.commit()
    return row.value


def effective(db: Session) -> dict:
    s = get_settings()
    o = load(db)
    provider = "simulated" if s.demo_mode else (o.get("provider") or s.ai_provider)
    return {
        "provider": provider,
        "model": o.get("model") or s.ai_model,
        "vision_model": o.get("vision_model") or s.ai_vision_model or o.get("model") or s.ai_model,
        "base_url": o.get("base_url") or s.ai_base_url,
        "vision_enabled": o.get("vision_enabled", True),
        "effort": s.ai_effort,
        "anthropic_key_configured": bool(s.anthropic_api_key and s.anthropic_api_key.get_secret_value()),
        "api_key_configured": bool(s.ai_api_key and s.ai_api_key.get_secret_value()),
        "demo_mode": s.demo_mode,
        "simulated": provider == "simulated",
    }


def provider_for(db: Session, *, vision: bool = False) -> LLMProvider:
    return get_provider(override=load(db), vision=vision)
