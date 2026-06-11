"""Locate session directories on disk for each supported AI client."""
from __future__ import annotations

import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence
from urllib.parse import quote

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DiscoveredSession:
    client: str
    session_id: str
    root: Path
    events_path: Path
    db_path: Optional[Path]
    mtime: float


def _user_home() -> Path:
    return Path.home()


def discover_copilot_cli_sessions(home: Optional[Path] = None) -> Iterable[DiscoveredSession]:
    """Yield every Copilot CLI session directory that has an events.jsonl."""
    root = (home or _user_home()) / ".copilot" / "session-state"
    if not root.is_dir():
        return
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        if not _UUID_RE.match(entry.name):
            continue
        events = entry / "events.jsonl"
        if not events.is_file():
            continue
        db = entry / "session.db"
        yield DiscoveredSession(
            client="copilot-cli",
            session_id=entry.name,
            root=entry,
            events_path=events,
            db_path=db if db.is_file() else None,
            mtime=events.stat().st_mtime,
        )


# ---------------------------------------------------------------------------
# VS Code GitHub Copilot Chat
# ---------------------------------------------------------------------------
#
# VS Code stores each chat session as a JSON file under, per workspace:
#   <userDataDir>/User/workspaceStorage/<wsHash>/chatSessions/<sessionId>.json
#
# `userDataDir` is OS-specific:
#   Windows:  %APPDATA%/Code/User
#   macOS:    ~/Library/Application Support/Code/User
#   Linux:    ~/.config/Code/User
#
# We also probe Insiders. Callers may inject `roots` to override (tests, future
# user-config). Sessions whose JSON is empty or corrupt are skipped by the
# collector, not here — we just need the path.


def default_vscode_workspace_storage_roots() -> List[Path]:
    """Best-effort list of VS Code workspaceStorage roots on this OS."""
    home = _user_home()
    user_dirs: List[Path] = []
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        if appdata:
            user_dirs += [Path(appdata) / "Code" / "User", Path(appdata) / "Code - Insiders" / "User"]
    elif sys.platform == "darwin":
        user_dirs += [
            home / "Library" / "Application Support" / "Code" / "User",
            home / "Library" / "Application Support" / "Code - Insiders" / "User",
        ]
    else:
        user_dirs += [home / ".config" / "Code" / "User", home / ".config" / "Code - Insiders" / "User"]
    return [u / "workspaceStorage" for u in user_dirs]


def default_vscode_copilot_store_paths() -> List[Path]:
    """Candidate SQLite session-store paths for the VS Code Copilot Chat extension.

    Newer Copilot Chat versions persist every session to a single SQLite database
    under ``globalStorage/github.copilot-chat/session-store.db`` (schema is
    identical to the standalone Copilot CLI). Older versions used per-workspace
    JSON files under ``workspaceStorage/<hash>/chatSessions/``.

    Returns every candidate path that exists on disk (Code + Code-Insiders, all
    OS variants). Empty list when nothing is installed.
    """
    home = _user_home()
    user_dirs: List[Path] = []
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        if appdata:
            user_dirs += [Path(appdata) / "Code" / "User", Path(appdata) / "Code - Insiders" / "User"]
    elif sys.platform == "darwin":
        user_dirs += [
            home / "Library" / "Application Support" / "Code" / "User",
            home / "Library" / "Application Support" / "Code - Insiders" / "User",
        ]
    else:
        user_dirs += [home / ".config" / "Code" / "User", home / ".config" / "Code - Insiders" / "User"]
    candidates = [u / "globalStorage" / "github.copilot-chat" / "session-store.db" for u in user_dirs]
    return [p for p in candidates if p.is_file()]


