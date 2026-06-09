from datetime import datetime, timezone

import pytest

from aianalyzer.classifier.session_types import SessionType
from aianalyzer.features import SessionFeatures
from aianalyzer.stats import ExtendedProfile, compute_extended_profile


def _sf(**overrides) -> SessionFeatures:
    base = dict(
        session_id="sid",
        client="copilot-cli",
        started_at=datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
        turn_count=4,
        session_duration_sec=1800.0,
        edited_files_per_turn_avg=0.5,
        tool_error_rate=0.0,
        abort_rate=0.0,
        todo_count=0,
        # Portal fields
        cwd="/repos/proj-a",
        avg_user_msg_words=10.0,
        tool_counts={"edit": 2, "read": 1},
        file_paths_touched={"src/a.py", "src/b.py"},
        started_hour_local=10,
        started_weekday=0,
        models_used={"claude-sonnet-4.5": 4},
        session_type=SessionType.FEATURE_WORK,
    )
    base.update(overrides)
    return SessionFeatures(**base)


def test_compute_extended_profile_aggregates_basics():
    sessions = [
        _sf(session_id="s1"),
        _sf(
            session_id="s2",
            started_at=datetime(2026, 6, 2, 14, 0, tzinfo=timezone.utc),
            session_duration_sec=2700.0,
            turn_count=6,
            session_type=SessionType.DEBUGGING,
            cwd="/repos/proj-b",
            tool_counts={"bash": 2, "edit": 1},
            file_paths_touched={"src/x.py"},
            models_used={"gpt-5": 5},
            avg_user_msg_words=20.0,
            started_hour_local=14,
            started_weekday=1,
        ),
    ]
    p = compute_extended_profile(sessions)

    assert isinstance(p, ExtendedProfile)
    assert p.total_sessions == 2
    assert p.total_turns == 10
    assert p.total_hours == pytest.approx(1.25)
    assert p.avg_turns_per_session == 5.0
    assert p.avg_session_minutes == pytest.approx(37.5)
    assert p.session_type_counts == {"feature_work": 1, "debugging": 1}
    assert dict(p.top_tools).get("edit") == 3  # 2 + 1
    assert dict(p.top_projects).get("/repos/proj-a") == 1
    assert dict(p.top_models).get("claude-sonnet-4.5") == 4
    assert sum(p.hour_histogram) == 2
    assert sum(p.weekday_histogram) == 2
    assert p.avg_prompt_words == pytest.approx(15.0)
    assert p.acceptance_rate == pytest.approx(1.0)


def test_compute_extended_profile_handles_empty_input():
    p = compute_extended_profile([])
    assert p.total_sessions == 0
    assert p.total_turns == 0
    assert p.session_type_counts == {}
    assert p.top_tools == []
    assert p.hour_histogram == [0] * 24
    assert p.weekday_histogram == [0] * 7
    assert p.activity_per_day_last_90 == []


def test_longest_streak_three_consecutive_days():
    sessions = [
        _sf(session_id="d1", started_at=datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)),
        _sf(session_id="d2", started_at=datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)),
        _sf(session_id="d3", started_at=datetime(2026, 6, 3, 10, 0, tzinfo=timezone.utc)),
        _sf(session_id="d5", started_at=datetime(2026, 6, 5, 10, 0, tzinfo=timezone.utc)),
    ]
    p = compute_extended_profile(sessions)
    assert p.days_active == 4
    assert p.longest_streak_days == 3


def test_top_file_extensions():
    sessions = [
        _sf(file_paths_touched={"a.py", "b.py", "c.md"}),
        _sf(file_paths_touched={"x.py", "y.ts", r"src\windows\z.py"}),
    ]
    p = compute_extended_profile(sessions)
    exts = dict(p.top_file_extensions)
    assert exts.get(".py") == 4  # a.py, b.py, x.py, z.py
    assert exts.get(".md") == 1
    assert exts.get(".ts") == 1
