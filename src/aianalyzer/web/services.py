"""Glue between FastAPI routes and the existing classifier pipeline."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

from aianalyzer.classifier.rules import classify
from aianalyzer.classifier.weights import load_weights
from aianalyzer.collectors.base import Collector
from aianalyzer.collectors.copilot_cli import CopilotCliCollector
from aianalyzer.collectors.vscode_copilot import VsCodeCopilotCollector
from aianalyzer.discovery import (
    DiscoveredSession,
    discover_copilot_cli_sessions,
    discover_vscode_copilot_sessions,
)
from aianalyzer.features import UserProfile, aggregate_user_profile, extract_session_features
from aianalyzer.insights import compute_personality
from aianalyzer.stats import compute_extended_profile
from aianalyzer.store import FeatureStore


# Human labels for the raw behavior signals surfaced in the portal.
_BEHAVIOR_LABELS: dict[str, str] = {
    "planning_language_ratio": "Planning language",
    "question_ratio": "Question ratio",
    "thinks_before_prompt_sec_avg": "Think time (sec)",
    "test_or_spec_mention_rate": "Test / spec mentions",
    "todo_density": "Todos per session",
    "tool_diversity": "Tool diversity",
    "edited_files_per_turn_avg": "Files edited / turn",
    "accept_and_go_ratio": "Accept-and-go",
    "revision_depth": "Revision depth",
    "tool_error_rate": "Tool error rate",
    "parallel_tool_call_rate": "Parallel tool calls",
    "abort_rate": "Aborted turns",
}

# Maps a modifier tag to the signal it gates on and the weight-key holding the
# threshold in weights.yaml. Keeps payload construction declarative.
_MODIFIER_SPECS: list[tuple[str, str, str]] = [
    ("questioner", "question_ratio", "questioner_min_question_ratio"),
    ("debugger", "tool_error_rate", "debugger_min_tool_error_rate"),
    ("planner", "todo_density", "planner_min_todo_density"),
    ("yolo", "accept_and_go_ratio", "yolo_min_accept_and_go"),
    ("parallelist", "parallel_tool_call_rate", "parallelist_min_parallel_tool_call_rate"),
]


def discover_all_sessions() -> Iterable[DiscoveredSession]:
    """Aggregator over all supported clients.

    Exposed as a module-level symbol so tests can monkeypatch it.
    """
    yield from discover_copilot_cli_sessions()
    yield from discover_vscode_copilot_sessions()


# Map a client name to the collector used to parse one of its sessions.
_COLLECTORS: dict[str, Collector] = {
    "copilot-cli": CopilotCliCollector(),
    "vscode-copilot": VsCodeCopilotCollector(),
}


def _cache_path() -> Path:
    override = os.environ.get("AIANALYZER_CACHE_DIR")
    base = Path(override) if override else Path.home() / ".aianalyzer"
    base.mkdir(parents=True, exist_ok=True)
    return base / "cache.duckdb"


def _confidence(planning: float, control: float) -> float:
    """Bounded heuristic: stronger axis magnitudes => higher confidence."""
    return min(1.0, (abs(planning) + abs(control)) / 2.0)


# Six independent traits that produce a real radar shape (unlike projecting
# the four archetype quadrants onto themselves, which always degenerates to
# at most two non-zero spokes). Each tuple is:
#   (signal, label, normalizer_max, help)
# - ``signal`` matches a UserProfile attribute (or "todo_density", computed
#   on the fly in ``_signal_value``).
# - ``normalizer_max`` rescales the raw value to [0, 1]. Pulled from
#   weights.yaml where possible so the radar matches what the classifier sees;
#   ``parallel_tool_call_rate`` is already a ratio so it uses 1.0.
_BEHAVIOR_RADAR_DIMS: list[tuple[str, str, float, str]] = [
    ("planning_language_ratio", "Planner", 0.6,
     "How often your prompts use planning words like 'plan', 'design', 'first'. High = you talk through the approach first."),
    ("question_ratio", "Questioner", 0.6,
     "Share of prompts that ask a question instead of giving an order. High = you check before acting."),
    ("todo_density", "TODO-driver", 2.0,
     "Average explicit TODO items you write per session. High = you decompose work into a list."),
    ("prompt_specificity_avg", "Hands-on", 0.5,
     "Average detail in your prompts (word count / 200, capped). High = you write long, specific instructions instead of short 'do it' replies."),
    ("thinks_before_prompt_sec_avg", "Deliberator", 60.0,
     "Mean seconds between an AI reply and your next prompt (capped at 5 min per gap). High = you pause to read and think."),
    ("parallel_tool_call_rate", "Multi-tasker", 1.0,
     "Share of turns where you issue two or more tool calls in parallel. High = you fan work out simultaneously."),
]


def _build_behavior_radar(profile: UserProfile) -> list[dict[str, Any]]:
    """Return one entry per spoke of the 'behavior shape' radar.

    Each entry exposes ``score`` in [0, 1] (the radius the chart plots),
    ``raw`` (the un-normalized value, for tooltips), and ``help`` (one-line
    description) so the front-end can render explanations without duplicating
    knowledge of every signal.
    """
    out: list[dict[str, Any]] = []
    for signal, label, ceiling, help_text in _BEHAVIOR_RADAR_DIMS:
        raw = _signal_value(profile, signal)
        score = 0.0 if ceiling <= 0 else max(0.0, min(1.0, raw / ceiling))
        out.append(
            {
                "name": signal,
                "label": label,
                "score": round(score, 3),
                "raw": round(raw, 3),
                "ceiling": ceiling,
                "help": help_text,
            }
        )
    return out


def _signal_value(profile: UserProfile, name: str) -> float:
    """Mirror of ``classifier.rules._signal_value`` for portal display.

    Kept duplicated rather than imported so the underscore-prefixed helper
    in the classifier package stays private to that package.
    """
    if name == "todo_density":
        sessions = max(profile.session_count, 1)
        return profile.total_todos / sessions
    return float(getattr(profile, name, 0.0))


def _signal_row(name: str, value: float, norm_max: float | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "name": name,
        "label": _BEHAVIOR_LABELS.get(name, name),
        "value": round(value, 3),
    }
    if norm_max is not None:
        row["norm_max"] = norm_max
    return row


def _build_behavior_block(profile: UserProfile) -> dict[str, Any]:
    """Surface the raw signals + modifier near-misses behind the archetype."""
    w = load_weights()
    def _norm_max(signal: str) -> float | None:
        rng = w.normalizers.get(signal)
        return rng.max if rng is not None else None

    planning_signals = [
        _signal_row(s, _signal_value(profile, s), _norm_max(s))
        for s in w.planning.keys()
    ]
    control_signals = [
        _signal_row(s, _signal_value(profile, s), _norm_max(s))
        for s in w.control.keys()
    ]
    other_signals = [
        _signal_row("parallel_tool_call_rate", profile.parallel_tool_call_rate),
        _signal_row("abort_rate", profile.abort_rate),
    ]
    modifiers = []
    for tag, signal, key in _MODIFIER_SPECS:
        value = _signal_value(profile, signal)
        threshold = float(w.modifiers[key])
        modifiers.append(
            {
                "tag": tag,
                "signal": signal,
                "label": _BEHAVIOR_LABELS.get(signal, signal),
                "value": round(value, 3),
                "threshold": threshold,
                "met": value >= threshold,
            }
        )
    return {
        "planning": planning_signals,
        "control": control_signals,
        "other": other_signals,
        "modifiers": modifiers,
        "reasoning_effort_distribution": {
            k: round(v, 3) for k, v in profile.reasoning_effort_distribution.items()
        },
    }


def run_scan(progress_cb=None) -> dict[str, Any]:
    """Discover -> normalize -> extract -> cache. Returns counts and per-client breakdown."""
    store = FeatureStore(_cache_path())
    try:
        discovered = list(discover_all_sessions())
        total = len(discovered)
        scanned = 0
        skipped = 0
        errors = 0
        # Per-client counts so the UI can show an honest "we found N from X" breakdown.
        by_client: dict[str, int] = {}
        for d in discovered:
            by_client[d.client] = by_client.get(d.client, 0) + 1
        for i, d in enumerate(discovered):
            collector = _COLLECTORS.get(d.client)
            if collector is None:
                errors += 1
                continue
            try:
                if store.has_fresh(d.client, d.session_id, d.mtime):
                    skipped += 1
                else:
                    ns = collector.parse(d)
                    sf = extract_session_features(ns)
                    store.upsert(sf, mtime=d.mtime)
                    scanned += 1
            except Exception:  # noqa: BLE001
                errors += 1
            if progress_cb:
                progress_cb((i + 1) / max(total, 1))
        return {
            "discovered": total,
            "new": scanned,
            "skipped": skipped,
            "errors": errors,
            "by_client": by_client,
            "supported_clients": sorted(_COLLECTORS.keys()),
        }
    finally:
        store.close()


def load_profile_payload() -> dict[str, Any]:
    store = FeatureStore(_cache_path())
    try:
        features = list(store.load_all())
    finally:
        store.close()

    user_profile = aggregate_user_profile(features, cwd_history=[])
    classification = classify(user_profile)
    ext = compute_extended_profile(features)

    return {
        "primary_archetype": classification.primary.value,
        "secondary_archetype": (
            classification.secondary.value if classification.secondary else None
        ),
        "macro_label": classification.macro_label,
        "tags": list(classification.tags),
        "confidence": round(_confidence(classification.planning_score, classification.control_score), 3),
        "axes": {
            "planning": round(classification.planning_score, 3),
            "control": round(classification.control_score, 3),
        },
        "behavior_radar": _build_behavior_radar(user_profile),
        "totals": {
            "sessions": ext.total_sessions,
            "turns": ext.total_turns,
            "hours": round(ext.total_hours, 2),
            "days_active": ext.days_active,
            "longest_streak_days": ext.longest_streak_days,
        },
        "averages": {
            "turns_per_session": round(ext.avg_turns_per_session, 2),
            "session_minutes": round(ext.avg_session_minutes, 2),
            "prompt_words": round(ext.avg_prompt_words, 2),
            "median_prompt_words": round(ext.median_prompt_words, 2),
            "p90_prompt_words": round(ext.p90_prompt_words, 2),
            "acceptance_rate": round(ext.acceptance_rate, 3),
        },
        "top_tools": ext.top_tools,
        "top_projects": ext.top_projects,
        "top_models": ext.top_models,
        "top_file_extensions": ext.top_file_extensions,
        "session_type_counts": ext.session_type_counts,
        "hour_histogram": ext.hour_histogram,
        "weekday_histogram": ext.weekday_histogram,
        "activity_per_day_last_90": ext.activity_per_day_last_90,
        "by_client": ext.by_client,
        "first_session_at": ext.first_session_at.isoformat() if ext.first_session_at else None,
        "last_session_at": ext.last_session_at.isoformat() if ext.last_session_at else None,
        "behavior": _build_behavior_block(user_profile),
        "personality": compute_personality(
            user_profile,
            features,
            longest_streak_days=ext.longest_streak_days,
            top_tools=ext.top_tools,
        ).model_dump(),
    }
