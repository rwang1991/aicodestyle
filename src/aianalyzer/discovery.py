"""Locate session directories on disk for each supported AI client."""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

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
