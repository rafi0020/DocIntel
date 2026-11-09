"""LLM providers behind one tiny interface.

Supported via LLM_PROVIDER:
  anthropic          native Messages API
  gemini             Google's OpenAI-compatible endpoint
  groq / openai      OpenAI-compatible
  ollama             local models via Ollama's OpenAI-compatible endpoint
  openai_compatible  any other gateway (OpenRouter, vLLM, LiteLLM, ...) via LLM_BASE_URL
  rules              no LLM; deterministic extractor only

Plain httpx, no vendor SDKs: one less dependency per provider, and the request
each provider receives is easy to audit.
"""
from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass

import httpx

from ..config import Settings, get_settings
from .prompts import SYSTEM_PROMPT, user_prompt

DEFAULTS = {
    "anthropic": ("https://api.anthropic.com/v1", "claude-haiku-4-5"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash"),
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "ollama": ("http://localhost:11434/v1", "qwen2.5:7b-instruct"),
    "openai_compatible": (None, None),
}


class LLMError(Exception):
    pass


@dataclass
class LLMResult:
    data: dict
    model: str
    latency_ms: int
    raw: str


def parse_json(text: str) -> dict:
    """Parse model output that should be JSON, tolerating code fences / chatter."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start >= 0 and end > start:
            return json.loads(t[start : end + 1])
        raise


class LLMClient:
    def __init__(self, settings: Settings | None = None):
        self.s = settings or get_settings()
        self.provider = self.s.llm_provider
        base, model = DEFAULTS.get(self.provider, (None, None))
        self.base_url = (self.s.llm_base_url or base or "").rstrip("/")
        self.model = self.s.llm_model or model
        if self.provider not in DEFAULTS:
            raise LLMError(f"Unknown LLM_PROVIDER '{self.provider}'")
        if not self.base_url or not self.model:
            raise LLMError("LLM_BASE_URL and LLM_MODEL are required for this provider")
        self.http = httpx.Client(timeout=self.s.llm_timeout_s)

    @property
    def name(self) -> str:
        return f"{self.provider}:{self.model}"

    def _post(self, url: str, headers: dict, body: dict) -> dict:
        last = None
        for attempt in range(self.s.llm_max_retries + 1):
            try:
                r = self.http.post(url, headers=headers, json=body)
                if r.status_code in (429, 500, 502, 503, 504, 529):
                    last = LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
                elif r.status_code >= 400:
                    raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
                else:
                    return r.json()
            except httpx.HTTPError as e:
                last = LLMError(f"network error: {e}")
            time.sleep(min(20, (2**attempt) + random.random()))
        raise last or LLMError("request failed")

    def complete(self, system: str, user: str) -> str:
        if self.provider == "anthropic":
            body = {
                "model": self.model,
                "max_tokens": 4096,
                "temperature": self.s.llm_temperature,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
            headers = {"x-api-key": self.s.llm_api_key or "", "anthropic-version": "2023-06-01"}
            data = self._post(f"{self.base_url}/messages", headers, body)
            return "".join(b.get("text", "") for b in data.get("content", []))

        body = {
            "model": self.model,
            "temperature": self.s.llm_temperature,
            "stream": False,  # some gateways stream by default; the client expects one JSON body
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if self.s.llm_json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.s.llm_api_key or 'none'}"}
        data = self._post(f"{self.base_url}/chat/completions", headers, body)
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"unexpected response shape: {str(data)[:200]}") from e

    def extract(self, document_text: str) -> LLMResult:
        t0 = time.perf_counter()
        raw = self.complete(SYSTEM_PROMPT, user_prompt(document_text))
        try:
            data = parse_json(raw)
        except (json.JSONDecodeError, ValueError):
            # One repair attempt: ask the model to return valid JSON only.
            raw = self.complete(SYSTEM_PROMPT, user_prompt(document_text) + "\n\nYour previous reply was not valid JSON. Reply with the JSON object only.")
            data = parse_json(raw)
        if not isinstance(data, dict):
            raise LLMError("model did not return a JSON object")
        return LLMResult(data, self.name, int((time.perf_counter() - t0) * 1000), raw)


_client: LLMClient | None = None
_client_sig: tuple | None = None


def _signature(s: Settings) -> tuple:
    return (s.llm_provider, s.llm_model, s.llm_base_url, s.llm_api_key, s.llm_timeout_s, s.llm_max_retries, s.llm_json_mode, s.llm_temperature)


def get_llm() -> LLMClient | None:
    """Return the client for the *current* configuration (UI settings override .env), or None when rules-only."""
    global _client, _client_sig
    from ..runtime_settings import effective_settings

    s = effective_settings()
    if s.llm_provider == "rules":
        return None
    sig = _signature(s)
    if _client is None or _client_sig != sig:
        _client, _client_sig = LLMClient(s), sig
    return _client
