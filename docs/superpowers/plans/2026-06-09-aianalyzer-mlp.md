# AIAnalyzer MLP (M0–M3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-first CLI that ingests GitHub Copilot CLI sessions, computes 18 usage signals, classifies the developer into an AI-collaboration archetype (Architect / Pilot / Tinkerer / Vibe Coder), and renders a terminal report — the Minimum Lovable Product for `aianalyzer`.

**Architecture:** A 5-stage pipeline (`discover → collect → normalize+redact → feature-extract → classify → report`) wired together by a Typer CLI. Each stage is a pure module operating on small dataclasses (`NormalizedSession`, `Turn`, `ToolCall`, `SessionFeatures`, `UserProfile`, `ClassificationResult`). A DuckDB file in `~/.aianalyzer/cache.duckdb` caches per-session features keyed on `(client, session_id, mtime)` so re-runs are incremental. The classifier is rule-based with weights externalized to `aianalyzer/classifier/weights.yaml`; the data path stays clean so a clustering classifier can be added in M6 without disturbing earlier stages.

**Tech Stack:** Python 3.11+, `typer` (CLI), `pydantic` v2 (dataclasses/validation), `duckdb` (feature cache), `rich` (terminal UI), `pyyaml` (weights), `pytest` + `pytest-cov` (tests). Single-package src layout under `src/aianalyzer/`. No network calls. Windows-first paths (`pathlib.Path`, `%USERPROFILE%`-friendly).

---

## File Structure

```
AIAnalyzer/
├── DESIGN.md                              (already exists — source of truth)
├── README.md                              (Task 21)
├── pyproject.toml                         (Task 2)
├── .gitignore                             (Task 3)
├── src/aianalyzer/
│   ├── __init__.py                        (Task 1)
│   ├── cli.py                             (Tasks 19–20)
│   ├── normalize.py                       (Task 4)
│   ├── redact.py                          (Task 5)
│   ├── discovery.py                       (Task 6)
│   ├── collectors/
│   │   ├── __init__.py                    (Task 7)
│   │   ├── base.py                        (Task 7)
│   │   └── copilot_cli.py                 (Task 8)
│   ├── features.py                        (Tasks 9–12)
│   ├── store.py                           (Task 13)
│   ├── archetypes.py                      (Task 14)
│   ├── classifier/
│   │   ├── __init__.py                    (Task 15)
│   │   ├── weights.yaml                   (Task 15)
│   │   └── rules.py                       (Tasks 16–17)
│   └── report/
│       ├── __init__.py                    (Task 18)
│       └── terminal.py                    (Task 18)
└── tests/
    ├── conftest.py                        (Task 4)
    ├── fixtures/
    │   ├── events_minimal.jsonl           (Task 7)
    │   ├── events_planner.jsonl           (Task 9)
    │   ├── events_vibe.jsonl              (Task 10)
    │   └── session_db_sample.sql          (Task 8)
    ├── test_normalize.py                  (Task 4)
    ├── test_redact.py                     (Task 5)
    ├── test_discovery.py                  (Task 6)
    ├── test_collectors_base.py            (Task 7)
    ├── test_copilot_cli.py                (Task 8)
    ├── test_features_text.py              (Task 9)
    ├── test_features_turn_tool.py         (Task 10)
    ├── test_features_meta.py              (Task 11)
    ├── test_features_profile.py           (Task 12)
    ├── test_store.py                      (Task 13)
    ├── test_archetypes.py                 (Task 14)
    ├── test_classifier_weights.py         (Task 15)
    ├── test_classifier_rules.py           (Task 16)
    ├── test_classifier_modifiers.py       (Task 17)
    ├── test_report_terminal.py            (Task 18)
    └── test_cli.py                        (Tasks 19–20)
```

---

## Task 1: Repository skeleton and git init

**Files:**
- Create: `src/aianalyzer/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create skeleton directories and initialize git**

```powershell
cd C:\Users\ruwang\source\repos\Temp\AIAnalyzer
git init
New-Item -ItemType Directory -Force -Path src\aianalyzer\collectors, src\aianalyzer\classifier, src\aianalyzer\report, tests\fixtures | Out-Null
```

- [ ] **Step 2: Create empty package init files**

`src/aianalyzer/__init__.py`:
```python
"""AIAnalyzer — local-first AI-collaboration session analyzer."""

__version__ = "0.1.0"
```

`src/aianalyzer/collectors/__init__.py`, `src/aianalyzer/classifier/__init__.py`, `src/aianalyzer/report/__init__.py`, `tests/__init__.py`: each is an empty file.

```powershell
"" | Out-File -Encoding utf8 src\aianalyzer\collectors\__init__.py
"" | Out-File -Encoding utf8 src\aianalyzer\classifier\__init__.py
"" | Out-File -Encoding utf8 src\aianalyzer\report\__init__.py
"" | Out-File -Encoding utf8 tests\__init__.py
```

- [ ] **Step 3: Create `tests/conftest.py` exposing a fixture directory**

```python
"""Shared pytest fixtures."""
from pathlib import Path
import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
```

- [ ] **Step 4: Verify the skeleton imports**

Run: `python -c "import sys; sys.path.insert(0, 'src'); import aianalyzer; print(aianalyzer.__version__)"`
Expected output: `0.1.0`

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "chore: scaffold aianalyzer package skeleton"
```

---

## Task 2: `pyproject.toml` (src layout, dependencies, pytest config)

**Files:**
- Create: `pyproject.toml`

- [ ] **Step 1: Write the failing test**

`tests/test_packaging.py`:
```python
"""Verify the project is installable and exposes the expected console script."""
from importlib import metadata


def test_distribution_metadata():
    dist = metadata.distribution("aianalyzer")
    assert dist.version == "0.1.0"
    entry_points = {ep.name: ep.value for ep in dist.entry_points}
    assert entry_points.get("aianalyzer") == "aianalyzer.cli:app"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_packaging.py -v`
Expected: FAIL with `PackageNotFoundError: aianalyzer`.

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling>=1.24"]
build-backend = "hatchling.build"

[project]
name = "aianalyzer"
version = "0.1.0"
description = "Local-first analyzer for AI coding-assistant sessions."
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
authors = [{ name = "ruwang" }]
dependencies = [
  "typer>=0.12",
  "pydantic>=2.7",
  "duckdb>=1.0",
  "rich>=13.7",
  "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.2",
  "pytest-cov>=5.0",
]

[project.scripts]
aianalyzer = "aianalyzer.cli:app"

[tool.hatch.build.targets.wheel]
packages = ["src/aianalyzer"]

[tool.pytest.ini_options]
addopts = "-ra"
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 4: Install and verify**

Run:
```powershell
python -m pip install -e ".[dev]"
python -m pytest tests/test_packaging.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/test_packaging.py
git commit -m "build: add pyproject.toml with hatchling and dev deps"
```

---

## Task 3: `.gitignore` and baseline lint check

**Files:**
- Create: `.gitignore`

- [ ] **Step 1: Write `.gitignore`**

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
build/
dist/
.eggs/
.venv/
venv/
.env

# Pytest / coverage
.pytest_cache/
.coverage
htmlcov/

# DuckDB cache
*.duckdb
*.duckdb.wal

# IDE
.vscode/
.idea/

# AIAnalyzer local cache
.aianalyzer/
```

- [ ] **Step 2: Verify git ignores the noise**

```powershell
python -m pytest -q
git status --short
```
Expected `git status` output: only tracked files appear; no `__pycache__/` or `*.egg-info/` lines.

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: add .gitignore"
```

---

## Task 4: `normalize.py` — canonical dataclasses

**Files:**
- Create: `src/aianalyzer/normalize.py`
- Create: `tests/test_normalize.py`

The canonical types every downstream stage agrees on. Use Pydantic v2 models so we get free validation, JSON serialization, and immutability via `frozen=True`.

- [ ] **Step 1: Write the failing test**

`tests/test_normalize.py`:
```python
from datetime import datetime, timezone

from aianalyzer.normalize import (
    NormalizedSession,
    Turn,
    ToolCall,
    UserMessage,
    AssistantMessage,
)


def _ts(seconds: int) -> datetime:
    return datetime(2026, 6, 9, 10, 0, seconds, tzinfo=timezone.utc)


def test_normalized_session_round_trip():
    session = NormalizedSession(
        client="copilot-cli",
        session_id="abc123",
        started_at=_ts(0),
        ended_at=_ts(120),
        cwd="C:/work/proj",
        models_used=["claude-opus-4.7-xhigh"],
        turns=[
            Turn(
                index=0,
                user=UserMessage(content="Plan the refactor before coding.", ts=_ts(0)),
                assistant=AssistantMessage(
                    turn_id="t1",
                    content="Here is the plan...",
                    model="claude-opus-4.7-xhigh",
                    reasoning_effort="xhigh",
                    ts=_ts(5),
                ),
                tool_calls=[
                    ToolCall(
                        tool_name="view",
                        arguments={"path": "README.md"},
                        success=True,
                        duration_ms=42,
                        ts_start=_ts(6),
                        ts_end=_ts(6),
                    )
                ],
                aborted=False,
            )
        ],
    )
    payload = session.model_dump_json()
    restored = NormalizedSession.model_validate_json(payload)
    assert restored == session
    assert restored.turns[0].assistant.reasoning_effort == "xhigh"
    assert restored.turns[0].tool_calls[0].duration_ms == 42


def test_turn_rejects_negative_index():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Turn(index=-1, user=None, assistant=None, tool_calls=[], aborted=False)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_normalize.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aianalyzer.normalize'`.

- [ ] **Step 3: Write `src/aianalyzer/normalize.py`**

```python
"""Canonical data model shared by every downstream stage."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

ClientName = Literal["copilot-cli", "claude-code", "codex-cli", "vscode-copilot"]
ReasoningEffort = Optional[Literal["low", "medium", "high", "xhigh"]]


class UserMessage(BaseModel):
    model_config = ConfigDict(frozen=True)
    content: str
    ts: datetime


class AssistantMessage(BaseModel):
    model_config = ConfigDict(frozen=True)
    turn_id: str
    content: str
    model: str
    reasoning_effort: ReasoningEffort = None
    ts: datetime


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)
    tool_name: str
    arguments: dict
    success: bool
    duration_ms: int = Field(ge=0)
    ts_start: datetime
    ts_end: datetime
    error: Optional[str] = None


class Turn(BaseModel):
    model_config = ConfigDict(frozen=True)
    index: int = Field(ge=0)
    user: Optional[UserMessage]
    assistant: Optional[AssistantMessage]
    tool_calls: list[ToolCall] = Field(default_factory=list)
    aborted: bool = False


class TodoSnapshot(BaseModel):
    """A row from the Copilot CLI session.db `todos` table at session end."""
    model_config = ConfigDict(frozen=True)
    todo_id: str
    title: str
    status: str
    description: str = ""


class NormalizedSession(BaseModel):
    model_config = ConfigDict(frozen=True)
    client: ClientName
    session_id: str
    started_at: datetime
    ended_at: datetime
    cwd: Optional[str] = None
    models_used: list[str] = Field(default_factory=list)
    turns: list[Turn] = Field(default_factory=list)
    todos: list[TodoSnapshot] = Field(default_factory=list)
    raw_mtime: float = 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_normalize.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add src/aianalyzer/normalize.py tests/test_normalize.py
git commit -m "feat(normalize): add canonical session dataclasses"
```

---

## Task 5: `redact.py` — strip secrets before features run

**Files:**
- Create: `src/aianalyzer/redact.py`
- Create: `tests/test_redact.py`

Run redaction on every user and assistant message during normalization. Patterns target the things most likely to appear in coding sessions: GitHub PATs (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, `github_pat_`), bearer tokens, AWS keys, and `password=`-style assignments. Also masks email addresses.

- [ ] **Step 1: Write the failing test**

`tests/test_redact.py`:
```python
import pytest

from aianalyzer.redact import redact


@pytest.mark.parametrize(
    "raw,expected_substring",
    [
        ("My token is ghp_AAAABBBBCCCCDDDDEEEEFFFFGGGGHHHHIIII",
         "[REDACTED_GITHUB_TOKEN]"),
        ("Authorization: Bearer abcdef1234567890abcdef1234567890",
         "[REDACTED_BEARER]"),
        ("AWS_KEY=AKIAIOSFODNN7EXAMPLE", "[REDACTED_AWS_KEY]"),
        ("password=hunter2 next", "[REDACTED_PASSWORD]"),
        ("Email me at jane.doe@example.com please", "[REDACTED_EMAIL]"),
    ],
)
def test_redact_known_patterns(raw, expected_substring):
    assert expected_substring in redact(raw)


def test_redact_is_idempotent():
    text = "ghp_AAAABBBBCCCCDDDDEEEEFFFFGGGGHHHHIIII and ghp_BBBBCCCCDDDDEEEEFFFFGGGGHHHHIIIIJJJJ"
    once = redact(text)
    twice = redact(once)
    assert once == twice


def test_redact_preserves_normal_text():
    assert redact("Refactor the parser to use pathlib") == "Refactor the parser to use pathlib"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_redact.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `src/aianalyzer/redact.py`**

```python
"""Best-effort redaction of obvious secrets in session text."""
from __future__ import annotations

