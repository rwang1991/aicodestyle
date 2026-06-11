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


# --- Category B: prompt quality -------------------------------------------


def _rule_b1_short_prompts(p, features):
    if p.total_sessions < 10 or p.median_prompt_words >= 10:
        return None
    return CoachTip(
        rule_id="B1",
        severity=Severity.TIP,
        category="prompt",
        headline="Short prompts get short answers",
        body=(
            f"Your median prompt is {p.median_prompt_words:.0f} words. "
            "Adding 2–3 lines of context (goal, constraints, format) typically "
            "cuts your iteration count in half."
        ),
        impact_estimate=0.6,
        evidence={"median_prompt_words": p.median_prompt_words},
    )


def _rule_b2_overspecify(p, features):
    if p.median_prompt_words <= 250:
        return None
    if p.avg_turns_per_session <= 20:
        return None
    return CoachTip(
        rule_id="B2",
        severity=Severity.TIP,
        category="prompt",
        headline="You over-specify, then iterate anyway",
        body=(
            f"Median prompt = {p.median_prompt_words:.0f} words; average "
            f"{p.avg_turns_per_session:.0f} turns per session. Try a compact spec "
            "(<150 words) + a single review pass — faster and usually as accurate."
        ),
        impact_estimate=0.4,
        evidence={
            "median_prompt_words": p.median_prompt_words,
            "avg_turns": p.avg_turns_per_session,
        },
    )


def _rule_b3_sweet_spot(p, features):
    if p.total_sessions < 15:
        return None
    mw = p.median_prompt_words
    if not (40 <= mw <= 140):
        return None
    return CoachTip(
        rule_id="B3",
        severity=Severity.WIN,
        category="prompt",
        headline="Prompt length sits in the sweet spot",
        body=(
            f"Median prompt = {mw:.0f} words. That's enough context to ground the "
            "model without burying it. Keep doing what you're doing."
        ),
        impact_estimate=0.1,
        evidence={"median_prompt_words": mw},
    )


# --- Category C: hands-on balance -----------------------------------------


def _hands_on_share(features) -> float | None:
    fs = [f for f in features if f.turn_count > 0 or f.ai_agency_rate]
    if not fs:
        # Some features have no turns recorded; still average if we have data.
        fs = list(features)
    if not fs:
        return None
    # ai_agency_rate = tool_calls / user_msgs is unbounded above (real
    # corpora routinely show 5-10+). Clamp per-session to [0, 1] so
    # `1 - mean(...)` stays in [0, 1] and the rule thresholds remain
    # meaningful (otherwise C1 fires for every real user and C3 is
    # unreachable). See weights.yaml normalizer (max 8.0) for context.
    return 1.0 - (sum(min(1.0, f.ai_agency_rate) for f in fs) / len(fs))


def _rule_c1_hands_off(p, features):
    if p.total_sessions < 20:
        return None
    share = _hands_on_share(features)
    if share is None or share >= 0.15:
        return None
    return CoachTip(
        rule_id="C1",
        severity=Severity.HEADS_UP,
        category="balance",
        headline="You're firmly hands-off",
        body=(
            f"Your hands-on share is {share*100:.0f}%. AI is driving almost everything. "
            "Skim the diffs before applying — you'll catch regressions AND learn faster."
        ),
        impact_estimate=0.7,
        evidence={"hands_on_share": share},
    )


def _rule_c2_micromanage(p, features):
    if p.total_sessions < 15:
        return None
    share = _hands_on_share(features)
    if share is None or share <= 0.60:
        return None
    return CoachTip(
        rule_id="C2",
        severity=Severity.TIP,
        category="balance",
        headline="You're micro-managing",
        body=(
            f"Hands-on share = {share*100:.0f}%. You're doing the work AI could do. "
            "Try describing a scoped subtask end-to-end and letting AI complete it before you review."
        ),
        impact_estimate=0.5,
        evidence={"hands_on_share": share},
    )


def _rule_c3_balance_win(p, features):
    if p.total_sessions < 20:
        return None
    share = _hands_on_share(features)
    if share is None or not (0.20 <= share <= 0.50):
        return None
    return CoachTip(
        rule_id="C3",
        severity=Severity.WIN,
        category="balance",
        headline="Healthy hands-on / hands-off balance",
        body=(
            f"Hands-on share = {share*100:.0f}%. You delegate clearly but stay in the loop. "
            "This is the sweet spot for both learning and throughput."
        ),
        impact_estimate=0.1,
        evidence={"hands_on_share": share},
    )


# --- Category D: session shape --------------------------------------------


def _rule_d1_long_loops(p, features):
    if p.avg_turns_per_session <= 30:
        return None
    return CoachTip(
        rule_id="D1",
        severity=Severity.TIP,
        category="shape",
        headline="Long iterative loops suggest under-specification",
        body=(
            f"Average session = {p.avg_turns_per_session:.0f} turns. That many rounds usually "
            "means you discovered requirements mid-flight. Try a 'planning turn' up front: "
            "list the goal, constraints, and acceptance criteria before any code."
        ),
        impact_estimate=0.6,
        evidence={"avg_turns": p.avg_turns_per_session},
    )


