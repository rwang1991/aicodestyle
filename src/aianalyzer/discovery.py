"""Locate session directories on disk for each supported AI client."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

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
