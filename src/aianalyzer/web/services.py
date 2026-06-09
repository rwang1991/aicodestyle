"""Glue between FastAPI routes and the existing classifier pipeline."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

from aianalyzer.classifier.rules import classify
from aianalyzer.classifier.weights import load_weights
from aianalyzer.collectors.copilot_cli import CopilotCliCollector
from aianalyzer.discovery import DiscoveredSession, discover_copilot_cli_sessions
from aianalyzer.features import UserProfile, aggregate_user_profile, extract_session_features
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
    """Aggregator over all supported clients. Currently only copilot-cli.

    Exposed as a module-level symbol so tests can monkeypatch it.
    """
    return discover_copilot_cli_sessions()


def _cache_path() -> Path:
    override = os.environ.get("AIANALYZER_CACHE_DIR")
    base = Path(override) if override else Path.home() / ".aianalyzer"
    base.mkdir(parents=True, exist_ok=True)
    return base / "cache.duckdb"


def _confidence(planning: float, control: float) -> float:
    """Bounded heuristic: stronger axis magnitudes => higher confidence."""
    return min(1.0, (abs(planning) + abs(control)) / 2.0)


# Ideal direction of each archetype in (planning, control) space.
# Used to project a user's score onto each quadrant.
_ARCHETYPE_DIRECTIONS: list[tuple[str, str, int, int]] = [
    ("architect", "Architect", +1, +1),
    ("pilot", "Pilot", +1, -1),
    ("tinkerer", "Tinkerer", -1, +1),
    ("vibe-coder", "Vibe Coder", -1, -1),
]


def _archetype_affinity(planning: float, control: float) -> list[dict[str, Any]]:
    """Project (planning, control) onto each of the 4 archetype quadrants.

    Score formula: ``alignment = (sign_p * P + sign_c * C) / 2``, clamped to
    ``[0, 1]``. The dominant archetype reaches 1.0 when the user's point sits
    exactly at the (+/- 1, +/- 1) corner of that quadrant; the opposite
    archetype always reads 0.0. This is what the radar chart on the portal
    consumes.
    """
    out: list[dict[str, Any]] = []
    for key, label, sp, sc in _ARCHETYPE_DIRECTIONS:
        score = (sp * planning + sc * control) / 2.0
        out.append(
            {
                "key": key,
                "label": label,
                "score": round(max(0.0, min(1.0, score)), 3),
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


def run_scan(progress_cb=None) -> dict[str, int]:
    """Discover -> normalize -> extract -> cache. Returns counts."""
    store = FeatureStore(_cache_path())
    try:
        discovered = list(discover_all_sessions())
        collector = CopilotCliCollector()
        total = len(discovered)
        scanned = 0
        skipped = 0
        errors = 0
        for i, d in enumerate(discovered):
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
        return {"discovered": total, "new": scanned, "skipped": skipped, "errors": errors}
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
        "archetype_affinity": _archetype_affinity(
            classification.planning_score, classification.control_score
        ),
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
        "first_session_at": ext.first_session_at.isoformat() if ext.first_session_at else None,
        "last_session_at": ext.last_session_at.isoformat() if ext.last_session_at else None,
        "behavior": _build_behavior_block(user_profile),
    }
