"""Tests for VS Code Copilot Chat discovery."""
from __future__ import annotations

import json
from pathlib import Path

from aianalyzer.discovery import (
    DiscoveredSession,
    discover_vscode_copilot_sessions,
)


def _write_session(ws_dir: Path, session_id: str, requests: int = 1) -> Path:
    chat_dir = ws_dir / "chatSessions"
    chat_dir.mkdir(parents=True, exist_ok=True)
    p = chat_dir / f"{session_id}.json"
    payload = {
        "version": 3,
        "sessionId": session_id,
        "creationDate": 1_700_000_000_000,
        "lastMessageDate": 1_700_000_900_000,
        "requesterUsername": "tester",
        "responderUsername": "GitHub Copilot",
        "initialLocation": "panel",
        "requests": [
            {
                "requestId": f"req-{i}",
                "responseId": f"res-{i}",
                "message": {"text": f"prompt {i}"},
                "response": [{"value": f"reply {i}"}],
                "modelId": "gpt-5",
                "timestamp": 1_700_000_000_000 + i * 1000,
                "isCanceled": False,
            }
            for i in range(requests)
        ],
    }
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_discover_finds_sessions_across_workspaces(tmp_path: Path):
    base = tmp_path / "AppData" / "Roaming" / "Code" / "User" / "workspaceStorage"
    ws_a = base / "0db60d936605ab9c35efe068e994626a"
    ws_b = base / "0edf1709387d50ab098edf7245584ccb"
    _write_session(ws_a, "0afaf1b4-0045-4480-be17-5ff5f6082f07")
    _write_session(ws_b, "11111111-2222-3333-4444-555555555555")
    _write_session(ws_b, "22222222-2222-3333-4444-555555555555", requests=3)

    found = list(discover_vscode_copilot_sessions(roots=[base]))

    assert len(found) == 3
    assert all(isinstance(d, DiscoveredSession) for d in found)
    assert {d.client for d in found} == {"vscode-copilot"}
    assert {d.session_id for d in found} == {
        "0afaf1b4-0045-4480-be17-5ff5f6082f07",
        "11111111-2222-3333-4444-555555555555",
        "22222222-2222-3333-4444-555555555555",
    }
    for d in found:
        assert d.events_path.is_file()
        assert d.db_path is None
        assert d.mtime > 0


def test_discover_missing_root_returns_empty(tmp_path: Path):
    """If the workspaceStorage folder doesn't exist, return nothing silently."""
    assert list(discover_vscode_copilot_sessions(roots=[tmp_path / "nope"])) == []


def test_discover_ignores_non_json_and_empty_files(tmp_path: Path):
    base = tmp_path / "ws"
    chat = base / "abcdef" / "chatSessions"
    chat.mkdir(parents=True)
    (chat / "not-a-session.txt").write_text("hi", encoding="utf-8")
    # A zero-byte JSON would be unreadable; skip it.
    (chat / "00000000-0000-0000-0000-000000000000.json").write_text("", encoding="utf-8")
    _write_session(base / "abcdef", "11111111-2222-3333-4444-555555555555")

    found = list(discover_vscode_copilot_sessions(roots=[base]))
    assert len(found) == 1
    assert found[0].session_id == "11111111-2222-3333-4444-555555555555"
