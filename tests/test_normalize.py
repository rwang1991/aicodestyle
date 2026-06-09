from datetime import datetime, timedelta, timezone

from aianalyzer.normalize import (
    NormalizedSession,
    Turn,
    ToolCall,
    UserMessage,
    AssistantMessage,
)


def _ts(seconds: int) -> datetime:
    base = datetime(2026, 6, 9, 10, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(seconds=seconds)


def test_normalized_session_round_trip():
    session = NormalizedSession(
        client="copilot-cli",
        session_id="abc123",
        started_at=_ts(0),
        ended_at=_ts(120),
        cwd="C:/work/proj",
        models_used=["claude-opus-4.7-xhigh"],
        turns=[
            Turn(
                index=0,
                user=UserMessage(content="Plan the refactor before coding.", ts=_ts(0)),
                assistant=AssistantMessage(
                    turn_id="t1",
                    content="Here is the plan...",
                    model="claude-opus-4.7-xhigh",
                    reasoning_effort="xhigh",
                    ts=_ts(5),
                ),
                tool_calls=[
                    ToolCall(
                        tool_name="view",
                        arguments={"path": "README.md"},
                        success=True,
                        duration_ms=42,
                        ts_start=_ts(6),
                        ts_end=_ts(6),
                    )
                ],
                aborted=False,
            )
        ],
    )
    payload = session.model_dump_json()
    restored = NormalizedSession.model_validate_json(payload)
    assert restored == session
    assert restored.turns[0].assistant.reasoning_effort == "xhigh"
    assert restored.turns[0].tool_calls[0].duration_ms == 42


def test_turn_rejects_negative_index():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Turn(index=-1, user=None, assistant=None, tool_calls=[], aborted=False)
