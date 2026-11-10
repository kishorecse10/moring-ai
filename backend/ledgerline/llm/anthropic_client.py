"""Anthropic Messages API client."""
from __future__ import annotations

import time

from .base import LLMResponse


class AnthropicClient:
    def __init__(self, api_key: str | None, model: str):
        import anthropic  # imported lazily so tests never need it configured

        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def complete(self, system: str, prompt: str, max_tokens: int = 16000) -> LLMResponse:
        started = time.monotonic()
        message = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in message.content if block.type == "text")
        return LLMResponse(
            text=text,
            model=self.model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
