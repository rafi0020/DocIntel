"""LLM provider layer: request shapes, JSON repair, retries (no network)."""
from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.extraction.llm import LLMClient, LLMError, parse_json


def client(provider, handler, **kw):
    s = Settings(llm_provider=provider, llm_api_key="k", llm_max_retries=2, **kw)
    c = LLMClient(s)
    c.http = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def test_openai_compatible_request_and_json_mode(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    seen = {}

    def handler(req: httpx.Request):
        seen["url"] = str(req.url)
        seen["auth"] = req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"total": 12.5}'}}]})

    c = client("openai_compatible", handler, llm_base_url="https://router.example/v1", llm_model="m1")
    r = c.extract("TOTAL 12.50")
    assert r.data == {"total": 12.5}
    assert seen["url"] == "https://router.example/v1/chat/completions"
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["response_format"] == {"type": "json_object"} and seen["body"]["temperature"] == 0


def test_anthropic_request_shape():
    def handler(req):
        body = json.loads(req.content)
        assert req.url.path == "/v1/messages" and req.headers["x-api-key"] == "k"
        assert body["system"].startswith("You are a meticulous")
        return httpx.Response(200, json={"content": [{"type": "text", "text": '```json\n{"invoice_number": "A-1"}\n```'}]})

    assert client("anthropic", handler).extract("x").data == {"invoice_number": "A-1"}


def test_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    assert client("groq", handler).extract("x").data == {}
    assert calls["n"] == 3


def test_client_error_is_not_retried(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(401, text="bad key")

    with pytest.raises(LLMError):
        client("openai", handler).extract("x")
    assert calls["n"] == 1


def test_parse_json_tolerates_chatter():
    assert parse_json('Sure! {"a": 1} hope that helps') == {"a": 1}
    with pytest.raises(ValueError):
        parse_json("no json here")
