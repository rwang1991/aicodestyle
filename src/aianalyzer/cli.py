"""aianalyzer CLI entry point."""
from __future__ import annotations

import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from aianalyzer.classifier.rules import classify
from aianalyzer.collectors.base import Collector
from aianalyzer.collectors.copilot_cli import CopilotCliCollector
from aianalyzer.collectors.vscode_copilot import VsCodeCopilotCollector
from aianalyzer.discovery import (
    discover_copilot_cli_sessions,
    discover_vscode_copilot_sessions,
    discover_vscode_copilot_store_sessions,
)
from aianalyzer.features import (
    SessionFeatures,
    aggregate_user_profile,
    extract_session_features,
)
from aianalyzer.report.terminal import render_report
from aianalyzer.store import FeatureStore

app = typer.Typer(add_completion=False, help="Analyze your AI coding sessions.")


_COLLECTORS: dict[str, Collector] = {
    "copilot-cli": CopilotCliCollector(),
    "vscode-copilot": VsCodeCopilotCollector(),
}


def _default_home() -> Path:
    return Path.home()


def _default_cache(home: Path) -> Path:
    return home / ".aianalyzer" / "cache.duckdb"


@app.command()
def scan(
    home: Optional[Path] = typer.Option(None, help="Override the home directory holding .copilot/."),
    cache: Optional[Path] = typer.Option(None, help="DuckDB cache file."),
) -> None:
    """Discover and ingest local AI coding sessions (Copilot CLI + VS Code Copilot Chat)."""
    home_dir = home or _default_home()
    cache_path = cache or _default_cache(home_dir)

    discovered = list(discover_copilot_cli_sessions(home=home_dir))
    # VS Code uses OS-specific user-data dirs (AppData/Library/.config) that
    # we never re-root from --home. So when a user explicitly overrides --home
    # (typically for tests or scratch sandboxes) we keep the scan scoped to
    # just the Copilot CLI dir and skip VS Code entirely. Real users don't
    # pass --home, so they still get everything.
    if home is None:
        discovered += list(discover_vscode_copilot_sessions())
        discovered += list(discover_vscode_copilot_store_sessions())

    store = FeatureStore(cache_path)
    by_client: dict[str, int] = {}
    scanned = 0
    skipped = 0
    errors = 0
    for d in discovered:
        by_client[d.client] = by_client.get(d.client, 0) + 1
        collector = _COLLECTORS.get(d.client)
        if collector is None:
            errors += 1
            typer.echo(f"unknown client {d.client} for {d.session_id}", err=True)
            continue
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
    breakdown = ", ".join(f"{c}={n}" for c, n in sorted(by_client.items())) or "no clients"
    typer.echo(
        f"scanned {scanned}, skipped {skipped}, errors {errors} (sources: {breakdown})"
    )


def _collect_cwd_history(home: Path) -> list[str | None]:
    import json

    base = home / ".copilot" / "session-state"
    if not base.exists():
        return []
    cwds: list[str | None] = []
    for events in base.glob("*/events.jsonl"):
        try:
            with events.open(encoding="utf-8") as fh:
                first = fh.readline()
            data = json.loads(first).get("data", {})
            cwd = data.get("context", {}).get("cwd")
            cwds.append(cwd)
        except Exception:  # noqa: BLE001
            cwds.append(None)
    return cwds


@app.command()
def report(
    home: Optional[Path] = typer.Option(None, help="Override the home directory holding .copilot/."),
    cache: Optional[Path] = typer.Option(None, help="DuckDB cache file."),
) -> None:
    """Aggregate cached features and print the archetype report."""
    home_dir = home or _default_home()
    cache_path = cache or _default_cache(home_dir)

    store = FeatureStore(cache_path)
    features: list[SessionFeatures] = list(store.load_all())
    store.close()

    cwd_history = _collect_cwd_history(home_dir)
    profile = aggregate_user_profile(features, cwd_history=cwd_history)
    result = classify(profile)

    console = Console()
    render_report(profile, result, features, console=console)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Host to bind the portal to."),
    port: int = typer.Option(8765, help="Port to bind the portal to."),
    open_browser: bool = typer.Option(True, "--open-browser/--no-open-browser", help="Open the portal in your default browser."),
) -> None:
    """Launch the local web portal at http://HOST:PORT/."""
    import uvicorn

    url = f"http://{host}:{port}/"
    typer.echo(f"AIAnalyzer portal: {url}")

    if open_browser:
        def _open() -> None:
            time.sleep(1.0)
            try:
                webbrowser.open(url)
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=_open, daemon=True).start()

    # Pass the factory as an object (not import string) so the packaged
    # PyInstaller bundle, which doesn't expose modules by string to Uvicorn's
    # importer, still works. In development this is equally fine.
    from aianalyzer.web.app import create_app as _create_app

    uvicorn.run(
        _create_app,
        host=host,
        port=port,
        factory=True,
        log_level="info",
    )

