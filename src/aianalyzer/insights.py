"""AI personality insights: nicknames, badges, and 'did-you-know' callouts.

Consumes a UserProfile + per-session SessionFeatures and produces a small,
human-friendly bundle the portal renders prominently in the hero card.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
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
    archetype_key: str = "newcomer"  # "architect" | "pilot" | "tinkerer" | "vibe-coder" | "newcomer"
    archetype_glyph: str = ""  # SVG markup rendered inside the avatar squircle
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

# Concrete line-icon SVGs (Lucide-style). Stroked in white over the
# gradient background — instantly recognisable, crisp at any size,
# no OS-specific emoji rendering.
_ARCHETYPE_GLYPH = {
    Archetype.ARCHITECT: (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<rect x="3" y="4" width="18" height="14" rx="1"/>'
        '<path d="M3 9h18"/><path d="M9 9v9"/><path d="M9 13h6"/>'
        '</svg>'
    ),  # blueprint grid
    Archetype.PILOT: (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<path d="M22 2L11 13"/>'
        '<path d="M22 2l-7 20-4-9-9-4 20-7z"/>'
        '</svg>'
    ),  # paper plane
    Archetype.TINKERER: (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<path d="M14.7 6.3a4 4 0 1 1 5 5l-9.5 9.5a2.83 2.83 0 1 1-4-4l9.5-9.5z"/>'
        '</svg>'
    ),  # wrench
    Archetype.VIBE_CODER: (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<path d="M4 18v-5a8 8 0 0 1 16 0v5"/>'
        '<path d="M4 18v1a2 2 0 0 0 2 2h1a1 1 0 0 0 1-1v-4a1 1 0 0 0-1-1H4z" fill="currentColor"/>'
        '<path d="M20 18v1a2 2 0 0 1-2 2h-1a1 1 0 0 1-1-1v-4a1 1 0 0 1 1-1h3z" fill="currentColor"/>'
        '</svg>'
    ),  # headphones
}
_NEWCOMER_GLYPH = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M12 3v3M12 18v3M3 12h3M18 12h3"/>'
    '<path d="M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>'
    '<circle cx="12" cy="12" r="3.5"/>'
    '</svg>'
)  # sun / sparkle for new users

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


def _archetype_key_and_glyph(
    profile: UserProfile,
) -> tuple[str, str]:
    """Return (archetype_key, glyph) — newcomer fallback when no sessions."""
    if profile.session_count == 0:
        return "newcomer", _NEWCOMER_GLYPH
    result = classify(profile)
    return result.primary.value, _ARCHETYPE_GLYPH.get(result.primary, _NEWCOMER_GLYPH)


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


def _fmt_date(d: date | datetime) -> str:
    """Format a date as 'Mon D' (cross-platform — avoids %-d / %#d footguns)."""
    if isinstance(d, datetime):
        d = d.astimezone().date()
    return f"{d.strftime('%b')} {d.day}"


def _fmt_duration_minutes(minutes: float) -> str:
    total = int(round(minutes))
    h, m = divmod(total, 60)
    return f"{h}h {m}m" if h else f"{m}m"


def _fmt_hour_minute(hm: tuple[int, int]) -> str:
    h, m = hm
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}"


