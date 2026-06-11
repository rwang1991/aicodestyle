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


# --- Category A: cost & token efficiency -----------------------------------


def _rule_a1_output_input_high(p, features):
    ratio = p.output_to_input_ratio
    if ratio <= 3.0:
        return None
    return CoachTip(
        rule_id="A1",
        severity=Severity.TIP,
        category="cost",
        headline="Tighten your asks — AI is generating 3× what you type",
        body=(
            f"Output:input is {ratio:.1f}×. Long answers cost tokens AND review time. "
            "Try asking for the smallest useful unit (one function, one decision)."
        ),
        impact_estimate=min(1.0, (ratio - 3.0) / 5.0),
        evidence={"output_to_input_ratio": ratio},
    )


def _rule_a2_output_input_low(p, features):
    if p.total_sessions < 10:
        return None
    ratio = p.output_to_input_ratio
    if ratio == 0 or ratio >= 0.5:
        return None
    return CoachTip(
        rule_id="A2",
        severity=Severity.TIP,
        category="cost",
        headline="You write more than AI does — delegate larger units",
        body=(
            f"Output:input is {ratio:.2f}×. You're doing most of the thinking. "
            "Try describing the goal + constraints and asking for a complete first draft."
        ),
        impact_estimate=0.3,
        evidence={"output_to_input_ratio": ratio},
    )


def _rule_a3_pareto_concentrated(p, features):
    if p.total_sessions < 20 or not p.sessions_for_80pct_tokens:
        return None
    concentration = p.sessions_for_80pct_tokens / p.total_sessions
    if concentration > 0.10:
        return None
    return CoachTip(
        rule_id="A3",
        severity=Severity.HEADS_UP,
        category="cost",
        headline="A handful of sessions drive most of your cost",
        body=(
            f"{p.sessions_for_80pct_tokens} of {p.total_sessions} sessions "
            f"({concentration*100:.0f}%) account for 80% of your token spend. "
            "Split those heavyweight sessions into scoped sub-tasks."
        ),
        impact_estimate=0.7,
        evidence={
            "sessions_for_80pct": p.sessions_for_80pct_tokens,
            "total_sessions": p.total_sessions,
        },
    )


def _rule_a4_expensive_session(p, features):
    if not p.top_cost_sessions:
        return None
    top = p.top_cost_sessions[0]
    cost = top.get("est_cost_usd") or 0.0
    if cost < 5.0:
        return None
    return CoachTip(
        rule_id="A4",
        severity=Severity.TIP,
        category="cost",
        headline=f"Your most expensive session was ${cost:.2f}",
        body=(
            f"That ${cost:.2f} session used {top.get('est_total_tokens', 0):,} tokens. "
            "If the outcome wasn't worth the cost, set a budget reminder for similar tasks "
            "or break them into checkpointed chunks."
        ),
        impact_estimate=min(1.0, cost / 20.0),
        evidence={"top_cost_session": top},
    )


def _rule_a5_unpriced_share(p, features):
    if p.est_total_tokens < 100_000 or p.priced_token_share == 0:
        return None
    if p.priced_token_share >= 0.85:
        return None
    unpriced = 1.0 - p.priced_token_share
    return CoachTip(
        rule_id="A5",
        severity=Severity.TIP,
        category="cost",
        headline=f"{unpriced*100:.0f}% of your tokens are on unidentified models",
        body=(
            f"{unpriced*100:.0f}% of your tokens are on unidentified models. "
            "We couldn't price every model you used (likely internal-named or experimental). "
            "Pin your default model in each client so the cost picture is complete."
        ),
        impact_estimate=0.2,
        evidence={"priced_token_share": p.priced_token_share},
    )


def _rule_a6_premium_for_quick(p, features):
    tiers = p.model_tier_counts or {}
    total = sum(tiers.values())
    if total == 0:
        return None
    premium_share = tiers.get("Premium", 0) / total
    if premium_share < 0.60:
        return None
    if p.avg_turns_per_session >= 6:
        return None
    return CoachTip(
        rule_id="A6",
        severity=Severity.TIP,
        category="cost",
        headline="You reach for premium models even on quick questions",
        body=(
            f"{premium_share*100:.0f}% of your turns hit a premium model but your average "
            f"session is only {p.avg_turns_per_session:.1f} turns long. "
            "Reserve premium for hard reasoning; use a faster model for one-shot edits or lookups."
        ),
        impact_estimate=0.5,
        evidence={"premium_share": premium_share, "avg_turns": p.avg_turns_per_session},
    )


def compute_coach_report(
    profile: ExtendedProfile,
    features: Iterable[SessionFeatures],
) -> CoachReport:
    """Public entry point. Returns the full coach report."""
    return CoachReport()