def discover_vscode_copilot_sessions(
    roots: Optional[Sequence[Path]] = None,
) -> Iterable[DiscoveredSession]:
    """Yield every VS Code Copilot Chat session JSON across all workspaceStorage roots.

    Args:
        roots: Override the workspaceStorage roots to scan (used by tests). When
            None, `default_vscode_workspace_storage_roots()` is used.
    """
    search_roots: Iterable[Path] = roots if roots is not None else default_vscode_workspace_storage_roots()
    for root in search_roots:
        if not root.is_dir():
            continue
        for ws in sorted(root.iterdir()):
            if not ws.is_dir():
                continue
            chat_dir = ws / "chatSessions"
            if not chat_dir.is_dir():
                continue
            for f in sorted(chat_dir.iterdir()):
                if not f.is_file() or f.suffix.lower() != ".json":
                    continue
                if f.stat().st_size == 0:
                    continue
                # session_id derived from filename so it's stable across
                # rescans even though the file lives under a workspace hash.
                session_id = f.stem
                yield DiscoveredSession(
                    client="vscode-copilot",
                    session_id=session_id,
                    root=ws,
                    events_path=f,
                    db_path=None,
                    mtime=f.stat().st_mtime,
                )


# ---------------------------------------------------------------------------
# VS Code Copilot Chat SQLite session store (newer extension versions)
# ---------------------------------------------------------------------------

# Sessions VS Code emits internally that are not user-driven and should be
# skipped so they don't dilute the user's profile. ``copilotcli`` rows in this
# DB are CLI sessions launched from VS Code that the standalone Copilot CLI
# collector ALREADY captures from ``~/.copilot/session-state`` — keep them out
# to avoid double-counting.
_VSCODE_STORE_SKIP_AGENTS = frozenset({
    "summarizeConversationHistory",
    "copilotcli",
})


def _open_sqlite_readonly(path: Path) -> sqlite3.Connection:
    """Open a SQLite DB read-only and tolerant of an active WAL.

    Using ``mode=ro`` avoids touching the DB at all and lets us coexist with
    a running VS Code window. ``cache=shared`` isn't needed but harmless.
    """
    uri = f"file:{quote(str(path))}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=2.0)


def _iso_to_unix(iso: str) -> float:
    """Convert ISO-8601 ``YYYY-MM-DDTHH:MM:SS.sssZ`` to a Unix timestamp."""
    if not isinstance(iso, str) or not iso:
        return 0.0
    s = iso[:-1] + "+00:00" if iso.endswith("Z") else iso
    try:
        from datetime import datetime
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return 0.0


def discover_vscode_copilot_store_sessions(
    db_paths: Optional[Sequence[Path]] = None,
) -> Iterable[DiscoveredSession]:
    """Yield every user-initiated session row from each Copilot Chat SQLite store.

    Args:
        db_paths: Override the ``session-store.db`` paths to scan (used by tests).
            When None, ``default_vscode_copilot_store_paths()`` is used.

    Session IDs are prefixed ``db:`` so they can never collide with the legacy
    JSON-file sessions (which use bare UUIDs as session_id). The
    ``DiscoveredSession.client`` stays ``vscode-copilot`` so both sources roll
    up under one row in the Data Sources panel.
    """
    paths: Iterable[Path] = db_paths if db_paths is not None else default_vscode_copilot_store_paths()
    for db in paths:
        if not db.is_file():
            continue
        try:
            con = _open_sqlite_readonly(db)
        except sqlite3.Error:
            continue
        try:
            try:
                rows = con.execute(
                    "SELECT s.id, s.agent_name, s.updated_at "
                    "FROM sessions s "
                    "WHERE EXISTS (SELECT 1 FROM turns t WHERE t.session_id = s.id) "
                    "ORDER BY s.updated_at"
                ).fetchall()
            except sqlite3.Error:
                continue
        finally:
            con.close()
        for row in rows:
            sid, agent_name, updated_at = row
            if not isinstance(sid, str) or not sid:
                continue
            if isinstance(agent_name, str) and agent_name in _VSCODE_STORE_SKIP_AGENTS:
                continue
            mtime = _iso_to_unix(updated_at) if isinstance(updated_at, str) else 0.0
            yield DiscoveredSession(
                client="vscode-copilot",
                session_id=f"db:{sid}",
                root=db.parent,
                events_path=db,
                db_path=db,
                mtime=mtime,
            )
