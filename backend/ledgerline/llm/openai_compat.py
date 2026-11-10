"""Client for any OpenAI-compatible /chat/completions endpoint.

Works with OpenAI, Gemini's OpenAI-compatible endpoint, Groq, OpenRouter, vLLM and local
Ollama (OPENAI_BASE_URL=http://localhost:11434/v1, no key needed).
"""
from __future__ import annotations

import time

import httpx

from .base import LLMResponse


class OpenAICompatClient:
    def __init__(self, base_url: str, api_key: str | None, model: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def complete(self, system: str, prompt: str, max_tokens: int = 2000) -> LLMResponse:
        started = time.monotonic()
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            timeout=self.timeout,
            json={
                "model": self.model,
                "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        body = response.json()
        usage = body.get("usage") or {}
        return LLMResponse(
            text=body["choices"][0]["message"]["content"] or "",
            model=self.model,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
