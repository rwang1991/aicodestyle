"""aianalyzer CLI entry point."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from aianalyzer.collectors.copilot_cli import CopilotCliCollector
from aianalyzer.discovery import discover_copilot_cli_sessions
from aianalyzer.features import extract_session_features
from aianalyzer.store import FeatureStore

app = typer.Typer(add_completion=False, help="Analyze your AI coding sessions.")


def _default_home() -> Path:
    return Path.home()


def _default_cache(home: Path) -> Path:
    return home / ".aianalyzer" / "cache.duckdb"


@app.command()
def scan(
    home: Optional[Path] = typer.Option(None, help="Override the home directory holding .copilot/."),
    cache: Optional[Path] = typer.Option(None, help="DuckDB cache file."),
) -> None:
    """Discover and ingest local Copilot CLI sessions."""
    home_dir = home or _default_home()
    cache_path = cache or _default_cache(home_dir)

    discovered = list(discover_copilot_cli_sessions(home=home_dir))
    store = FeatureStore(cache_path)
    collector = CopilotCliCollector()

    scanned = 0
    skipped = 0
    errors = 0
    for d in discovered:
        try:
            if store.has_fresh(d.client, d.session_id, d.mtime):
                skipped += 1
                continue
            session = collector.parse(d)
            features = extract_session_features(session)
            store.upsert(features, mtime=d.mtime)
            scanned += 1
        except Exception as exc:  # noqa: BLE001
            errors += 1
            typer.echo(f"error in {d.session_id}: {exc}", err=True)

    store.close()
    typer.echo(f"scanned {scanned}, skipped {skipped}, errors {errors}")
