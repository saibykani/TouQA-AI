"""Provider-independent LLM service.

Each provider implements ``generate(system, prompt, schema, images)`` and returns a
validated Pydantic instance of ``schema``. Output that fails validation is retried once
with the validation error, then surfaced as ``AIOutputError``.
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings
from app.security.netguard import validate_outbound_url
from app.security.redaction import redact_text

log = logging.getLogger("touqa.ai")
T = TypeVar("T", bound=BaseModel)


class AIError(Exception):
    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


class AINotConfigured(AIError):
    pass


class AIOutputError(AIError):
    pass


class AIRefusal(AIError):
    pass


@dataclass
class ImageInput:
    media_type: str
    data: bytes
    label: str = ""


@dataclass
class AIResult:
    output: BaseModel
    provider: str
    model: str
    simulated: bool = False
    usage: dict = field(default_factory=dict)


class LLMProvider:
    name = "base"
    simulated = False

    def __init__(self, model: str):
        self.model = model

    def generate(self, *, system: str, prompt: str, schema: type[T], images: list[ImageInput] | None = None,
                 task: str = "", context: dict | None = None) -> AIResult:
        raise NotImplementedError


# --------------------------------------------------------------------------- Anthropic
class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, settings: Settings, model: str | None = None):
        super().__init__(model or settings.ai_model)
        key = settings.anthropic_api_key or settings.ai_api_key
        if key is None or not key.get_secret_value():
            raise AINotConfigured("ANTHROPIC_API_KEY is not set. Add it to .env or choose another AI provider.")
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=key.get_secret_value(), timeout=settings.ai_timeout_seconds,
                                          max_retries=3)
        self.settings = settings

    def _content(self, prompt: str, images: list[ImageInput] | None) -> list[dict]:
        blocks: list[dict] = []
        for img in images or []:
            if img.label:
                blocks.append({"type": "text", "text": f"Screenshot: {img.label}"})
            blocks.append({"type": "image", "source": {
                "type": "base64", "media_type": img.media_type,
                "data": base64.standard_b64encode(img.data).decode("ascii"),
            }})
        blocks.append({"type": "text", "text": prompt})
        return blocks

    def generate(self, *, system, prompt, schema, images=None, task="", context=None):
        a = self._anthropic
        content = self._content(prompt, images)
        messages: list[dict] = [{"role": "user", "content": content}]
        extra_headers, extra_body = {}, {}
        if self.settings.anthropic_enable_fallbacks:
            # Server-side refusal fallback (beta): re-runs a declined request on a fallback model.
            extra_headers["anthropic-beta"] = "server-side-fallback-2026-07-01"
            extra_body["fallbacks"] = "default"
        last_error = ""
        for attempt in range(2):
            try:
                with self.client.messages.stream(
                    model=self.model,
                    max_tokens=self.settings.ai_max_tokens,
                    system=system,
                    messages=messages,
                    thinking={"type": "adaptive"},
                    output_config={"effort": self.settings.ai_effort},
                    output_format=schema,
                    extra_headers=extra_headers or None,
                    extra_body=extra_body or None,
                ) as stream:
                    message = stream.get_final_message()
            except a.BadRequestError as exc:
                if extra_body and "fallback" in str(exc).lower():
                    log.warning("Anthropic rejected the fallbacks parameter; retrying without it")
                    extra_headers, extra_body = {}, {}
                    continue
                raise AIError(f"The AI provider rejected the request: {redact_text(str(exc))[:300]}") from exc
            except a.AuthenticationError as exc:
                raise AINotConfigured("The Anthropic API key was rejected (401).") from exc
            except a.PermissionDeniedError as exc:
                raise AIError("The Anthropic API key lacks permission for this model (403).") from exc
            except a.NotFoundError as exc:
                raise AIError(f"Model '{self.model}' was not found. Check AI_MODEL.") from exc
            except a.RateLimitError as exc:
                raise AIError("The AI provider rate limit was reached. Try again shortly.") from exc
            except a.APIStatusError as exc:
                raise AIError(f"The AI provider returned an error (HTTP {exc.status_code}).") from exc
            except a.APIConnectionError as exc:
                raise AIError("Could not reach the Anthropic API. Check network connectivity.") from exc

            if message.stop_reason == "refusal":
                raise AIRefusal("The model declined this request. Review the input content and try again.")
            if message.stop_reason == "max_tokens":
                raise AIOutputError("The AI response hit the output limit. Reduce the requested scope or raise AI_MAX_TOKENS.")
            usage = {"input_tokens": getattr(message.usage, "input_tokens", None),
                     "output_tokens": getattr(message.usage, "output_tokens", None)}
            parsed = getattr(message, "parsed_output", None)
            if isinstance(parsed, schema):
                return AIResult(parsed, self.name, self.model, usage=usage)
            text = "".join(getattr(b, "text", "") for b in message.content if getattr(b, "type", "") == "text")
            try:
                return AIResult(schema.model_validate_json(text), self.name, self.model, usage=usage)
            except ValidationError as exc:
                last_error = str(exc)[:2000]
                repair = {"type": "text", "text": "A previous attempt failed schema validation:\n" + last_error +
                          "\nReturn a response that satisfies the schema."}
                messages = [{"role": "user", "content": content + [repair]}]
        raise AIOutputError(f"The AI output did not match the required schema: {last_error[:300]}")


# ------------------------------------------------------------------ OpenAI-compatible
class OpenAICompatibleProvider(LLMProvider):
    name = "openai_compatible"

    def __init__(self, settings: Settings, model: str | None = None, *, local: bool = False,
                 transport: httpx.BaseTransport | None = None):
        super().__init__(model or settings.ai_model)
        default = "http://localhost:11434/v1" if local else "https://api.openai.com/v1"
        base = settings.ai_base_url or default
        self.base_url = validate_outbound_url(base, allow_loopback_http=True)
        self.name = "local" if local else "openai_compatible"
        key = settings.ai_api_key.get_secret_value() if settings.ai_api_key else ""
        if not key and not local:
            raise AINotConfigured("AI_API_KEY is not set for the OpenAI-compatible provider.")
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        self.http = httpx.Client(base_url=self.base_url, headers=headers, timeout=settings.ai_timeout_seconds,
                                 verify=settings.verify_tls, transport=transport)
        self.settings = settings

    def _messages(self, system: str, prompt: str, images: list[ImageInput] | None) -> list[dict]:
        content: list[dict] | str
        if images:
            content = [{"type": "image_url", "image_url": {
                "url": f"data:{i.media_type};base64,{base64.b64encode(i.data).decode()}"}} for i in images]
            content.append({"type": "text", "text": prompt})
        else:
            content = prompt
        return [{"role": "system", "content": system}, {"role": "user", "content": content}]

    def generate(self, *, system, prompt, schema, images=None, task="", context=None):
        json_schema = schema.model_json_schema()
        sys_prompt = system + "\n\nRespond ONLY with a JSON object that conforms to this JSON Schema:\n" + json.dumps(json_schema)
        messages = self._messages(sys_prompt, prompt, images)
        response_format: dict[str, Any] = {"type": "json_schema", "json_schema": {
            "name": schema.__name__, "schema": json_schema, "strict": False}}
        last_error = ""
        for attempt in range(3):
            body = {"model": self.model, "messages": messages, "response_format": response_format,
                    "max_tokens": min(self.settings.ai_max_tokens, 16000)}
            try:
                resp = self.http.post("/chat/completions", json=body)
            except httpx.HTTPError as exc:
                raise AIError(f"Could not reach the AI provider at {self.base_url}: {exc.__class__.__name__}") from exc
            if resp.status_code == 400 and response_format.get("type") == "json_schema":
                response_format = {"type": "json_object"}  # provider lacks json_schema support
                continue
            if resp.status_code == 401:
                raise AINotConfigured("The AI provider rejected the API key (401).")
            if resp.status_code >= 400:
                raise AIError(f"The AI provider returned HTTP {resp.status_code}: {redact_text(resp.text[:300])}")
            data = resp.json()
            text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
            text = text.strip()
            if text.startswith("```"):
                text = text.strip("`").removeprefix("json").strip()
            try:
                return AIResult(schema.model_validate_json(text), self.name, self.model, usage=data.get("usage") or {})
            except ValidationError as exc:
                last_error = str(exc)[:2000]
                messages = messages + [{"role": "assistant", "content": text},
                                       {"role": "user", "content": "That output failed validation:\n" + last_error +
                                        "\nReturn only the corrected JSON object."}]
        raise AIOutputError(f"The AI output did not match the required schema: {last_error[:300]}")


def get_provider(settings: Settings | None = None, *, vision: bool = False, override: dict | None = None) -> LLMProvider:
    """Resolve the configured provider. ``override`` comes from the AI settings saved in the UI."""
    settings = settings or get_settings()
    o = override or {}
    provider = o.get("provider") or settings.ai_provider
    model = o.get("vision_model" if vision else "model") or (settings.ai_vision_model if vision else None) or o.get("model") or settings.ai_model
    if settings.demo_mode and provider != "simulated" and not o.get("allow_real_ai_in_demo"):
        provider = "simulated"
    if provider == "simulated":
        from app.ai.simulated import SimulatedProvider

        return SimulatedProvider()
    if o.get("base_url"):
        settings = settings.model_copy(update={"ai_base_url": o["base_url"]})
    if provider == "anthropic":
        return AnthropicProvider(settings, model)
    if provider == "openai_compatible":
        return OpenAICompatibleProvider(settings, model)
    if provider == "local":
        return OpenAICompatibleProvider(settings, model, local=True)
    raise AINotConfigured(f"Unknown AI provider '{provider}'")