import re
from typing import Final

_PATTERNS: Final[list[tuple[re.Pattern[str], str]]] = [
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{20,}\b"), "Bearer [REDACTED_BEARER]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"(?i)(password|passwd|secret|api[_\-]?key)\s*=\s*\S+"),
     r"\1=[REDACTED_PASSWORD]"),
    (re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
     "[REDACTED_EMAIL]"),
]


def redact(text: str) -> str:
    """Replace obvious secrets with stable placeholders. Idempotent."""
    if not text:
        return text
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_redact.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aianalyzer/redact.py tests/test_redact.py
git commit -m "feat(redact): strip tokens, bearer auth, emails before storage"
```

---

## Task 6: `discovery.py` — find Copilot CLI session directories

**Files:**
- Create: `src/aianalyzer/discovery.py`
- Create: `tests/test_discovery.py`

Each Copilot CLI session lives in `~/.copilot/session-state/{sessionId}/` and must contain at least one of: `events.jsonl` or `session.db`. We yield `DiscoveredSession(client, session_id, root, events_path, db_path, mtime)` records and skip directories that look incomplete.

- [ ] **Step 1: Write the failing test**

`tests/test_discovery.py`:
```python
from pathlib import Path

from aianalyzer.discovery import DiscoveredSession, discover_copilot_cli_sessions


def test_discover_returns_sessions(tmp_path: Path):
    home = tmp_path / "home"
    session_root = home / ".copilot" / "session-state"

    good = session_root / "11111111-2222-3333-4444-555555555555"
    good.mkdir(parents=True)
    (good / "events.jsonl").write_text("{}\n", encoding="utf-8")
    (good / "session.db").write_bytes(b"\x00")

    no_artifacts = session_root / "deadbeef-0000-0000-0000-000000000000"
    no_artifacts.mkdir(parents=True)

    not_a_session_id = session_root / "not-a-uuid"
    not_a_session_id.mkdir(parents=True)
    (not_a_session_id / "events.jsonl").write_text("{}\n", encoding="utf-8")

    found = list(discover_copilot_cli_sessions(home=home))
    assert len(found) == 1
    only = found[0]
    assert isinstance(only, DiscoveredSession)
    assert only.session_id == "11111111-2222-3333-4444-555555555555"
    assert only.events_path.name == "events.jsonl"
    assert only.db_path is not None and only.db_path.name == "session.db"
    assert only.client == "copilot-cli"
    assert only.mtime > 0


def test_discover_missing_root_returns_empty(tmp_path: Path):
    assert list(discover_copilot_cli_sessions(home=tmp_path / "nope")) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_discovery.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `src/aianalyzer/discovery.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_discovery.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add src/aianalyzer/discovery.py tests/test_discovery.py
git commit -m "feat(discovery): locate copilot-cli session directories"
```

---

## Task 7: `collectors/base.py` — abstract collector contract

**Files:**
- Create: `src/aianalyzer/collectors/base.py`
- Create: `tests/test_collectors_base.py`
- Create: `tests/fixtures/events_minimal.jsonl`

Establish the shape every collector must satisfy: `parse(discovered) -> NormalizedSession`. Also stash a tiny `events_minimal.jsonl` fixture that downstream tasks will reuse.

- [ ] **Step 1: Create the minimal events fixture**

`tests/fixtures/events_minimal.jsonl`:
```jsonl
{"type":"session.start","ts":"2026-06-09T10:00:00Z","data":{"sessionId":"11111111-2222-3333-4444-555555555555","startTime":"2026-06-09T10:00:00Z","context":{"cwd":"C:/work/proj"},"copilotVersion":"1.0.60"}}
{"type":"session.model_change","ts":"2026-06-09T10:00:01Z","data":{"newModel":"claude-opus-4.7-xhigh","reasoningEffort":"xhigh"}}
{"type":"user.message","ts":"2026-06-09T10:00:05Z","data":{"content":"Please plan the refactor."}}
{"type":"assistant.turn_start","ts":"2026-06-09T10:00:06Z","data":{"turnId":"t-1","interactionId":"i-1"}}
{"type":"assistant.message","ts":"2026-06-09T10:00:08Z","data":{"messageId":"m-1","model":"claude-opus-4.7-xhigh","content":"Here is the plan.","toolRequests":[],"interactionId":"i-1","turnId":"t-1"}}
{"type":"assistant.turn_end","ts":"2026-06-09T10:00:09Z","data":{"turnId":"t-1"}}
```

- [ ] **Step 2: Write the failing test**

`tests/test_collectors_base.py`:
```python
from datetime import datetime, timezone
from pathlib import Path

from aianalyzer.collectors.base import Collector, iter_jsonl_events


def test_iter_jsonl_events_yields_typed_dicts(fixtures_dir: Path):
    events = list(iter_jsonl_events(fixtures_dir / "events_minimal.jsonl"))
    assert events[0]["type"] == "session.start"
    assert events[0]["ts"] == datetime(2026, 6, 9, 10, 0, 0, tzinfo=timezone.utc)
    assert events[-1]["type"] == "assistant.turn_end"
    assert len(events) == 6


def test_iter_jsonl_events_skips_blank_and_invalid_lines(tmp_path: Path):
    path = tmp_path / "evt.jsonl"
    path.write_text(
        '{"type":"a","ts":"2026-06-09T10:00:00Z","data":{}}\n'
        "\n"
        "not json\n"
        '{"type":"b","ts":"2026-06-09T10:00:01Z","data":{}}\n',
        encoding="utf-8",
    )
    types = [e["type"] for e in iter_jsonl_events(path)]
    assert types == ["a", "b"]


def test_collector_protocol_exists():
    assert hasattr(Collector, "parse")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_collectors_base.py -v`
Expected: FAIL.

- [ ] **Step 4: Write `src/aianalyzer/collectors/base.py`**

```python
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
```

- [ ] **Step 5: Verify and commit**

Run: `python -m pytest tests/test_collectors_base.py -v`
Expected: PASS.

```bash
git add src/aianalyzer/collectors/base.py tests/test_collectors_base.py tests/fixtures/events_minimal.jsonl
git commit -m "feat(collectors): add base Collector protocol + JSONL helper"
```

---

## Task 8: `copilot_cli.py` — full Copilot CLI collector

**Files:**
- Create: `src/aianalyzer/collectors/copilot_cli.py`
- Create: `tests/test_copilot_cli.py`
- Create: `tests/fixtures/session_db_sample.sql`

Walks `events.jsonl`, threading `user.message` → next `assistant.turn_start` by stream order, joining tool start/complete pairs by `toolCallId`, applying redaction on the fly. Reads the session `todos` table from `session.db` (SQLite) if present.

- [ ] **Step 1: Create the SQL fixture**

`tests/fixtures/session_db_sample.sql`:
```sql
CREATE TABLE todos (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT DEFAULT '',
  status TEXT NOT NULL,
  created_at INTEGER,
  updated_at INTEGER
);
INSERT INTO todos (id, title, description, status, created_at, updated_at)
VALUES ('todo-1', 'Plan the refactor', 'Map files first', 'done', 0, 0),
       ('todo-2', 'Implement parser', '', 'in_progress', 0, 0);
```

- [ ] **Step 2: Write the failing test**

