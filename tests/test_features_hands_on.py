"""Tests for the new hands-on signal extractors (Phase A of axis rework)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aianalyzer.features import extract_session_features
from aianalyzer.normalize import (
    AssistantMessage,
    NormalizedSession,
    ToolCall,
    Turn,
    UserMessage,
)


def _ts(off: int = 0) -> datetime:
    return datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=off)


def _turn(
    idx: int,
    user_text: str,
    *,
    tool_calls: list[ToolCall] | None = None,
) -> Turn:
    base = _ts(idx * 10)
    return Turn(
        index=idx,
        user=UserMessage(content=user_text, ts=base),
        assistant=AssistantMessage(
            turn_id=f"t{idx}", content="ok", model="m", ts=base + timedelta(seconds=1)
        ),
        tool_calls=tool_calls or [],
    )


def _session(turns: list[Turn]) -> NormalizedSession:
    started = _ts(0)
    ended = started + timedelta(seconds=max(len(turns), 1) * 10)
    return NormalizedSession(
        client="copilot-cli",
        session_id="s1",
        started_at=started,
        ended_at=ended,
        cwd="/tmp",
        models_used=[],
        turns=turns,
        todos=[],
    )


def _tool(name: str, idx: int = 0) -> ToolCall:
    return ToolCall(
        tool_name=name,
        arguments={"path": f"/p/{idx}"},
        success=True,
        duration_ms=1,
        ts_start=_ts(2),
        ts_end=_ts(3),
    )


# ---------- prompt_specificity_avg ----------


def test_prompt_specificity_long_detailed_messages_score_high():
    short = "fix it"  # 2 words / 200 = 0.01
    long = (
        "please refactor the parser module to use the new ast helper and add unit "
        "tests for the edge cases we discussed yesterday in the design review"
    )
    feats = extract_session_features(_session([_turn(0, short), _turn(1, long)]))
    # avg of (0.01, ~0.12) ≈ 0.06–0.07
    assert 0.05 < feats.prompt_specificity_avg < 0.10


def test_prompt_specificity_capped_at_one():
    huge = " ".join(["word"] * 500)
    feats = extract_session_features(_session([_turn(0, huge)]))
    assert feats.prompt_specificity_avg == 1.0


# ---------- code_block_density ----------


def test_code_block_density_detects_fenced_blocks():
    msg_with = "Here's what I tried:\n```python\nprint(x)\n```\nWhat's wrong?"
    msg_without = "what's wrong with my code"
    feats = extract_session_features(
        _session([_turn(0, msg_with), _turn(1, msg_without)])
    )
    assert feats.code_block_density == 0.5


def test_code_block_density_detects_inline_code_lines():
    msg = "Look:\ndef foo():\n    return 1\nclass Bar:\n    pass"
    feats = extract_session_features(_session([_turn(0, msg)]))
    assert feats.code_block_density == 1.0


def test_code_block_density_zero_for_plain_chat():
    feats = extract_session_features(
        _session([_turn(0, "hello"), _turn(1, "what next"), _turn(2, "ok do that")])
    )
    assert feats.code_block_density == 0.0


# ---------- file_reference_rate ----------


def test_file_reference_rate_detects_paths_and_line_refs():
    msgs = [
        "edit src/foo.py to add a guard",              # path
        "look at parser.ts:123 - the regex is wrong",  # path + :line
        "what does load_weights() return",             # function()
        "@README explain this",                        # @ mention
        "fix the bug",                                 # none
    ]
    feats = extract_session_features(
        _session([_turn(i, m) for i, m in enumerate(msgs)])
    )
    assert feats.file_reference_rate == 0.8


# ---------- ai_agency_rate ----------


def test_ai_agency_rate_high_when_many_tools_per_prompt():
    tools = [_tool("view", i) for i in range(10)]
    feats = extract_session_features(
        _session([_turn(0, "do everything", tool_calls=tools)])
    )
    assert feats.ai_agency_rate == 10.0


def test_ai_agency_rate_zero_when_no_tools():
    feats = extract_session_features(_session([_turn(0, "hi"), _turn(1, "bye")]))
    assert feats.ai_agency_rate == 0.0


def test_ai_agency_rate_zero_when_no_user_messages():
    feats = extract_session_features(_session([]))
    assert feats.ai_agency_rate == 0.0
