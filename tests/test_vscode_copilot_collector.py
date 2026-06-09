"""Tests for the VS Code Copilot Chat collector."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from aianalyzer.collectors.vscode_copilot import VsCodeCopilotCollector
from aianalyzer.discovery import DiscoveredSession


def _make_session_file(
    path: Path,
    *,
    session_id: str,
    creation_ms: int,
    last_ms: int,
    requests: list[dict],
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 3,
        "sessionId": session_id,
        "creationDate": creation_ms,
        "lastMessageDate": last_ms,
        "requesterUsername": "tester",
        "responderUsername": "GitHub Copilot",
        "initialLocation": "panel",
        "requests": requests,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _discovered(json_path: Path, session_id: str = "abc") -> DiscoveredSession:
    return DiscoveredSession(
        client="vscode-copilot",
        session_id=session_id,
        root=json_path.parent,
        events_path=json_path,
        db_path=None,
        mtime=json_path.stat().st_mtime,
    )


def test_parse_extracts_session_metadata_and_turns(tmp_path: Path):
    p = _make_session_file(
        tmp_path / "chatSessions" / "11111111-2222-3333-4444-555555555555.json",
        session_id="11111111-2222-3333-4444-555555555555",
        creation_ms=1_700_000_000_000,
        last_ms=1_700_000_900_000,
        requests=[
            {
                "requestId": "r0",
                "responseId": "rsp0",
                "message": {"text": "first prompt"},
                "response": [
                    {"value": "Sure, here's the plan: "},
                    {"value": "step one, then two."},
                ],
                "modelId": "gpt-5",
                "timestamp": 1_700_000_100_000,
                "isCanceled": False,
            },
            {
                "requestId": "r1",
                "responseId": "rsp1",
                "message": {"text": "follow up question?"},
                "response": [{"value": "Yes."}],
                "modelId": "claude-sonnet-4",
                "timestamp": 1_700_000_500_000,
                "isCanceled": True,
            },
        ],
    )

    ns = VsCodeCopilotCollector().parse(
        _discovered(p, session_id="11111111-2222-3333-4444-555555555555")
    )

    assert ns.client == "vscode-copilot"
    assert ns.session_id == "11111111-2222-3333-4444-555555555555"
    assert ns.started_at == datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)
    assert ns.ended_at == datetime.fromtimestamp(1_700_000_900, tz=timezone.utc)
    assert ns.models_used == ["gpt-5", "claude-sonnet-4"]
    assert len(ns.turns) == 2

    t0 = ns.turns[0]
    assert t0.user is not None and t0.user.content == "first prompt"
    assert t0.assistant is not None
    assert t0.assistant.content == "Sure, here's the plan: step one, then two."
    assert t0.assistant.model == "gpt-5"
    assert t0.aborted is False

    t1 = ns.turns[1]
    assert t1.user is not None and t1.user.content == "follow up question?"
    assert t1.assistant is not None and t1.assistant.model == "claude-sonnet-4"
    assert t1.aborted is True


def test_parse_skips_corrupt_and_empty_files(tmp_path: Path):
    p = tmp_path / "chatSessions" / "bad.json"
    p.parent.mkdir(parents=True)
    p.write_text("{not valid json", encoding="utf-8")

    ns = VsCodeCopilotCollector().parse(_discovered(p, session_id="bad"))
    # Corrupt -> still get a NormalizedSession but with zero turns.
    assert ns.client == "vscode-copilot"
    assert ns.turns == []


def test_parse_handles_request_without_response_or_text(tmp_path: Path):
    """Empty/canceled turns: user present, assistant may be absent or empty."""
    p = _make_session_file(
        tmp_path / "chatSessions" / "edge.json",
        session_id="edge",
        creation_ms=1_700_000_000_000,
        last_ms=1_700_000_000_000,
        requests=[
            {
                "requestId": "r0",
                "message": {"text": "ping"},
                "response": [],  # no reply yet
                "modelId": "",
                "timestamp": 1_700_000_000_000,
                "isCanceled": False,
            },
            {
                "requestId": "r1",
                # no message.text -> drop the user content but keep the turn
                "response": [{"value": "orphan reply"}],
                "timestamp": 1_700_000_100_000,
            },
        ],
    )

    ns = VsCodeCopilotCollector().parse(_discovered(p, session_id="edge"))
    assert len(ns.turns) == 2
    assert ns.turns[0].user is not None
    assert ns.turns[0].user.content == "ping"
    # When response is empty, assistant should be None or have empty content.
    assert ns.turns[0].assistant is None or ns.turns[0].assistant.content == ""
    assert ns.turns[1].assistant is not None
    assert ns.turns[1].assistant.content == "orphan reply"
