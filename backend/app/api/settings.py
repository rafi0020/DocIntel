"""Model / API settings (admin) and system status (everyone signed in)."""
from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .. import runtime_settings as rt
from ..auth import Principal, audit, get_principal, need
from ..config import get_settings
from ..db import get_session
from ..extraction.llm import DEFAULTS, LLMClient, LLMError
from ..models import AppSetting, Document
from ..secrets_store import decrypt, encrypt, hint
from ..worker.queue import queue_health

router = APIRouter(prefix="/api", tags=["settings & status"])


# ------------------------------------------------------------------ models and API
class ModelsIn(BaseModel):
    enabled: bool = True
    provider: str = "openai_compatible"
    model: str | None = Field(None, max_length=200)
    base_url: str | None = Field(None, max_length=500)
    api_key: str | None = Field(None, max_length=1000, description="omit to keep the saved key")
    clear_key: bool = False
    timeout_s: float = Field(60, ge=5, le=300)
    max_retries: int = Field(3, ge=0, le=6)
    temperature: float = Field(0, ge=0, le=1)
    max_chars: int = Field(14000, ge=2000, le=100000)
    concurrency: int = Field(4, ge=1, le=16)
    json_mode: bool = True
    ocr_engine: str = "tesseract"


def _validate(body: ModelsIn) -> None:
    if body.provider not in rt.PROVIDERS:
        raise HTTPException(422, f"provider must be one of {', '.join(rt.PROVIDERS)}")
    if body.ocr_engine not in rt.OCR_ENGINES:
        raise HTTPException(422, f"ocr_engine must be one of {', '.join(rt.OCR_ENGINES)}")
    if body.base_url:
        u = urlparse(body.base_url.strip())
        if u.scheme not in ("http", "https") or not u.netloc:
            raise HTTPException(422, "Base URL must start with http:// or https://")
    if body.enabled:
        base, model = DEFAULTS[body.provider]
        if not (body.base_url or base):
            raise HTTPException(422, "This provider needs a base URL.")
        if not (body.model or model):
            raise HTTPException(422, "This provider needs a model name.")


def _view(session: Session) -> dict:
    env = get_settings()
    row = session.scalars(select(AppSetting).where(AppSetting.key == rt.KEY)).first()
    o = dict(row.value) if row else None
    eff = rt.apply_override(env, o)
    plain = decrypt(o.get("api_key_enc")) if o else env.llm_api_key
    return {
        "source": "ui" if o else "env",
        "enabled": eff.llm_provider != "rules",
        "provider": o.get("provider") if o else (env.llm_provider if env.llm_provider != "rules" else "openai_compatible"),
        "model": eff.llm_model if o else env.llm_model,
        "base_url": eff.llm_base_url if o else env.llm_base_url,
        "key_set": bool(plain), "key_hint": hint(plain),
        "key_unreadable": bool(o and o.get("api_key_enc") and not plain),
        "timeout_s": eff.llm_timeout_s, "max_retries": eff.llm_max_retries, "temperature": eff.llm_temperature,
        "max_chars": eff.llm_max_chars, "concurrency": eff.llm_concurrency, "json_mode": eff.llm_json_mode, "ocr_engine": eff.ocr_engine,
        "updated_by": row.updated_by if row else None, "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
        "providers": [{"id": p, "base_url": DEFAULTS[p][0], "model": DEFAULTS[p][1]} for p in rt.PROVIDERS],
    }


@router.get("/settings/models", summary="Model and API settings (admin). The key is never returned, only whether one is set")
def get_models(session: Session = Depends(get_session), _: Principal = Depends(need("admin"))):
    return _view(session)


@router.put("/settings/models", summary="Save model and API settings (admin). Applies to the next document, no restart")
def put_models(body: ModelsIn, request: Request, session: Session = Depends(get_session), p: Principal = Depends(need("admin"))):
    _validate(body)
    row = session.scalars(select(AppSetting).where(AppSetting.key == rt.KEY)).first()
    old = dict(row.value) if row else {}
    env = get_settings()
    enc = old.get("api_key_enc") if row else (encrypt(env.llm_api_key) if env.llm_api_key else None)  # first save adopts the .env key
    key_action = None
    if body.clear_key:
        enc, key_action = None, "cleared"
    elif body.api_key and body.api_key.strip():
        enc, key_action = encrypt(body.api_key.strip()), "replaced"
    value = {"enabled": body.enabled, "provider": body.provider, "model": (body.model or "").strip() or None,
             "base_url": (body.base_url or "").strip().rstrip("/") or None, "api_key_enc": enc, "timeout_s": body.timeout_s,
             "max_retries": body.max_retries, "temperature": body.temperature, "max_chars": body.max_chars,
             "concurrency": body.concurrency, "json_mode": body.json_mode, "ocr_engine": body.ocr_engine}
    if row:
        row.value, row.updated_by = value, p.email
    else:
        session.add(AppSetting(key=rt.KEY, value=value, updated_by=p.email))
    changed = [k for k in value if k != "api_key_enc" and old.get(k) != value[k]] if old else ["initial save"]
    audit(session, p, "settings.models_update", "settings", rt.KEY,
          {"provider": body.provider, "model": value["model"], "enabled": body.enabled, "changed": changed, **({"key": key_action} if key_action else {})}, request)
    session.commit()
    rt.invalidate()
    return _view(session)


