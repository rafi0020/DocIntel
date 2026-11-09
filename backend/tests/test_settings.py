"""Model / API settings edited from the UI, and the system status endpoints."""
from __future__ import annotations

import pytest
from sqlalchemy import select

SECRET = "test-api-key-0123456789abcdef"
BODY = {"enabled": True, "provider": "openai_compatible", "model": "gpt-test", "base_url": "https://gateway.example.com/v1/", "api_key": SECRET}


def saved_row():
    from app.db import SessionLocal
    from app.models import AppSetting

    with SessionLocal() as s:
        return s.scalars(select(AppSetting)).first()


def test_only_admins_can_read_or_change_model_settings(anon, make_client):
    rev, viewer = make_client("reviewer"), make_client("viewer")
    for c in (rev, viewer):
        assert c.get("/api/settings/models").status_code == 403
        assert c.put("/api/settings/models", json=BODY).status_code == 403
        assert c.post("/api/settings/models/test", json=BODY).status_code == 403
        assert c.delete("/api/settings/models").status_code == 403
        assert c.get("/api/settings/models/active").status_code == 200  # the model *name* is visible to everyone
    assert anon.put("/api/settings/models", json=BODY).status_code == 401


def test_defaults_come_from_env_and_rules_engine_is_the_fresh_install_state(client):
    v = client.get("/api/settings/models").json()
    assert v["source"] == "env" and v["enabled"] is False and v["key_set"] is False
    assert {p["id"] for p in v["providers"]} >= {"anthropic", "gemini", "groq", "openai", "ollama", "openai_compatible"}


def test_saved_key_is_encrypted_masked_and_never_returned(client):
    r = client.put("/api/settings/models", json=BODY)
    assert r.status_code == 200 and SECRET not in r.text
    v = r.json()
    assert v["source"] == "ui" and v["enabled"] and v["key_set"] and v["key_hint"] == "…cdef" and v["base_url"] == "https://gateway.example.com/v1"
    assert SECRET not in client.get("/api/settings/models").text
    enc = saved_row().value["api_key_enc"]
    assert enc and SECRET not in enc  # ciphertext in the database
    from app.secrets_store import decrypt

    assert decrypt(enc) == SECRET


def test_ui_settings_override_env_for_the_pipeline(client):
    from app import runtime_settings as rt

    client.put("/api/settings/models", json={**BODY, "concurrency": 2, "ocr_engine": "rapidocr"})
    eff = rt.effective_settings()
    assert (eff.llm_provider, eff.llm_model, eff.llm_api_key, eff.llm_concurrency, eff.ocr_engine) == ("openai_compatible", "gpt-test", SECRET, 2, "rapidocr")
    active = client.get("/api/settings/models/active").json()
    assert active == {"enabled": True, "provider": "openai_compatible", "model": "gpt-test", "ocr_engine": "rapidocr"}
    client.put("/api/settings/models", json={**BODY, "enabled": False, "api_key": None})
    assert rt.effective_settings().llm_provider == "rules"  # the on/off switch means rules only


def test_key_is_kept_replaced_or_cleared(client):
    from app.secrets_store import decrypt

    client.put("/api/settings/models", json=BODY)
    client.put("/api/settings/models", json={**BODY, "api_key": None, "model": "other"})  # omitted: unchanged
    assert decrypt(saved_row().value["api_key_enc"]) == SECRET
    client.put("/api/settings/models", json={**BODY, "api_key": "replacement-key-0000zzzz"})
    assert decrypt(saved_row().value["api_key_enc"]) == "replacement-key-0000zzzz"
    v = client.put("/api/settings/models", json={**BODY, "api_key": None, "clear_key": True}).json()
    assert v["key_set"] is False and saved_row().value["api_key_enc"] is None


@pytest.mark.parametrize("patch,msg", [
    ({"provider": "skynet"}, "provider must be"),
    ({"base_url": "ftp://x"}, "http"),
    ({"model": None}, "model name"),
    ({"base_url": None}, "base URL"),
    ({"ocr_engine": "magic"}, "ocr_engine"),
    ({"timeout_s": 1}, None),
])
def test_invalid_settings_are_rejected(client, patch, msg):
    r = client.put("/api/settings/models", json={**BODY, **patch})
    assert r.status_code == 422
    if msg:
        assert msg in r.text


