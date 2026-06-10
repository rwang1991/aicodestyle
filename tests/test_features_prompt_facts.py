"""Tests for prompt-mined per-session facts (Phase C vivid report)."""
from __future__ import annotations

from datetime import datetime, timezone

from aianalyzer.features import extract_session_features
from aianalyzer.normalize import (
    AssistantMessage,
    NormalizedSession,
    Turn,
    UserMessage,
)


def _dt(h: int, m: int = 0) -> datetime:
    return datetime(2026, 1, 1, h, m, 0, tzinfo=timezone.utc)


def _session_with_user_msgs(msgs: list[tuple[str, datetime]]) -> NormalizedSession:
    """Build a NormalizedSession with one turn per (text, ts) pair.

    Each turn has a matching assistant reply 1 second later (kept trivial — we
    only care about user-side fields here).
    """
    turns = []
    for i, (text, ts) in enumerate(msgs):
        turns.append(Turn(
            index=i,
            user=UserMessage(content=text, ts=ts),
            assistant=AssistantMessage(
                turn_id=f"t{i}", content="ok", model="m",
                ts=ts.replace(second=1) if ts.second == 0 else ts,
            ),
        ))
    starts = [t[1] for t in msgs] or [_dt(0)]
    return NormalizedSession(
        client="copilot-cli",
        session_id="s1",
        started_at=min(starts),
        ended_at=max(starts),
        cwd=None,
        models_used=[],
        turns=turns,
        todos=[],
    )


def test_extract_session_features_emits_prompt_facts():
    msgs = [
        ("hello world this is short", _dt(9, 30)),                # 5 words
        (" ".join(["word"] * 200),    _dt(10, 0)),                # 200 words
        ("add a unit test for the parser", _dt(11, 15)),          # 7 words
    ]
    sf = extract_session_features(_session_with_user_msgs(msgs))

    assert sf.longest_prompt_words == 200
    assert sf.total_user_words == 5 + 200 + 7
    assert sf.first_user_msg_at == _dt(9, 30)
    assert sf.last_user_msg_at == _dt(11, 15)
    assert sf.first_words == ["hello", "word", "add"]


def test_empty_session_has_zeroed_prompt_facts():
    sf = extract_session_features(_session_with_user_msgs([]))
    assert sf.longest_prompt_words == 0
    assert sf.total_user_words == 0
    assert sf.first_user_msg_at is None
    assert sf.last_user_msg_at is None
    assert sf.first_words == []


def test_first_words_strips_punctuation_and_lowercases():
    msgs = [
        ("Fix the bug", _dt(9)),
        ("/refactor please", _dt(10)),   # leading slash should be stripped
        ("CREATE a new module", _dt(11)),
    ]
    sf = extract_session_features(_session_with_user_msgs(msgs))
    assert sf.first_words == ["fix", "refactor", "create"]
