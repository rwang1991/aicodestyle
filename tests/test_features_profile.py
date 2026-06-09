from datetime import datetime, timezone

from aianalyzer.features import (
    SessionFeatures,
    UserProfile,
    aggregate_user_profile,
)


def _sf(**overrides):
    base = dict(
        session_id="s",
        client="copilot-cli",
        started_at=datetime(2026, 6, 9, tzinfo=timezone.utc),
        turn_count=1,
    )
    base.update(overrides)
    return SessionFeatures(**base)


def test_aggregate_weighted_by_turn_count():
    a = _sf(session_id="a", turn_count=10, avg_user_msg_chars=100.0,
            planning_language_ratio=0.0, todo_count=2, model_variety=1)
    b = _sf(session_id="b", turn_count=30, avg_user_msg_chars=50.0,
            planning_language_ratio=0.5, todo_count=1, model_variety=2)

    profile = aggregate_user_profile([a, b], cwd_history=["C:/p1", "C:/p1", "C:/p2"])

    assert isinstance(profile, UserProfile)
    assert profile.session_count == 2
    assert profile.total_turns == 40
    # weighted mean: (100*10 + 50*30)/40 = 62.5
    assert profile.avg_user_msg_chars == 62.5
    # weighted: (0.0*10 + 0.5*30)/40 = 0.375
    assert profile.planning_language_ratio == 0.375
    assert profile.total_todos == 3
    assert profile.distinct_models_total == 2  # max across sessions; conservative
    # 2 distinct cwds -> 1 switch
    assert profile.cwd_switch_count == 1


def test_aggregate_empty_input():
    profile = aggregate_user_profile([], cwd_history=[])
    assert profile.session_count == 0
    assert profile.total_turns == 0
    assert profile.avg_user_msg_chars == 0.0
    assert profile.cwd_switch_count == 0