@router.delete("/settings/models", summary="Discard the saved configuration and fall back to the .env defaults (admin)")
def reset_models(request: Request, session: Session = Depends(get_session), p: Principal = Depends(need("admin"))):
    row = session.scalars(select(AppSetting).where(AppSetting.key == rt.KEY)).first()
    if row:
        session.delete(row)
        audit(session, p, "settings.models_reset", "settings", rt.KEY, request=request)
        session.commit()
    rt.invalidate()
    return _view(session)


def _ping(cfg) -> dict:
    """One tiny completion. Never raises; the error text is trimmed and never contains the key."""
    if cfg.llm_provider == "rules":
        return {"ok": None, "message": "Rule engine only: no model is called."}
    t0 = time.perf_counter()
    try:
        client = LLMClient(cfg)
        reply = client.complete("Reply with JSON only.", 'Return {"ok": true}')
        return {"ok": True, "latency_ms": int((time.perf_counter() - t0) * 1000), "model": client.name, "reply": reply.strip()[:120]}
    except (LLMError, Exception) as e:  # noqa: BLE001
        msg = str(e)
        key = cfg.llm_api_key or ""
        if key:
            msg = msg.replace(key, "***")
        return {"ok": False, "latency_ms": int((time.perf_counter() - t0) * 1000), "error": msg[:300]}


@router.post("/settings/models/test", summary="Try the entered settings with a tiny request, without saving (admin)")
def test_models(body: ModelsIn, request: Request, session: Session = Depends(get_session), p: Principal = Depends(need("admin"))):
    _validate(body)
    env = get_settings()
    row = session.scalars(select(AppSetting).where(AppSetting.key == rt.KEY)).first()
    stored = decrypt(row.value.get("api_key_enc")) if row else env.llm_api_key
    key = None if body.clear_key else ((body.api_key or "").strip() or stored)
    cfg = rt.apply_override(env, {**body.model_dump(), "provider": body.provider}, api_key=key or "")
    cfg = cfg.model_copy(update={"llm_timeout_s": min(cfg.llm_timeout_s, 30), "llm_max_retries": 0, "llm_provider": body.provider if body.enabled else "rules"})
    res = _ping(cfg)
    audit(session, p, "settings.models_test", "settings", rt.KEY, {"provider": body.provider, "ok": res.get("ok")}, request)
    session.commit()
    return res


@router.get("/settings/models/active", summary="Which model is in use (any signed-in user). Never includes the key")
def active_model(_: Principal = Depends(get_principal)):
    s = rt.effective_settings()
    return {"enabled": s.llm_provider != "rules", "provider": s.llm_provider, "model": s.llm_model, "ocr_engine": s.ocr_engine}


# ------------------------------------------------------------------ system status
_ping_cache: dict = {"at": 0.0, "res": None}


@router.post("/system/ping-model", summary="Live check of the active model (reviewers and admins; cached for 8 s)")
def ping_model(_: Principal = Depends(need("reviewer"))):
    if time.monotonic() - _ping_cache["at"] < 8 and _ping_cache["res"]:
        return {**_ping_cache["res"], "cached": True}
    s = rt.effective_settings()
    res = _ping(s.model_copy(update={"llm_timeout_s": min(s.llm_timeout_s, 20), "llm_max_retries": 0}))
    _ping_cache.update(at=time.monotonic(), res=res)
    return res


@router.get("/system/status", summary="Health, the last 24 hours and recent failures (any signed-in user)")
def system_status(session: Session = Depends(get_session), _: Principal = Depends(get_principal)):
    s = rt.effective_settings()
    try:
        session.execute(text("select 1"))
        db = {"ok": True}
    except Exception as e:  # noqa: BLE001
        db = {"ok": False, "error": str(e)[:200]}
    since = datetime.now(UTC) - timedelta(hours=24)
    row = session.execute(
        select(func.count(), func.count().filter(Document.status == "failed"), func.avg(Document.processing_ms),
               func.percentile_cont(0.95).within_group(Document.processing_ms), func.sum(Document.page_count))
        .where(Document.finished_at >= since)).one()
    by_kind = session.execute(
        select(Document.source_kind, func.count(), func.avg(Document.processing_ms)).where(Document.finished_at >= since, Document.status != "failed")
        .group_by(Document.source_kind)).all()
    fails = session.scalars(select(Document).where(Document.status == "failed").order_by(Document.updated_at.desc()).limit(8)).all()
    return {
        "database": db, "queue": queue_health(),
        "extraction": {"enabled": s.llm_provider != "rules", "provider": s.llm_provider, "model": s.llm_model, "ocr_engine": s.ocr_engine,
                       "source": "ui" if rt.load_override() else "env"},
        "last_24h": {"processed": row[0] or 0, "failed": row[1] or 0, "avg_ms": round(float(row[2])) if row[2] else None,
                     "p95_ms": round(float(row[3])) if row[3] else None, "pages": int(row[4] or 0),
                     "by_kind": [{"source_kind": k, "documents": n, "avg_ms": round(float(a or 0))} for k, n, a in by_kind if k]},
        "recent_failures": [{"id": str(d.id), "filename": d.filename, "error_code": d.error_code, "error_message": d.error_message,
                             "at": (d.updated_at or d.created_at).isoformat()} for d in fails],
    }
