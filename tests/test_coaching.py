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


def test_score_perfect_user():
    p = _profile_with(
        total_sessions=50,
        avg_turns_per_session=8.0,
        median_prompt_words=70,
        output_to_input_ratio=1.5,
        priced_token_share=0.95,
    )
    fs = _features_with_agency([0.65] * 50)
    rep = compute_coach_report(p, fs)
    assert rep.score >= 85
    assert rep.band == "Conductor"
    assert set(rep.sub_scores.keys()) == {"cost", "handson", "prompt", "shape"}


def test_score_apprentice():
    p = _profile_with(
        total_sessions=50,
        avg_turns_per_session=80.0,
        median_prompt_words=3,
        output_to_input_ratio=6.0,
        priced_token_share=0.20,
    )
    fs = _features_with_agency([0.99] * 50)
    rep = compute_coach_report(p, fs)
    assert rep.score <= 40
    assert rep.band == "Apprentice"


def test_score_sub_scores_each_capped_at_25():
    # Set all 4 sub-score inputs into their sweet spots so every score
    # path executes int(round(25 * fit)) — not the == 0 early returns.
    p = _profile_with(
        total_sessions=50,
        output_to_input_ratio=1.5,
        priced_token_share=1.0,
        avg_turns_per_session=10.0,   # inside [4, 20]
        median_prompt_words=70,       # inside [30, 160]
    )
    fs = _features_with_agency([0.65] * 50)
    rep = compute_coach_report(p, fs)
    assert set(rep.sub_scores.keys()) == {"cost", "handson", "prompt", "shape"}
    for v in rep.sub_scores.values():
        assert 0 <= v <= 25


def test_score_bands_exhaustive():
    from aianalyzer.coaching import _band_for_score
    assert _band_for_score(10) == "Apprentice"
    assert _band_for_score(50) == "Practitioner"
    assert _band_for_score(75) == "Operator"
    assert _band_for_score(95) == "Conductor"


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
    assert "30" in tip.headline or "30%" in tip.headline  # 1 - 0.70 = 30%


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


def _features_with_duration_minutes(values: list[float]) -> list[SessionFeatures]:
    return [
        SessionFeatures(
            session_id=f"s{i}",
            client="copilot-cli",
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            session_duration_sec=v * 60.0,
        )
        for i, v in enumerate(values)
    ]


def _features_with_start_hour(hours: list[int]) -> list[SessionFeatures]:
    return [
        SessionFeatures(
            session_id=f"s{i}",
            client="copilot-cli",
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            started_hour_local=h,
        )
        for i, h in enumerate(hours)
    ]


def test_rule_d1_long_iterative_loops():
    from aianalyzer.coaching import _rule_d1_long_loops
    p = _profile_with(avg_turns_per_session=42)
    tip = _rule_d1_long_loops(p, [])
    assert tip is not None
    assert tip.rule_id == "D1"


def test_rule_d1_skips_short_avg():
    from aianalyzer.coaching import _rule_d1_long_loops
    p = _profile_with(avg_turns_per_session=15)
    assert _rule_d1_long_loops(p, []) is None


def test_rule_d2_long_sessions():
    from aianalyzer.coaching import _rule_d2_long_sessions
    p = _profile_with(total_sessions=25)
    fs = _features_with_duration_minutes([150] * 25)
    tip = _rule_d2_long_sessions(p, fs)
    assert tip is not None
    assert tip.rule_id == "D2"


def test_rule_d2_skips_when_short():
    from aianalyzer.coaching import _rule_d2_long_sessions
    p = _profile_with(total_sessions=25)
    fs = _features_with_duration_minutes([40] * 25)
    assert _rule_d2_long_sessions(p, fs) is None


def test_rule_d3_late_night():
    from aianalyzer.coaching import _rule_d3_late_night
    p = _profile_with(total_sessions=20)
    fs = _features_with_start_hour([23] * 10 + [14] * 10)
    tip = _rule_d3_late_night(p, fs)
    assert tip is not None
    assert tip.severity == Severity.HEADS_UP


def test_rule_d3_skips_when_balanced():
    from aianalyzer.coaching import _rule_d3_late_night
    p = _profile_with(total_sessions=20)
    fs = _features_with_start_hour([10, 14, 16, 22] * 5)
    assert _rule_d3_late_night(p, fs) is None


