"""Pricing table tests — verifies model name resolution and cost math."""
from __future__ import annotations

import pytest

from aianalyzer.pricing import (
    estimate_cost_usd,
    is_priced,
    resolve_pricing,
)


def test_resolve_pricing_exact_match_for_claude_opus():
    p = resolve_pricing("claude-opus-4.7-xhigh")
    assert p is not None
    assert p.input_per_1m == 15.0
    assert p.output_per_1m == 75.0


def test_resolve_pricing_handles_copilot_prefix():
    p = resolve_pricing("copilot/gpt-5")
    assert p is not None
    assert p.input_per_1m > 0


def test_resolve_pricing_returns_none_for_unknown_model():
    assert resolve_pricing("vendor-x-mystery-model-9") is None


def test_estimate_cost_usd_basic_arithmetic():
    # claude-haiku-4.5: $1 in / $5 out per 1M.
    cost = estimate_cost_usd("claude-haiku-4.5", input_tokens=1_000_000, output_tokens=200_000)
    assert cost == pytest.approx(1.0 + 1.0)


def test_estimate_cost_usd_none_for_unknown_model():
    assert estimate_cost_usd("totally-unknown", 1_000_000, 100_000) is None


def test_is_priced_true_for_known_model():
    assert is_priced("claude-opus-4.6") is True


def test_is_priced_false_for_unknown_model():
    assert is_priced("custom-private-model") is False
