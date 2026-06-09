"""Glue between FastAPI routes and the existing classifier pipeline."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

from aianalyzer.classifier.rules import classify
from aianalyzer.collectors.copilot_cli import CopilotCliCollector
from aianalyzer.discovery import DiscoveredSession, discover_copilot_cli_sessions
from aianalyzer.features import aggregate_user_profile, extract_session_features
from aianalyzer.stats import compute_extended_profile
from aianalyzer.store import FeatureStore


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
    }
