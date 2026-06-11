"""Phase G — AI Coach rule engine."""
from __future__ import annotations

from datetime import datetime, timezone

from aianalyzer.coaching import (
    CoachReport,
    CoachTip,
    Severity,
    compute_coach_report,
)
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
