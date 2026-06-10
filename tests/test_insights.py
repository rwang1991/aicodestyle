"""Tests for AIPersonality / compute_personality (Phase B vivid report)."""
from __future__ import annotations

from datetime import datetime, timezone

from aianalyzer.classifier.session_types import SessionType
from aianalyzer.features import SessionFeatures, UserProfile
from aianalyzer.insights import compute_personality


def _profile(**overrides) -> UserProfile:
    base = dict(
        session_count=50,
        total_turns=500,
        total_todos=10,
        avg_user_msg_chars=80.0,
        planning_language_ratio=0.4,
        question_ratio=0.2,
        thinks_before_prompt_sec_avg=20.0,
        test_or_spec_mention_rate=0.1,
        tool_diversity=1.5,
        accept_and_go_ratio=0.1,
        revision_depth=3.0,
        session_duration_sec=900.0,
        tool_error_rate=0.1,
        edited_files_per_turn_avg=2.0,
        parallel_tool_call_rate=0.2,
        abort_rate=0.05,
        prompt_specificity_avg=0.3,
        code_block_density=0.2,
        file_reference_rate=0.4,
        ai_agency_rate=2.0,
    )
    base.update(overrides)
    return UserProfile(**base)


def _feat(
    *,
    hour: int = 14,
    weekday: int = 2,
    turn_count: int = 10,
    session_type: SessionType = SessionType.MIXED,
) -> SessionFeatures:
    return SessionFeatures(
        session_id="s",
        client="copilot-cli",
        started_at=datetime(2026, 1, 1, hour, 0, tzinfo=timezone.utc),
        turn_count=turn_count,
        started_hour_local=hour,
        started_weekday=weekday,
        session_type=session_type,
    )


def test_personality_returns_nickname_and_tagline():
    p = compute_personality(_profile(), [_feat()])
    assert p.nickname
    assert p.tagline
    assert isinstance(p.badges, list)
    assert isinstance(p.did_you_know, list)


def test_night_owl_badge_when_most_sessions_after_22():
    feats = [_feat(hour=h) for h in (22, 23, 0, 1, 23, 22, 0)]
    p = compute_personality(_profile(), feats)
    assert any(b.title == "Night Owl" for b in p.badges)


def test_early_bird_badge_when_most_sessions_before_9():
    feats = [_feat(hour=h) for h in (6, 7, 7, 8, 6, 5, 8)]
    p = compute_personality(_profile(), feats)
    assert any(b.title == "Early Bird" for b in p.badges)


def test_polyglot_badge_when_many_models_touched():
    p = compute_personality(_profile(distinct_models_total=8), [_feat()])
    assert any(b.title == "Polyglot" for b in p.badges)


def test_planner_badge_when_high_todo_density():
    # 200 todos / 50 sessions = 4 todos/session >> threshold 1.0
    p = compute_personality(_profile(total_todos=200, session_count=50), [_feat()])
    assert any(b.title == "Planner" for b in p.badges)


def test_did_you_know_includes_total_sessions():
    p = compute_personality(_profile(session_count=247), [_feat() for _ in range(247)])
    text = " ".join(d.detail for d in p.did_you_know)
    assert "247" in text


def test_nickname_includes_archetype_word():
    # High planning + high control → "Architect"-ish nickname
    p = compute_personality(
        _profile(
            planning_language_ratio=0.8,
            prompt_specificity_avg=0.7,
            file_reference_rate=0.6,
            accept_and_go_ratio=0.05,
        ),
        [_feat()],
    )
    assert any(
        arch in p.nickname
        for arch in ("Architect", "Pilot", "Tinkerer", "Vibe Coder", "Coder")
    )


def test_handles_empty_session_list():
    p = compute_personality(UserProfile(), [])
    assert p.nickname
    assert p.tagline
    assert p.badges == []
    assert p.did_you_know == []


def test_streak_badge_appears_when_longest_streak_meets_threshold():
    p = compute_personality(
        _profile(),
        [_feat()],
        longest_streak_days=14,
    )
    assert any(b.title == "On a Roll" for b in p.badges)
    streak = next(b for b in p.badges if b.title == "On a Roll")
    assert "14" in streak.detail


def test_streak_badge_absent_when_streak_too_short():
    p = compute_personality(_profile(), [_feat()], longest_streak_days=2)
    assert not any(b.title == "On a Roll" for b in p.badges)


def test_favorite_tool_insight_appears_when_top_tools_provided():
    p = compute_personality(
        _profile(),
        [_feat()],
        top_tools=[("edit", 9824), ("readFile", 4000), ("search", 1200)],
    )
    titles = [d.title for d in p.did_you_know]
    assert "Favourite tool" in titles
    fav = next(d for d in p.did_you_know if d.title == "Favourite tool")
    assert "edit" in fav.detail
    assert "9824" in fav.detail or "9,824" in fav.detail


def test_favorite_tool_insight_absent_when_no_tools():
    p = compute_personality(_profile(), [_feat()], top_tools=[])
    assert not any(d.title == "Favourite tool" for d in p.did_you_know)