`tests/test_copilot_cli.py`:
```python
import sqlite3
import textwrap
from pathlib import Path

from aianalyzer.collectors.copilot_cli import CopilotCliCollector
from aianalyzer.discovery import DiscoveredSession


def _bootstrap_db(db_path: Path, sql_file: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(sql_file.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def test_collector_parses_minimal_session(tmp_path: Path, fixtures_dir: Path):
    root = tmp_path / "session"
    root.mkdir()
    events = root / "events.jsonl"
    events.write_text(
        (fixtures_dir / "events_minimal.jsonl").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    db = root / "session.db"
    _bootstrap_db(db, fixtures_dir / "session_db_sample.sql")

    discovered = DiscoveredSession(
        client="copilot-cli",
        session_id="11111111-2222-3333-4444-555555555555",
        root=root,
        events_path=events,
        db_path=db,
        mtime=events.stat().st_mtime,
    )

    session = CopilotCliCollector().parse(discovered)
    assert session.client == "copilot-cli"
    assert session.session_id == "11111111-2222-3333-4444-555555555555"
    assert session.cwd == "C:/work/proj"
    assert session.models_used == ["claude-opus-4.7-xhigh"]
    assert len(session.turns) == 1
    turn = session.turns[0]
    assert turn.user.content == "Please plan the refactor."
    assert turn.assistant.content == "Here is the plan."
    assert turn.assistant.reasoning_effort == "xhigh"
    assert {t.title for t in session.todos} == {"Plan the refactor", "Implement parser"}


def test_collector_pairs_tool_start_with_complete(tmp_path: Path):
    events_text = textwrap.dedent(
        """\
        {"type":"session.start","ts":"2026-06-09T10:00:00Z","data":{"sessionId":"s","startTime":"2026-06-09T10:00:00Z","context":{"cwd":"."},"copilotVersion":"x"}}
        {"type":"user.message","ts":"2026-06-09T10:00:01Z","data":{"content":"go"}}
        {"type":"assistant.turn_start","ts":"2026-06-09T10:00:02Z","data":{"turnId":"t1","interactionId":"i1"}}
        {"type":"tool.execution_start","ts":"2026-06-09T10:00:03Z","data":{"toolCallId":"c1","toolName":"view","arguments":{"path":"README.md"},"turnId":"t1"}}
        {"type":"tool.execution_complete","ts":"2026-06-09T10:00:04Z","data":{"toolCallId":"c1","success":true,"model":"m","turnId":"t1"}}
        {"type":"assistant.message","ts":"2026-06-09T10:00:05Z","data":{"messageId":"m1","model":"m","content":"done","toolRequests":[],"turnId":"t1"}}
        {"type":"assistant.turn_end","ts":"2026-06-09T10:00:06Z","data":{"turnId":"t1"}}
        """
    )
    events = tmp_path / "events.jsonl"
    events.write_text(events_text, encoding="utf-8")
    discovered = DiscoveredSession(
        client="copilot-cli",
        session_id="s",
        root=tmp_path,
        events_path=events,
        db_path=None,
        mtime=events.stat().st_mtime,
    )
    session = CopilotCliCollector().parse(discovered)
    assert len(session.turns) == 1
    calls = session.turns[0].tool_calls
    assert len(calls) == 1
    assert calls[0].tool_name == "view"
    assert calls[0].duration_ms == 1000
    assert calls[0].success is True


def test_collector_aborted_turn_flagged(tmp_path: Path):
    events_text = textwrap.dedent(
        """\
        {"type":"session.start","ts":"2026-06-09T10:00:00Z","data":{"sessionId":"s","startTime":"2026-06-09T10:00:00Z","context":{"cwd":"."},"copilotVersion":"x"}}
        {"type":"user.message","ts":"2026-06-09T10:00:01Z","data":{"content":"go"}}
        {"type":"assistant.turn_start","ts":"2026-06-09T10:00:02Z","data":{"turnId":"t1","interactionId":"i1"}}
        {"type":"abort","ts":"2026-06-09T10:00:03Z","data":{"reason":"user_cancel"}}
        """
    )
    events = tmp_path / "events.jsonl"
    events.write_text(events_text, encoding="utf-8")
    discovered = DiscoveredSession(
        client="copilot-cli",
        session_id="s",
        root=tmp_path,
        events_path=events,
        db_path=None,
        mtime=events.stat().st_mtime,
    )
    session = CopilotCliCollector().parse(discovered)
    assert session.turns[0].aborted is True
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_copilot_cli.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Write `src/aianalyzer/collectors/copilot_cli.py`**

```python
"""Copilot CLI collector: events.jsonl + session.db -> NormalizedSession."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from aianalyzer.collectors.base import iter_jsonl_events
from aianalyzer.discovery import DiscoveredSession
from aianalyzer.normalize import (
    AssistantMessage,
    NormalizedSession,
    ToolCall,
    TodoSnapshot,
    Turn,
    UserMessage,
)
from aianalyzer.redact import redact


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class CopilotCliCollector:
    client = "copilot-cli"

    def parse(self, discovered: DiscoveredSession) -> NormalizedSession:
        events = list(iter_jsonl_events(discovered.events_path))
        if not events:
            return self._empty(discovered)

        started_at = _first_ts(events) or _EPOCH
        ended_at = _last_ts(events) or started_at
        cwd: Optional[str] = None
        models_used: list[str] = []
        turns: list[Turn] = []

        pending_user: Optional[UserMessage] = None
        current_turn_id: Optional[str] = None
        current_user: Optional[UserMessage] = None
        current_assistant: Optional[AssistantMessage] = None
        current_calls: dict[str, dict] = {}
        current_aborted = False
        turn_index = 0

        def _flush_turn() -> None:
            nonlocal current_turn_id, current_user, current_assistant, current_calls, current_aborted, turn_index
            if current_turn_id is None and current_user is None:
                return
            tool_calls = []
            for call in current_calls.values():
                if "ts_end" not in call:
                    continue
                tool_calls.append(
                    ToolCall(
                        tool_name=call["tool_name"],
                        arguments=call["arguments"],
                        success=call["success"],
                        duration_ms=int((call["ts_end"] - call["ts_start"]).total_seconds() * 1000),
                        ts_start=call["ts_start"],
                        ts_end=call["ts_end"],
                        error=call.get("error"),
                    )
                )
            turns.append(
                Turn(
                    index=turn_index,
                    user=current_user,
                    assistant=current_assistant,
                    tool_calls=tool_calls,
                    aborted=current_aborted,
                )
            )
            turn_index += 1
            current_turn_id = None
            current_user = None
            current_assistant = None
            current_calls = {}
            current_aborted = False

        for event in events:
            etype = event.get("type")
            data = event.get("data", {}) or {}
            ts = event.get("ts")

            if etype == "session.start":
                ctx = data.get("context") or {}
                cwd = ctx.get("cwd") or cwd
            elif etype == "session.model_change":
                model = data.get("newModel")
                if model and model not in models_used:
                    models_used.append(model)
            elif etype == "user.message":
                content = redact(data.get("content") or "")
                pending_user = UserMessage(content=content, ts=ts)
            elif etype == "assistant.turn_start":
                if current_turn_id is not None:
                    _flush_turn()
                current_turn_id = data.get("turnId")
                current_user = pending_user
                pending_user = None
            elif etype == "assistant.message":
                model = data.get("model") or ""
                if model and model not in models_used:
                    models_used.append(model)
                current_assistant = AssistantMessage(
                    turn_id=str(data.get("turnId") or current_turn_id or ""),
                    content=redact(data.get("content") or ""),
                    model=model,
                    reasoning_effort=_reasoning_effort_for(events, model),
                    ts=ts,
                )
            elif etype == "tool.execution_start":
                call_id = data.get("toolCallId")
                if not call_id:
                    continue
                current_calls[call_id] = {
                    "tool_name": data.get("toolName") or "unknown",
                    "arguments": data.get("arguments") or {},
                    "ts_start": ts,
                }
            elif etype == "tool.execution_complete":
                call_id = data.get("toolCallId")
                if not call_id or call_id not in current_calls:
                    continue
                call = current_calls[call_id]
                call["ts_end"] = ts
                call["success"] = bool(data.get("success"))
                call["error"] = data.get("error")
            elif etype == "abort":
                current_aborted = True
                _flush_turn()
            elif etype == "assistant.turn_end":
                _flush_turn()

        if current_turn_id is not None or current_user is not None:
            _flush_turn()

        todos = _read_todos(discovered.db_path)

        return NormalizedSession(
            client="copilot-cli",
            session_id=discovered.session_id,
            started_at=started_at,
            ended_at=ended_at,
            cwd=cwd,
            models_used=models_used,
            turns=turns,
            todos=todos,
            raw_mtime=discovered.mtime,
        )

    def _empty(self, d: DiscoveredSession) -> NormalizedSession:
        return NormalizedSession(
            client="copilot-cli",
            session_id=d.session_id,
            started_at=_EPOCH,
            ended_at=_EPOCH,
            raw_mtime=d.mtime,
        )


def _first_ts(events: list[dict]):
    for e in events:
        ts = e.get("ts")
        if isinstance(ts, datetime):
            return ts
    return None


def _last_ts(events: list[dict]):
    for e in reversed(events):
        ts = e.get("ts")
        if isinstance(ts, datetime):
            return ts
    return None


def _reasoning_effort_for(events: list[dict], model: str):
    """Return the most recent reasoning effort applicable to `model`."""
    last_effort = None
    for e in events:
        if e.get("type") == "session.model_change":
            data = e.get("data") or {}
            if data.get("newModel") == model or model == "":
                effort = data.get("reasoningEffort")
                if effort in {"low", "medium", "high", "xhigh"}:
                    last_effort = effort
    return last_effort


def _read_todos(db_path: Optional[Path]) -> list[TodoSnapshot]:
    if not db_path or not db_path.is_file():
        return []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return []
    try:
        cur = conn.execute("SELECT id, title, status, COALESCE(description, '') FROM todos")
        return [
            TodoSnapshot(todo_id=row[0], title=row[1], status=row[2], description=row[3])
            for row in cur.fetchall()
        ]
    except sqlite3.DatabaseError:
        return []
    finally:
        conn.close()
```

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/test_copilot_cli.py -v`
Expected: PASS (3 tests).

```bash
git add src/aianalyzer/collectors/copilot_cli.py tests/test_copilot_cli.py tests/fixtures/session_db_sample.sql
git commit -m "feat(collectors): full copilot-cli events + todos parser"
```

---

## Task 9: `features.py` — text signals (S1, S2, S3, S9, S17)

**Files:**
- Create: `src/aianalyzer/features.py`
- Create: `tests/test_features_text.py`
- Create: `tests/fixtures/events_planner.jsonl`

Introduces the `SessionFeatures` model with **all 18 signal fields defined upfront** (Tasks 10–11 will populate the remaining ones — leaving defaults at `0` here makes that incremental and keeps types stable across tasks). This task implements:

| Signal | Field | Definition |
| --- | --- | --- |
| S1 | `avg_user_msg_chars` | mean character length of user messages |
| S2 | `planning_language_ratio` | fraction of user messages containing a planning keyword (plan, design, approach, options, tradeoff, before we code, first, propose, outline, architecture) |
| S3 | `question_ratio` | fraction of user messages containing `?` or starting with a question word (what, why, how, when, which, where, who, can, could, should, would) |
| S9 | `thinks_before_prompt_sec_avg` | mean seconds between previous `assistant.turn_end` and next `user.message` (`Turn[i+1].user.ts − Turn[i].assistant.ts`) |
| S17 | `test_or_spec_mention_rate` | fraction of user messages mentioning "test", "spec", "tdd", "pytest", "unit test", or "fixture" |

- [ ] **Step 1: Add a richer planner fixture**

`tests/fixtures/events_planner.jsonl`:
```jsonl
{"type":"session.start","ts":"2026-06-09T10:00:00Z","data":{"sessionId":"sp","startTime":"2026-06-09T10:00:00Z","context":{"cwd":"C:/w"},"copilotVersion":"x"}}
{"type":"user.message","ts":"2026-06-09T10:00:05Z","data":{"content":"Before we code, please plan the architecture and outline tradeoffs."}}
{"type":"assistant.turn_start","ts":"2026-06-09T10:00:06Z","data":{"turnId":"t1","interactionId":"i1"}}
{"type":"assistant.message","ts":"2026-06-09T10:00:08Z","data":{"messageId":"m1","model":"m","content":"Plan...","toolRequests":[],"turnId":"t1"}}
{"type":"assistant.turn_end","ts":"2026-06-09T10:00:10Z","data":{"turnId":"t1"}}
{"type":"user.message","ts":"2026-06-09T10:00:30Z","data":{"content":"What tests should we write first? Add pytest fixtures for the parser."}}
{"type":"assistant.turn_start","ts":"2026-06-09T10:00:31Z","data":{"turnId":"t2","interactionId":"i2"}}
{"type":"assistant.message","ts":"2026-06-09T10:00:33Z","data":{"messageId":"m2","model":"m","content":"Tests...","toolRequests":[],"turnId":"t2"}}
{"type":"assistant.turn_end","ts":"2026-06-09T10:00:34Z","data":{"turnId":"t2"}}
{"type":"user.message","ts":"2026-06-09T10:00:50Z","data":{"content":"Proceed."}}
{"type":"assistant.turn_start","ts":"2026-06-09T10:00:51Z","data":{"turnId":"t3","interactionId":"i3"}}
{"type":"assistant.message","ts":"2026-06-09T10:00:52Z","data":{"messageId":"m3","model":"m","content":"OK","toolRequests":[],"turnId":"t3"}}
{"type":"assistant.turn_end","ts":"2026-06-09T10:00:53Z","data":{"turnId":"t3"}}
```

- [ ] **Step 2: Write the failing test**

`tests/test_features_text.py`:
```python
from pathlib import Path

from aianalyzer.collectors.copilot_cli import CopilotCliCollector
from aianalyzer.discovery import DiscoveredSession
from aianalyzer.features import SessionFeatures, extract_session_features


def _parse(fixtures_dir: Path, name: str) -> SessionFeatures:
    src = fixtures_dir / name
    discovered = DiscoveredSession(
        client="copilot-cli",
        session_id="sp",
        root=src.parent,
        events_path=src,
        db_path=None,
        mtime=src.stat().st_mtime,
    )
    session = CopilotCliCollector().parse(discovered)
    return extract_session_features(session)


def test_text_signals_for_planner_session(fixtures_dir: Path):
    f = _parse(fixtures_dir, "events_planner.jsonl")

    assert isinstance(f, SessionFeatures)
    assert f.session_id == "sp"
    assert f.turn_count == 3
    # S1: messages = [73 chars, 64 chars, 8 chars] -> mean ~ 48-50
    assert 40 <= f.avg_user_msg_chars <= 60
    # S2: 1 of 3 messages contains a planning keyword (the first) -> 1/3
    assert abs(f.planning_language_ratio - (1 / 3)) < 1e-6
    # S3: question_ratio: m2 contains '?' and starts with "What" -> 1/3
    assert abs(f.question_ratio - (1 / 3)) < 1e-6
    # S9: gaps are (30 - 10) and (50 - 34) -> mean 18s
    assert abs(f.thinks_before_prompt_sec_avg - 18.0) < 1e-6
    # S17: m2 mentions test/pytest/fixture -> 1/3
    assert abs(f.test_or_spec_mention_rate - (1 / 3)) < 1e-6


def test_all_signal_fields_defined():
    expected_fields = {
        "session_id", "client", "started_at", "turn_count",
        "avg_user_msg_chars", "planning_language_ratio", "question_ratio",
        "tool_diversity", "accept_and_go_ratio", "revision_depth",
        "session_duration_sec", "tool_error_rate",
        "thinks_before_prompt_sec_avg", "edited_files_per_turn_avg",
        "model_variety", "reasoning_effort_distribution",
        "cwd_switch_count", "command_repetition_rate",
        "todo_count", "abort_rate",
        "test_or_spec_mention_rate", "parallel_tool_call_rate",
    }
    assert set(SessionFeatures.model_fields.keys()) == expected_fields
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_features_text.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Write `src/aianalyzer/features.py`**

```python
"""Per-session feature extraction. All 18 signals from DESIGN.md §6."""
from __future__ import annotations

import re
from datetime import datetime
from statistics import mean
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from aianalyzer.normalize import NormalizedSession, Turn

_PLANNING_TOKENS = (
    "plan", "design", "approach", "options", "tradeoff", "before we code",
    "first", "propose", "outline", "architecture",
)
_QUESTION_PREFIXES = (
    "what", "why", "how", "when", "which", "where", "who",
    "can", "could", "should", "would",
)
_TEST_TOKENS = ("test", "spec", "tdd", "pytest", "unit test", "fixture")


class SessionFeatures(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    client: str
    started_at: datetime
    turn_count: int = 0

    # Text signals (Task 9)
    avg_user_msg_chars: float = 0.0
    planning_language_ratio: float = 0.0
    question_ratio: float = 0.0
    thinks_before_prompt_sec_avg: float = 0.0
    test_or_spec_mention_rate: float = 0.0

    # Turn/tool signals (Task 10)
    tool_diversity: float = 0.0
    accept_and_go_ratio: float = 0.0
    revision_depth: float = 0.0
    session_duration_sec: float = 0.0
    tool_error_rate: float = 0.0
    edited_files_per_turn_avg: float = 0.0
    parallel_tool_call_rate: float = 0.0

    # Meta signals (Task 11)
    model_variety: int = 0
    reasoning_effort_distribution: dict[str, float] = Field(default_factory=dict)
    cwd_switch_count: int = 0
    command_repetition_rate: float = 0.0
    todo_count: int = 0
    abort_rate: float = 0.0


def _user_messages(turns: Iterable[Turn]) -> list[str]:
    return [t.user.content for t in turns if t.user is not None]


def _contains_any(text: str, tokens: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(tok in lowered for tok in tokens)


def _starts_with_question_word(text: str) -> bool:
    first = text.lstrip().split()
    if not first:
        return False
    return first[0].lower().rstrip(",.?!") in _QUESTION_PREFIXES


def _avg(values: list[float]) -> float:
    return float(mean(values)) if values else 0.0


def extract_session_features(session: NormalizedSession) -> SessionFeatures:
    turns = session.turns
    user_msgs = _user_messages(turns)

    # S1
    avg_chars = _avg([float(len(m)) for m in user_msgs])
    # S2
    planning = _avg([1.0 if _contains_any(m, _PLANNING_TOKENS) else 0.0 for m in user_msgs])
    # S3
    question = _avg([
        1.0 if ("?" in m or _starts_with_question_word(m)) else 0.0 for m in user_msgs
    ])
    # S17
    test_mention = _avg([1.0 if _contains_any(m, _TEST_TOKENS) else 0.0 for m in user_msgs])
    # S9
    gaps: list[float] = []
    for prev, nxt in zip(turns, turns[1:]):
        if prev.assistant and nxt.user:
            gaps.append((nxt.user.ts - prev.assistant.ts).total_seconds())
    thinks_avg = _avg(gaps)

    return SessionFeatures(
        session_id=session.session_id,
        client=session.client,
        started_at=session.started_at,
        turn_count=len(turns),
        avg_user_msg_chars=avg_chars,
        planning_language_ratio=planning,
        question_ratio=question,
        thinks_before_prompt_sec_avg=thinks_avg,
        test_or_spec_mention_rate=test_mention,
    )
```

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/test_features_text.py -v`
Expected: PASS (2 tests).

```bash
git add src/aianalyzer/features.py tests/test_features_text.py tests/fixtures/events_planner.jsonl
git commit -m "feat(features): text signals S1, S2, S3, S9, S17"
```

---

## Task 10: `features.py` — turn/tool signals (S4, S5, S6, S7, S8, S10, S18)

**Files:**
- Modify: `src/aianalyzer/features.py`
- Create: `tests/test_features_turn_tool.py`
- Create: `tests/fixtures/events_vibe.jsonl`

Adds:

| Signal | Field | Definition |
| --- | --- | --- |
| S4 | `tool_diversity` | Shannon entropy (natural log) of tool-name distribution across all `ToolCall`s in the session |
| S5 | `accept_and_go_ratio` | fraction of turns whose user content is one of {"yes", "ok", "go", "proceed", "continue", "do it", "ship it", "sounds good", "looks good", "lgtm"} (case-insensitive, stripped of punctuation) |
| S6 | `revision_depth` | mean tool calls per turn (`total_tool_calls / turn_count`) |
| S7 | `session_duration_sec` | `(ended_at − started_at).total_seconds()` |
| S8 | `tool_error_rate` | fraction of tool calls with `success=False` |
| S10 | `edited_files_per_turn_avg` | mean distinct paths touched per turn by tools whose name is in `{"edit", "create", "write"}`; the path is read from `arguments["path"]` |
| S18 | `parallel_tool_call_rate` | fraction of turns with more than one tool call |

- [ ] **Step 1: Add a "vibe coder" fixture**

`tests/fixtures/events_vibe.jsonl`:
```jsonl
{"type":"session.start","ts":"2026-06-09T11:00:00Z","data":{"sessionId":"vibe","startTime":"2026-06-09T11:00:00Z","context":{"cwd":"C:/v"},"copilotVersion":"x"}}
{"type":"user.message","ts":"2026-06-09T11:00:01Z","data":{"content":"build me a todo app"}}
{"type":"assistant.turn_start","ts":"2026-06-09T11:00:02Z","data":{"turnId":"t1","interactionId":"i1"}}
{"type":"tool.execution_start","ts":"2026-06-09T11:00:03Z","data":{"toolCallId":"c1","toolName":"create","arguments":{"path":"app.py"},"turnId":"t1"}}
{"type":"tool.execution_complete","ts":"2026-06-09T11:00:04Z","data":{"toolCallId":"c1","success":true,"model":"m","turnId":"t1"}}
{"type":"tool.execution_start","ts":"2026-06-09T11:00:04Z","data":{"toolCallId":"c2","toolName":"create","arguments":{"path":"requirements.txt"},"turnId":"t1"}}
{"type":"tool.execution_complete","ts":"2026-06-09T11:00:05Z","data":{"toolCallId":"c2","success":true,"model":"m","turnId":"t1"}}
{"type":"assistant.message","ts":"2026-06-09T11:00:06Z","data":{"messageId":"m1","model":"m","content":"done","toolRequests":[],"turnId":"t1"}}
{"type":"assistant.turn_end","ts":"2026-06-09T11:00:07Z","data":{"turnId":"t1"}}
{"type":"user.message","ts":"2026-06-09T11:00:10Z","data":{"content":"ok"}}
{"type":"assistant.turn_start","ts":"2026-06-09T11:00:11Z","data":{"turnId":"t2","interactionId":"i2"}}
{"type":"tool.execution_start","ts":"2026-06-09T11:00:12Z","data":{"toolCallId":"c3","toolName":"powershell","arguments":{"command":"python app.py"},"turnId":"t2"}}
{"type":"tool.execution_complete","ts":"2026-06-09T11:00:13Z","data":{"toolCallId":"c3","success":false,"error":"boom","model":"m","turnId":"t2"}}
{"type":"assistant.message","ts":"2026-06-09T11:00:14Z","data":{"messageId":"m2","model":"m","content":"fix?","toolRequests":[],"turnId":"t2"}}
{"type":"assistant.turn_end","ts":"2026-06-09T11:00:15Z","data":{"turnId":"t2"}}
{"type":"user.message","ts":"2026-06-09T11:00:20Z","data":{"content":"go"}}
{"type":"assistant.turn_start","ts":"2026-06-09T11:00:21Z","data":{"turnId":"t3","interactionId":"i3"}}
{"type":"tool.execution_start","ts":"2026-06-09T11:00:22Z","data":{"toolCallId":"c4","toolName":"edit","arguments":{"path":"app.py"},"turnId":"t3"}}
{"type":"tool.execution_complete","ts":"2026-06-09T11:00:23Z","data":{"toolCallId":"c4","success":true,"model":"m","turnId":"t3"}}
{"type":"assistant.message","ts":"2026-06-09T11:00:24Z","data":{"messageId":"m3","model":"m","content":"done","toolRequests":[],"turnId":"t3"}}
{"type":"assistant.turn_end","ts":"2026-06-09T11:00:25Z","data":{"turnId":"t3"}}
```

- [ ] **Step 2: Write the failing test**

`tests/test_features_turn_tool.py`:
```python
import math
from pathlib import Path

from aianalyzer.collectors.copilot_cli import CopilotCliCollector
from aianalyzer.discovery import DiscoveredSession
from aianalyzer.features import extract_session_features


def _features(fixtures_dir: Path, name: str):
    src = fixtures_dir / name
    discovered = DiscoveredSession(
        client="copilot-cli",
        session_id="vibe",
        root=src.parent,
        events_path=src,
        db_path=None,
        mtime=src.stat().st_mtime,
    )
    return extract_session_features(CopilotCliCollector().parse(discovered))


def test_turn_tool_signals_for_vibe_session(fixtures_dir: Path):
    f = _features(fixtures_dir, "events_vibe.jsonl")

    # 4 tool calls total: create, create, powershell, edit
    # distribution: create=2/4, powershell=1/4, edit=1/4
    # entropy = -(0.5*ln 0.5 + 0.25*ln 0.25 + 0.25*ln 0.25)
    expected_entropy = -(0.5 * math.log(0.5) + 0.25 * math.log(0.25) * 2)
    assert abs(f.tool_diversity - expected_entropy) < 1e-6

    # accept-and-go: messages = ["build me a todo app", "ok", "go"] -> 2/3
    assert abs(f.accept_and_go_ratio - (2 / 3)) < 1e-6

    # revision depth: 4 calls / 3 turns
    assert abs(f.revision_depth - (4 / 3)) < 1e-6

    # session duration: 11:00:25 - 11:00:00 = 25s
    assert f.session_duration_sec == 25.0

    # tool error rate: 1 of 4 calls failed
    assert abs(f.tool_error_rate - 0.25) < 1e-6

    # edited files per turn: t1 -> 2 (app.py, requirements.txt), t2 -> 0, t3 -> 1 (app.py)
    # mean = (2 + 0 + 1) / 3 = 1.0
    assert abs(f.edited_files_per_turn_avg - 1.0) < 1e-6

    # parallel tool calls: t1 has 2 calls (parallel), t2 and t3 have 1 each -> 1/3
    assert abs(f.parallel_tool_call_rate - (1 / 3)) < 1e-6
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_features_turn_tool.py -v`
Expected: FAIL (all assertions miss because fields are 0.0).

- [ ] **Step 4: Extend `src/aianalyzer/features.py`**

Add the constants and helpers at the top (just below `_TEST_TOKENS`):

```python
import math
from collections import Counter

_ACCEPT_TOKENS = {
    "yes", "ok", "okay", "go", "proceed", "continue",
    "do it", "ship it", "sounds good", "looks good", "lgtm",
}
_EDIT_TOOL_NAMES = {"edit", "create", "write"}
```

Add these helper functions below `_avg`:

```python
def _shannon_entropy(counts: list[int]) -> float:
    total = sum(counts)
    if total == 0:
        return 0.0
    entropy = 0.0
    for c in counts:
        if c == 0:
            continue
        p = c / total
        entropy -= p * math.log(p)
    return entropy


def _is_accept_and_go(text: str) -> bool:
    stripped = text.strip().lower().rstrip(".!?,")
    return stripped in _ACCEPT_TOKENS
```

Replace the body of `extract_session_features` to compute and pass the new fields. Replace the entire function (keep the existing return arguments and add the new ones):

```python
def extract_session_features(session: NormalizedSession) -> SessionFeatures:
    turns = session.turns
    user_msgs = _user_messages(turns)

    avg_chars = _avg([float(len(m)) for m in user_msgs])
    planning = _avg([1.0 if _contains_any(m, _PLANNING_TOKENS) else 0.0 for m in user_msgs])
    question = _avg([
        1.0 if ("?" in m or _starts_with_question_word(m)) else 0.0 for m in user_msgs
    ])
    test_mention = _avg([1.0 if _contains_any(m, _TEST_TOKENS) else 0.0 for m in user_msgs])

    gaps: list[float] = []
    for prev, nxt in zip(turns, turns[1:]):
        if prev.assistant and nxt.user:
            gaps.append((nxt.user.ts - prev.assistant.ts).total_seconds())
    thinks_avg = _avg(gaps)

    all_tool_calls = [c for t in turns for c in t.tool_calls]
    tool_name_counts = Counter(c.tool_name for c in all_tool_calls)
    tool_diversity = _shannon_entropy(list(tool_name_counts.values()))

    accept_and_go = _avg([1.0 if (t.user and _is_accept_and_go(t.user.content)) else 0.0 for t in turns])
    revision_depth = (len(all_tool_calls) / len(turns)) if turns else 0.0
    duration = (session.ended_at - session.started_at).total_seconds()
    tool_error_rate = (
        sum(1 for c in all_tool_calls if not c.success) / len(all_tool_calls)
        if all_tool_calls else 0.0
    )

    edited_per_turn: list[float] = []
    for t in turns:
        paths = {
            str(c.arguments.get("path"))
            for c in t.tool_calls
            if c.tool_name in _EDIT_TOOL_NAMES and c.arguments.get("path")
        }
        edited_per_turn.append(float(len(paths)))
    edited_avg = _avg(edited_per_turn) if turns else 0.0

    parallel_rate = (
        sum(1 for t in turns if len(t.tool_calls) > 1) / len(turns)
        if turns else 0.0
    )

    return SessionFeatures(
        session_id=session.session_id,
        client=session.client,
        started_at=session.started_at,
        turn_count=len(turns),
        avg_user_msg_chars=avg_chars,
        planning_language_ratio=planning,
        question_ratio=question,
        thinks_before_prompt_sec_avg=thinks_avg,
        test_or_spec_mention_rate=test_mention,
        tool_diversity=tool_diversity,
        accept_and_go_ratio=accept_and_go,
        revision_depth=revision_depth,
        session_duration_sec=duration,
        tool_error_rate=tool_error_rate,
        edited_files_per_turn_avg=edited_avg,
        parallel_tool_call_rate=parallel_rate,
    )
```

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/test_features_text.py tests/test_features_turn_tool.py -v`
Expected: PASS (both files; older text tests must still pass).

```bash
git add src/aianalyzer/features.py tests/test_features_turn_tool.py tests/fixtures/events_vibe.jsonl
git commit -m "feat(features): turn & tool signals S4-S8, S10, S18"
```

---

## Task 11: `features.py` — meta signals (S11, S12, S13, S14, S15, S16)

**Files:**
- Modify: `src/aianalyzer/features.py`
- Create: `tests/test_features_meta.py`

Adds:

| Signal | Field | Definition |
| --- | --- | --- |
| S11 | `model_variety` | `len(session.models_used)` (count of distinct models) |
| S12 | `reasoning_effort_distribution` | `{effort_label: fraction_of_assistant_messages}` for each non-null `assistant.reasoning_effort`; effort labels are `"low" \| "medium" \| "high" \| "xhigh"`. Empty dict when no labels. |
| S13 | `cwd_switch_count` | always `0` per-session (cwd switches are detected across sessions in `UserProfile`); kept as a field for parity |
| S14 | `command_repetition_rate` | for tool calls whose `tool_name == "powershell"`, fraction whose `arguments["command"]` exactly matches another command in the same session. `0.0` if fewer than 2 powershell calls. |
| S15 | `todo_count` | `len(session.todos)` |
| S16 | `abort_rate` | fraction of turns with `aborted=True` |

- [ ] **Step 1: Write the failing test**

`tests/test_features_meta.py`:
```python
from datetime import datetime, timezone

from aianalyzer.features import extract_session_features
from aianalyzer.normalize import (
    AssistantMessage,
    NormalizedSession,
    TodoSnapshot,
    ToolCall,
    Turn,
    UserMessage,
)


def _ts(seconds: int):
    return datetime(2026, 6, 9, 12, 0, seconds, tzinfo=timezone.utc)


def test_meta_signals():
    session = NormalizedSession(
        client="copilot-cli",
        session_id="meta-1",
        started_at=_ts(0),
        ended_at=_ts(60),
        cwd="C:/x",
        models_used=["claude-opus-4.7-xhigh", "gpt-5-mini"],
        turns=[
            Turn(
                index=0,
                user=UserMessage(content="hi", ts=_ts(1)),
                assistant=AssistantMessage(
                    turn_id="t1", content="ok", model="claude-opus-4.7-xhigh",
                    reasoning_effort="xhigh", ts=_ts(2),
                ),
                tool_calls=[
                    ToolCall(tool_name="powershell", arguments={"command": "ls"},
                             success=True, duration_ms=10, ts_start=_ts(3), ts_end=_ts(3)),
                    ToolCall(tool_name="powershell", arguments={"command": "ls"},
                             success=True, duration_ms=10, ts_start=_ts(4), ts_end=_ts(4)),
                    ToolCall(tool_name="powershell", arguments={"command": "pwd"},
                             success=True, duration_ms=10, ts_start=_ts(5), ts_end=_ts(5)),
                ],
                aborted=False,
            ),
            Turn(
                index=1,
                user=UserMessage(content="more", ts=_ts(10)),
                assistant=AssistantMessage(
                    turn_id="t2", content="ok", model="gpt-5-mini",
                    reasoning_effort=None, ts=_ts(11),
                ),
                tool_calls=[],
                aborted=True,
            ),
        ],
        todos=[
            TodoSnapshot(todo_id="d1", title="Plan", status="done"),
            TodoSnapshot(todo_id="d2", title="Build", status="pending"),
        ],
    )

    f = extract_session_features(session)

    assert f.model_variety == 2
    # 1 of 2 assistant messages has a reasoning_effort label
    assert f.reasoning_effort_distribution == {"xhigh": 1.0}
    assert f.cwd_switch_count == 0
    # 3 powershell calls; 2 ('ls') repeat -> 2/3
    assert abs(f.command_repetition_rate - (2 / 3)) < 1e-6
    assert f.todo_count == 2
    # 1 of 2 turns aborted
    assert f.abort_rate == 0.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_features_meta.py -v`
Expected: FAIL (defaults are 0/{}).

- [ ] **Step 3: Extend the body of `extract_session_features`**

Compute the meta signals and pass them to `SessionFeatures(...)`. Add these blocks above the `return SessionFeatures(...)`:

```python
    model_variety = len(session.models_used)

    efforts = [
        t.assistant.reasoning_effort
        for t in turns
        if t.assistant and t.assistant.reasoning_effort
    ]
    if efforts:
        counts = Counter(efforts)
        total = sum(counts.values())
        reasoning_distribution = {k: v / total for k, v in counts.items()}
    else:
        reasoning_distribution = {}

    powershell_cmds = [
        str(c.arguments.get("command"))
        for c in all_tool_calls
        if c.tool_name == "powershell" and c.arguments.get("command") is not None
    ]
    if len(powershell_cmds) >= 2:
        cmd_counts = Counter(powershell_cmds)
        repeats = sum(c for c in cmd_counts.values() if c > 1)
        command_repetition = repeats / len(powershell_cmds)
    else:
        command_repetition = 0.0

    todo_count = len(session.todos)
    abort_rate = _avg([1.0 if t.aborted else 0.0 for t in turns])
```

Then extend the `return SessionFeatures(...)` call with:

```python
        model_variety=model_variety,
        reasoning_effort_distribution=reasoning_distribution,
        cwd_switch_count=0,
        command_repetition_rate=command_repetition,
        todo_count=todo_count,
        abort_rate=abort_rate,
```

- [ ] **Step 4: Run tests and verify nothing regressed**

Run: `python -m pytest tests/test_features_text.py tests/test_features_turn_tool.py tests/test_features_meta.py -v`
Expected: PASS (all three test files).

- [ ] **Step 5: Commit**

```bash
git add src/aianalyzer/features.py tests/test_features_meta.py
git commit -m "feat(features): meta signals S11-S16"
```

---

## Task 12: `features.py` — `UserProfile` aggregator

**Files:**
- Modify: `src/aianalyzer/features.py`
- Create: `tests/test_features_profile.py`

A `UserProfile` summarizes many sessions: it averages each scalar feature (weighted by `turn_count`), totals integer counts (`todo_count`, `model_variety` becomes `distinct_models_total`), and computes the across-session `cwd_switch_count` (distinct `cwd` values across sessions, minus 1, floor 0).

- [ ] **Step 1: Write the failing test**

`tests/test_features_profile.py`:
```python
from datetime import datetime, timezone

from aianalyzer.features import (
    SessionFeatures,
    UserProfile,
    aggregate_user_profile,
)


def _sf(**overrides):
    base = dict(
        session_id="s",
        client="copilot-cli",
        started_at=datetime(2026, 6, 9, tzinfo=timezone.utc),
        turn_count=1,
    )
    base.update(overrides)
    return SessionFeatures(**base)


def test_aggregate_weighted_by_turn_count():
    a = _sf(session_id="a", turn_count=10, avg_user_msg_chars=100.0,
            planning_language_ratio=0.0, todo_count=2, model_variety=1)
    b = _sf(session_id="b", turn_count=30, avg_user_msg_chars=50.0,
            planning_language_ratio=0.5, todo_count=1, model_variety=2)

    profile = aggregate_user_profile([a, b], cwd_history=["C:/p1", "C:/p1", "C:/p2"])

    assert isinstance(profile, UserProfile)
    assert profile.session_count == 2
    assert profile.total_turns == 40
    # weighted mean: (100*10 + 50*30)/40 = 62.5
    assert profile.avg_user_msg_chars == 62.5
    # weighted: (0.0*10 + 0.5*30)/40 = 0.375
    assert profile.planning_language_ratio == 0.375
    assert profile.total_todos == 3
    assert profile.distinct_models_total == 2  # max across sessions; conservative
    # 2 distinct cwds -> 1 switch
    assert profile.cwd_switch_count == 1


def test_aggregate_empty_input():
    profile = aggregate_user_profile([], cwd_history=[])
    assert profile.session_count == 0
    assert profile.total_turns == 0
    assert profile.avg_user_msg_chars == 0.0
    assert profile.cwd_switch_count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_features_profile.py -v`
Expected: FAIL (`UserProfile` / `aggregate_user_profile` not defined).

- [ ] **Step 3: Extend `src/aianalyzer/features.py`**

Add at the bottom of the file:

```python
class UserProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_count: int = 0
    total_turns: int = 0
    total_todos: int = 0
    distinct_models_total: int = 0
    cwd_switch_count: int = 0

    avg_user_msg_chars: float = 0.0
    planning_language_ratio: float = 0.0
    question_ratio: float = 0.0
    thinks_before_prompt_sec_avg: float = 0.0
    test_or_spec_mention_rate: float = 0.0
    tool_diversity: float = 0.0
    accept_and_go_ratio: float = 0.0
    revision_depth: float = 0.0
    session_duration_sec: float = 0.0
    tool_error_rate: float = 0.0
    edited_files_per_turn_avg: float = 0.0
    parallel_tool_call_rate: float = 0.0
    abort_rate: float = 0.0
    reasoning_effort_distribution: dict[str, float] = Field(default_factory=dict)


_WEIGHTED_SCALARS = (
    "avg_user_msg_chars",
    "planning_language_ratio",
    "question_ratio",
    "thinks_before_prompt_sec_avg",
    "test_or_spec_mention_rate",
    "tool_diversity",
    "accept_and_go_ratio",
    "revision_depth",
    "session_duration_sec",
    "tool_error_rate",
    "edited_files_per_turn_avg",
    "parallel_tool_call_rate",
    "abort_rate",
)


def aggregate_user_profile(
    features: list[SessionFeatures],
    cwd_history: list[str | None],
) -> UserProfile:
    if not features:
        return UserProfile()

    total_turns = sum(f.turn_count for f in features) or 1
    weighted: dict[str, float] = {}
    for field in _WEIGHTED_SCALARS:
        weighted[field] = sum(getattr(f, field) * f.turn_count for f in features) / total_turns

    merged_efforts: Counter[str] = Counter()
    for f in features:
        for k, v in f.reasoning_effort_distribution.items():
            merged_efforts[k] += v * f.turn_count
    if merged_efforts:
        s = sum(merged_efforts.values())
        merged_distribution = {k: v / s for k, v in merged_efforts.items()}
    else:
        merged_distribution = {}

    distinct_cwds = {c for c in cwd_history if c}
    cwd_switches = max(len(distinct_cwds) - 1, 0)

    return UserProfile(
        session_count=len(features),
        total_turns=sum(f.turn_count for f in features),
        total_todos=sum(f.todo_count for f in features),
        distinct_models_total=max((f.model_variety for f in features), default=0),
        cwd_switch_count=cwd_switches,
        reasoning_effort_distribution=merged_distribution,
        **weighted,
    )
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_features_profile.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add src/aianalyzer/features.py tests/test_features_profile.py
git commit -m "feat(features): UserProfile weighted aggregator"
```

---

## Task 13: `store.py` — DuckDB feature cache

**Files:**
- Create: `src/aianalyzer/store.py`
- Create: `tests/test_store.py`

Persists `SessionFeatures` JSON to a single DuckDB database, keyed on `(client, session_id, mtime)` so re-scans skip unchanged sessions. Schema:

```
CREATE TABLE IF NOT EXISTS features (
  client      VARCHAR NOT NULL,
  session_id  VARCHAR NOT NULL,
  mtime       DOUBLE  NOT NULL,
  json        VARCHAR NOT NULL,
  PRIMARY KEY (client, session_id)
);
```

`upsert` deletes any existing row for the `(client, session_id)` pair, then inserts the new one. `has_fresh` returns True when a row exists with `mtime >= given_mtime`. `load_all` returns all rows as `SessionFeatures` instances.

- [ ] **Step 1: Write the failing test**

`tests/test_store.py`:
```python
from datetime import datetime, timezone
from pathlib import Path

from aianalyzer.features import SessionFeatures
from aianalyzer.store import FeatureStore


def _sf(session_id: str, turn_count: int = 1) -> SessionFeatures:
    return SessionFeatures(
        session_id=session_id,
        client="copilot-cli",
        started_at=datetime(2026, 6, 9, tzinfo=timezone.utc),
        turn_count=turn_count,
    )


def test_upsert_and_load_roundtrip(tmp_path: Path):
    store = FeatureStore(tmp_path / "cache.duckdb")
    store.upsert(_sf("a"), mtime=1.0)
    store.upsert(_sf("b", turn_count=5), mtime=2.0)

    loaded = sorted(store.load_all(), key=lambda f: f.session_id)
    assert [f.session_id for f in loaded] == ["a", "b"]
    assert loaded[1].turn_count == 5


def test_upsert_replaces_existing(tmp_path: Path):
    store = FeatureStore(tmp_path / "cache.duckdb")
    store.upsert(_sf("a", turn_count=1), mtime=1.0)
    store.upsert(_sf("a", turn_count=99), mtime=2.0)

    rows = list(store.load_all())
    assert len(rows) == 1
    assert rows[0].turn_count == 99


def test_has_fresh(tmp_path: Path):
    store = FeatureStore(tmp_path / "cache.duckdb")
    assert store.has_fresh("copilot-cli", "a", mtime=10.0) is False
    store.upsert(_sf("a"), mtime=10.0)
    assert store.has_fresh("copilot-cli", "a", mtime=10.0) is True
    assert store.has_fresh("copilot-cli", "a", mtime=11.0) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_store.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `src/aianalyzer/store.py`**

```python
"""DuckDB cache for SessionFeatures."""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

import duckdb

from aianalyzer.features import SessionFeatures


class FeatureStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(str(self.db_path))
        self._con.execute(
            """
            CREATE TABLE IF NOT EXISTS features (
                client      VARCHAR NOT NULL,
                session_id  VARCHAR NOT NULL,
                mtime       DOUBLE  NOT NULL,
                json        VARCHAR NOT NULL,
                PRIMARY KEY (client, session_id)
            )
            """
        )

    def has_fresh(self, client: str, session_id: str, mtime: float) -> bool:
        row = self._con.execute(
            "SELECT mtime FROM features WHERE client = ? AND session_id = ?",
            [client, session_id],
        ).fetchone()
        return row is not None and row[0] >= mtime

    def upsert(self, features: SessionFeatures, mtime: float) -> None:
        self._con.execute(
            "DELETE FROM features WHERE client = ? AND session_id = ?",
            [features.client, features.session_id],
        )
        self._con.execute(
            "INSERT INTO features (client, session_id, mtime, json) VALUES (?, ?, ?, ?)",
            [features.client, features.session_id, mtime, features.model_dump_json()],
        )

    def load_all(self) -> Iterator[SessionFeatures]:
        rows = self._con.execute("SELECT json FROM features").fetchall()
        for (payload,) in rows:
            yield SessionFeatures.model_validate_json(payload)

    def close(self) -> None:
        self._con.close()
```

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/test_store.py -v`
Expected: PASS (3 tests).

```bash
git add src/aianalyzer/store.py tests/test_store.py
git commit -m "feat(store): DuckDB feature cache keyed on (client, session_id, mtime)"
```

---

## Task 14: `archetypes.py` — `Archetype` enum + `ClassificationResult`

**Files:**
- Create: `src/aianalyzer/archetypes.py`
- Create: `tests/test_archetypes.py`

Defines the four primary archetypes from DESIGN.md §7 plus the result model returned by the classifier. `Archetype` is a `str` enum so it serializes cleanly. `ClassificationResult` carries planning/control axis scores in `[-1, 1]`, the primary archetype, an optional secondary (when within `secondary_margin` of the primary's axis side), modifier tags, and the user-facing macro label.

- [ ] **Step 1: Write the failing test**

`tests/test_archetypes.py`:
```python
from aianalyzer.archetypes import Archetype, ClassificationResult


def test_archetype_values():
    assert Archetype.ARCHITECT.value == "architect"
    assert Archetype.PILOT.value == "pilot"
    assert Archetype.TINKERER.value == "tinkerer"
    assert Archetype.VIBE_CODER.value == "vibe-coder"


def test_classification_result_serializes():
    r = ClassificationResult(
        planning_score=0.4,
        control_score=-0.2,
        primary=Archetype.ARCHITECT,
        secondary=None,
        tags=["questioner"],
        macro_label="Architect (questioner)",
        secondary_margin=0.15,
    )

    payload = r.model_dump()
    assert payload["primary"] == "architect"
    assert payload["secondary"] is None
    assert payload["tags"] == ["questioner"]
    assert payload["macro_label"] == "Architect (questioner)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_archetypes.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `src/aianalyzer/archetypes.py`**

```python
"""Archetype enum and classifier result model."""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Archetype(str, Enum):
    ARCHITECT = "architect"
    PILOT = "pilot"
    TINKERER = "tinkerer"
    VIBE_CODER = "vibe-coder"


class ClassificationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    planning_score: float = Field(..., ge=-1.0, le=1.0)
    control_score: float = Field(..., ge=-1.0, le=1.0)
    primary: Archetype
    secondary: Optional[Archetype] = None
    tags: list[str] = Field(default_factory=list)
    macro_label: str
    secondary_margin: float = 0.15
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_archetypes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aianalyzer/archetypes.py tests/test_archetypes.py
git commit -m "feat(archetypes): Archetype enum + ClassificationResult"
```

---

## Task 15: `classifier/weights.yaml` + `load_weights()`

**Files:**
- Create: `src/aianalyzer/classifier/__init__.py`
- Create: `src/aianalyzer/classifier/weights.yaml`
- Create: `src/aianalyzer/classifier/weights.py`
- Create: `tests/test_classifier_weights.py`

`weights.yaml` is the **only place** axis weights live so future calibration (DESIGN §13) doesn't require code changes. Each axis maps a feature name to a signed coefficient. `normalizers` clamps each raw feature into `[0, 1]` via a min/max range before weighting.

- [ ] **Step 1: Create the package marker**

`src/aianalyzer/classifier/__init__.py`:
```python
"""Archetype classifier."""
```

- [ ] **Step 2: Write `weights.yaml`**

`src/aianalyzer/classifier/weights.yaml`:
```yaml
# Axis weights. Positive => pushes toward POSITIVE end of the axis.
# planning axis: + = Architect/Pilot, - = Tinkerer/Vibe Coder
# control axis:  + = Architect/Tinkerer (hands-on), - = Pilot/Vibe Coder (hands-off)
planning:
  planning_language_ratio: 1.0
  question_ratio: 0.5
  thinks_before_prompt_sec_avg: 0.7
  test_or_spec_mention_rate: 0.6
  todo_density: 0.8
control:
  tool_diversity: 0.6
  edited_files_per_turn_avg: 0.4
  accept_and_go_ratio: -1.0
  revision_depth: -0.3
  tool_error_rate: 0.2

# Normalizers map raw signal -> [0, 1] via linear clamp.
normalizers:
  planning_language_ratio: {min: 0.0, max: 0.6}
  question_ratio: {min: 0.0, max: 0.6}
  thinks_before_prompt_sec_avg: {min: 0.0, max: 60.0}
  test_or_spec_mention_rate: {min: 0.0, max: 0.4}
  todo_density: {min: 0.0, max: 2.0}
  tool_diversity: {min: 0.0, max: 2.0}
  edited_files_per_turn_avg: {min: 0.0, max: 5.0}
  accept_and_go_ratio: {min: 0.0, max: 0.6}
  revision_depth: {min: 0.0, max: 4.0}
  tool_error_rate: {min: 0.0, max: 0.4}

modifiers:
  questioner_min_question_ratio: 0.4
  debugger_min_tool_error_rate: 0.2
  planner_min_todo_density: 1.0
  yolo_min_accept_and_go: 0.5
  parallelist_min_parallel_tool_call_rate: 0.3
```

- [ ] **Step 3: Write the failing loader test**

`tests/test_classifier_weights.py`:
```python
from aianalyzer.classifier.weights import Weights, load_weights


def test_load_default_weights():
    w = load_weights()
    assert isinstance(w, Weights)
    assert w.planning["planning_language_ratio"] == 1.0
    assert w.control["accept_and_go_ratio"] == -1.0
    assert w.normalizers["planning_language_ratio"].max == 0.6
    assert w.modifiers["questioner_min_question_ratio"] == 0.4


def test_normalize_clamps_to_unit_interval():
    w = load_weights()
    norm = w.normalize("planning_language_ratio", 0.3)
    # (0.3 - 0.0) / (0.6 - 0.0) = 0.5
    assert abs(norm - 0.5) < 1e-9
    assert w.normalize("planning_language_ratio", -1.0) == 0.0
    assert w.normalize("planning_language_ratio", 99.0) == 1.0
    assert w.normalize("unknown_signal", 5.0) == 5.0  # unmapped -> passthrough
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m pytest tests/test_classifier_weights.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 5: Implement `src/aianalyzer/classifier/weights.py`**

```python
"""YAML-backed classifier weights loader."""
from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Optional

import yaml


@dataclass(frozen=True)
class _Range:
    min: float
    max: float


@dataclass(frozen=True)
class Weights:
    planning: dict[str, float]
    control: dict[str, float]
    normalizers: dict[str, _Range]
    modifiers: dict[str, float]

    def normalize(self, signal: str, value: float) -> float:
        rng = self.normalizers.get(signal)
        if rng is None:
            return value
        if rng.max == rng.min:
            return 0.0
        scaled = (value - rng.min) / (rng.max - rng.min)
        return max(0.0, min(1.0, scaled))


def load_weights(path: Optional[Path] = None) -> Weights:
    if path is None:
        data = yaml.safe_load(
            resources.files("aianalyzer.classifier").joinpath("weights.yaml").read_text(encoding="utf-8")
        )
    else:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    normalizers = {k: _Range(min=v["min"], max=v["max"]) for k, v in data["normalizers"].items()}
    return Weights(
        planning=dict(data["planning"]),
        control=dict(data["control"]),
        normalizers=normalizers,
        modifiers=dict(data["modifiers"]),
    )
```

- [ ] **Step 6: Update `pyproject.toml` to ship the YAML**

In `pyproject.toml`, add to the `[tool.hatch.build.targets.wheel]` section (create the section if missing):

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/aianalyzer"]

[tool.hatch.build.targets.wheel.force-include]
"src/aianalyzer/classifier/weights.yaml" = "aianalyzer/classifier/weights.yaml"
```

- [ ] **Step 7: Run tests and commit**

Run: `python -m pytest tests/test_classifier_weights.py -v`
Expected: PASS (2 tests).

```bash
git add src/aianalyzer/classifier tests/test_classifier_weights.py pyproject.toml
git commit -m "feat(classifier): YAML weights + loader"
```

---

## Task 16: `classifier/rules.py` — primary archetype scoring

**Files:**
- Create: `src/aianalyzer/classifier/rules.py`
- Create: `tests/test_classifier_primary.py`

Computes planning/control axis scores from a `UserProfile`, then maps to the primary archetype quadrant:

| Planning | Control | Archetype |
| --- | --- | --- |
| + | + | Architect |
| + | − | Pilot |
| − | + | Tinkerer |
| − | − | Vibe Coder |

Each axis score = `sum(weight * normalize(signal, value)) / sum(|weight|)`, clamped to `[-1, 1]`. The `todo_density` signal is derived per-profile as `total_todos / max(session_count, 1)` since it isn't a raw `UserProfile` field.

When the axis score on either dimension is within `secondary_margin` (default 0.15) of zero, the result also records the adjacent quadrant as `secondary` (the one differing only on the close axis). When both axes are within the margin, the closer-to-zero axis wins; ties prefer the planning axis.

- [ ] **Step 1: Write the failing test**

`tests/test_classifier_primary.py`:
```python
from datetime import datetime, timezone

from aianalyzer.archetypes import Archetype
from aianalyzer.classifier.rules import classify
from aianalyzer.classifier.weights import load_weights
from aianalyzer.features import UserProfile


def _profile(**overrides) -> UserProfile:
    base = dict(session_count=1, total_turns=10, total_todos=0)
    base.update(overrides)
    return UserProfile(**base)


def test_architect_quadrant_high_planning_high_control():
    weights = load_weights()
    p = _profile(
        planning_language_ratio=0.6,
        question_ratio=0.5,
        thinks_before_prompt_sec_avg=60.0,
        test_or_spec_mention_rate=0.4,
        total_todos=3,
        tool_diversity=2.0,
        edited_files_per_turn_avg=3.0,
        accept_and_go_ratio=0.0,
        revision_depth=0.5,
        tool_error_rate=0.1,
    )
    r = classify(p, weights=weights)
    assert r.primary == Archetype.ARCHITECT
    assert r.planning_score > 0
    assert r.control_score > 0


def test_vibe_coder_quadrant_low_planning_low_control():
    weights = load_weights()
    p = _profile(
        planning_language_ratio=0.0,
        question_ratio=0.0,
        thinks_before_prompt_sec_avg=2.0,
        test_or_spec_mention_rate=0.0,
        total_todos=0,
        tool_diversity=0.2,
        edited_files_per_turn_avg=0.5,
        accept_and_go_ratio=0.6,
        revision_depth=3.0,
        tool_error_rate=0.0,
    )
    r = classify(p, weights=weights)
    assert r.primary == Archetype.VIBE_CODER
    assert r.planning_score < 0
    assert r.control_score < 0


def test_pilot_quadrant_high_planning_low_control():
    weights = load_weights()
    p = _profile(
        planning_language_ratio=0.6,
        thinks_before_prompt_sec_avg=60.0,
        accept_and_go_ratio=0.5,
        revision_depth=3.0,
        tool_diversity=0.0,
        edited_files_per_turn_avg=0.0,
    )
    r = classify(p, weights=weights)
    assert r.primary == Archetype.PILOT


def test_tinkerer_quadrant_low_planning_high_control():
    weights = load_weights()
    p = _profile(
        planning_language_ratio=0.0,
        question_ratio=0.0,
        thinks_before_prompt_sec_avg=0.0,
        tool_diversity=2.0,
        edited_files_per_turn_avg=5.0,
        accept_and_go_ratio=0.0,
        revision_depth=0.5,
    )
    r = classify(p, weights=weights)
    assert r.primary == Archetype.TINKERER


def test_secondary_set_when_planning_axis_near_zero():
    weights = load_weights()
    # Construct a profile that puts |planning_score| < 0.15 but control_score > 0
    p = _profile(
        planning_language_ratio=0.3,  # midway
        thinks_before_prompt_sec_avg=30.0,
        tool_diversity=2.0,
        edited_files_per_turn_avg=4.0,
        accept_and_go_ratio=0.0,
    )
    r = classify(p, weights=weights)
    # control axis is positive; primary should still resolve, but secondary
    # should be set since planning is close to zero.
    assert r.secondary in {Archetype.ARCHITECT, Archetype.TINKERER}
    assert r.primary != r.secondary
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_classifier_primary.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `src/aianalyzer/classifier/rules.py`**

```python
"""Archetype classification from a UserProfile."""
from __future__ import annotations

from aianalyzer.archetypes import Archetype, ClassificationResult
from aianalyzer.classifier.weights import Weights, load_weights
from aianalyzer.features import UserProfile


def _signal_value(profile: UserProfile, name: str) -> float:
    if name == "todo_density":
        sessions = max(profile.session_count, 1)
        return profile.total_todos / sessions
    return float(getattr(profile, name, 0.0))


def _axis_score(profile: UserProfile, weights: dict[str, float], w: Weights) -> float:
    total = 0.0
    denom = 0.0
    for signal, coeff in weights.items():
        raw = _signal_value(profile, signal)
        norm = w.normalize(signal, raw)
        total += coeff * norm
        denom += abs(coeff)
    if denom == 0.0:
        return 0.0
    # The normalized signal is in [0, 1]; map weighted average from [0, 1] to [-1, 1].
    avg = total / denom
    return max(-1.0, min(1.0, avg * 2.0 - 1.0))


_QUADRANT: dict[tuple[bool, bool], Archetype] = {
    (True, True): Archetype.ARCHITECT,
    (True, False): Archetype.PILOT,
    (False, True): Archetype.TINKERER,
    (False, False): Archetype.VIBE_CODER,
}


def _primary(planning: float, control: float) -> Archetype:
    return _QUADRANT[(planning >= 0, control >= 0)]


def _secondary(planning: float, control: float, margin: float) -> Archetype | None:
    plan_close = abs(planning) < margin
    ctrl_close = abs(control) < margin
    if not plan_close and not ctrl_close:
        return None
    # Pick the axis closer to zero to flip; tie -> flip planning.
    if plan_close and (not ctrl_close or abs(planning) <= abs(control)):
        return _QUADRANT[(not (planning >= 0), control >= 0)]
    return _QUADRANT[(planning >= 0, not (control >= 0))]


def classify(profile: UserProfile, weights: Weights | None = None) -> ClassificationResult:
    w = weights or load_weights()
    planning = _axis_score(profile, w.planning, w)
    control = _axis_score(profile, w.control, w)
    primary = _primary(planning, control)
    secondary = _secondary(planning, control, margin=0.15)
    label = primary.value.replace("-", " ").title()
    return ClassificationResult(
        planning_score=planning,
        control_score=control,
        primary=primary,
        secondary=secondary,
        tags=[],
        macro_label=label,
        secondary_margin=0.15,
    )
```

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/test_classifier_primary.py -v`
Expected: PASS (5 tests).

```bash
git add src/aianalyzer/classifier/rules.py tests/test_classifier_primary.py
git commit -m "feat(classifier): primary archetype scoring with secondary detection"
```

---

## Task 17: `classifier/rules.py` — modifier tags + macro label

**Files:**
- Modify: `src/aianalyzer/classifier/rules.py`
- Create: `tests/test_classifier_modifiers.py`

Adds modifier tags applied on top of the primary archetype, using thresholds from `weights.yaml`:

| Tag | Trigger |
| --- | --- |
| `questioner` | `question_ratio >= questioner_min_question_ratio` |
| `debugger` | `tool_error_rate >= debugger_min_tool_error_rate` |
| `planner` | `todo_density >= planner_min_todo_density` |
| `yolo` | `accept_and_go_ratio >= yolo_min_accept_and_go` |
| `parallelist` | `parallel_tool_call_rate >= parallelist_min_parallel_tool_call_rate` |

The macro label is `"<Primary>[ / <Secondary>][ (tag1, tag2)]"`.

- [ ] **Step 1: Write the failing test**

`tests/test_classifier_modifiers.py`:
```python
from aianalyzer.archetypes import Archetype
from aianalyzer.classifier.rules import classify
from aianalyzer.classifier.weights import load_weights
from aianalyzer.features import UserProfile


def _profile(**overrides):
    base = dict(session_count=1, total_turns=10, total_todos=0)
    base.update(overrides)
    return UserProfile(**base)


def test_questioner_tag_applied():
    r = classify(_profile(question_ratio=0.5), weights=load_weights())
    assert "questioner" in r.tags


def test_yolo_tag_applied_when_accept_and_go_high():
    r = classify(_profile(accept_and_go_ratio=0.6), weights=load_weights())
    assert "yolo" in r.tags


def test_parallelist_and_debugger_tags():
    r = classify(
        _profile(parallel_tool_call_rate=0.5, tool_error_rate=0.3),
        weights=load_weights(),
    )
    assert "parallelist" in r.tags
    assert "debugger" in r.tags


def test_planner_tag_when_todo_density_high():
    r = classify(_profile(session_count=2, total_todos=4), weights=load_weights())
    # density = 4 / 2 = 2.0 >= 1.0
    assert "planner" in r.tags


def test_macro_label_includes_tags_and_secondary():
    weights = load_weights()
    p = _profile(
        planning_language_ratio=0.3,
        question_ratio=0.5,  # questioner
        tool_diversity=2.0,
        edited_files_per_turn_avg=4.0,
    )
    r = classify(p, weights=weights)
    assert r.primary.value.replace("-", " ").title() in r.macro_label
    assert "questioner" in r.macro_label
    if r.secondary is not None:
        assert r.secondary.value.replace("-", " ").title() in r.macro_label
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_classifier_modifiers.py -v`
Expected: FAIL (tags currently always empty).

- [ ] **Step 3: Add `_modifiers` and update `classify` in `rules.py`**

Add this helper above `classify`:

```python
def _modifiers(profile: UserProfile, w: Weights) -> list[str]:
    m = w.modifiers
    tags: list[str] = []
    if profile.question_ratio >= m["questioner_min_question_ratio"]:
        tags.append("questioner")
    if profile.tool_error_rate >= m["debugger_min_tool_error_rate"]:
        tags.append("debugger")
    todo_density = profile.total_todos / max(profile.session_count, 1)
    if todo_density >= m["planner_min_todo_density"]:
        tags.append("planner")
    if profile.accept_and_go_ratio >= m["yolo_min_accept_and_go"]:
        tags.append("yolo")
    if profile.parallel_tool_call_rate >= m["parallelist_min_parallel_tool_call_rate"]:
        tags.append("parallelist")
    return tags
```

Replace the body of `classify` with:

```python
def classify(profile: UserProfile, weights: Weights | None = None) -> ClassificationResult:
    w = weights or load_weights()
    planning = _axis_score(profile, w.planning, w)
    control = _axis_score(profile, w.control, w)
    primary = _primary(planning, control)
    secondary = _secondary(planning, control, margin=0.15)
    tags = _modifiers(profile, w)

    primary_label = primary.value.replace("-", " ").title()
    label = primary_label
    if secondary is not None:
        label += f" / {secondary.value.replace('-', ' ').title()}"
    if tags:
        label += f" ({', '.join(tags)})"

    return ClassificationResult(
        planning_score=planning,
        control_score=control,
        primary=primary,
        secondary=secondary,
        tags=tags,
        macro_label=label,
        secondary_margin=0.15,
    )
```

- [ ] **Step 4: Run all classifier tests**

Run: `python -m pytest tests/test_classifier_primary.py tests/test_classifier_modifiers.py -v`
Expected: PASS (all 10 tests).

- [ ] **Step 5: Commit**

```bash
git add src/aianalyzer/classifier/rules.py tests/test_classifier_modifiers.py
git commit -m "feat(classifier): modifier tags + macro label"
```

---

## Task 18: `report/terminal.py` — rich terminal renderer

**Files:**
- Create: `src/aianalyzer/report/__init__.py`
- Create: `src/aianalyzer/report/terminal.py`
- Create: `tests/test_report_terminal.py`

Renders a `UserProfile` + `ClassificationResult` to the terminal via `rich`. Three blocks:

1. **Archetype panel** — large headline with the macro label, axis scores, and a tiny ASCII quadrant marker.
2. **Signals table** — every numeric `UserProfile` field with one-line descriptions.
3. **Session timeline sparkline** — one Unicode block per session, height proportional to `turn_count`. Sessions are supplied as a list of `SessionFeatures` ordered by `started_at`.

The renderer accepts a `Console` so tests can capture output.

- [ ] **Step 1: Create the package marker**

`src/aianalyzer/report/__init__.py`:
```python
"""Terminal reporting for aianalyzer."""
```

- [ ] **Step 2: Write the failing test**

`tests/test_report_terminal.py`:
```python
from datetime import datetime, timezone
from io import StringIO

from rich.console import Console

from aianalyzer.archetypes import Archetype, ClassificationResult
from aianalyzer.features import SessionFeatures, UserProfile
from aianalyzer.report.terminal import render_report


def _sf(idx: int, turn_count: int) -> SessionFeatures:
    return SessionFeatures(
        session_id=f"s{idx}",
        client="copilot-cli",
        started_at=datetime(2026, 6, idx + 1, tzinfo=timezone.utc),
        turn_count=turn_count,
    )


def test_render_report_contains_all_blocks():
    profile = UserProfile(
        session_count=3, total_turns=42, total_todos=5,
        distinct_models_total=2, cwd_switch_count=1,
        avg_user_msg_chars=120.5, planning_language_ratio=0.4,
        question_ratio=0.3, thinks_before_prompt_sec_avg=25.0,
        test_or_spec_mention_rate=0.1, tool_diversity=1.5,
        accept_and_go_ratio=0.2, revision_depth=1.7,
        session_duration_sec=900.0, tool_error_rate=0.1,
        edited_files_per_turn_avg=1.2, parallel_tool_call_rate=0.15,
        abort_rate=0.05,
        reasoning_effort_distribution={"high": 0.6, "xhigh": 0.4},
    )
    result = ClassificationResult(
        planning_score=0.3, control_score=0.4,
        primary=Archetype.ARCHITECT, secondary=None,
        tags=["questioner", "planner"],
        macro_label="Architect (questioner, planner)",
        secondary_margin=0.15,
    )
    sessions = [_sf(0, 5), _sf(1, 20), _sf(2, 17)]

    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=120, color_system=None)
    render_report(profile, result, sessions, console=console)
    out = buf.getvalue()

    assert "Architect (questioner, planner)" in out
    assert "planning" in out.lower()
    assert "control" in out.lower()
    assert "120.5" in out  # avg_user_msg_chars rendered
    assert "questioner" in out
    # sparkline line should appear (any block char)
    assert any(ch in out for ch in "▁▂▃▄▅▆▇█")


def test_render_report_handles_empty_session_list():
    profile = UserProfile()
    result = ClassificationResult(
        planning_score=0.0, control_score=0.0,
        primary=Archetype.VIBE_CODER, secondary=None,
        tags=[], macro_label="Vibe Coder", secondary_margin=0.15,
    )
    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=80, color_system=None)
    render_report(profile, result, [], console=console)
    out = buf.getvalue()
    assert "Vibe Coder" in out
    assert "0 sessions" in out
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_report_terminal.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 4: Implement `src/aianalyzer/report/terminal.py`**

```python
"""Terminal rendering for analyzer output."""
from __future__ import annotations

from typing import Sequence

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from aianalyzer.archetypes import ClassificationResult
from aianalyzer.features import SessionFeatures, UserProfile

_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _sparkline(values: Sequence[float]) -> str:
    if not values:
        return ""
    hi = max(values)
    if hi <= 0:
        return _SPARK_CHARS[0] * len(values)
    step = hi / (len(_SPARK_CHARS) - 1)
    return "".join(_SPARK_CHARS[min(len(_SPARK_CHARS) - 1, int(v / step))] for v in values)


_SIGNAL_LABELS: list[tuple[str, str]] = [
    ("avg_user_msg_chars", "S1 Avg user message length (chars)"),
    ("planning_language_ratio", "S2 Planning-language ratio"),
    ("question_ratio", "S3 Question ratio"),
    ("tool_diversity", "S4 Tool diversity (entropy)"),
    ("accept_and_go_ratio", "S5 Accept-and-go ratio"),
    ("revision_depth", "S6 Revision depth (tool calls/turn)"),
    ("session_duration_sec", "S7 Avg session duration (sec)"),
    ("tool_error_rate", "S8 Tool error rate"),
    ("thinks_before_prompt_sec_avg", "S9 Think time before prompt (sec)"),
    ("edited_files_per_turn_avg", "S10 Edited files per turn"),
    ("distinct_models_total", "S11 Distinct models used"),
    ("cwd_switch_count", "S13 cwd switches across sessions"),
    ("total_todos", "S15 Total todos created"),
    ("abort_rate", "S16 Abort rate"),
    ("test_or_spec_mention_rate", "S17 Test/spec mention rate"),
    ("parallel_tool_call_rate", "S18 Parallel tool-call rate"),
]


def render_report(
    profile: UserProfile,
    result: ClassificationResult,
    sessions: Sequence[SessionFeatures],
    console: Console,
) -> None:
    panel_body = (
        f"[bold]{result.macro_label}[/bold]\n"
        f"planning axis: {result.planning_score:+.2f}    "
        f"control axis: {result.control_score:+.2f}\n"
        f"{len(sessions)} sessions, {profile.total_turns} turns total"
    )
    console.print(Panel(panel_body, title="AI archetype", expand=False))

    table = Table(title="Signals", show_lines=False)
    table.add_column("Signal")
    table.add_column("Value", justify="right")
    for field, label in _SIGNAL_LABELS:
        value = getattr(profile, field, 0)
        if isinstance(value, float):
            cell = f"{value:.2f}" if value != 0 else "0.00"
        else:
            cell = str(value)
        table.add_row(label, cell)
    console.print(table)

    if profile.reasoning_effort_distribution:
        effort_line = "  ".join(
            f"{k}={v:.0%}" for k, v in sorted(profile.reasoning_effort_distribution.items())
        )
        console.print(f"reasoning effort: {effort_line}")

    if sessions:
        ordered = sorted(sessions, key=lambda s: s.started_at)
        spark = _sparkline([float(s.turn_count) for s in ordered])
        console.print(f"timeline (turns/session): {spark}")
```

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/test_report_terminal.py -v`
Expected: PASS (2 tests).

```bash
git add src/aianalyzer/report tests/test_report_terminal.py
git commit -m "feat(report): terminal renderer with archetype panel, signals table, sparkline"
```

---

## Task 19: `cli.py` — `scan` command

**Files:**
- Create: `src/aianalyzer/cli.py`
- Create: `tests/test_cli_scan.py`
- Create: `tests/fixtures/home/.copilot/session-state/session-x/events.jsonl`

Adds a `typer` app exposing `aianalyzer scan`. The command:

1. Resolves the Copilot CLI base directory (`--home <dir>` or `$HOME / .copilot / session-state`).
2. Discovers sessions via `find_copilot_cli_sessions`.
3. For each session, skips if `store.has_fresh(...)` returns True; otherwise collects → normalizes → extracts features → upserts into the DuckDB store at `--cache <path>` (default `<home>/.aianalyzer/cache.duckdb`).
4. Prints a summary: total sessions scanned, skipped (cached), and errors.

- [ ] **Step 1: Create the synthetic home fixture**

`tests/fixtures/home/.copilot/session-state/session-x/events.jsonl`:
```jsonl
{"type":"session.start","ts":"2026-06-09T13:00:00Z","data":{"sessionId":"session-x","startTime":"2026-06-09T13:00:00Z","context":{"cwd":"C:/scan"},"copilotVersion":"x"}}
{"type":"user.message","ts":"2026-06-09T13:00:01Z","data":{"content":"plan before coding"}}
{"type":"assistant.turn_start","ts":"2026-06-09T13:00:02Z","data":{"turnId":"t1","interactionId":"i1"}}
{"type":"assistant.message","ts":"2026-06-09T13:00:03Z","data":{"messageId":"m1","model":"m","content":"ok","toolRequests":[],"turnId":"t1"}}
{"type":"assistant.turn_end","ts":"2026-06-09T13:00:04Z","data":{"turnId":"t1"}}
```

- [ ] **Step 2: Write the failing test**

`tests/test_cli_scan.py`:
```python
from pathlib import Path

from typer.testing import CliRunner

from aianalyzer.cli import app
from aianalyzer.store import FeatureStore


def test_scan_populates_cache(tmp_path: Path, fixtures_dir: Path):
    home = fixtures_dir / "home"
    cache = tmp_path / "cache.duckdb"
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["scan", "--home", str(home), "--cache", str(cache)],
    )
    assert result.exit_code == 0, result.output
    assert "scanned" in result.output.lower()

    store = FeatureStore(cache)
    rows = list(store.load_all())
    store.close()
    assert len(rows) == 1
    assert rows[0].session_id == "session-x"


def test_scan_is_idempotent(tmp_path: Path, fixtures_dir: Path):
    home = fixtures_dir / "home"
    cache = tmp_path / "cache.duckdb"
    runner = CliRunner()

    runner.invoke(app, ["scan", "--home", str(home), "--cache", str(cache)])
    second = runner.invoke(app, ["scan", "--home", str(home), "--cache", str(cache)])

    assert second.exit_code == 0
    assert "skipped" in second.output.lower()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_cli_scan.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 4: Implement `src/aianalyzer/cli.py`**

```python
"""aianalyzer CLI entry point."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from aianalyzer.collectors.copilot_cli import CopilotCliCollector
from aianalyzer.discovery import find_copilot_cli_sessions
from aianalyzer.features import extract_session_features
from aianalyzer.store import FeatureStore