def test_rule_e1_single_model_dominance():
    from aianalyzer.coaching import _rule_e1_single_model
    p = _profile_with(
        total_sessions=40,
        top_models=[("claude-sonnet-4.5", 920), ("gpt-5", 50), ("haiku", 30)],
    )
    tip = _rule_e1_single_model(p, [])
    assert tip is not None
    assert "claude-sonnet-4.5" in tip.body


def test_rule_e1_skips_balanced():
    from aianalyzer.coaching import _rule_e1_single_model
    p = _profile_with(
        total_sessions=40,
        top_models=[("claude-sonnet-4.5", 500), ("gpt-5", 350), ("haiku", 150)],
    )
    assert _rule_e1_single_model(p, []) is None


def test_rule_e2_smart_juggling_win():
    from aianalyzer.coaching import _rule_e2_smart_juggling
    p = _profile_with(
        total_sessions=40,
        top_models=[("a", 400), ("b", 350), ("c", 250)],
    )
    tip = _rule_e2_smart_juggling(p, [])
    assert tip is not None
    assert tip.severity == Severity.WIN


def test_rule_e2_skips_when_dominant_model():
    from aianalyzer.coaching import _rule_e2_smart_juggling
    p = _profile_with(
        total_sessions=40,
        top_models=[("a", 900), ("b", 50), ("c", 50)],
    )
    assert _rule_e2_smart_juggling(p, []) is None


def test_rule_f1_single_client():
    from aianalyzer.coaching import _rule_f1_single_client
    p = _profile_with(
        total_sessions=100,
        by_client={"copilot-cli": {"sessions": 95}, "vscode": {"sessions": 5}},
    )
    tip = _rule_f1_single_client(p, [])
    assert tip is not None
    assert "copilot-cli" in tip.body


def test_rule_f1_skips_when_small_sample():
    from aianalyzer.coaching import _rule_f1_single_client
    p = _profile_with(
        total_sessions=10,
        by_client={"copilot-cli": {"sessions": 10}},
    )
    assert _rule_f1_single_client(p, []) is None


def test_aggregator_returns_top_n_sorted():
    p = _profile_with(
        total_sessions=100,
        avg_turns_per_session=42,
        output_to_input_ratio=4.0,
        sessions_for_80pct_tokens=5,
        median_prompt_words=70,
        top_models=[("a", 950), ("b", 30), ("c", 20)],
        by_client={"copilot-cli": {"sessions": 100}},
    )
    fs = _features_with_agency([0.7] * 100)
    rep = compute_coach_report(p, fs)
    assert rep.tips[0].severity == Severity.HEADS_UP
    assert len(rep.tips) <= 6
    win_count = sum(1 for t in rep.tips if t.severity == Severity.WIN)
    assert win_count <= 2
    # Lock in within-severity ordering by impact descending.
    assert rep.tips[0].rule_id == "A3"  # heads_up, impact 0.7
    assert rep.tips[1].rule_id == "D3"  # heads_up, impact 0.5


def test_aggregator_win_cap_enforced_when_many_wins_emit():
    # Profile crafted to fire ONLY win rules (B3 + C3 + E2) — no heads_up,
    # no tips compete for the 6 slots, so the cap of 2 is exercised.
    p = _profile_with(
        total_sessions=25,
        avg_turns_per_session=15,  # < 30, D1 skips
        median_prompt_words=70,    # B3 win
        top_models=[("a", 400), ("b", 300), ("c", 300)],  # E2 win (0.40 share)
        by_client={"copilot-cli": {"sessions": 25}},      # < 50, F1 skips
    )
    fs = _features_with_agency([0.7] * 25)  # C3 win (30% hands-on)
    rep = compute_coach_report(p, fs)
    win_count = sum(1 for t in rep.tips if t.severity == Severity.WIN)
    assert win_count == 2  # cap hit (3 emitted, 2 kept)


def test_aggregator_handles_empty():
    p = _empty_profile()
    rep = compute_coach_report(p, [])
    assert rep.tips == []
    assert 0 <= rep.score <= 100