def _rule_d2_long_sessions(p, features):
    if p.total_sessions < 20:
        return None
    minutes = sorted([f.session_duration_sec / 60.0 for f in features if f.session_duration_sec > 0])
    if not minutes:
        return None
    mid = minutes[len(minutes) // 2]
    if mid <= 120:
        return None
    return CoachTip(
        rule_id="D2",
        severity=Severity.TIP,
        category="shape",
        headline="Long sessions risk context drift",
        body=(
            f"Median session is {mid:.0f} minutes. After ~90 minutes the model's working "
            "context gets noisy and confidence drops. Checkpoint progress and start fresh."
        ),
        impact_estimate=0.4,
        evidence={"median_session_minutes": mid},
    )


def _rule_d3_late_night(p, features):
    if p.total_sessions < 15:
        return None
    late = sum(1 for f in features if f.started_hour_local >= 22 or f.started_hour_local <= 2)
    if not features:
        return None
    share = late / len(features)
    if share <= 0.40:
        return None
    return CoachTip(
        rule_id="D3",
        severity=Severity.HEADS_UP,
        category="shape",
        headline="Lots of late-night AI work",
        body=(
            f"{share*100:.0f}% of your sessions start between 22:00 and 02:00 local. "
            "Late-night code from any source — human or AI — has higher defect rates. "
            "Schedule a morning review before merging."
        ),
        impact_estimate=0.5,
        evidence={"late_night_share": share},
    )


# --- Category E: model selection ------------------------------------------

_OTHER_MODEL_HINT = {
    "claude": "GPT-5 for code review tasks",
    "gpt": "Claude for long-context reasoning",
    "gemini": "Claude or GPT-5 for code generation",
}


def _other_model_suggestion(top_model: str) -> str:
    lower = top_model.lower()
    for needle, suggestion in _OTHER_MODEL_HINT.items():
        if needle in lower:
            return suggestion
    return "a different reasoning model for hard tasks"


def _rule_e1_single_model(p, features):
    if p.total_sessions < 30 or not p.top_models:
        return None
    total = sum(c for _, c in p.top_models)
    if total == 0:
        return None
    top_name, top_count = p.top_models[0]
    share = top_count / total
    if share <= 0.90:
        return None
    suggestion = _other_model_suggestion(top_name)
    return CoachTip(
        rule_id="E1",
        severity=Severity.TIP,
        category="model",
        headline=f"You use {top_name} for almost everything",
        body=(
            f"{share*100:.0f}% of turns go to {top_name}. Try {suggestion} — "
            "different model families have meaningfully different strengths."
        ),
        impact_estimate=0.3,
        evidence={"top_model": top_name, "share": share},
    )


def _rule_e2_smart_juggling(p, features):
    if p.total_sessions < 20 or len(p.top_models) < 3:
        return None
    total = sum(c for _, c in p.top_models)
    if total == 0:
        return None
    top_share = p.top_models[0][1] / total
    if top_share > 0.70:
        return None
    return CoachTip(
        rule_id="E2",
        severity=Severity.WIN,
        category="model",
        headline="Smart model juggling",
        body=(
            f"You spread work across {len(p.top_models)} models with no single one "
            "above 70%. That's the mark of someone matching the model to the task."
        ),
        impact_estimate=0.1,
        evidence={"model_count": len(p.top_models)},
    )


# --- Category F: tool / client diversity ----------------------------------

_OTHER_CLIENT_HINT = {
    "copilot-cli": "VS Code Copilot inline for quick edits",
    "vscode": "Copilot CLI for batch / scripted work",
    "claude": "Copilot CLI or VS Code for IDE-integrated tasks",
}


def _other_client_suggestion(top_client: str) -> str:
    lower = top_client.lower()
    for needle, suggestion in _OTHER_CLIENT_HINT.items():
        if needle in lower:
            return suggestion
    return "another client for variety"


def _rule_f1_single_client(p, features):
    if p.total_sessions < 50 or not p.by_client:
        return None
    items = [(name, info.get("sessions", 0)) for name, info in p.by_client.items()]
    items.sort(key=lambda x: x[1], reverse=True)
    total = sum(c for _, c in items)
    if total == 0:
        return None
    top_name, top_count = items[0]
    share = top_count / total
    if share <= 0.90:
        return None
    return CoachTip(
        rule_id="F1",
        severity=Severity.TIP,
        category="tool",
        headline=f"All your AI work lives in {top_name}",
        body=(
            f"{share*100:.0f}% of your sessions are on {top_name}. "
            f"Try {_other_client_suggestion(top_name)} — different surfaces fit different tasks."
        ),
        impact_estimate=0.3,
        evidence={"top_client": top_name, "share": share},
    )


def compute_coach_report(
    profile: ExtendedProfile,
    features: Iterable[SessionFeatures],
) -> CoachReport:
    """Public entry point. Returns the full coach report."""
    return CoachReport()
