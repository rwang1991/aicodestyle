import subprocess

import pytest

from aianalyzer.classifier.archetypes import Archetype
from aianalyzer.narrative import (
    NarrativeError,
    build_narrative_prompt,
    generate_narrative,
)


def _facts():
    return {
        "primary_archetype": Archetype.ARCHITECT.value,
        "secondary_archetype": Archetype.PILOT.value,
        "archetype_lean": 0.78,
        "archetype_lean_label": "Strong Architect tendency",
        "axes": {"planning": 0.32, "control": 0.37, "depth": 0.05, "speed": -0.10},
        "totals": {"sessions": 168, "turns": 1820, "hours": 92.4, "days_active": 41},
        "top_tools": [("edit", 220), ("read", 180)],
        "top_projects": [("/repos/aianalyzer", 80)],
        "top_models": [("claude-sonnet-4.5", 600)],
        "session_type_counts": {"feature_work": 60, "debugging": 40},
    }


def test_build_narrative_prompt_includes_key_facts():
    prompt = build_narrative_prompt(_facts())
    assert "architect" in prompt.lower()
    assert "168" in prompt
    assert "feature_work" in prompt
    # Must give the model a clear structural mandate so the UI can render it.
    assert "Markdown" in prompt or "markdown" in prompt


def test_generate_narrative_invokes_copilot_with_expected_args(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="# Your AI Profile\n\nYou are an Architect.\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = generate_narrative(_facts(), copilot_binary="copilot")
    assert out.startswith("# Your AI Profile")
    assert captured["cmd"][0] == "copilot"
    assert "-p" in captured["cmd"]
    # We MUST NOT pass --allow-all-tools: the narrative is a pure text task,
    # and giving the CLI tool access caused it to write a stray profile.md
    # to the user's cwd and then short-circuit subsequent runs with
    # "the file already exists" instead of returning markdown.
    assert "--allow-all-tools" not in captured["cmd"]
    assert "--no-color" in captured["cmd"]
    assert "-s" in captured["cmd"]
    assert "--output-format" in captured["cmd"]
    assert "text" in captured["cmd"]
    # The prompt must explicitly forbid file writes and tool use so the model
    # emits markdown to stdout instead of side-effecting the filesystem.
    prompt_idx = captured["cmd"].index("-p") + 1
    prompt_text = captured["cmd"][prompt_idx]
    assert "do NOT write" in prompt_text.lower() or "do not write" in prompt_text.lower()
    # Critical for Windows: subprocess must decode as UTF-8 with replace so
    # we never produce mojibake from the OS code page (e.g. cp1252 / cp936).
    assert captured["kwargs"].get("encoding") == "utf-8"
    assert captured["kwargs"].get("errors") == "replace"
    # Must run in an isolated cwd so any stray tool-driven file writes do not
    # pollute the user's working directory.
    assert captured["kwargs"].get("cwd") is not None


def test_generate_narrative_raises_on_nonzero_exit(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(args=cmd, returncode=2, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(NarrativeError):
        generate_narrative(_facts())


def test_generate_narrative_raises_on_timeout(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(NarrativeError):
        generate_narrative(_facts(), timeout_sec=1.0)


def test_generate_narrative_raises_when_binary_missing(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(NarrativeError, match="copilot CLI binary not found"):
        generate_narrative(_facts(), copilot_binary="copilot-that-does-not-exist")
