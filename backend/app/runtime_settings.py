"""Configuration that can be changed at run time from the UI.

Precedence: a saved UI configuration (table `app_settings`, key "models") overrides the `.env` values, which act as the
starting defaults until an administrator saves something. Workers and the API read this per job through a short cache,
so a change applies to the next document without a restart.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import select

from .config import Settings, get_settings
from .db import SessionLocal
from .models import AppSetting
from .secrets_store import decrypt

log = logging.getLogger(__name__)
KEY = "models"
TTL_S = 5.0
PROVIDERS = ("anthropic", "gemini", "groq", "openai", "ollama", "openai_compatible")
OCR_ENGINES = ("tesseract", "rapidocr")

_cache: dict[str, Any] = {"at": 0.0, "row": None}


def invalidate() -> None:
    _cache["at"] = 0.0


def load_override(force: bool = False) -> dict | None:
    """The saved UI configuration, or None. Cached for a few seconds; falls back to .env if the database is unavailable."""
    now = time.monotonic()
    if not force and now - _cache["at"] < TTL_S:
        return _cache["row"]
    try:
        with SessionLocal() as s:
            row = s.scalars(select(AppSetting).where(AppSetting.key == KEY)).first()
            _cache["row"] = dict(row.value) if row else None
    except Exception:  # noqa: BLE001 - never let a settings read break processing
        log.exception("could not read runtime settings; using .env values")
    _cache["at"] = now
    return _cache["row"]


def apply_override(base: Settings, o: dict | None, api_key: str | None = None) -> Settings:
    """`base` (the .env settings) with a saved configuration applied."""
    if not o:
        return base
    update: dict[str, Any] = {
        "llm_provider": o.get("provider", "rules") if o.get("enabled") else "rules",
        "llm_model": o.get("model") or None,
        "llm_base_url": o.get("base_url") or None,
        "llm_api_key": api_key if api_key is not None else decrypt(o.get("api_key_enc")),
        "llm_timeout_s": float(o.get("timeout_s", base.llm_timeout_s)),
        "llm_max_retries": int(o.get("max_retries", base.llm_max_retries)),
        "llm_temperature": float(o.get("temperature", base.llm_temperature)),
        "llm_max_chars": int(o.get("max_chars", base.llm_max_chars)),
        "llm_concurrency": int(o.get("concurrency", base.llm_concurrency)),
        "llm_json_mode": bool(o.get("json_mode", base.llm_json_mode)),
        "ocr_engine": o.get("ocr_engine", base.ocr_engine),
    }
    return base.model_copy(update=update)


def effective_settings() -> Settings:
    """What the pipeline should use right now: .env defaults overridden by the saved UI configuration."""
    return apply_override(get_settings(), load_override())
