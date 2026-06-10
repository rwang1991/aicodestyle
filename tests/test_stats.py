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
    assert p.by_client == {}
    assert p.top_tools == []
    assert p.hour_histogram == [0] * 24
    assert p.weekday_histogram == [0] * 7
    assert p.activity_per_day_last_90 == []


def test_by_client_breakdown_aggregates_sessions_turns_and_tool_calls():
    """Multiple clients must produce a per-client {sessions, turns, hours, tool_calls}."""
    sessions = [
        _sf(session_id="cli1", client="copilot-cli", turn_count=4,
            tool_counts={"edit": 3, "bash": 2}, session_duration_sec=3600.0),
        _sf(session_id="cli2", client="copilot-cli", turn_count=6,
            tool_counts={"edit": 1}),
        _sf(session_id="vsc1", client="vscode-copilot", turn_count=10,
            tool_counts={"copilot_readFile": 8, "copilot_replaceString": 2},
            session_duration_sec=1800.0),
    ]
    p = compute_extended_profile(sessions)

    assert set(p.by_client.keys()) == {"copilot-cli", "vscode-copilot"}
    cli = p.by_client["copilot-cli"]
    vsc = p.by_client["vscode-copilot"]
    assert cli["sessions"] == 2
    assert cli["turns"] == 10
    assert cli["tool_calls"] == 6  # 3+2+1
    assert vsc["sessions"] == 1
    assert vsc["turns"] == 10
    assert vsc["tool_calls"] == 10  # 8+2
    # hours rounded to 2dp; cli is 1.0 (3600s) + 0.5 (1800s default) = 1.5
    assert cli["hours"] == 1.5
    assert vsc["hours"] == 0.5


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


# ---------------------------------------------------------------------------
# Phase C: prompt-mined aggregates
# ---------------------------------------------------------------------------


def test_marathon_session_picks_max_engaged_duration():
    sessions = [
        _sf(session_id="short", session_duration_sec=600.0,
            started_at=datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)),
        _sf(session_id="long", session_duration_sec=22320.0,  # 372 min
            started_at=datetime(2026, 3, 12, 9, 0, tzinfo=timezone.utc)),
        _sf(session_id="mid", session_duration_sec=5400.0,
            started_at=datetime(2026, 6, 2, 14, 0, tzinfo=timezone.utc)),
    ]
    p = compute_extended_profile(sessions)
    assert p.marathon_session_minutes == pytest.approx(372.0)
    assert p.marathon_session_started_at == datetime(2026, 3, 12, 9, 0, tzinfo=timezone.utc)


def test_longest_prompt_aggregation():
    sessions = [
        _sf(session_id="a", longest_prompt_words=42, total_user_words=120,
            started_at=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)),
        _sf(session_id="b", longest_prompt_words=380, total_user_words=900,
            started_at=datetime(2026, 5, 2, 11, 0, tzinfo=timezone.utc)),
        _sf(session_id="c", longest_prompt_words=10, total_user_words=30),
    ]
    p = compute_extended_profile(sessions)
    assert p.longest_prompt_words == 380
    assert p.longest_prompt_session_started_at == datetime(2026, 5, 2, 11, 0, tzinfo=timezone.utc)
    assert p.total_user_words == 120 + 900 + 30


def test_latest_and_earliest_prompt_local_hm_picks_extreme_local_time():
    morning = datetime(2026, 6, 1, 5, 14, tzinfo=timezone.utc)   # local hour 5
    evening = datetime(2026, 6, 1, 13, 30, tzinfo=timezone.utc)  # local hour 13
    midnight = datetime(2026, 6, 1, 2, 47, tzinfo=timezone.utc)  # local hour 2
    sessions = [
        _sf(session_id="m", first_user_msg_at=morning, last_user_msg_at=morning),
        _sf(session_id="e", first_user_msg_at=evening, last_user_msg_at=evening),
        _sf(session_id="n", first_user_msg_at=midnight, last_user_msg_at=midnight),
    ]
    p = compute_extended_profile(sessions)

    # earliest_local_hm = min hour-of-day
    assert p.earliest_prompt_local_hm == (midnight.astimezone().hour, midnight.astimezone().minute)
    assert p.earliest_prompt_at == midnight
    # latest_local_hm = max hour-of-day
    assert p.latest_prompt_local_hm == (evening.astimezone().hour, evening.astimezone().minute)
    assert p.latest_prompt_at == evening


def test_peak_day_picks_busiest_calendar_day():
    sessions = (
        [_sf(session_id=f"a{i}", started_at=datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)) for i in range(5)]
        + [_sf(session_id=f"b{i}", started_at=datetime(2026, 6, 2, 10, 0, tzinfo=timezone.utc)) for i in range(2)]
    )
    p = compute_extended_profile(sessions)
    # Peak day is computed in local time, so just check the count is correct.
    assert p.peak_day_count == 5
    assert p.peak_day_date is not None


def test_weekend_session_pct_counts_saturday_and_sunday():
    sessions = [
        _sf(session_id="mon", started_weekday=0),
        _sf(session_id="tue", started_weekday=1),
        _sf(session_id="sat", started_weekday=5),
        _sf(session_id="sun", started_weekday=6),
    ]
    p = compute_extended_profile(sessions)
    assert p.weekend_session_pct == pytest.approx(0.5)


def test_top_first_words_aggregates_across_sessions():
    sessions = [
        _sf(session_id="a", first_words=["fix", "fix", "add"]),
        _sf(session_id="b", first_words=["fix", "create", "add"]),
    ]
    p = compute_extended_profile(sessions)
    tw = dict(p.top_first_words)
    assert tw["fix"] == 3
    assert tw["add"] == 2
    assert tw["create"] == 1


def test_empty_profile_has_zeroed_prompt_aggregates():
    p = compute_extended_profile([])
    assert p.longest_prompt_words == 0
    assert p.longest_prompt_session_started_at is None
    assert p.total_user_words == 0
    assert p.marathon_session_minutes == 0.0
    assert p.marathon_session_started_at is None
    assert p.latest_prompt_local_hm is None
    assert p.earliest_prompt_local_hm is None
    assert p.peak_day_count == 0
    assert p.peak_day_date is None
    assert p.weekend_session_pct == 0.0
    assert p.top_first_words == []
