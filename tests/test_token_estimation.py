"""Tests for the lazy tiktoken-backed token counter."""
from __future__ import annotations

from aianalyzer.features import _count_tokens, _reset_encoder_cache


def test_count_tokens_returns_positive_for_non_empty_text():
    n = _count_tokens("Hello, world! This is a sentence.")
    assert n > 3
    assert n < 20


def test_count_tokens_returns_zero_for_empty_text():
    assert _count_tokens("") == 0
    assert _count_tokens(None) == 0


def test_count_tokens_scales_with_length():
    short = _count_tokens("hi")
    long_ = _count_tokens("hello there how are you doing today my friend")
    assert long_ > short


def test_count_tokens_caches_encoder_between_calls():
    _reset_encoder_cache()
    a = _count_tokens("first call")
    b = _count_tokens("second call")
    assert a > 0 and b > 0