def test_provider_presets_need_no_url_or_model(client):
    r = client.put("/api/settings/models", json={"enabled": True, "provider": "anthropic", "api_key": "k-123456789"})
    assert r.status_code == 200


def test_changes_are_audited_without_the_key(client):
    client.put("/api/settings/models", json=BODY)
    client.post("/api/settings/models/test", json=BODY)
    events = client.get("/api/audit?action=settings").json()["events"]
    assert {"settings.models_update", "settings.models_test"} <= {e["action"] for e in events}
    assert SECRET not in client.get("/api/audit?action=settings").text
    upd = next(e for e in events if e["action"] == "settings.models_update")
    assert upd["detail"]["key"] == "replaced" and upd["user_email"] == "admin@docintel.demo"


def test_reset_returns_to_env_defaults(client):
    client.put("/api/settings/models", json=BODY)
    v = client.delete("/api/settings/models").json()
    assert v["source"] == "env" and v["enabled"] is False and saved_row() is None


def test_connection_test_reports_success_latency_and_redacts_the_key(client, monkeypatch):
    from app.extraction.llm import LLMClient, LLMError

    monkeypatch.setattr(LLMClient, "complete", lambda self, system, user: '{"ok": true}')
    ok = client.post("/api/settings/models/test", json=BODY).json()
    assert ok["ok"] is True and ok["latency_ms"] >= 0 and "gpt-test" in ok["model"]

    def boom(self, system, user):
        raise LLMError(f"HTTP 401: bad key {self.s.llm_api_key}")

    monkeypatch.setattr(LLMClient, "complete", boom)
    bad = client.post("/api/settings/models/test", json=BODY).json()
    assert bad["ok"] is False and "HTTP 401" in bad["error"] and SECRET not in str(bad)
    assert saved_row() is None  # testing never saves


def test_test_uses_the_saved_key_when_none_is_typed(client, monkeypatch):
    from app.extraction.llm import LLMClient

    seen = {}
    monkeypatch.setattr(LLMClient, "complete", lambda self, s, u: seen.setdefault("key", self.s.llm_api_key) and '{"ok": true}')
    client.put("/api/settings/models", json=BODY)
    client.post("/api/settings/models/test", json={**BODY, "api_key": None})
    assert seen["key"] == SECRET


def test_system_status_for_any_signed_in_user(make_client, invoice):
    from tests.conftest import pdf_bytes

    rev, viewer = make_client("reviewer"), make_client("viewer")
    rev.post("/api/documents", files=[("files", ("a.pdf", pdf_bytes(invoice))), ("files", ("bad.pdf", b"%PDF-1.4 truncated"))])
    s = viewer.get("/api/system/status").json()
    assert s["database"]["ok"] and s["queue"]["ok"]
    assert s["last_24h"]["processed"] == 2 and s["last_24h"]["failed"] == 1 and s["last_24h"]["avg_ms"] is not None
    assert s["recent_failures"][0]["filename"] == "bad.pdf" and s["recent_failures"][0]["error_code"] == "corrupted_file"
    assert s["extraction"]["enabled"] is False
    assert viewer.post("/api/system/ping-model").status_code == 403
    assert rev.post("/api/system/ping-model").json()["ok"] is None  # rules engine: nothing to ping


def test_health_reflects_saved_settings(client):
    client.put("/api/settings/models", json={**BODY, "api_key": None})
    h = client.get("/api/health").json()["extraction"]
    assert h["llm_provider"] == "openai_compatible" and h["llm_model"] == "gpt-test"


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE", "POST"])
def test_browser_preflight_allows_every_method_the_ui_uses(anon, method):
    r = anon.options("/api/settings/models", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": method,
                                                      "Access-Control-Request-Headers": "content-type"})
    assert r.status_code == 200 and method in r.headers["access-control-allow-methods"]
    assert r.headers["access-control-allow-credentials"] == "true"
