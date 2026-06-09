"""Test the CLI scan command."""
from pathlib import Path

from typer.testing import CliRunner

from aianalyzer.cli import app
from aianalyzer.store import FeatureStore


def test_scan_populates_cache(tmp_path: Path, fixtures_dir: Path):
    home = fixtures_dir / "home"
    cache = tmp_path / "cache.duckdb"
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["--home", str(home), "--cache", str(cache)],
    )
    assert result.exit_code == 0, result.output
    assert "scanned" in result.output.lower()

    store = FeatureStore(cache)
    rows = list(store.load_all())
    store.close()
    assert len(rows) == 1
    assert rows[0].session_id == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def test_scan_is_idempotent(tmp_path: Path, fixtures_dir: Path):
    home = fixtures_dir / "home"
    cache = tmp_path / "cache.duckdb"
    runner = CliRunner()

    runner.invoke(app, ["--home", str(home), "--cache", str(cache)])
    second = runner.invoke(app, ["--home", str(home), "--cache", str(cache)])

    assert second.exit_code == 0
    assert "skipped" in second.output.lower()
