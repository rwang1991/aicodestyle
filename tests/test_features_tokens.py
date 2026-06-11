"""Tests that extract_session_features emits Phase F token-economy fields."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aianalyzer.features import extract_session_features
from aianalyzer.normalize import (
    AssistantMessage,
    NormalizedSession,
    Turn,
    UserMessage,
    UsageRecord,
)


def _ts(off: int = 0) -> datetime:
    return datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=off)


def _turn(idx: int, user_text: str, assistant_text: str, model: str) -> Turn:
    return Turn(
        index=idx,
        user=UserMessage(content=user_text, ts=_ts(idx * 10)),
        assistant=AssistantMessage(
            turn_id=f"t{idx}",
            content=assistant_text,
            model=model,
            ts=_ts(idx * 10 + 5),
        ),
        tool_calls=[],
    )


def _session(turns: list[Turn], **kwargs) -> NormalizedSession:
    return NormalizedSession(
        session_id=kwargs.get("session_id", "s1"),
        client="copilot-cli",
        started_at=_ts(),
        ended_at=_ts(len(turns) * 10 + 10),
        cwd="/tmp",
        models_used=kwargs.get("models_used", set()),
        turns=turns,
        todos=[],
    )


def test_token_economy_fields_populated_for_priced_model():
    session = _session(
        [_turn(0, "hello world", "hi back to you", "claude-sonnet-4.6")],
        models_used={"claude-sonnet-4.6"},
    )
    f = extract_session_features(session)
    assert f.est_input_tokens > 0
    assert f.est_output_tokens > 0
    assert f.est_total_tokens == f.est_input_tokens + f.est_output_tokens
    assert f.est_cost_usd is not None and f.est_cost_usd > 0
    assert f.priced_token_share == 1.0


def test_token_economy_cost_none_for_unknown_model():
    session = _session(
        [_turn(0, "hello", "world", "mystery-model-xyz")],
        session_id="s2",
        models_used={"mystery-model-xyz"},
    )
    f = extract_session_features(session)
    assert f.est_total_tokens > 0
    assert f.est_cost_usd is None
    assert f.priced_token_share == 0.0
def test_actual_usage_fields_prefer_billed_totals():
    usage = UsageRecord(
        input_tokens=100,
        output_tokens=200,
        cache_read_tokens=1000,
        cache_write_tokens=50,
        premium_requests=2.5,
    )
    session = NormalizedSession(
        session_id="actual-s1",
        client="copilot-cli",
        started_at=_ts(),
        ended_at=_ts(60),
        turns=[_turn(0, "hello", "world", "claude-opus")],
        actual_usage=usage,
        actual_usage_by_model={"claude-opus": usage},
    )

    f = extract_session_features(session)

    assert f.actual_total_tokens == 1350
    assert f.has_actual_usage is True
    assert f.actual_cost_usd is not None and f.actual_cost_usd > 0
    assert f.premium_requests == 2.5


