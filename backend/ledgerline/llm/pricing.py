"""Token pricing for the cost dashboard and the llm_calls table."""
from __future__ import annotations

# USD per million tokens: (input, output). From the providers' pricing pages.
# Last updated Oct 2026 (RK) when we moved to the 5.5 models.
USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (0.004, 0.020),
    "claude-sonnet-5-5": (0.002, 0.010),
    "claude-haiku-5-5": (0.0001, 0.0005),
    "claude-opus-4-5": (0.005, 0.025),
    "claude-sonnet-4-5": (0.003, 0.015),
    "gpt-4o-mini": (0.00015, 0.0006),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    input_price, output_price = USD_PER_MTOK.get(model, (0.0, 0.0))
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000