app = typer.Typer(add_completion=False, help="Analyze your AI coding sessions.")


def _default_home() -> Path:
    return Path.home()


def _default_cache(home: Path) -> Path:
    return home / ".aianalyzer" / "cache.duckdb"


@app.command()
def scan(
    home: Optional[Path] = typer.Option(None, help="Override the home directory holding .copilot/."),
    cache: Optional[Path] = typer.Option(None, help="DuckDB cache file."),
) -> None:
    """Discover and ingest local Copilot CLI sessions."""
    home_dir = home or _default_home()
    cache_path = cache or _default_cache(home_dir)

    base = home_dir / ".copilot" / "session-state"
    discovered = list(find_copilot_cli_sessions(base))
    store = FeatureStore(cache_path)
    collector = CopilotCliCollector()

    scanned = 0
    skipped = 0
    errors = 0
    for d in discovered:
        try:
            if store.has_fresh(d.client, d.session_id, d.mtime):
                skipped += 1
                continue
            session = collector.parse(d)
            features = extract_session_features(session)
            store.upsert(features, mtime=d.mtime)
            scanned += 1
        except Exception as exc:  # noqa: BLE001
            errors += 1
            typer.echo(f"error in {d.session_id}: {exc}", err=True)

    store.close()
    typer.echo(f"scanned {scanned}, skipped {skipped}, errors {errors}")
