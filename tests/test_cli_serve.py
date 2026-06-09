"""Tests for the CLI serve command."""
from typer.testing import CliRunner

from aianalyzer.cli import app


def test_serve_help_lists_options():
    runner = CliRunner()
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "--host" in out
    assert "--port" in out
    assert "--open-browser" in out
    assert "--no-open-browser" in out


def test_serve_advertises_url_and_calls_uvicorn(monkeypatch):
    captured: dict = {}

    def fake_run(target, **kwargs):
        captured["target"] = target
        captured["kwargs"] = kwargs

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_run)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["serve", "--host", "127.0.0.1", "--port", "9999", "--no-open-browser"],
    )
    assert result.exit_code == 0, result.output
    assert "http://127.0.0.1:9999/" in result.output
    assert captured["target"] == "aianalyzer.web.app:create_app"
    assert captured["kwargs"]["host"] == "127.0.0.1"
    assert captured["kwargs"]["port"] == 9999
    assert captured["kwargs"]["factory"] is True
