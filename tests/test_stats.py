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


# ---------------------------------------------------------------------------
# Phase D — weekday-hour matrix, off-peak share, model tier classification
# ---------------------------------------------------------------------------

def test_weekday_hour_matrix_buckets_by_local_weekday_and_hour():
    fs = [
        _sf(started_weekday=0, started_hour_local=9),   # Mon 9
        _sf(started_weekday=0, started_hour_local=9),   # Mon 9 again
        _sf(started_weekday=2, started_hour_local=14),  # Wed 14
        _sf(started_weekday=6, started_hour_local=23),  # Sun 23
    ]
    p = compute_extended_profile(fs)
    assert p.weekday_hour_matrix[0][9] == 2
    assert p.weekday_hour_matrix[2][14] == 1
    assert p.weekday_hour_matrix[6][23] == 1
    assert p.weekday_hour_matrix[3][10] == 0  # empty cell


def test_peak_cell_picks_modal_weekday_hour():
    fs = [_sf(started_weekday=2, started_hour_local=9) for _ in range(5)]
    fs += [_sf(started_weekday=3, started_hour_local=14) for _ in range(2)]
    p = compute_extended_profile(fs)
    assert p.peak_cell_weekday == 2
    assert p.peak_cell_hour == 9
    assert p.peak_cell_count == 5


def test_peak_cell_is_none_when_no_sessions():
    p = compute_extended_profile([])
    assert p.peak_cell_weekday is None
    assert p.peak_cell_hour is None
    assert p.peak_cell_count == 0


def test_off_peak_session_pct_counts_weekends_and_outside_9_to_18():
    fs = [
        _sf(started_weekday=0, started_hour_local=10),  # Mon 10 — peak
        _sf(started_weekday=1, started_hour_local=14),  # Tue 14 — peak
        _sf(started_weekday=2, started_hour_local=8),   # Wed 08 — off-peak
        _sf(started_weekday=3, started_hour_local=19),  # Thu 19 — off-peak
        _sf(started_weekday=5, started_hour_local=14),  # Sat 14 — off-peak
        _sf(started_weekday=6, started_hour_local=10),  # Sun 10 — off-peak
    ]
    p = compute_extended_profile(fs)
    assert p.off_peak_session_pct == pytest.approx(4 / 6)


def test_model_tier_counts_classify_premium_standard_fast():
    fs = [
        _sf(models_used={"claude-opus-4.7-xhigh": 100, "claude-haiku-4.5": 5}),
        _sf(models_used={"copilot/gpt-5-codex": 50, "copilot/gpt-5.5": 20}),
        _sf(models_used={"claude-sonnet-4.6": 30, "made-up-model": 7}),
    ]
    p = compute_extended_profile(fs)
    tiers = p.model_tier_counts
    # Opus + 5.5 -> Premium = 100 + 20 = 120
    assert tiers.get("Premium") == 120
    # Sonnet + GPT-5-codex -> Standard = 30 + 50 = 80
    assert tiers.get("Standard") == 80
    # Haiku -> Fast = 5
    assert tiers.get("Fast") == 5
    # Unknown -> Other = 7
    assert tiers.get("Other") == 7


def test_model_tier_helper_handles_edge_cases():
    from aianalyzer.stats import _model_tier
    assert _model_tier("") == "Other"
    assert _model_tier("CLAUDE-OPUS-4.7") == "Premium"
    assert _model_tier("gpt-5.5") == "Premium"
    assert _model_tier("gpt-5.4-mini") == "Fast"  # mini beats standard
    assert _model_tier("claude-sonnet-4.5") == "Standard"
    assert _model_tier("copilot/gpt-5-codex") == "Standard"
    assert _model_tier("totally-unknown") == "Other"


# ---------------------------------------------------------------------------
# Phase F — token economy aggregates
# ---------------------------------------------------------------------------

def test_compute_extended_profile_aggregates_token_totals():
    sessions = [
        _sf(session_id="s1", est_input_tokens=1000, est_output_tokens=2000,
            est_total_tokens=3000, est_cost_usd=0.05, priced_token_share=1.0),
        _sf(session_id="s2", est_input_tokens=500, est_output_tokens=1500,
            est_total_tokens=2000, est_cost_usd=0.03, priced_token_share=1.0),
        _sf(session_id="s3", est_input_tokens=200, est_output_tokens=300,
            est_total_tokens=500, est_cost_usd=None, priced_token_share=0.0),
    ]
    p = compute_extended_profile(sessions)
    assert p.est_input_tokens == 1700
    assert p.est_output_tokens == 3800
    assert p.est_total_tokens == 5500
    assert p.est_cost_usd == pytest.approx(0.08)
    # output (3800) / input (1700) ≈ 2.235
    assert p.output_to_input_ratio == pytest.approx(3800 / 1700)
    # 5000 of 5500 total tokens are priced ≈ 0.909
    assert p.priced_token_share == pytest.approx(5000 / 5500)


def test_pareto_sessions_for_80pct():
    # 10 sessions where session 1 has 800 tokens, rest 100 each => session 1 alone is 80%.
    sessions = [_sf(session_id="big", est_input_tokens=400, est_output_tokens=400,
                    est_total_tokens=800, est_cost_usd=0.01)]
    for i in range(9):
        sessions.append(_sf(session_id=f"s{i}", est_input_tokens=50, est_output_tokens=50,
                            est_total_tokens=100, est_cost_usd=0.001))
    p = compute_extended_profile(sessions)
    # total = 1700; 80% = 1360. The 800-session alone is 800, plus next sessions
    # at 100 each until cumulative >= 1360. 800 + 6*100 = 1400 >= 1360.
    assert p.sessions_for_80pct_tokens == 7


def test_top_cost_sessions_truncated_to_five_and_ordered():
    sessions = []
    for i in range(7):
        sessions.append(_sf(
            session_id=f"s{i}",
            est_input_tokens=i*100, est_output_tokens=i*100,
            est_total_tokens=i*200, est_cost_usd=float(i) * 0.01,
        ))
    p = compute_extended_profile(sessions)
    assert len(p.top_cost_sessions) == 5
    costs = [s["est_cost_usd"] for s in p.top_cost_sessions]
    assert costs == sorted(costs, reverse=True)