```

- [ ] **Step 5: Add the entry point and re-install**

In `pyproject.toml`, ensure the `[project.scripts]` section contains:

```toml
[project.scripts]
aianalyzer = "aianalyzer.cli:app"
```

Run: `python -m pip install -e .`
Expected: succeeds.

- [ ] **Step 6: Run tests and commit**

Run: `python -m pytest tests/test_cli_scan.py -v`
Expected: PASS (2 tests).

```bash
git add src/aianalyzer/cli.py tests/test_cli_scan.py tests/fixtures/home pyproject.toml
git commit -m "feat(cli): scan command — discover, ingest, cache features"
```

---

## Task 20: `cli.py` — `report` command

**Files:**
- Modify: `src/aianalyzer/cli.py`
- Create: `tests/test_cli_report.py`

`aianalyzer report` loads cached features, aggregates them into a `UserProfile`, classifies, and renders via `report.terminal.render_report`. Flags:
- `--cache <path>` — DuckDB file (default `<home>/.aianalyzer/cache.duckdb`).
- `--home <dir>` — used only to compute default cache path and to enumerate `cwd` history (to feed `cwd_switch_count`).

- [ ] **Step 1: Write the failing test**

`tests/test_cli_report.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli_report.py -v`
Expected: FAIL (`No such command 'report'`).

- [ ] **Step 3: Extend `src/aianalyzer/cli.py`**

Add these imports near the top:

```python
from rich.console import Console

