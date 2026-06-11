"""Tests for the VS Code Copilot Chat SQLite session-store discovery + collector.

Newer Copilot Chat versions persist sessions to
``globalStorage/github.copilot-chat/session-store.db`` rather than per-workspace
JSON files. The schema is the same as Copilot CLI's; see
``inspect_db.py`` output in checkpoint notes for the exact DDL.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from aianalyzer.collectors.vscode_copilot import VsCodeCopilotCollector
from aianalyzer.discovery import (
    DiscoveredSession,
    discover_vscode_copilot_store_sessions,
)


_SCHEMA_SQL = """
CREATE TABLE schema_version (version INTEGER NOT NULL);
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    cwd TEXT,
    repository TEXT,
    host_type TEXT,
    branch TEXT,
    summary TEXT,
    agent_name TEXT,
    agent_description TEXT,
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    turn_index INTEGER NOT NULL,
    user_message TEXT,
    assistant_response TEXT,
    timestamp TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(session_id, turn_index)
);
"""


def _make_store(path: Path, rows: list[dict]) -> None:
    """Build a minimal session-store.db at ``path`` with the given session rows.

    Each row is a dict with keys: id, cwd, agent_name, host_type, created_at,
    updated_at, turns (list of (idx, user_msg, asst_msg, ts)).
    """
    con = sqlite3.connect(path)
    try:
        con.executescript(_SCHEMA_SQL)
        for r in rows:
            con.execute(
                "INSERT INTO sessions (id, cwd, repository, host_type, branch, "
                "summary, agent_name, agent_description, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    r["id"], r.get("cwd", "/tmp"), r.get("repository", ""),
                    r.get("host_type", "vscode"), r.get("branch", "main"),
                    r.get("summary", ""), r.get("agent_name", "GitHub Copilot Chat"),
                    r.get("agent_description", ""),
                    r.get("created_at", "2026-01-01T09:00:00.000Z"),
                    r.get("updated_at", "2026-01-01T10:00:00.000Z"),
                ),
            )
            for idx, user_msg, asst_msg, ts in r.get("turns", []):
                con.execute(
                    "INSERT INTO turns (session_id, turn_index, user_message, "
                    "assistant_response, timestamp) VALUES (?, ?, ?, ?, ?)",
                    (r["id"], idx, user_msg, asst_msg, ts),
                )
        con.commit()
    finally:
        con.close()


@pytest.fixture
def store_db(tmp_path: Path) -> Path:
    db = tmp_path / "session-store.db"
    _make_store(db, rows=[
        {
            "id": "sess-1",
            "cwd": "/repo/foo",
            "agent_name": "GitHub Copilot Chat",
            "created_at": "2026-01-01T09:00:00.000Z",
            "updated_at": "2026-01-01T09:45:00.000Z",
            "turns": [
                (0, "fix the parser bug", "Done — patched `parser.py`.", "2026-01-01T09:00:30.000Z"),
                (1, "now add a test", "Added `test_parser.py` with three cases.", "2026-01-01T09:15:00.000Z"),
            ],
        },
        {
            "id": "sess-2",
            "agent_name": "Todd",  # custom agent — should still be counted
            "created_at": "2026-01-02T10:00:00.000Z",
            "updated_at": "2026-01-02T10:30:00.000Z",
            "turns": [(0, "review this design", "Looks solid; one concern below.", "2026-01-02T10:00:30.000Z")],
        },
        {
            "id": "sess-skip-summarize",
            "agent_name": "summarizeConversationHistory",  # internal — must be filtered
            "turns": [(0, "compact me", "ok", "2026-01-01T11:00:00.000Z")],
        },
        {
            "id": "sess-skip-cli",
            "agent_name": "copilotcli",  # captured by Copilot CLI collector; skip to avoid dup
            "turns": [(0, "build it", "done", "2026-01-01T12:00:00.000Z")],
        },
        {
            "id": "sess-empty",
            "agent_name": "GitHub Copilot Chat",
            "turns": [],  # no turns -> not user-meaningful, must be filtered
        },
    ])
    return db


def test_discovery_yields_only_user_sessions_with_turns(store_db: Path) -> None:
    discovered = list(discover_vscode_copilot_store_sessions([store_db]))
    ids = sorted(d.session_id for d in discovered)
    assert ids == ["db:sess-1", "db:sess-2"]
    for d in discovered:
        assert d.client == "vscode-copilot"  # rolls up under the same row in Data Sources
        assert d.events_path == store_db
        assert d.db_path == store_db
        assert d.mtime > 0


def test_discovery_namespaces_session_id_to_avoid_collisions(store_db: Path) -> None:
    # A bare UUID from chatSessions/*.json must never collide with a SQLite row.
    discovered = list(discover_vscode_copilot_store_sessions([store_db]))
    for d in discovered:
        assert d.session_id.startswith("db:")


def test_discovery_skips_missing_or_unreadable_paths(tmp_path: Path) -> None:
    bogus = tmp_path / "does-not-exist.db"
    assert list(discover_vscode_copilot_store_sessions([bogus])) == []


def test_collector_parses_sqlite_session(store_db: Path) -> None:
    discovered = next(
        d for d in discover_vscode_copilot_store_sessions([store_db])
        if d.session_id == "db:sess-1"
    )
    ns = VsCodeCopilotCollector().parse(discovered)
    assert ns.client == "vscode-copilot"
    assert ns.session_id == "db:sess-1"
    assert ns.cwd == "/repo/foo"
    assert len(ns.turns) == 2
    assert ns.turns[0].user is not None
    assert "parser bug" in ns.turns[0].user.content
    assert ns.turns[0].assistant is not None
    assert "Done" in ns.turns[0].assistant.content
    # SQLite store doesn't carry per-turn model info; that's fine.
    assert ns.turns[0].assistant.model == ""
    assert ns.turns[0].tool_calls == []
    # Started/ended derived from created_at/updated_at ISO strings.
    assert ns.started_at.isoformat().startswith("2026-01-01T09:00:00")
    assert ns.ended_at.isoformat().startswith("2026-01-01T09:45:00")


def test_collector_returns_empty_for_unknown_session_id(store_db: Path) -> None:
    bogus = DiscoveredSession(
        client="vscode-copilot",
        session_id="db:nope",
        root=store_db.parent,
        events_path=store_db,
        db_path=store_db,
        mtime=0.0,
    )
    ns = VsCodeCopilotCollector().parse(bogus)
    assert ns.client == "vscode-copilot"
    assert ns.turns == []


def test_collector_still_handles_legacy_json_path(tmp_path: Path) -> None:
    # Regression guard: dispatching on file extension must not break the JSON path.
    import json
    payload = {
        "sessionId": "abc-123",
        "creationDate": 1_700_000_000_000,
        "lastMessageDate": 1_700_000_500_000,
        "requests": [
            {"requestId": "r1", "message": {"text": "hello"},
             "response": [{"kind": "markdownContent", "value": "hi"}],
             "modelId": "gpt-5", "timestamp": 1_700_000_100_000},
        ],
    }
    f = tmp_path / "abc-123.json"
    f.write_text(json.dumps(payload), encoding="utf-8")
    d = DiscoveredSession(
        client="vscode-copilot", session_id="abc-123",
        root=tmp_path, events_path=f, db_path=None,
        mtime=f.stat().st_mtime,
    )
    ns = VsCodeCopilotCollector().parse(d)
    assert ns.session_id == "abc-123"
    assert len(ns.turns) == 1
    assert ns.turns[0].assistant is not None
    assert ns.turns[0].assistant.model == "gpt-5"
