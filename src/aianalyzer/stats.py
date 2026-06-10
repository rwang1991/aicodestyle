"""Aggregate statistics for the portal (M4)."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Iterable

from aianalyzer.features import SessionFeatures


@dataclass
class ExtendedProfile:
    total_sessions: int = 0
    total_turns: int = 0
    total_hours: float = 0.0
    days_active: int = 0
    longest_streak_days: int = 0
    first_session_at: datetime | None = None
    last_session_at: datetime | None = None
    acceptance_rate: float = 0.0
    avg_turns_per_session: float = 0.0
    avg_session_minutes: float = 0.0
    avg_prompt_words: float = 0.0
    median_prompt_words: float = 0.0
    p90_prompt_words: float = 0.0
    top_tools: list[tuple[str, int]] = field(default_factory=list)
    top_projects: list[tuple[str, int]] = field(default_factory=list)
    top_models: list[tuple[str, int]] = field(default_factory=list)
    top_file_extensions: list[tuple[str, int]] = field(default_factory=list)
    session_type_counts: dict[str, int] = field(default_factory=dict)
    hour_histogram: list[int] = field(default_factory=lambda: [0] * 24)
    weekday_histogram: list[int] = field(default_factory=lambda: [0] * 7)
    activity_per_day_last_90: list[tuple[str, int]] = field(default_factory=list)
    # Per-client breakdown so the portal can show users where their data
    # actually came from. Each value is { sessions, turns, hours, tool_calls }.
    by_client: dict[str, dict[str, float]] = field(default_factory=dict)

    # Prompt-mined aggregates (Phase C vivid report). The portal drops these
    # into the "Did you know?" hero list so the user sees things they actually
    # typed — their longest prompt, the latest hour they ever asked the AI for
    # something, their favourite opener, their marathon session, etc.
    longest_prompt_words: int = 0
    longest_prompt_session_started_at: datetime | None = None
    total_user_words: int = 0
    marathon_session_minutes: float = 0.0
    marathon_session_started_at: datetime | None = None
    latest_prompt_local_hm: tuple[int, int] | None = None
    latest_prompt_at: datetime | None = None
    earliest_prompt_local_hm: tuple[int, int] | None = None
    earliest_prompt_at: datetime | None = None
    peak_day_count: int = 0
    peak_day_date: date | None = None
    weekend_session_pct: float = 0.0
    top_first_words: list[tuple[str, int]] = field(default_factory=list)


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _ext(path: str) -> str | None:
    # Normalize Windows separators so the final segment is correct
    last = path.replace("\\", "/").rsplit("/", 1)[-1]
    if "." not in last or last.startswith("."):
        return None
    return "." + last.rsplit(".", 1)[-1].lower()


def compute_extended_profile(features: Iterable[SessionFeatures]) -> ExtendedProfile:
    fs = list(features)
    p = ExtendedProfile()
    if not fs:
        return p

    p.total_sessions = len(fs)
    p.total_turns = sum(f.turn_count for f in fs)
    p.total_hours = sum(f.session_duration_sec for f in fs) / 3600.0
    p.avg_turns_per_session = p.total_turns / p.total_sessions
    p.avg_session_minutes = (p.total_hours * 60.0) / p.total_sessions
    p.acceptance_rate = max(0.0, min(1.0, 1.0 - (sum(f.abort_rate for f in fs) / p.total_sessions)))

    starts = [f.started_at for f in fs if f.started_at is not None]
    if starts:
        p.first_session_at = min(starts)
        p.last_session_at = max(starts)

    # Day-of-activity bucketing using local timezone
    by_day: Counter[date] = Counter()
    for s in starts:
        by_day[s.astimezone().date()] += 1
    p.days_active = len(by_day)

    # Longest consecutive-day streak
    if by_day:
        days_sorted = sorted(by_day)
        streak = best = 1
        for prev, cur in zip(days_sorted, days_sorted[1:]):
            if (cur - prev).days == 1:
                streak += 1
                best = max(best, streak)
            else:
                streak = 1
        p.longest_streak_days = best

    # Last-90-day activity (most recent date last)
    today = datetime.now(timezone.utc).astimezone().date()
    window = [today - timedelta(days=i) for i in range(89, -1, -1)]
    p.activity_per_day_last_90 = [(d.isoformat(), by_day.get(d, 0)) for d in window]

    # Prompt-length distribution
    word_counts = [f.avg_user_msg_words for f in fs if f.avg_user_msg_words > 0]
    if word_counts:
        p.avg_prompt_words = sum(word_counts) / len(word_counts)
        p.median_prompt_words = float(median(word_counts))
        p.p90_prompt_words = _percentile(word_counts, 0.9)

    # Top-N aggregations
    tool_totals: Counter[str] = Counter()
    project_totals: Counter[str] = Counter()
    model_totals: Counter[str] = Counter()
    ext_totals: Counter[str] = Counter()
    type_totals: Counter[str] = Counter()

    for f in fs:
        tool_totals.update(f.tool_counts)
        if f.cwd:
            project_totals[f.cwd] += 1
        model_totals.update(f.models_used)
        for path in f.file_paths_touched:
            e = _ext(path)
            if e:
                ext_totals[e] += 1
        type_totals[f.session_type.value] += 1
        if 0 <= f.started_hour_local <= 23:
            p.hour_histogram[f.started_hour_local] += 1
        if 0 <= f.started_weekday <= 6:
            p.weekday_histogram[f.started_weekday] += 1

    p.top_tools = tool_totals.most_common(12)
    p.top_projects = project_totals.most_common(12)
    p.top_models = model_totals.most_common(12)
    p.top_file_extensions = ext_totals.most_common(12)
    p.session_type_counts = dict(type_totals)

    # Per-client breakdown of where the data came from. ``tool_calls`` lets
    # the portal honestly say "X% of your tool-call signals came from
    # Copilot CLI" so users know if their archetype is skewed by tool
    # coverage differences across clients.
    by_client: dict[str, dict[str, float]] = {}
    for f in fs:
        bucket = by_client.setdefault(
            f.client,
            {"sessions": 0, "turns": 0, "hours": 0.0, "tool_calls": 0},
        )
        bucket["sessions"] += 1
        bucket["turns"] += f.turn_count
        bucket["hours"] += f.session_duration_sec / 3600.0
        bucket["tool_calls"] += sum(f.tool_counts.values())
    # Round hours so the payload is JSON-friendly.
    for v in by_client.values():
        v["hours"] = round(v["hours"], 2)
    p.by_client = by_client

    # -----------------------------------------------------------------
    # Phase C: prompt-mined aggregates
    # -----------------------------------------------------------------

    # Marathon (single longest engaged session).
    max_f = max(fs, key=lambda f: f.session_duration_sec)
    p.marathon_session_minutes = max_f.session_duration_sec / 60.0
    p.marathon_session_started_at = max_f.started_at

    # Longest single prompt across all sessions.
    candidates = [f for f in fs if f.longest_prompt_words > 0]
    if candidates:
        lf = max(candidates, key=lambda f: f.longest_prompt_words)
        p.longest_prompt_words = lf.longest_prompt_words
        p.longest_prompt_session_started_at = lf.started_at

    # Total words the user has ever typed to AI.
    p.total_user_words = sum(f.total_user_words for f in fs)

    # Latest / earliest prompt by local time-of-day. We want "the most extreme
    # hour you ever typed a prompt", regardless of date — so we compare on
    # (hour, minute) tuples after converting each timestamp to local time.
    def _hm(ts: datetime) -> tuple[int, int]:
        local = ts.astimezone()
        return (local.hour, local.minute)

    last_with_hm = [(f.last_user_msg_at, _hm(f.last_user_msg_at)) for f in fs if f.last_user_msg_at]
    if last_with_hm:
        # Pick the session whose latest prompt has the largest (hour, minute)
        # tuple but tie-break on the timestamp itself for deterministic
        # behaviour when multiple sessions hit the same wall-clock time.
        ts, hm = max(last_with_hm, key=lambda x: (x[1], x[0]))
        p.latest_prompt_local_hm = hm
        p.latest_prompt_at = ts

    first_with_hm = [(f.first_user_msg_at, _hm(f.first_user_msg_at)) for f in fs if f.first_user_msg_at]
    if first_with_hm:
        ts, hm = min(first_with_hm, key=lambda x: (x[1], x[0]))
        p.earliest_prompt_local_hm = hm
        p.earliest_prompt_at = ts

    # Peak single calendar day.
    if by_day:
        peak_date, peak_count = by_day.most_common(1)[0]
        p.peak_day_date = peak_date
        p.peak_day_count = peak_count

    # Weekend %.
    p.weekend_session_pct = sum(1 for f in fs if f.started_weekday in (5, 6)) / len(fs)

    # Top prompt openers.
    fw_counter: Counter[str] = Counter()
    for f in fs:
        fw_counter.update(f.first_words)
    p.top_first_words = fw_counter.most_common(5)

    return p