from aianalyzer.archetypes import ClassificationResult
from aianalyzer.classifier.rules import classify
from aianalyzer.features import (
    SessionFeatures,
    UserProfile,
    aggregate_user_profile,
)
from aianalyzer.report.terminal import render_report
```

Add the new command at the bottom of the file:

```python
def _collect_cwd_history(home: Path) -> list[str | None]:
    base = home / ".copilot" / "session-state"
    if not base.exists():
        return []
    cwds: list[str | None] = []
    for events in base.glob("*/events.jsonl"):
        try:
            with events.open(encoding="utf-8") as fh:
                first = fh.readline()
            import json
            data = json.loads(first).get("data", {})
            cwd = data.get("context", {}).get("cwd")
            cwds.append(cwd)
        except Exception:  # noqa: BLE001
            cwds.append(None)
    return cwds


@app.command()
def report(
    home: Optional[Path] = typer.Option(None, help="Override the home directory holding .copilot/."),
    cache: Optional[Path] = typer.Option(None, help="DuckDB cache file."),
) -> None:
    """Aggregate cached features and print the archetype report."""
    home_dir = home or _default_home()
    cache_path = cache or _default_cache(home_dir)

    store = FeatureStore(cache_path)
    features: list[SessionFeatures] = list(store.load_all())
    store.close()

    cwd_history = _collect_cwd_history(home_dir)
    profile = aggregate_user_profile(features, cwd_history=cwd_history)
    result = classify(profile)

    console = Console()
    render_report(profile, result, features, console=console)
