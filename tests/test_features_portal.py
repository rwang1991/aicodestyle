"""Tests for portal-extended session fields (M4)."""
from datetime import datetime, timezone, timedelta

from aianalyzer.features import extract_session_features
from aianalyzer.normalize import (
    AssistantMessage,
    NormalizedSession,
    ToolCall,
    Turn,
    UserMessage,
)


def _ns_for_portal() -> NormalizedSession:
    ts0 = datetime(2026, 6, 10, 14, 30, tzinfo=timezone.utc)
    return NormalizedSession(
        client="copilot-cli",
        session_id="s-portal",
        started_at=ts0,
        ended_at=ts0 + timedelta(minutes=15),
        cwd="/home/dev/repos/proj-a",
        models_used=["claude-sonnet-4.5", "gpt-5"],
        turns=[
            Turn(
                index=0,
                user=UserMessage(content="hello world test prompt", ts=ts0),
                assistant=AssistantMessage(
                    turn_id="t0",
                    content="ok",
                    model="claude-sonnet-4.5",
                    ts=ts0 + timedelta(seconds=2),
                ),
                tool_calls=[
                    ToolCall(
                        tool_name="read",
                        arguments={"path": "src/a.py"},
                        success=True,
                        duration_ms=10,
                        ts_start=ts0 + timedelta(seconds=3),
                        ts_end=ts0 + timedelta(seconds=4),
                    ),
                    ToolCall(
                        tool_name="edit",
                        arguments={"path": "src/a.py"},
                        success=True,
                        duration_ms=20,
                        ts_start=ts0 + timedelta(seconds=5),
                        ts_end=ts0 + timedelta(seconds=6),
                    ),
                    ToolCall(
                        tool_name="bash",
                        arguments={"command": "pytest"},
                        success=False,
                        duration_ms=30,
                        ts_start=ts0 + timedelta(seconds=7),
                        ts_end=ts0 + timedelta(seconds=8),
                        error="x",
                    ),
                ],
                aborted=False,
            ),
            Turn(
                index=1,
                user=UserMessage(content="another short one", ts=ts0 + timedelta(seconds=10)),
                assistant=AssistantMessage(
                    turn_id="t1",
                    content="done",
                    model="gpt-5",
                    ts=ts0 + timedelta(seconds=11),
                ),
                tool_calls=[],
                aborted=False,
            ),
        ],
    )


def test_extract_session_features_populates_portal_fields():
    ns = _ns_for_portal()
    sf = extract_session_features(ns)

    assert sf.cwd == "/home/dev/repos/proj-a"
    # Turn 0: "hello world test prompt" = 4 words; Turn 1: "another short one" = 3 words; avg = 3.5
    assert sf.avg_user_msg_words == 3.5
    assert sf.tool_counts == {"read": 1, "edit": 1, "bash": 1}
    assert sf.file_paths_touched == {"src/a.py"}
    assert 0 <= sf.started_hour_local <= 23
    assert 0 <= sf.started_weekday <= 6
    # models_used is derived from per-turn assistant.model, not NormalizedSession.models_used
    assert sf.models_used == {"claude-sonnet-4.5": 1, "gpt-5": 1}


def test_extract_session_features_portal_defaults_when_empty():
    ns = NormalizedSession(
        client="copilot-cli",
        session_id="s-empty",
        started_at=datetime(2026, 6, 10, 9, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 6, 10, 9, 1, tzinfo=timezone.utc),
        turns=[],
    )
    sf = extract_session_features(ns)
    assert sf.cwd is None
    assert sf.avg_user_msg_words == 0.0
    assert sf.tool_counts == {}
    assert sf.file_paths_touched == set()
    assert sf.models_used == {}


def test_majority_test_files_detects_windows_backslash_paths():
    """Regression: real Copilot CLI sessions on Windows store paths with backslashes.
    The classifier's _is_test_path must normalize them so TESTING fires correctly."""
    from aianalyzer.classifier.session_types import SessionType

    ts0 = datetime(2026, 6, 10, 14, 30, tzinfo=timezone.utc)
    ns = NormalizedSession(
        client="copilot-cli",
        session_id="s-win-tests",
        started_at=ts0,
        ended_at=ts0 + timedelta(minutes=10),  # > 300s avoids QUICK_TASK
        turns=[
            Turn(
                index=0,
                user=UserMessage(content="add coverage for the auth module", ts=ts0),
                assistant=AssistantMessage(
                    turn_id="t0",
                    content="ok",
                    model="claude-sonnet-4.5",
                    ts=ts0 + timedelta(seconds=2),
                ),
                tool_calls=[
                    ToolCall(
                        tool_name="edit",
                        arguments={"path": r"src\tests\test_auth.py"},
                        success=True,
                        duration_ms=10,
                        ts_start=ts0 + timedelta(seconds=3),
                        ts_end=ts0 + timedelta(seconds=4),
                    ),
                ],
                aborted=False,
            ),
        ],
    )
    sf = extract_session_features(ns)
    assert sf.session_type == SessionType.TESTING
