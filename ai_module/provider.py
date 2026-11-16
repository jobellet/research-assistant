"""Provider-agnostic LLM access (port of ADHDtools' core/ai-provider.js).

Supported: OpenAI, Google Gemini, Anthropic (Claude), Mistral, Groq,
OpenRouter and any OpenAI-compatible endpoint (Ollama, LM Studio, vLLM...).
Everything in the app works without AI; this module just reports "not enabled".

Configuration, first match wins:
1. ``ai_settings.json`` in DATA_DIR (written by Settings → AI in the web UI; git-ignored)
2. ``AI_PROVIDER`` / ``AI_API_KEY`` / ``AI_MODEL`` / ``AI_BASE_URL`` environment variables (.env)
3. a provider key already in the environment: OPENAI_API_KEY, ANTHROPIC_API_KEY,
   GEMINI_API_KEY / GOOGLE_API_KEY, MISTRAL_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY

API keys are only sent to the chosen provider and are never returned by the API
(``public_settings`` masks them).
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, Iterator, Optional

import requests

logger = logging.getLogger(__name__)

PROVIDERS: Dict[str, dict] = {
    "none": {"label": "None (no AI)", "requires_key": False},
    "openai": {"label": "OpenAI (ChatGPT)", "default_model": "gpt-4o-mini",
               "base_url": "https://api.openai.com/v1", "style": "openai", "requires_key": True,
               "env_key": "OPENAI_API_KEY", "key_hint": "platform.openai.com/api-keys"},
    "gemini": {"label": "Google Gemini", "default_model": "gemini-2.5-flash", "style": "gemini",
               "base_url": "https://generativelanguage.googleapis.com/v1beta", "requires_key": True,
               "env_key": "GEMINI_API_KEY", "key_hint": "aistudio.google.com/app/apikey"},
    "anthropic": {"label": "Anthropic (Claude)", "default_model": "claude-opus-5-5",
                  "base_url": "https://api.anthropic.com/v1", "style": "anthropic", "requires_key": True,
                  "env_key": "ANTHROPIC_API_KEY", "key_hint": "console.anthropic.com"},
    "mistral": {"label": "Mistral", "default_model": "mistral-small-latest",
                "base_url": "https://api.mistral.ai/v1", "style": "openai", "requires_key": True,
                "env_key": "MISTRAL_API_KEY", "key_hint": "console.mistral.ai/api-keys"},
    "groq": {"label": "Groq", "default_model": "llama-3.3-70b-versatile",
             "base_url": "https://api.groq.com/openai/v1", "style": "openai", "requires_key": True,
             "env_key": "GROQ_API_KEY", "key_hint": "console.groq.com/keys"},
    "openrouter": {"label": "OpenRouter (many models)", "default_model": "openai/gpt-4o-mini",
                   "base_url": "https://openrouter.ai/api/v1", "style": "openai", "requires_key": True,
                   "env_key": "OPENROUTER_API_KEY", "key_hint": "openrouter.ai/keys"},
    "custom": {"label": "Custom / local (OpenAI-compatible: Ollama, LM Studio…)", "default_model": "llama3.2",
               "base_url": "http://localhost:11434/v1", "style": "openai", "requires_key": False,
               "key_hint": "optional, depends on your server"},
}
# Order used to pick a provider from keys already present in the environment
AUTODETECT_ORDER = ["anthropic", "openai", "gemini", "mistral", "groq", "openrouter"]
TIMEOUT = 120


class AIError(RuntimeError):
    """Raised with a user-readable message."""


def _settings_path() -> Path:
    try:
        from config import DATA_DIR
        return Path(DATA_DIR) / "ai_settings.json"
    except Exception:  # pragma: no cover
        return Path("ai_settings.json")


def _env_key(provider: str) -> str:
    env = PROVIDERS.get(provider, {}).get("env_key")
    if not env:
        return ""
    if provider == "gemini":
        return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    return os.getenv(env, "")


def get_settings() -> dict:
    """Current settings with their ``source`` (file, env, autodetect or none)."""
    path = _settings_path()
    if path.exists():
        try:
            saved = json.loads(path.read_text())
            if isinstance(saved, dict) and saved.get("provider"):
                cfg = {"provider": "none", "api_key": "", "model": "", "base_url": "", **saved, "source": "settings"}
                if not cfg.get("api_key"):
                    cfg["api_key"] = _env_key(cfg["provider"])
                return cfg
        except Exception as exc:
            logger.warning("Could not read %s: %s", path, exc)
    if os.getenv("AI_PROVIDER"):
        prov = os.getenv("AI_PROVIDER", "none").strip().lower()
        return {"provider": prov, "api_key": os.getenv("AI_API_KEY") or _env_key(prov),
                "model": os.getenv("AI_MODEL", ""), "base_url": os.getenv("AI_BASE_URL", ""), "source": "env"}
    for prov in AUTODETECT_ORDER:
        key = _env_key(prov)
        if key:
            return {"provider": prov, "api_key": key, "model": "", "base_url": "", "source": "autodetect"}
    return {"provider": "none", "api_key": "", "model": "", "base_url": "", "source": "none"}


def save_settings(provider: str, api_key: Optional[str] = None, model: str = "", base_url: str = "") -> dict:
    """Persist settings to ai_settings.json. ``api_key=None`` keeps the stored key."""
    if provider not in PROVIDERS:
        raise AIError(f"Unknown provider '{provider}'.")
    current = {}
    path = _settings_path()
    if path.exists():
        try:
            current = json.loads(path.read_text())
        except Exception:
            current = {}
    if api_key is None:
        api_key = current.get("api_key", "") if current.get("provider") == provider else ""
    data = {"provider": provider, "api_key": api_key.strip(), "model": model.strip(), "base_url": base_url.strip()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return public_settings()


def clear_settings():
    path = _settings_path()
    if path.exists():
        path.unlink()


def resolve(settings: Optional[dict] = None) -> dict:
    cfg = dict(settings or get_settings())
    pdef = PROVIDERS.get(cfg.get("provider") or "none", PROVIDERS["none"])
    cfg["provider_def"] = pdef
    cfg["model"] = cfg.get("model") or pdef.get("default_model", "")
    cfg["base_url"] = (cfg.get("base_url") or pdef.get("base_url", "")).rstrip("/")
    return cfg


def is_enabled(settings: Optional[dict] = None) -> bool:
    cfg = resolve(settings)
    if cfg.get("provider") in (None, "", "none"):
        return False
    return not (cfg["provider_def"].get("requires_key") and not cfg.get("api_key"))


def public_settings() -> dict:
    """Settings safe to send to the browser (key masked)."""
    cfg = resolve()
    key = cfg.get("api_key") or ""
    return {
        "provider": cfg.get("provider", "none"),
        "label": cfg["provider_def"].get("label"),
        "model": cfg["model"],
        "base_url": cfg["base_url"],
        "key_set": bool(key),
        "key_hint": f"…{key[-4:]}" if len(key) >= 8 else ("set" if key else ""),
        "source": cfg.get("source"),
        "enabled": is_enabled(cfg),
        "providers": {k: {"label": v["label"], "default_model": v.get("default_model", ""),
                          "base_url": v.get("base_url", ""), "requires_key": v.get("requires_key", False),
                          "key_hint": v.get("key_hint", "")} for k, v in PROVIDERS.items()},
    }


# ---------------------------------------------------------------------------
# Requests per provider style
# ---------------------------------------------------------------------------

def _build(cfg: dict, prompt: str, system: Optional[str], max_tokens: int, temperature: Optional[float],
           streaming: bool) -> dict:
    style = cfg["provider_def"].get("style")
    if style == "gemini":
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": max_tokens}}
        if temperature is not None:
            body["generationConfig"]["temperature"] = temperature
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        action = "streamGenerateContent?alt=sse" if streaming else "generateContent"
        return {"url": f"{cfg['base_url']}/models/{cfg['model']}:{action}",
                "headers": {"Content-Type": "application/json", "x-goog-api-key": cfg["api_key"]},
                "body": body}
    if style == "anthropic":
        # Sampling parameters are rejected by current Claude models: none are sent.
        # Server-side refusal fallback ("default" routes by refusal category).
        body = {"model": cfg["model"], "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}], "fallbacks": "default"}
        if system:
            body["system"] = system
        if streaming:
            body["stream"] = True
        return {"url": f"{cfg['base_url']}/messages",
                "headers": {"Content-Type": "application/json", "x-api-key": cfg["api_key"],
                            "anthropic-version": "2023-06-01",
                            "anthropic-beta": "server-side-fallback-2026-07-01"},
                "body": body}
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body = {"model": cfg["model"], "messages": messages, "max_tokens": max_tokens}
    if temperature is not None:
        body["temperature"] = temperature
    if streaming:
        body["stream"] = True
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    return {"url": f"{cfg['base_url']}/chat/completions", "headers": headers, "body": body}


def _extract(style: str, data: dict) -> str:
    if style == "gemini":
        cands = data.get("candidates") or [{}]
        return "".join(p.get("text", "") for p in (cands[0].get("content") or {}).get("parts", []))
    if style == "anthropic":
        if data.get("stop_reason") == "refusal":
            raise AIError("The model declined this request.")
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""


def _post(cfg: dict, req: dict, streaming: bool) -> requests.Response:
    if not is_enabled(cfg):
        raise AIError("No AI provider configured. Open Settings → AI provider (optional).")
    try:
        resp = requests.post(req["url"], headers=req["headers"], json=req["body"], timeout=TIMEOUT, stream=streaming)
    except requests.RequestException as exc:
        raise AIError(f"Could not reach {cfg['provider_def']['label']} ({exc.__class__.__name__}).") from exc
    if resp.status_code != 200:
        detail = resp.text[:300]
        if cfg.get("api_key"):
            detail = detail.replace(cfg["api_key"], "***")
        raise AIError(f"AI request failed ({resp.status_code}): {detail}")
    return resp


def complete(prompt: str, system: Optional[str] = None, max_tokens: int = 4000,
             temperature: Optional[float] = 0.3, settings: Optional[dict] = None) -> str:
    cfg = resolve(settings)
    req = _build(cfg, prompt, system, max_tokens, temperature, streaming=False)
    text = _extract(cfg["provider_def"].get("style"), _post(cfg, req, streaming=False).json()).strip()
    if not text:
        raise AIError("The AI provider returned an empty response.")
    return text


def stream(prompt: str, system: Optional[str] = None, max_tokens: int = 8000,
           temperature: Optional[float] = 0.3, settings: Optional[dict] = None) -> Iterator[str]:
    """Yield text chunks as they arrive (server-sent events for every style)."""
    cfg = resolve(settings)
    style = cfg["provider_def"].get("style")
    resp = _post(cfg, _build(cfg, prompt, system, max_tokens, temperature, streaming=True), streaming=True)
    for raw in resp.iter_lines(decode_unicode=True):
        if not raw or not raw.startswith("data:"):
            continue
        payload = raw[5:].strip()
        if payload == "[DONE]":
            break
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if style == "anthropic":
            if data.get("type") == "content_block_delta" and (data.get("delta") or {}).get("type") == "text_delta":
                yield data["delta"].get("text", "")
            elif data.get("type") == "message_delta" and (data.get("delta") or {}).get("stop_reason") == "refusal":
                yield "\n\n[The model declined this request.]"
            elif data.get("type") == "error":
                yield f"\n\n[AI error: {(data.get('error') or {}).get('message', 'unknown')}]"
        elif style == "gemini":
            chunk = _extract("gemini", data)
            if chunk:
                yield chunk
        else:
            delta = ((data.get("choices") or [{}])[0].get("delta") or {}).get("content")
            if delta:
                yield delta


def extract_json(text: str):
    if not text:
        return None
    candidate = text.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", candidate, re.I)
    if fenced:
        candidate = fenced.group(1).strip()
    start = min([i for i in (candidate.find("{"), candidate.find("[")) if i >= 0], default=-1)
    if start > 0:
        candidate = candidate[start:]
    end = max(candidate.rfind("}"), candidate.rfind("]"))
    if end != -1:
        candidate = candidate[:end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def complete_json(prompt: str, system: Optional[str] = None, **kwargs):
    sys_msg = (system + "\n" if system else "") + "Respond with valid JSON only. No prose, no markdown fences."
    parsed = extract_json(complete(prompt, system=sys_msg, temperature=kwargs.pop("temperature", 0.1), **kwargs))
    if parsed is None:
        raise AIError("The AI response was not valid JSON.")
    return parsed


def test_connection(settings: Optional[dict] = None) -> str:
    return complete("Reply with the single word: OK", max_tokens=200, temperature=0, settings=settings)
