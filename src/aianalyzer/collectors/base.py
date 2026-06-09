"""Abstract collector contract + shared JSONL helpers."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterator, Protocol

from aianalyzer.discovery import DiscoveredSession
from aianalyzer.normalize import NormalizedSession


def _parse_ts(value: str) -> datetime:
    # Python 3.11+ handles trailing 'Z' since 3.11; normalize to be safe.
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def iter_jsonl_events(path: Path) -> Iterator[dict]:
    """Yield each JSONL event with `ts` parsed to a datetime. Skip junk lines."""
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = event.get("ts")
            if isinstance(ts, str):
                try:
                    event["ts"] = _parse_ts(ts)
                except ValueError:
                    continue
            yield event


class Collector(Protocol):
    """Every per-client collector parses a discovered session into normalized form."""

    client: str

    def parse(self, discovered: DiscoveredSession) -> NormalizedSession: ...
