"""Curated public-list prices per model (USD per 1M tokens).

Prices are best-effort and based on publicly published list rates as of
mid-2026. Models without a published per-token price (notably some
Copilot-proprietary routings and unknown vendor models) return ``None`` —
the portal displays token counts only in that case rather than a fabricated
dollar figure.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ModelPricing:
    input_per_1m: float
    output_per_1m: float


# Match rules are evaluated in order; the FIRST substring that the lowercase
# model name contains wins. Put more-specific keys before less-specific ones.
_PRICING: list[tuple[str, ModelPricing]] = [
    # ---- Anthropic Claude family ----
    ("claude-haiku-4",   ModelPricing(1.00,  5.00)),
    ("haiku",            ModelPricing(0.80,  4.00)),
    ("claude-sonnet-4",  ModelPricing(3.00, 15.00)),
    ("sonnet-4",         ModelPricing(3.00, 15.00)),
    ("claude-sonnet",    ModelPricing(3.00, 15.00)),
    ("sonnet",           ModelPricing(3.00, 15.00)),
    ("claude-opus-4",    ModelPricing(15.00, 75.00)),
    ("opus-4",           ModelPricing(15.00, 75.00)),
    ("claude-opus",      ModelPricing(15.00, 75.00)),
    ("opus",             ModelPricing(15.00, 75.00)),
    ("claude-3.5",       ModelPricing(3.00, 15.00)),
    # ---- OpenAI / GPT family ----
    ("gpt-5.5",          ModelPricing(15.00, 60.00)),
    ("gpt-5.4-mini",     ModelPricing(0.25,  2.00)),
    ("gpt-5.4",          ModelPricing(10.00, 40.00)),
    ("gpt-5.3-codex",    ModelPricing(5.00,  20.00)),
    ("gpt-5.1-codex-max",ModelPricing(8.00,  32.00)),
    ("gpt-5.1-codex",    ModelPricing(5.00,  20.00)),
    ("gpt-5-codex",      ModelPricing(5.00,  20.00)),
    ("gpt-5-mini",       ModelPricing(0.20,  1.60)),
    ("gpt-5",            ModelPricing(5.00,  20.00)),
    ("gpt-4o-mini",      ModelPricing(0.15,  0.60)),
    ("gpt-4o",           ModelPricing(2.50,  10.00)),
    # ---- Other ----
    ("gemini-2.5-pro",   ModelPricing(1.25,  5.00)),
    ("gemini-3.1-pro",   ModelPricing(1.50,  6.00)),
    ("gemini",           ModelPricing(0.35,  1.05)),
    ("mai-code",         ModelPricing(2.00,  8.00)),
]


def _normalize(model: str) -> str:
    m = model.lower().strip()
    for prefix in ("copilot/", "github-copilot/", "github/"):
        if m.startswith(prefix):
            m = m[len(prefix):]
            break
    return m


def resolve_pricing(model: str) -> Optional[ModelPricing]:
    if not model:
        return None
    m = _normalize(model)
    for key, price in _PRICING:
        if key in m:
            return price
    return None


def is_priced(model: str) -> bool:
    return resolve_pricing(model) is not None


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> Optional[float]:
    """Return the estimated USD cost, or None when the model has no published price."""
    p = resolve_pricing(model)
    if p is None:
        return None
    return (
        input_tokens / 1_000_000 * p.input_per_1m
        + output_tokens / 1_000_000 * p.output_per_1m
    )
def _cache_read_discount(model: str) -> float:
    m = _normalize(model)
    if "claude" in m:
        return 0.10
    if "gpt" in m or "codex" in m:
        return 0.50
    if "gemini" in m:
        return 0.25
    return 0.25


def estimate_cost_usd_v2(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> Optional[float]:
    """Cost with cache-aware pricing.

    `input_tokens` here is UNCACHED input (full rate).
    `cache_write_tokens` is charged at the input rate (provider stores it).
    `cache_read_tokens` is charged at a fraction of the input rate.
    """
    p = resolve_pricing(model)
    if p is None:
        return None
    discount = _cache_read_discount(model)
    return (
        input_tokens / 1_000_000 * p.input_per_1m
        + cache_write_tokens / 1_000_000 * p.input_per_1m
        + cache_read_tokens / 1_000_000 * p.input_per_1m * discount
        + output_tokens / 1_000_000 * p.output_per_1m
    )