def _did_you_know(
    profile: UserProfile,
    features: list[SessionFeatures],
    *,
    top_tools: list[tuple[str, int]] | None = None,
    total_user_words: int = 0,
    longest_prompt_words: int = 0,
    longest_prompt_at: datetime | None = None,
    marathon_session_minutes: float = 0.0,
    marathon_session_at: datetime | None = None,
    latest_prompt_local_hm: tuple[int, int] | None = None,
    latest_prompt_at: datetime | None = None,
    earliest_prompt_local_hm: tuple[int, int] | None = None,
    earliest_prompt_at: datetime | None = None,
    peak_day_count: int = 0,
    peak_day_date: date | None = None,
    weekend_session_pct: float = 0.0,
    top_first_words: list[tuple[str, int]] | None = None,
    peak_cell_weekday: int | None = None,
    peak_cell_hour: int | None = None,
    peak_cell_count: int = 0,
    off_peak_session_pct: float = 0.0,
    model_tier_counts: dict[str, int] | None = None,
) -> list[Insight]:
    """Vivid prompt-mined facts. Each item is gated on its data being meaningful.

    Order is by rank (highest first). The UI shows them all in a collapsible
    expander, so we err on the side of including more.
    """
    insights: list[Insight] = []
    if not features:
        return insights

    # 1) Total prompts you've typed
    if total_user_words > 0:
        # ~260 words per typical book page; "small novel" is ~50k words.
        pages = max(1, total_user_words // 260)
        insights.append(Insight(
            kind="did_you_know", icon="💬", title="Words typed",
            detail=(
                f"You've typed {total_user_words:,} words to AI across "
                f"{profile.session_count} sessions — about {pages:,} pages of text."
            ),
            rank=100,
        ))
    else:
        insights.append(Insight(
            kind="did_you_know", icon="💬", title="Total sessions",
            detail=f"You've run {profile.session_count} sessions and exchanged "
                   f"{profile.total_turns} turns with AI.",
            rank=100,
        ))

    # 2) Marathon session (single longest)
    if marathon_session_minutes >= 30 and marathon_session_at is not None:
        insights.append(Insight(
            kind="did_you_know", icon="🏃", title="Marathon session",
            detail=(
                f"Your longest session lasted {_fmt_duration_minutes(marathon_session_minutes)} "
                f"on {_fmt_date(marathon_session_at)} — even after idle gaps were trimmed."
            ),
            rank=95,
        ))

    # 3) Longest single prompt
    if longest_prompt_words >= 50 and longest_prompt_at is not None:
        insights.append(Insight(
            kind="did_you_know", icon="📜", title="Longest prompt",
            detail=(
                f"Your most detailed prompt was {longest_prompt_words:,} words long — "
                f"written on {_fmt_date(longest_prompt_at)}."
            ),
            rank=88,
        ))

    # 4) Latest hour you ever worked (night owl moment)
    if latest_prompt_local_hm is not None and latest_prompt_at is not None:
        h = latest_prompt_local_hm[0]
        if h >= 22 or h <= 4:
            insights.append(Insight(
                kind="did_you_know", icon="🌙", title="Night-owl moment",
                detail=(
                    f"You once fired off a prompt at {_fmt_hour_minute(latest_prompt_local_hm)} "
                    f"on {_fmt_date(latest_prompt_at)}. The AI was awake too."
                ),
                rank=85,
            ))

    # 5) Earliest hour you ever worked (early bird moment)
    if earliest_prompt_local_hm is not None and earliest_prompt_at is not None:
        h = earliest_prompt_local_hm[0]
        if h <= 7:
            insights.append(Insight(
                kind="did_you_know", icon="🌅", title="Early-bird moment",
                detail=(
                    f"Your earliest prompt of the day landed at "
                    f"{_fmt_hour_minute(earliest_prompt_local_hm)} on {_fmt_date(earliest_prompt_at)}."
                ),
                rank=80,
            ))

    # 6) Peak day (busiest single calendar day)
    if peak_day_count >= 3 and peak_day_date is not None:
        insights.append(Insight(
            kind="did_you_know", icon="🔥", title="Peak day",
            detail=(
                f"Your busiest single day was {_fmt_date(peak_day_date)} — "
                f"{peak_day_count} sessions in one day."
            ),
            rank=75,
        ))

    # 7) Favourite opener (most common first word across all prompts)
    if top_first_words:
        word, count = top_first_words[0]
        if count >= 3:
            insights.append(Insight(
                kind="did_you_know", icon="🗣", title="Favourite opener",
                detail=(
                    f"You start prompts with “{word}” more than any other word — "
                    f"{count:,} times."
                ),
                rank=70,
            ))

    # 8) Weekend %
    if weekend_session_pct >= 0.20:
        pct = round(100 * weekend_session_pct)
        insights.append(Insight(
            kind="did_you_know", icon="🎉", title="Weekend warrior",
            detail=f"{pct}% of your sessions happen on weekends.",
            rank=65,
        ))

    # 9) Favourite tool
    if top_tools:
        name, count = top_tools[0]
        insights.append(Insight(
            kind="did_you_know", icon="🔧", title="Favourite tool",
            detail=f"You reach for `{name}` more than any other tool — {count:,} uses.",
            rank=60,
        ))

    # 10) Favourite day-of-week
    weekday_counts: Counter[int] = Counter(f.started_weekday for f in features)
    if weekday_counts:
        top_day, top_n = weekday_counts.most_common(1)[0]
        insights.append(Insight(
            kind="did_you_know", icon="📅", title="Favourite day",
            detail=f"{_DAY_NAMES[top_day]} is your busiest day — {top_n} sessions.",
            rank=50,
        ))

    # 11) Peak hour-of-week (specific weekday × hour cell)
    if (
        peak_cell_weekday is not None
        and peak_cell_hour is not None
        and peak_cell_count >= 3
    ):
        hour_label = _fmt_hour_minute((peak_cell_hour, 0))
        insights.append(Insight(
            kind="did_you_know", icon="⏰", title="Hot hour",
            detail=(
                f"{_DAY_NAMES[peak_cell_weekday]}s at {hour_label} is your hottest "
                f"window — {peak_cell_count} sessions started in that hour."
            ),
            rank=78,
        ))

    # 12) Off-peak orchestrator (work outside Mon–Fri 9–6)
    if off_peak_session_pct >= 0.25:
        pct = round(100 * off_peak_session_pct)
        insights.append(Insight(
            kind="did_you_know", icon="🌒", title="Off-peak operator",
            detail=(
                f"{pct}% of your sessions start outside the typical 9–6 weekday "
                f"window — you keep the AI running on your schedule."
            ),
            rank=72,
        ))

    # 13) Favourite model tier (Premium/Standard/Fast)
    if model_tier_counts:
        top_tier, top_turns = max(model_tier_counts.items(), key=lambda kv: kv[1])
        total = sum(model_tier_counts.values())
        if total > 0:
            pct = round(100 * top_turns / total)
            tier_blurb = {
                "Premium": "the heaviest reasoning models (Opus, GPT-5.5)",
                "Standard": "mid-tier daily-driver models (Sonnet, GPT-5)",
                "Fast": "small/fast models (Haiku, mini variants)",
                "Other": "models outside the usual tiers",
            }.get(top_tier, "models in this tier")
            insights.append(Insight(
                kind="did_you_know", icon="🎚", title="Model preference",
                detail=(
                    f"{pct}% of your AI turns ran on {tier_blurb}. "
                    f"You tend to reach for the **{top_tier}** tier."
                ),
                rank=62,
            ))

    insights.sort(key=lambda i: -i.rank)
    return insights


def compute_personality(
    profile: UserProfile,
    features: list[SessionFeatures],
    *,
    longest_streak_days: int = 0,
    top_tools: list[tuple[str, int]] | None = None,
    total_user_words: int = 0,
    longest_prompt_words: int = 0,
    longest_prompt_at: datetime | None = None,
    marathon_session_minutes: float = 0.0,
    marathon_session_at: datetime | None = None,
    latest_prompt_local_hm: tuple[int, int] | None = None,
    latest_prompt_at: datetime | None = None,
    earliest_prompt_local_hm: tuple[int, int] | None = None,
    earliest_prompt_at: datetime | None = None,
    peak_day_count: int = 0,
    peak_day_date: date | None = None,
    weekend_session_pct: float = 0.0,
    top_first_words: list[tuple[str, int]] | None = None,
    peak_cell_weekday: int | None = None,
    peak_cell_hour: int | None = None,
    peak_cell_count: int = 0,
    off_peak_session_pct: float = 0.0,
    model_tier_counts: dict[str, int] | None = None,
) -> AIPersonality:
    """Compute the human-friendly personality bundle for the portal hero."""
    arch_key, arch_glyph = _archetype_key_and_glyph(profile)
    return AIPersonality(
        nickname=_nickname(profile, features),
        tagline=_tagline(profile),
        archetype_key=arch_key,
        archetype_glyph=arch_glyph,
        badges=_badges(profile, features, longest_streak_days=longest_streak_days),
        did_you_know=_did_you_know(
            profile,
            features,
            top_tools=top_tools,
            total_user_words=total_user_words,
            longest_prompt_words=longest_prompt_words,
            longest_prompt_at=longest_prompt_at,
            marathon_session_minutes=marathon_session_minutes,
            marathon_session_at=marathon_session_at,
            latest_prompt_local_hm=latest_prompt_local_hm,
            latest_prompt_at=latest_prompt_at,
            earliest_prompt_local_hm=earliest_prompt_local_hm,
            earliest_prompt_at=earliest_prompt_at,
            peak_day_count=peak_day_count,
            peak_day_date=peak_day_date,
            weekend_session_pct=weekend_session_pct,
            top_first_words=top_first_words,
            peak_cell_weekday=peak_cell_weekday,
            peak_cell_hour=peak_cell_hour,
            peak_cell_count=peak_cell_count,
            off_peak_session_pct=off_peak_session_pct,
            model_tier_counts=model_tier_counts,
        ),
    )
