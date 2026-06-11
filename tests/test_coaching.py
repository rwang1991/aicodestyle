"""Phase G — AI Coach rule engine."""
from __future__ import annotations

from datetime import datetime, timezone

from aianalyzer.coaching import (
    CoachReport,
    CoachTip,
    Severity,
    compute_coach_report,
)
from aianalyzer.features import SessionFeatures
from aianalyzer.stats import ExtendedProfile


def _empty_profile() -> ExtendedProfile:
    return ExtendedProfile(
        total_sessions=0,
        total_turns=0,
        first_session_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_session_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_coach_report_dataclass_default():
    rep = CoachReport()
    assert rep.score == 0
    assert rep.band == "Apprentice"
    assert rep.tips == []


def test_coach_tip_dataclass_required_fields():
    t = CoachTip(
        rule_id="A1",
        severity=Severity.TIP,
        category="cost",
        headline="Tighten your asks",
        body="Your output/input ratio is high.",
        impact_estimate=0.4,
        evidence={"output_to_input_ratio": 3.5},
    )
    assert t.rule_id == "A1"
    assert t.severity == Severity.TIP


def test_empty_profile_returns_empty_tips_and_low_score():
    rep = compute_coach_report(_empty_profile(), features=[])
    assert isinstance(rep, CoachReport)
    assert rep.tips == []
    assert 0 <= rep.score <= 100
    assert rep.band in {"Apprentice", "Practitioner", "Operator", "Conductor"}


def _profile_with(**overrides) -> ExtendedProfile:
    p = _empty_profile()
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


def _features_with_agency(values: list[float]) -> list[SessionFeatures]:
    return [
        SessionFeatures(
            session_id=f"s{i}",
            client="copilot-cli",
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ai_agency_rate=v,
        )
        for i, v in enumerate(values)
    ]


def _tip_with_id(rep_or_tips, rule_id):
    tips = rep_or_tips.tips if hasattr(rep_or_tips, "tips") else rep_or_tips
    for t in tips:
        if t.rule_id == rule_id:
            return t
    return None


def test_rule_a1_output_input_ratio_high():
    from aianalyzer.coaching import _rule_a1_output_input_high
    p = _profile_with(output_to_input_ratio=3.5, total_sessions=20)
    tip = _rule_a1_output_input_high(p, [])
    assert tip is not None
    assert tip.rule_id == "A1"
    assert tip.severity == Severity.TIP
    assert "3.5" in tip.body or "3.5x" in tip.body or "Output is 3.5×" in tip.body


def test_rule_a1_does_not_fire_when_ratio_balanced():
    from aianalyzer.coaching import _rule_a1_output_input_high
    p = _profile_with(output_to_input_ratio=2.0, total_sessions=20)
    assert _rule_a1_output_input_high(p, []) is None


def test_rule_a2_output_input_ratio_low():
    from aianalyzer.coaching import _rule_a2_output_input_low
    p = _profile_with(output_to_input_ratio=0.3, total_sessions=15)
    tip = _rule_a2_output_input_low(p, [])
    assert tip is not None
    assert tip.rule_id == "A2"


def test_rule_a2_skips_when_too_few_sessions():
    from aianalyzer.coaching import _rule_a2_output_input_low
    p = _profile_with(output_to_input_ratio=0.3, total_sessions=5)
    assert _rule_a2_output_input_low(p, []) is None


def test_rule_a3_pareto_concentrated():
    from aianalyzer.coaching import _rule_a3_pareto_concentrated
    p = _profile_with(
        total_sessions=100,
        sessions_for_80pct_tokens=8,
        est_total_tokens=1_000_000,
    )
    tip = _rule_a3_pareto_concentrated(p, [])
    assert tip is not None
    assert tip.severity == Severity.HEADS_UP


def test_rule_a3_does_not_fire_when_even():
    from aianalyzer.coaching import _rule_a3_pareto_concentrated
    p = _profile_with(
        total_sessions=100,
        sessions_for_80pct_tokens=40,
        est_total_tokens=1_000_000,
    )
    assert _rule_a3_pareto_concentrated(p, []) is None


def test_rule_a4_expensive_session():
    from aianalyzer.coaching import _rule_a4_expensive_session
    p = _profile_with(top_cost_sessions=[
        {"session_id": "x", "est_cost_usd": 7.21, "est_total_tokens": 180_000},
    ])
    tip = _rule_a4_expensive_session(p, [])
    assert tip is not None
    assert "$7.21" in tip.body


def test_rule_a4_skips_under_threshold():
    from aianalyzer.coaching import _rule_a4_expensive_session
    p = _profile_with(top_cost_sessions=[
        {"session_id": "x", "est_cost_usd": 2.10, "est_total_tokens": 50_000},
    ])
    assert _rule_a4_expensive_session(p, []) is None


def test_rule_a5_unpriced_share_high():
    from aianalyzer.coaching import _rule_a5_unpriced_share
    p = _profile_with(priced_token_share=0.70, est_total_tokens=500_000)
    tip = _rule_a5_unpriced_share(p, [])
    assert tip is not None
    assert "30" in tip.body or "30%" in tip.body  # 1 - 0.70 = 30%


def test_rule_a5_skips_when_priced_share_high():
    from aianalyzer.coaching import _rule_a5_unpriced_share
    p = _profile_with(priced_token_share=0.95, est_total_tokens=500_000)
    assert _rule_a5_unpriced_share(p, []) is None


def test_rule_a6_premium_on_short_sessions():
    from aianalyzer.coaching import _rule_a6_premium_for_quick
    p = _profile_with(
         model_tier_counts={"Premium": 80, "Standard": 10, "Fast": 5},
        avg_turns_per_session=3.0,
    )
    tip = _rule_a6_premium_for_quick(p, [])
    assert tip is not None
    assert tip.rule_id == "A6"


def test_rule_a6_skips_when_balanced_use():
    from aianalyzer.coaching import _rule_a6_premium_for_quick
    p = _profile_with(
        model_tier_counts={"Premium": 30, "Standard": 50, "Fast": 20},
        avg_turns_per_session=12.0,
    )
    assert _rule_a6_premium_for_quick(p, []) is None


def test_rule_b1_short_prompts():
    from aianalyzer.coaching import _rule_b1_short_prompts
    p = _profile_with(median_prompt_words=6, total_sessions=15)
    tip = _rule_b1_short_prompts(p, [])
    assert tip is not None
    assert tip.severity == Severity.TIP


def test_rule_b1_skips_at_threshold():
    from aianalyzer.coaching import _rule_b1_short_prompts
    p = _profile_with(median_prompt_words=10, total_sessions=15)
    assert _rule_b1_short_prompts(p, []) is None


def test_rule_b2_overspecify_then_iterate():
    from aianalyzer.coaching import _rule_b2_overspecify
    p = _profile_with(median_prompt_words=300, avg_turns_per_session=25, total_sessions=20)
    tip = _rule_b2_overspecify(p, [])
    assert tip is not None
    assert tip.severity == Severity.TIP


def test_rule_b2_skips_when_short_sessions():
    from aianalyzer.coaching import _rule_b2_overspecify
    p = _profile_with(median_prompt_words=300, avg_turns_per_session=5, total_sessions=20)
    assert _rule_b2_overspecify(p, []) is None


def test_rule_b3_sweet_spot_win():
    from aianalyzer.coaching import _rule_b3_sweet_spot
    p = _profile_with(median_prompt_words=70, total_sessions=20)
    tip = _rule_b3_sweet_spot(p, [])
    assert tip is not None
    assert tip.severity == Severity.WIN


def test_rule_b3_skips_outside_range():
    from aianalyzer.coaching import _rule_b3_sweet_spot
    p = _profile_with(median_prompt_words=5, total_sessions=20)
    assert _rule_b3_sweet_spot(p, []) is None


def test_rule_c1_hands_off_extreme():
    from aianalyzer.coaching import _rule_c1_hands_off
    p = _profile_with(total_sessions=30)
    fs = _features_with_agency([0.95] * 30)  # 5% hands-on
    tip = _rule_c1_hands_off(p, fs)
    assert tip is not None
    assert tip.severity == Severity.HEADS_UP


def test_rule_c1_skips_when_balanced():
    from aianalyzer.coaching import _rule_c1_hands_off
    p = _profile_with(total_sessions=30)
    fs = _features_with_agency([0.7] * 30)  # 30% hands-on
    assert _rule_c1_hands_off(p, fs) is None


def test_rule_c2_micromanage():
    from aianalyzer.coaching import _rule_c2_micromanage
    p = _profile_with(total_sessions=25)
    fs = _features_with_agency([0.30] * 25)  # 70% hands-on
    tip = _rule_c2_micromanage(p, fs)
    assert tip is not None
    assert tip.severity == Severity.TIP


def test_rule_c2_skips_when_balanced():
    from aianalyzer.coaching import _rule_c2_micromanage
    p = _profile_with(total_sessions=25)
    fs = _features_with_agency([0.65] * 25)  # 35% hands-on
    assert _rule_c2_micromanage(p, fs) is None


def test_rule_c3_balance_win():
    from aianalyzer.coaching import _rule_c3_balance_win
    p = _profile_with(total_sessions=25)
    fs = _features_with_agency([0.7] * 25)  # 30% hands-on
    tip = _rule_c3_balance_win(p, fs)
    assert tip is not None
    assert tip.severity == Severity.WIN


def test_hands_on_share_clamps_unbounded_agency_rates():
    # ai_agency_rate = tool_calls / user_msgs is unbounded above; real
    # corpora show 5-10. Without clamping, share would go negative and
    # C1 would fire for everyone while C3 would be unreachable.
    from aianalyzer.coaching import _hands_on_share, _rule_c1_hands_off, _rule_c3_balance_win
    fs = _features_with_agency([5.0, 8.0, 10.0, 3.0, 6.0] * 6)  # 30 sessions
    share = _hands_on_share(fs)
    assert share is not None
    assert 0.0 <= share <= 1.0
    p = _profile_with(total_sessions=30)
    # With all rates >= 1.0, every session clamps to 1.0 → share == 0.0 → C1 fires
    tip = _rule_c1_hands_off(p, fs)
    assert tip is not None
    assert "0%" in tip.body  # not "-240%"
    assert _rule_c3_balance_win(p, fs) is None
