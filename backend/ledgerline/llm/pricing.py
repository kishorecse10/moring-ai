"""Token pricing for the cost dashboard and the llm_calls table."""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# USD per million tokens: (input, output), from the providers' pricing pages (checked November 2026).
# The v0.3 table was 1000x too low (claude-opus-5-5 at $0.004 / $0.020 instead of $4 / $20), which is
# why the dashboard showed about ₹15 for a month Anthropic billed at about $165.
USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-opus-4-5": (5.00, 25.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "gpt-4o-mini": (0.15, 0.60),
    "fake": (0.0, 0.0),
}

_warned: set[str] = set()


def is_priced(model: str) -> bool:
    return model in USD_PER_MTOK


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Cost of one call. None for a model we have no price for, so it isn't counted as free on the dashboard."""
    if model not in USD_PER_MTOK:
        if model not in _warned:
            log.warning("no price for model %r; its calls are reported as unpriced", model)
            _warned.add(model)
        return None
    input_price, output_price = USD_PER_MTOK[model]
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000