```

- [ ] **Step 4: Run all CLI tests**

Run: `python -m pytest tests/test_cli_scan.py tests/test_cli_report.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/aianalyzer/cli.py tests/test_cli_report.py
git commit -m "feat(cli): report command — aggregate, classify, render"
```

---

## Task 21: `README.md` + end-to-end smoke against the real corpus

**Files:**
- Create: `README.md`
- (No production code changes)

Documents installation, the two commands, and the four archetypes — then validates the MLP end-to-end against the real 172 local Copilot CLI sessions on this machine.

- [ ] **Step 1: Write `README.md`**

````markdown
# AIAnalyzer

Local-first analyzer for AI-coding sessions. Ingests sessions from GitHub Copilot CLI (Claude Code, OpenAI Codex CLI, and VS Code Copilot Chat are planned), computes usage signals, and classifies your collaboration archetype.

> Status: **M0–M3 (MLP)**. Copilot CLI only. See `DESIGN.md` for the full roadmap.

## Install

```bash
pip install -e .
```

Requires Python 3.11+.

## Usage

```bash
# 1. Ingest all local Copilot CLI sessions into a DuckDB cache.
aianalyzer scan

# 2. Aggregate and print your archetype report.
aianalyzer report
```

Both commands accept `--home <dir>` (defaults to your home directory) and `--cache <path>` (defaults to `<home>/.aianalyzer/cache.duckdb`).

## Archetypes

Two axes — **planning** (how much you think before prompting) × **control** (how much you steer the AI hands-on) — yield four primary archetypes:

| Planning | Control | Archetype | Sketch |
| --- | --- | --- | --- |
| High | High | **Architect** | Designs first, drives tools |
| High | Low  | **Pilot**     | Plans, then lets the AI fly |
| Low  | High | **Tinkerer**  | Hands-on, exploratory |
| Low  | Low  | **Vibe Coder**| "Just build it, ship it" |

Modifier tags (`questioner`, `debugger`, `planner`, `yolo`, `parallelist`) add nuance on top. Weights live in `src/aianalyzer/classifier/weights.yaml` — tune them for your team.

## Privacy

Everything stays on disk. No network calls. PII redaction (PATs, Bearer tokens, AWS keys, `password=` strings, emails) runs at the normalization stage.

## Tests

```bash
python -m pytest
```
````

- [ ] **Step 2: Commit the README**

```bash
git add README.md
git commit -m "docs: README for MLP"
```

- [ ] **Step 3: Run the full test suite**

Run: `python -m pytest -v`
Expected: ALL tests pass.

- [ ] **Step 4: Smoke-run against your real local sessions**

Run:

```bash
aianalyzer scan
aianalyzer report
```

Expected:
- `scan` exits 0 and prints `scanned N, skipped 0, errors 0` where N matches your local session count (≈ 172 on this machine).
- A second `aianalyzer scan` prints `scanned 0, skipped N, errors 0`.
- `report` exits 0 and renders the archetype panel, signals table, and timeline sparkline.

If `errors > 0`, capture the first failing session id from stderr and add a regression fixture before fixing — do not skip silently.

- [ ] **Step 5: Tag the milestone**

```bash
git tag m3-mlp
```

---

## Self-Review

After finishing all tasks above, walk through this checklist before declaring done:

1. **Spec coverage** — every signal `S1`–`S18` in `DESIGN.md §6` corresponds to a `SessionFeatures` field populated by Tasks 9–11. Every archetype in `DESIGN.md §7` (`Architect`, `Pilot`, `Tinkerer`, `Vibe Coder`) maps to a `_QUADRANT` entry in Task 16. The five modifier tags listed in §7 all appear in Task 17's `_modifiers`. Every milestone deliverable for M0–M3 in `§12` ships in this plan.
2. **Placeholder scan** — search the plan for `TODO`, `TBD`, `fill in`, `appropriate`, `similar to`, and confirm none survive in step bodies. Every code step has a complete code block.
3. **Type consistency** — `SessionFeatures`, `UserProfile`, `ClassificationResult`, `Archetype`, `NormalizedSession`, `Turn`, `ToolCall`, `UserMessage`, `AssistantMessage`, `TodoSnapshot`, and `DiscoveredSession` are spelled identically wherever they appear. Function names `extract_session_features`, `aggregate_user_profile`, `classify`, `load_weights`, `render_report`, `find_copilot_cli_sessions`, and `CopilotCliCollector.parse` are stable across tasks.

If anything is off, fix it inline before handing off.

---
