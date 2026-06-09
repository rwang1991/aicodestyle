from datetime import datetime, timezone, timedelta

from aianalyzer.features import extract_session_features
from aianalyzer.normalize import (
    AssistantMessage,
    NormalizedSession,
    TodoSnapshot,
    ToolCall,
    Turn,
    UserMessage,
)


def _ts(seconds: int):
    return datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=seconds)


def test_meta_signals():
    session = NormalizedSession(
        client="copilot-cli",
        session_id="meta-1",
        started_at=_ts(0),
        ended_at=_ts(60),
        cwd="C:/x",
        models_used=["claude-opus-4.7-xhigh", "gpt-5-mini"],
        turns=[
            Turn(
                index=0,
                user=UserMessage(content="hi", ts=_ts(1)),
                assistant=AssistantMessage(
                    turn_id="t1", content="ok", model="claude-opus-4.7-xhigh",
                    reasoning_effort="xhigh", ts=_ts(2),
                ),
                tool_calls=[
                    ToolCall(tool_name="powershell", arguments={"command": "ls"},
                             success=True, duration_ms=10, ts_start=_ts(3), ts_end=_ts(3)),
                    ToolCall(tool_name="powershell", arguments={"command": "ls"},
                             success=True, duration_ms=10, ts_start=_ts(4), ts_end=_ts(4)),
                    ToolCall(tool_name="powershell", arguments={"command": "pwd"},
                             success=True, duration_ms=10, ts_start=_ts(5), ts_end=_ts(5)),
                ],
                aborted=False,
            ),
            Turn(
                index=1,
                user=UserMessage(content="more", ts=_ts(10)),
                assistant=AssistantMessage(
                    turn_id="t2", content="ok", model="gpt-5-mini",
                    reasoning_effort=None, ts=_ts(11),
                ),
                tool_calls=[],
                aborted=True,
            ),
        ],
        todos=[
            TodoSnapshot(todo_id="d1", title="Plan", status="done"),
            TodoSnapshot(todo_id="d2", title="Build", status="pending"),
        ],
    )

    f = extract_session_features(session)

    assert f.model_variety == 2
    # 1 of 2 assistant messages has a reasoning_effort label
    assert f.reasoning_effort_distribution == {"xhigh": 1.0}
    assert f.cwd_switch_count == 0
    # 3 powershell calls; 2 ('ls') repeat -> 2/3
    assert abs(f.command_repetition_rate - (2 / 3)) < 1e-6
    assert f.todo_count == 2
    # 1 of 2 turns aborted
    assert f.abort_rate == 0.5
