"""Phase G — AI Coach. Deterministic rule engine that turns an ExtendedProfile
into a small set of prioritized, actionable tips plus an Efficiency Score.

The coach is intentionally rule-based (no LLM) so it ships in the offline
.exe, runs in <50 ms, and is fully unit-testable. Each rule is a pure
function `(profile, features) -> CoachTip | None`. The aggregator collects
emitted tips, ranks them by (severity, impact_estimate), and returns the
top N.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from aianalyzer.features import SessionFeatures
from aianalyzer.stats import ExtendedProfile


class Severity(str, Enum):
    HEADS_UP = "heads_up"
    TIP = "tip"
    WIN = "win"


SEVERITY_PRIORITY = {Severity.HEADS_UP: 3, Severity.TIP: 2, Severity.WIN: 1}


@dataclass(frozen=True)
class CoachTip:
    rule_id: str
    severity: Severity
    category: str
    headline: str
    body: str
    impact_estimate: float = 0.0
    evidence: dict = field(default_factory=dict)


@dataclass
class CoachReport:
    score: int = 0
    band: str = "Apprentice"
    sub_scores: dict[str, int] = field(default_factory=dict)
    tips: list[CoachTip] = field(default_factory=list)


def compute_coach_report(
    profile: ExtendedProfile,
    features: Iterable[SessionFeatures],
) -> CoachReport:
    """Public entry point. Returns the full coach report."""
    return CoachReport()
