"""Test the CLI report command."""
from pathlib import Path

from typer.testing import CliRunner

from aianalyzer.cli import app


def test_report_after_scan(tmp_path: Path, fixtures_dir: Path):
    home = fixtures_dir / "home"
    cache = tmp_path / "cache.duckdb"
    runner = CliRunner()

    scan_result = runner.invoke(app, ["scan", "--home", str(home), "--cache", str(cache)])
    assert scan_result.exit_code == 0, scan_result.output

    report_result = runner.invoke(app, ["report", "--home", str(home), "--cache", str(cache)])
    assert report_result.exit_code == 0, report_result.output
    assert "AI archetype" in report_result.output
    # Macro label must contain one of the four primary archetype names (title case)
    assert any(
        name in report_result.output
        for name in ("Architect", "Pilot", "Tinkerer", "Vibe Coder")
    )


def test_report_on_empty_cache(tmp_path: Path):
    cache = tmp_path / "cache.duckdb"
    runner = CliRunner()
    result = runner.invoke(app, ["report", "--cache", str(cache)])
    assert result.exit_code == 0
    assert "0 sessions" in result.output
