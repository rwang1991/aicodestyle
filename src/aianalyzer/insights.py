"""AI personality insights: nicknames, badges, and 'did-you-know' callouts.

Consumes a UserProfile + per-session SessionFeatures and produces a small,
human-friendly bundle the portal renders prominently in the hero card.
"""
from __future__ import annotations

from collections import Counter
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from aianalyzer.classifier.archetypes import Archetype
from aianalyzer.classifier.rules import classify
from aianalyzer.features import SessionFeatures, UserProfile


class Insight(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: str            # "did_you_know" | "achievement"
    icon: str            # short emoji
    title: str           # short headline
    detail: str          # one-sentence explanation with the actual number
    rank: int = 0        # higher = more important; UI shows top N


class AIPersonality(BaseModel):
    model_config = ConfigDict(frozen=True)
    nickname: str
    tagline: str
    badges: list[Insight] = Field(default_factory=list)
    did_you_know: list[Insight] = Field(default_factory=list)


_ARCHETYPE_WORD = {
    Archetype.ARCHITECT: "Architect",
    Archetype.PILOT: "Pilot",
    Archetype.TINKERER: "Tinkerer",
    Archetype.VIBE_CODER: "Vibe Coder",
}

_ARCHETYPE_TAGLINE = {
    Archetype.ARCHITECT: "Plans the work, then drives the tools.",
    Archetype.PILOT: "Sets the direction, lets the AI fly.",
    Archetype.TINKERER: "Hands deep in the code, learning by doing.",
    Archetype.VIBE_CODER: "Trusts the flow — fast, instinctive, light-touch.",
}

_DAY_NAMES = (
    "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday",
)


def _modal_hour_bucket(features: list[SessionFeatures]) -> Optional[str]:
    """Return 'night' (22-4), 'early' (5-9), 'midday' (10-16), or 'evening' (17-21)."""
    if not features:
        return None
    buckets: Counter[str] = Counter()
    for f in features:
        h = f.started_hour_local
        if h >= 22 or h <= 4:
            buckets["night"] += 1
        elif 5 <= h <= 9:
            buckets["early"] += 1
        elif 10 <= h <= 16:
            buckets["midday"] += 1
        else:
            buckets["evening"] += 1
    return buckets.most_common(1)[0][0]


def _adjective_for(profile: UserProfile, features: list[SessionFeatures]) -> str:
    """Pick a single adjective that captures the user's most distinctive trait."""
    bucket = _modal_hour_bucket(features)
    if bucket == "night":
        return "Night-Owl"
    if bucket == "early":
        return "Early-Bird"
    if profile.session_count >= 200:
        return "Prolific"
    if profile.prompt_specificity_avg > 0.4:
        return "Verbose"
    if profile.accept_and_go_ratio > 0.4:
        return "Trusting"
    if profile.tool_error_rate > 0.2:
        return "Persistent"
    if profile.question_ratio > 0.4:
        return "Curious"
    return "Steady"


def _nickname(profile: UserProfile, features: list[SessionFeatures]) -> str:
    if profile.session_count == 0:
        return "The Newcomer"
    result = classify(profile)
    arch_word = _ARCHETYPE_WORD.get(result.primary, "Coder")
    adj = _adjective_for(profile, features)
    return f"The {adj} {arch_word}"


def _tagline(profile: UserProfile) -> str:
    if profile.session_count == 0:
        return "Run a scan to discover your AI partnership style."
    result = classify(profile)
    return _ARCHETYPE_TAGLINE.get(result.primary, "Your AI coding style.")


def _badges(
    profile: UserProfile,
    features: list[SessionFeatures],
    *,
    longest_streak_days: int = 0,
) -> list[Insight]:
    badges: list[Insight] = []
    if not features:
        return badges

    bucket = _modal_hour_bucket(features)
    if bucket == "night":
        night_pct = round(
            100 * sum(1 for f in features if f.started_hour_local >= 22 or f.started_hour_local <= 4)
            / len(features)
        )
        badges.append(Insight(
            kind="achievement", icon="🌙", title="Night Owl",
            detail=f"{night_pct}% of your sessions start between 10 PM and 4 AM.",
            rank=90,
        ))
    elif bucket == "early":
        early_pct = round(
            100 * sum(1 for f in features if 5 <= f.started_hour_local <= 9)
            / len(features)
        )
        badges.append(Insight(
            kind="achievement", icon="🌅", title="Early Bird",
            detail=f"{early_pct}% of your sessions start between 5 AM and 9 AM.",
            rank=90,
        ))

    if profile.distinct_models_total >= 5:
        badges.append(Insight(
            kind="achievement", icon="🌐", title="Polyglot",
            detail=f"You've worked with {profile.distinct_models_total} different AI models.",
            rank=70,
        ))

    todo_density = profile.total_todos / max(profile.session_count, 1)
    if todo_density >= 1.0:
        badges.append(Insight(
            kind="achievement", icon="📋", title="Planner",
            detail=f"You average {todo_density:.1f} TODOs per session.",
            rank=80,
        ))

    if profile.session_count >= 100:
        badges.append(Insight(
            kind="achievement", icon="🔥", title="Prolific",
            detail=f"You've run {profile.session_count} AI sessions.",
            rank=85,
        ))

    if profile.tool_error_rate >= 0.2:
        err_pct = round(100 * profile.tool_error_rate)
        badges.append(Insight(
            kind="achievement", icon="🔧", title="Persistent Debugger",
            detail=f"{err_pct}% of your tool calls hit errors — and you kept going.",
            rank=60,
        ))

    if profile.parallel_tool_call_rate >= 0.3:
        par_pct = round(100 * profile.parallel_tool_call_rate)
        badges.append(Insight(
            kind="achievement", icon="⚡", title="Parallelist",
            detail=f"{par_pct}% of your turns fire multiple tools at once.",
            rank=65,
        ))

    if profile.code_block_density >= 0.3:
        cb_pct = round(100 * profile.code_block_density)
        badges.append(Insight(
            kind="achievement", icon="📝", title="Code Sharer",
            detail=f"{cb_pct}% of your prompts include code blocks.",
            rank=55,
        ))

    if profile.file_reference_rate >= 0.4:
        fr_pct = round(100 * profile.file_reference_rate)
        badges.append(Insight(
            kind="achievement", icon="🎯", title="Pin-Pointer",
            detail=f"{fr_pct}% of your prompts cite a specific file, line, or function.",
            rank=58,
        ))

    if longest_streak_days >= 7:
        badges.append(Insight(
            kind="achievement", icon="📈", title="On a Roll",
            detail=f"You coded with AI for {longest_streak_days} days in a row.",
            rank=92,
        ))

    badges.sort(key=lambda b: -b.rank)
    return badges


def _did_you_know(
    profile: UserProfile,
    features: list[SessionFeatures],
    *,
    top_tools: list[tuple[str, int]] | None = None,
) -> list[Insight]:
    insights: list[Insight] = []
    if not features:
        return insights

    insights.append(Insight(
        kind="did_you_know", icon="💬", title="Total sessions",
        detail=f"You've run {profile.session_count} sessions and exchanged "
               f"{profile.total_turns} turns with AI.",
        rank=100,
    ))

    if profile.session_duration_sec > 0:
        avg_min = profile.session_duration_sec / 60
        insights.append(Insight(
            kind="did_you_know", icon="⏱", title="Time with AI",
            detail=f"Your average engaged session lasts {avg_min:.1f} minutes.",
            rank=80,
        ))

    weekday_counts: Counter[int] = Counter(f.started_weekday for f in features)
    if weekday_counts:
        top_day, top_n = weekday_counts.most_common(1)[0]
        insights.append(Insight(
            kind="did_you_know", icon="📅", title="Favourite day",
            detail=f"{_DAY_NAMES[top_day]} is your busiest day — {top_n} sessions.",
            rank=70,
        ))

    if profile.prompt_specificity_avg > 0:
        # Inverse of _SPECIFICITY_MAX_WORDS (200) in features.py
        words = round(profile.prompt_specificity_avg * 200)
        insights.append(Insight(
            kind="did_you_know", icon="✍", title="Prompt length",
            detail=f"Your average prompt is around {words} words long.",
            rank=60,
        ))

    if profile.accept_and_go_ratio > 0:
        ag_pct = round(100 * profile.accept_and_go_ratio)
        insights.append(Insight(
            kind="did_you_know", icon="✅", title="Trust signal",
            detail=f"{ag_pct}% of your replies are short approvals like 'ok' or 'go ahead'.",
            rank=50,
        ))

    if profile.ai_agency_rate > 0:
        insights.append(Insight(
            kind="did_you_know", icon="🤖", title="AI workload",
            detail=f"On average the AI fires {profile.ai_agency_rate:.1f} "
                   f"tool calls per prompt you write.",
            rank=55,
        ))

    if top_tools:
        name, count = top_tools[0]
        insights.append(Insight(
            kind="did_you_know", icon="🔧", title="Favourite tool",
            detail=f"You reach for `{name}` more than any other tool — {count:,} uses.",
            rank=75,
        ))

    insights.sort(key=lambda i: -i.rank)
    return insights


def compute_personality(
    profile: UserProfile,
    features: list[SessionFeatures],
    *,
    longest_streak_days: int = 0,
    top_tools: list[tuple[str, int]] | None = None,
) -> AIPersonality:
    """Compute the human-friendly personality bundle for the portal hero."""
    return AIPersonality(
        nickname=_nickname(profile, features),
        tagline=_tagline(profile),
        badges=_badges(profile, features, longest_streak_days=longest_streak_days),
        did_you_know=_did_you_know(profile, features, top_tools=top_tools),
    )
