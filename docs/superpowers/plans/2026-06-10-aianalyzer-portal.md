# AIAnalyzer M4 Portal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a friendly browser-based portal on top of the MLP that scans sessions, presents comprehensive AI-collaboration statistics + per-session purpose classification, and generates an LLM-authored "AI profile" narrative via the local GitHub Copilot CLI.

**Architecture:** FastAPI server (bound to 127.0.0.1) wraps the existing classification pipeline, recomputing an `ExtendedProfile` on each request from the cached `FeatureStore`. A vanilla-JS single-page frontend (Chart.js vendored) calls `/api/profile`, renders the report, and exposes a button that triggers `POST /api/narrative/start` → background subprocess `copilot -p "<prompt>" --allow-all-tools --no-color -s --output-format text` whose stdout becomes the rendered narrative. Tasks 22-24 deepen the data model (cache schema_version, extended per-session features, session-type classifier); 25 aggregates them; 26-29 add the narrative + HTTP layer; 30-33 build the frontend; 34-35 add the `serve` CLI command and ship docs.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, Pydantic v2, DuckDB (existing), Typer (existing), Chart.js 4.4 (vendored), vanilla HTML/CSS/JS, GitHub Copilot CLI subprocess.

**Spec:** Implements `docs/DESIGN-PORTAL.md`. Plan numbering continues from the MLP plan (`docs/superpowers/plans/2026-06-09-aianalyzer-mlp.md`, Tasks 1-21).

**Pre-task convention reminders (apply to every task):**
- Run `pytest -q` after each implementation step; the suite must stay green before committing.
- Commits use Conventional Commit prefixes (`feat:`, `fix:`, `chore:`, `docs:`, `test:`).
- `SessionFeatures` is `frozen=True`; extending it means *adding fields with defaults* and using `model_copy(update={...})` for in-place updates in tests.
- `Archetype` lives at `aianalyzer.classifier.archetypes`. Don't move it.
- The CLI now has `scan` + `report` + (soon) `serve`; `CliRunner.invoke(app, [...])` calls MUST include the subcommand name.
- All new modules live under `src/aianalyzer/`; tests under `tests/`.

---

### Task 22: Cache schema_version + auto-invalidate

**Files:**
- Modify: `src/aianalyzer/store.py`
- Modify: `tests/test_store.py`

**Why:** Tasks 23-24 will add new fields to `SessionFeatures`. Existing DuckDB caches from MLP runs would deserialize with missing fields and silently mask bugs. A `schema_version` column lets the store discard stale rows on read.

- [ ] **Step 1: Add a failing test for stale-row invalidation**

Append to `tests/test_store.py`:
```python
def test_store_invalidates_rows_with_older_schema_version(tmp_path):
    from aianalyzer.store import FeatureStore
    from aianalyzer.features import SessionFeatures

    db = tmp_path / "cache.duckdb"
    store = FeatureStore(db)

    sf = _features(session_id="s1")  # reuse existing helper in this file
    store.upsert("copilot_cli", sf, mtime=1.0)

    # Simulate an older schema version on disk
    with store._conn() as conn:
        conn.execute("UPDATE session_features SET schema_version = schema_version - 1")

    hit = store.get("copilot_cli", "s1", mtime=1.0)
    assert hit is None, "rows from older schema must be treated as cache miss"
```
If `_features` doesn't already exist in `tests/test_store.py`, copy the existing per-file helper used in `tests/test_classifier_primary.py` (`_profile`/`_features` style) and adapt it to build a minimal `SessionFeatures`. Keep it local to the test file.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_store.py::test_store_invalidates_rows_with_older_schema_version -v`
Expected: FAIL (column `schema_version` does not exist OR assertion fails).

- [ ] **Step 3: Add `SCHEMA_VERSION` constant + column + read-side filter**

In `src/aianalyzer/store.py`:
```python
# Bump whenever SessionFeatures shape changes meaningfully.
SCHEMA_VERSION = 2
```
Update the `CREATE TABLE IF NOT EXISTS` DDL inside `FeatureStore.__init__` (or wherever the table is created) to include `schema_version INTEGER NOT NULL`:
```python
conn.execute(
    """
    CREATE TABLE IF NOT EXISTS session_features (
        client          VARCHAR NOT NULL,
        session_id      VARCHAR NOT NULL,
        mtime           DOUBLE  NOT NULL,
        schema_version  INTEGER NOT NULL,
        json            VARCHAR NOT NULL,
        PRIMARY KEY (client, session_id)
    )
    """
)
```
Add a lightweight migration *after* `CREATE TABLE`:
```python
cols = {row[1] for row in conn.execute("PRAGMA table_info('session_features')").fetchall()}
if "schema_version" not in cols:
    conn.execute("ALTER TABLE session_features ADD COLUMN schema_version INTEGER NOT NULL DEFAULT 0")
```
Update `upsert` to write `SCHEMA_VERSION`. Update `get` to require `schema_version = ?` with `SCHEMA_VERSION`. Same for any `get_many` / iterator method.

- [ ] **Step 4: Run the full store test module**

Run: `pytest tests/test_store.py -v`
Expected: PASS (new test + all pre-existing tests).

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: PASS (53+ tests).

- [ ] **Step 6: Commit**

```bash
git add src/aianalyzer/store.py tests/test_store.py
git commit -m "feat(store): version cache rows and invalidate on schema bumps"
```

---

### Task 23: Extend SessionFeatures with cwd + 6 new per-session fields

**Files:**
- Modify: `src/aianalyzer/features.py`
- Modify: `tests/test_features.py`

**Why:** The portal needs per-session data the MLP didn't capture: working directory (for `top_projects`), word-level prompt length, tool-call breakdown, files touched, local hour/weekday, models used. Adding these as defaulted fields keeps the existing 53 tests green.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_features.py`:
```python
def test_extract_session_features_populates_new_portal_fields(tmp_path):
    from datetime import datetime, timezone
    from aianalyzer.features import extract_session_features
    from aianalyzer.normalize import (
        NormalizedSession, Turn, UserMessage, AssistantMessage, ToolCall,
    )

    ns = NormalizedSession(
        client="copilot_cli",
        session_id="s-extended",
        path="/fake/events.jsonl",
        cwd="/home/dev/repos/proj-a",
        started_at=datetime(2026, 6, 10, 14, 30, tzinfo=timezone.utc),
        ended_at=datetime(2026, 6, 10, 14, 45, tzinfo=timezone.utc),
        models_used={"claude-sonnet-4.5": 3, "gpt-5": 1},
        todos=[],
        turns=[
            Turn(
                user=UserMessage(text="hello world test prompt"),
                assistant=AssistantMessage(text="ok", model="claude-sonnet-4.5"),
                tool_calls=[
                    ToolCall(tool_name="read", arguments={"path": "src/a.py"}, success=True),
                    ToolCall(tool_name="edit", arguments={"path": "src/a.py"}, success=True),
                    ToolCall(tool_name="bash", arguments={"command": "pytest"}, success=False, error="x"),
                ],
                aborted=False,
            ),
        ],
    )
    sf = extract_session_features(ns)
    assert sf.cwd == "/home/dev/repos/proj-a"
    assert sf.avg_user_msg_words == 4.0
    assert sf.tool_counts == {"read": 1, "edit": 1, "bash": 1}
    assert sf.file_paths_touched == {"src/a.py"}
    # 14:30 UTC: hour/weekday computed in local TZ; just assert types and ranges.
    assert 0 <= sf.started_hour_local <= 23
    assert 0 <= sf.started_weekday <= 6
    assert sf.models_used == {"claude-sonnet-4.5": 3, "gpt-5": 1}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_features.py::test_extract_session_features_populates_new_portal_fields -v`
Expected: FAIL with `AttributeError` on `sf.cwd` (or one of the new fields).

- [ ] **Step 3: Extend `SessionFeatures` with defaulted fields**

In `src/aianalyzer/features.py`, add these fields to the `SessionFeatures` model. Keep all defaults so existing tests/cache rows continue to load:
```python
# Portal-extended fields (M4)
cwd: str | None = None
avg_user_msg_words: float = 0.0
tool_counts: dict[str, int] = Field(default_factory=dict)
file_paths_touched: set[str] = Field(default_factory=set)
started_hour_local: int = 0
started_weekday: int = 0  # 0 = Monday
models_used: dict[str, int] = Field(default_factory=dict)
```
Pydantic serialises `set[str]` as a JSON array by default; add a `field_serializer` if DuckDB round-trip tests later complain.

- [ ] **Step 4: Populate the fields in `extract_session_features`**

Inside `extract_session_features(ns: NormalizedSession) -> SessionFeatures`, compute the new fields *before* the final `return SessionFeatures(...)`:
```python
import re
from collections import Counter

_WORD_RE = re.compile(r"\S+")

user_msg_word_counts = [
    len(_WORD_RE.findall(t.user.text))
    for t in ns.turns
    if t.user and t.user.text
]
avg_user_msg_words = (
    sum(user_msg_word_counts) / len(user_msg_word_counts) if user_msg_word_counts else 0.0
)

tool_counts: dict[str, int] = dict(Counter(
    tc.tool_name
    for t in ns.turns
    for tc in t.tool_calls
))

file_paths_touched: set[str] = set()
for t in ns.turns:
    for tc in t.tool_calls:
        path = tc.arguments.get("path") if isinstance(tc.arguments, dict) else None
        if isinstance(path, str) and path:
            file_paths_touched.add(path)

if ns.started_at is not None:
    local = ns.started_at.astimezone()  # honour system tz
    started_hour_local = local.hour
    started_weekday = local.weekday()
else:
    started_hour_local = 0
    started_weekday = 0
```
Pass each value through to the `SessionFeatures(...)` constructor along with `cwd=ns.cwd`, `models_used=dict(ns.models_used)`.

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: PASS (54+ tests; pre-existing tests unaffected because all new fields are defaulted).

- [ ] **Step 6: Bump cache schema version**

In `src/aianalyzer/store.py`, change `SCHEMA_VERSION` to `3`. (Each task that changes SessionFeatures shape bumps this.) No test change needed.

- [ ] **Step 7: Commit**

```bash
git add src/aianalyzer/features.py tests/test_features.py src/aianalyzer/store.py
git commit -m "feat(features): add portal-extended per-session fields"
```

---

### Task 24: SessionType enum + classify_session_type + integrate

**Files:**
- Create: `src/aianalyzer/classifier/session_types.py`
- Create: `tests/test_session_types.py`
- Modify: `src/aianalyzer/features.py` (add `session_type` field + populate it)
- Modify: `src/aianalyzer/store.py` (bump `SCHEMA_VERSION` to 4)

**Why:** The portal shows a "session breakdown" chart (pie). Each session is classified into one of 10 types using rules from `docs/DESIGN-PORTAL.md` §4. Keep it primitive-arg-only to avoid a circular import (`features.py` → `classifier/session_types.py` is OK because the function takes ints/floats/sets, not `SessionFeatures`).

- [ ] **Step 1: Write failing tests for the classifier**

Create `tests/test_session_types.py`:
```python
import pytest
from aianalyzer.classifier.session_types import SessionType, classify_session_type


def _call(**overrides):
    base = dict(
        turns=10,
        duration_seconds=900.0,
        tool_error_rate=0.0,
        debug_kw_density=0.0,
        test_or_spec_mention_rate=0.0,
        majority_test_files=False,
        majority_doc_files=False,
        planning_language=0.0,
        todos_count=0,
        edited_files_per_turn=0.4,
        question_ratio=0.0,
        refactor_kw_density=0.0,
        review_kw_density=0.0,
        edit_tool_calls=2,
        create_tool_calls=0,
    )
    base.update(overrides)
    return classify_session_type(**base)


def test_quick_task_rule_fires_first():
    assert _call(turns=2, duration_seconds=120.0) is SessionType.QUICK_TASK


def test_debugging_rule_on_tool_error_rate():
    assert _call(tool_error_rate=0.5) is SessionType.DEBUGGING


def test_debugging_rule_on_debug_keywords():
    assert _call(debug_kw_density=0.2) is SessionType.DEBUGGING


def test_testing_rule_on_test_mentions():
    assert _call(test_or_spec_mention_rate=0.5) is SessionType.TESTING


def test_testing_rule_on_majority_test_files():
    assert _call(majority_test_files=True) is SessionType.TESTING


def test_documentation_rule():
    assert _call(majority_doc_files=True) is SessionType.DOCUMENTATION


def test_planning_rule_requires_all_three():
    assert _call(planning_language=0.4, todos_count=3, edited_files_per_turn=0.2) is SessionType.PLANNING


def test_exploration_rule():
    assert _call(question_ratio=0.5, edited_files_per_turn=0.1) is SessionType.EXPLORATION


def test_refactoring_rule_needs_edits_no_creates():
    assert _call(refactor_kw_density=0.15, edit_tool_calls=5, create_tool_calls=0) is SessionType.REFACTORING


def test_code_review_rule_needs_zero_edits_and_creates():
    assert _call(review_kw_density=0.2, edit_tool_calls=0, create_tool_calls=0) is SessionType.CODE_REVIEW


def test_feature_work_rule():
    assert _call(edited_files_per_turn=0.8, create_tool_calls=2) is SessionType.FEATURE_WORK


def test_mixed_is_the_fallback():
    assert _call() is SessionType.MIXED
```

- [ ] **Step 2: Run tests to verify they all fail (module missing)**

Run: `pytest tests/test_session_types.py -v`
Expected: All FAIL with `ModuleNotFoundError: No module named 'aianalyzer.classifier.session_types'`.

- [ ] **Step 3: Implement the classifier**

Create `src/aianalyzer/classifier/session_types.py`:
```python
"""Per-session purpose classifier (M4).

First-match-wins rules defined in docs/DESIGN-PORTAL.md §4.
Inputs are primitives so callers in aianalyzer.features can use this without
introducing a circular import.
"""
from __future__ import annotations

from enum import Enum


class SessionType(str, Enum):
    QUICK_TASK = "quick_task"
    DEBUGGING = "debugging"
    TESTING = "testing"
    DOCUMENTATION = "documentation"
    PLANNING = "planning"
    EXPLORATION = "exploration"
    REFACTORING = "refactoring"
    CODE_REVIEW = "code_review"
    FEATURE_WORK = "feature_work"
    MIXED = "mixed"


def classify_session_type(
    *,
    turns: int,
    duration_seconds: float,
    tool_error_rate: float,
    debug_kw_density: float,
    test_or_spec_mention_rate: float,
    majority_test_files: bool,
    majority_doc_files: bool,
    planning_language: float,
    todos_count: int,
    edited_files_per_turn: float,
    question_ratio: float,
    refactor_kw_density: float,
    review_kw_density: float,
    edit_tool_calls: int,
    create_tool_calls: int,
) -> SessionType:
    if turns <= 3 and duration_seconds < 300.0:
        return SessionType.QUICK_TASK
    if tool_error_rate >= 0.25 or debug_kw_density >= 0.15:
        return SessionType.DEBUGGING
    if test_or_spec_mention_rate >= 0.4 or majority_test_files:
        return SessionType.TESTING
    if majority_doc_files:
        return SessionType.DOCUMENTATION
    if planning_language >= 0.3 and todos_count >= 2 and edited_files_per_turn < 0.5:
        return SessionType.PLANNING
    if question_ratio >= 0.4 and edited_files_per_turn < 0.2:
        return SessionType.EXPLORATION
    if refactor_kw_density >= 0.1 and edit_tool_calls > 0 and create_tool_calls == 0:
        return SessionType.REFACTORING
    if review_kw_density >= 0.1 and edit_tool_calls == 0 and create_tool_calls == 0:
        return SessionType.CODE_REVIEW
    if edited_files_per_turn >= 0.5:
        return SessionType.FEATURE_WORK
    return SessionType.MIXED
```

- [ ] **Step 4: Run the classifier tests, expect PASS**

Run: `pytest tests/test_session_types.py -v`
Expected: All 12 PASS.

- [ ] **Step 5: Wire `session_type` into `SessionFeatures` + `extract_session_features`**

In `src/aianalyzer/features.py`:

a) Add the field on `SessionFeatures`:
```python
from aianalyzer.classifier.session_types import SessionType, classify_session_type

session_type: SessionType = SessionType.MIXED
```

b) Inside `extract_session_features`, after the Task-23 block, compute the keyword densities and call the classifier:
```python
DEBUG_KW = ("error", "exception", "traceback", "stack trace", "fail", "bug", "crash")
TEST_KW  = ("test", "spec", "pytest", "unittest", "jest")
DOC_KW   = (".md", ".rst", ".txt")
REFACTOR_KW = ("refactor", "rename", "cleanup", "tidy", "extract")
REVIEW_KW   = ("review", "look at", "what do you think", "feedback")
PLAN_KW     = ("plan", "design", "approach", "strategy", "outline")

def _density(text: str, vocab: tuple[str, ...]) -> float:
    if not text:
        return 0.0
    low = text.lower()
    words = len(_WORD_RE.findall(text)) or 1
    return sum(low.count(kw) for kw in vocab) / words

all_user = " ".join(t.user.text for t in ns.turns if t.user and t.user.text)
debug_kw_density   = _density(all_user, DEBUG_KW)
refactor_kw_density = _density(all_user, REFACTOR_KW)
review_kw_density   = _density(all_user, REVIEW_KW)
planning_language   = _density(all_user, PLAN_KW)

n_questions = sum(1 for t in ns.turns if t.user and "?" in (t.user.text or ""))
question_ratio = n_questions / max(len(ns.turns), 1)

test_mentions = sum(1 for t in ns.turns if t.user and any(k in (t.user.text or "").lower() for k in TEST_KW))
test_or_spec_mention_rate = test_mentions / max(len(ns.turns), 1)

paths = file_paths_touched
def _is_test(p: str) -> bool:
    low = p.lower()
    return "/test" in low or low.startswith("test") or low.endswith(("_test.py", ".spec.ts", ".spec.js", ".test.ts", ".test.js"))
def _is_doc(p: str) -> bool:
    return p.lower().endswith(DOC_KW)
majority_test_files = bool(paths) and sum(_is_test(p) for p in paths) / len(paths) >= 0.5
majority_doc_files  = bool(paths) and sum(_is_doc(p) for p in paths)  / len(paths) >= 0.5

edit_tool_calls   = tool_counts.get("edit",   0) + tool_counts.get("str_replace_editor", 0)
create_tool_calls = tool_counts.get("create", 0) + tool_counts.get("write", 0)

# `edited_files_per_turn` and `tool_error_rate` already computed for MLP features
# (reuse the local variables; if you renamed them, adapt here).
session_type = classify_session_type(
    turns=len(ns.turns),
    duration_seconds=duration_seconds,
    tool_error_rate=tool_error_rate,
    debug_kw_density=debug_kw_density,
    test_or_spec_mention_rate=test_or_spec_mention_rate,
    majority_test_files=majority_test_files,
    majority_doc_files=majority_doc_files,
    planning_language=planning_language,
    todos_count=len(ns.todos),
    edited_files_per_turn=edited_files_per_turn,
    question_ratio=question_ratio,
    refactor_kw_density=refactor_kw_density,
    review_kw_density=review_kw_density,
    edit_tool_calls=edit_tool_calls,
    create_tool_calls=create_tool_calls,
)
```
Pass `session_type=session_type` to the `SessionFeatures(...)` constructor.

If `duration_seconds`, `tool_error_rate`, or `edited_files_per_turn` are not already local variables in `extract_session_features`, locate where they're computed for the existing `SessionFeatures` fields and hoist them.

- [ ] **Step 6: Run the full suite**

Run: `pytest -q`
Expected: PASS (all tests, including pre-existing 53, the Task-23 test, and the 12 new classifier tests).

- [ ] **Step 7: Bump cache schema version to 4**

In `src/aianalyzer/store.py`, set `SCHEMA_VERSION = 4`.

- [ ] **Step 8: Commit**

```bash
git add src/aianalyzer/classifier/session_types.py tests/test_session_types.py \
        src/aianalyzer/features.py src/aianalyzer/store.py
git commit -m "feat(classifier): per-session purpose classifier (10 types)"
```

---

### Task 25: ExtendedProfile + compute_extended_profile

**Files:**
- Create: `src/aianalyzer/stats.py`
- Create: `tests/test_stats.py`

**Why:** The portal needs ~18 aggregate stats (totals, averages, distributions) on top of the existing `UserProfile`. Computing from the cached `list[SessionFeatures]` keeps the existing classifier pipeline untouched.

- [ ] **Step 1: Write failing tests**

Create `tests/test_stats.py`:
```python
from datetime import datetime, timezone

from aianalyzer.classifier.session_types import SessionType
from aianalyzer.features import SessionFeatures
from aianalyzer.stats import ExtendedProfile, compute_extended_profile


def _sf(**overrides) -> SessionFeatures:
    base = dict(
        client="copilot_cli",
        session_id="sid",
        path="/x",
        started_at=datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
        ended_at=datetime(2026, 6, 1, 10, 30, tzinfo=timezone.utc),
        turns_count=4,
        user_message_count=2,
        assistant_message_count=2,
        avg_user_msg_chars=50.0,
        edited_files=2,
        edited_files_per_turn=0.5,
        tool_call_count=3,
        tool_error_rate=0.0,
        abort_rate=0.0,
        todos_count=0,
        duration_seconds=1800.0,
        # M4 fields:
        cwd="/repos/proj-a",
        avg_user_msg_words=10.0,
        tool_counts={"edit": 2, "read": 1},
        file_paths_touched={"src/a.py", "src/b.py"},
        started_hour_local=10,
        started_weekday=0,
        models_used={"claude-sonnet-4.5": 4},
        session_type=SessionType.FEATURE_WORK,
    )
    base.update(overrides)
    return SessionFeatures(**base)


def test_compute_extended_profile_aggregates_basics():
    sessions = [
        _sf(session_id="s1"),
        _sf(session_id="s2",
            started_at=datetime(2026, 6, 2, 14, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 6, 2, 14, 45, tzinfo=timezone.utc),
            duration_seconds=2700.0,
            turns_count=6,
            session_type=SessionType.DEBUGGING,
            cwd="/repos/proj-b",
            tool_counts={"bash": 2, "edit": 1},
            file_paths_touched={"src/x.py"},
            models_used={"gpt-5": 5},
            avg_user_msg_words=20.0,
            started_hour_local=14,
            started_weekday=1,
        ),
    ]
    p = compute_extended_profile(sessions)
    assert isinstance(p, ExtendedProfile)
    assert p.total_sessions == 2
    assert p.total_turns == 10
    assert p.total_hours == pytest_approx(1.25)
    assert p.avg_turns_per_session == 5.0
    assert p.avg_session_minutes == pytest_approx(37.5)
    assert p.session_type_counts == {"feature_work": 1, "debugging": 1}
    assert "edit" in dict(p.top_tools)
    assert "/repos/proj-a" in dict(p.top_projects)
    assert "claude-sonnet-4.5" in dict(p.top_models)
    assert sum(p.hour_histogram) == 2
    assert sum(p.weekday_histogram) == 2
    assert p.avg_prompt_words == pytest_approx(15.0)


def test_compute_extended_profile_handles_empty_input():
    p = compute_extended_profile([])
    assert p.total_sessions == 0
    assert p.total_turns == 0
    assert p.session_type_counts == {}
    assert p.top_tools == []


def pytest_approx(v: float, rel: float = 1e-6):
    import pytest as _p
    return _p.approx(v, rel=rel)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_stats.py -v`
Expected: FAIL with `ModuleNotFoundError: aianalyzer.stats`.

- [ ] **Step 3: Implement `ExtendedProfile` + aggregator**

Create `src/aianalyzer/stats.py`:
```python
"""Aggregate statistics for the portal (M4)."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Iterable

from aianalyzer.features import SessionFeatures


@dataclass
class ExtendedProfile:
    total_sessions: int = 0
    total_turns: int = 0
    total_hours: float = 0.0
    days_active: int = 0
    longest_streak_days: int = 0
    first_session_at: datetime | None = None
    last_session_at: datetime | None = None
    acceptance_rate: float = 0.0
    avg_turns_per_session: float = 0.0
    avg_session_minutes: float = 0.0
    avg_prompt_words: float = 0.0
    median_prompt_words: float = 0.0
    p90_prompt_words: float = 0.0
    top_tools: list[tuple[str, int]] = field(default_factory=list)
    top_projects: list[tuple[str, int]] = field(default_factory=list)
    top_models: list[tuple[str, int]] = field(default_factory=list)
    top_file_extensions: list[tuple[str, int]] = field(default_factory=list)
    session_type_counts: dict[str, int] = field(default_factory=dict)
    hour_histogram: list[int] = field(default_factory=lambda: [0] * 24)
    weekday_histogram: list[int] = field(default_factory=lambda: [0] * 7)
    activity_per_day_last_90: list[tuple[str, int]] = field(default_factory=list)


def _p(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _ext(path: str) -> str | None:
    if "." not in path.rsplit("/", 1)[-1]:
        return None
    return "." + path.rsplit(".", 1)[-1].lower()


def compute_extended_profile(features: Iterable[SessionFeatures]) -> ExtendedProfile:
    fs = list(features)
    p = ExtendedProfile()
    if not fs:
        return p

    p.total_sessions = len(fs)
    p.total_turns = sum(f.turns_count for f in fs)
    p.total_hours = sum(f.duration_seconds for f in fs) / 3600.0
    p.avg_turns_per_session = p.total_turns / p.total_sessions
    p.avg_session_minutes = (p.total_hours * 60.0) / p.total_sessions
    p.acceptance_rate = 1.0 - (sum(f.abort_rate for f in fs) / p.total_sessions)

    starts = [f.started_at for f in fs if f.started_at is not None]
    if starts:
        p.first_session_at = min(starts)
        p.last_session_at = max(starts)

    # Day activity (local date of started_at)
    by_day: Counter[date] = Counter()
    for s in starts:
        by_day[s.astimezone().date()] += 1
    p.days_active = len(by_day)

    # Longest consecutive-day streak
    if by_day:
        days_sorted = sorted(by_day)
        streak = best = 1
        for prev, cur in zip(days_sorted, days_sorted[1:]):
            if (cur - prev).days == 1:
                streak += 1
                best = max(best, streak)
            else:
                streak = 1
        p.longest_streak_days = best

    # Last-90-day activity
    today = datetime.now(timezone.utc).date()
    window = [today - timedelta(days=i) for i in range(89, -1, -1)]
    p.activity_per_day_last_90 = [(d.isoformat(), by_day.get(d, 0)) for d in window]

    # Prompt-length distribution (word-level)
    word_counts = [f.avg_user_msg_words for f in fs if f.avg_user_msg_words > 0]
    if word_counts:
        p.avg_prompt_words = sum(word_counts) / len(word_counts)
        p.median_prompt_words = float(median(word_counts))
        p.p90_prompt_words = _p(word_counts, 0.9)

    # Top-N aggregations
    tool_totals: Counter[str] = Counter()
    project_totals: Counter[str] = Counter()
    model_totals: Counter[str] = Counter()
    ext_totals: Counter[str] = Counter()
    type_totals: Counter[str] = Counter()

    for f in fs:
        tool_totals.update(f.tool_counts)
        if f.cwd:
            project_totals[f.cwd] += 1
        model_totals.update(f.models_used)
        for path in f.file_paths_touched:
            e = _ext(path)
            if e:
                ext_totals[e] += 1
        type_totals[f.session_type.value] += 1
        p.hour_histogram[f.started_hour_local] += 1
        p.weekday_histogram[f.started_weekday] += 1

    p.top_tools = tool_totals.most_common(12)
    p.top_projects = project_totals.most_common(12)
    p.top_models = model_totals.most_common(12)
    p.top_file_extensions = ext_totals.most_common(12)
    p.session_type_counts = dict(type_totals)

    return p
```

- [ ] **Step 4: Run tests to verify PASS**

Run: `pytest tests/test_stats.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run full suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/aianalyzer/stats.py tests/test_stats.py
git commit -m "feat(stats): ExtendedProfile aggregator for portal"
```

---

### Task 26: Narrative generator (subprocess wrapper for `copilot`)

**Files:**
- Create: `src/aianalyzer/narrative.py`
- Create: `tests/test_narrative.py`

**Why:** The portal exposes a button that generates an LLM-written "AI profile" narrative. We invoke the user's installed `copilot` CLI as a subprocess. Two layers: `build_narrative_prompt` (pure) and `generate_narrative` (subprocess) keep things test-friendly.

- [ ] **Step 1: Write failing tests**

Create `tests/test_narrative.py`:
```python
import subprocess
import textwrap

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
        "secondary_archetype": Archetype.COLLABORATOR.value,
        "confidence": 0.78,
        "axes": {"planning": 0.32, "control": 0.37, "depth": 0.05, "speed": -0.10},
        "totals": {"sessions": 168, "turns": 1820, "hours": 92.4, "days_active": 41},
        "top_tools": [("edit", 220), ("read", 180)],
        "top_projects": [("/repos/aianalyzer", 80)],
        "top_models": [("claude-sonnet-4.5", 600)],
        "session_type_counts": {"feature_work": 60, "debugging": 40},
    }


def test_build_narrative_prompt_includes_key_facts():
    prompt = build_narrative_prompt(_facts())
    assert "Architect" in prompt
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
            args=cmd, returncode=0, stdout="# Your AI Profile\n\nYou are an Architect.\n", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = generate_narrative(_facts(), copilot_binary="copilot")
    assert out.startswith("# Your AI Profile")
    assert captured["cmd"][0] == "copilot"
    assert "-p" in captured["cmd"]
    assert "--allow-all-tools" in captured["cmd"]
    assert "--no-color" in captured["cmd"]
    assert "-s" in captured["cmd"]


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
```

- [ ] **Step 2: Run tests, expect failure**

Run: `pytest tests/test_narrative.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement the narrative module**

Create `src/aianalyzer/narrative.py`:
```python
"""LLM narrative generator backed by the local GitHub Copilot CLI."""
from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any


class NarrativeError(RuntimeError):
    """Raised when the copilot subprocess fails or times out."""


_PROMPT_TEMPLATE = """\
You are writing an "AI Collaboration Profile" for a developer based on aggregated,
anonymised statistics from their local AI coding sessions. Do NOT invent any facts —
only use the JSON below.

Write the profile in **Markdown** with these sections, in this order:

1. `# Your AI Profile` — a one-paragraph headline summary that names the primary
   archetype and the dominant collaboration style in plain language.
2. `## How you work with AI` — 3-5 bullets describing observed habits
   (planning, control, depth, speed). Quote the most striking numbers.
3. `## What you build` — 2-3 bullets covering top projects, top tools, and the
   mix of session types.
4. `## Suggestions to grow` — 2-3 concrete, kind, archetype-aware suggestions.
   Avoid generic advice; tie each to a fact from the data.

Tone: warm, specific, second-person ("you"). Avoid hype. No emojis. ~250-400 words.

DATA:
```json
{facts_json}
```
"""


def build_narrative_prompt(facts: dict[str, Any]) -> str:
    """Render the prompt string from a facts dict (pure function, easy to test)."""
    return _PROMPT_TEMPLATE.format(facts_json=json.dumps(facts, indent=2, default=str))


def generate_narrative(
    facts: dict[str, Any],
    *,
    copilot_binary: str = "copilot",
    timeout_sec: float = 180.0,
) -> str:
    """Invoke the Copilot CLI to produce a Markdown narrative.

    Raises NarrativeError if the binary is missing, exits non-zero, or times out.
    """
    if shutil.which(copilot_binary) is None and copilot_binary == "copilot":
        # Tests monkeypatch subprocess.run, so this check is a friendly-error
        # only for real invocations.
        pass  # don't fail eagerly; let subprocess.run raise FileNotFoundError if needed.

    prompt = build_narrative_prompt(facts)
    cmd = [
        copilot_binary,
        "-p", prompt,
        "--allow-all-tools",
        "--no-color",
        "-s",
        "--output-format", "text",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise NarrativeError(f"copilot CLI timed out after {timeout_sec}s") from e
    except FileNotFoundError as e:
        raise NarrativeError(
            "copilot CLI binary not found on PATH; install GitHub Copilot CLI."
        ) from e

    if proc.returncode != 0:
        raise NarrativeError(
            f"copilot CLI exited {proc.returncode}: {proc.stderr.strip()[:500]}"
        )
    return proc.stdout
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `pytest tests/test_narrative.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Run full suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/aianalyzer/narrative.py tests/test_narrative.py
git commit -m "feat(narrative): copilot CLI subprocess wrapper for AI profile narrative"
```

---

### Task 27: Add web deps + FastAPI server skeleton + vendor Chart.js

**Files:**
- Modify: `pyproject.toml`
- Create: `src/aianalyzer/web/__init__.py` (empty)
- Create: `src/aianalyzer/web/app.py`
- Create: `src/aianalyzer/web/static/` (directory)
- Create: `src/aianalyzer/web/static/chart.umd.js` (vendored)
- Create: `src/aianalyzer/web/static/.gitkeep`
- Create: `tests/test_web_skeleton.py`

**Why:** Establish the server entry point + serve static assets before adding routes. Vendor Chart.js so the portal works offline (the user is local-first by design).

- [ ] **Step 1: Add deps to `pyproject.toml`**

In `[project] dependencies`, append:
```toml
"fastapi>=0.110",
"uvicorn[standard]>=0.27",
"httpx>=0.27",  # FastAPI's TestClient dependency
```
Add (or update) `[tool.hatch.build.targets.wheel.force-include]`:
```toml
[tool.hatch.build.targets.wheel.force-include]
"src/aianalyzer/web/static" = "aianalyzer/web/static"
```
If a `force-include` block already exists from MLP, *add* the line — don't replace.

- [ ] **Step 2: Install deps**

Run: `pip install -e .[dev]` (or `pip install -e .` if no `dev` extra exists).
Expected: pip resolves FastAPI / Uvicorn / httpx without errors.

- [ ] **Step 3: Vendor Chart.js**

Create `src/aianalyzer/web/static/.gitkeep` (empty file so the directory ships).
Download Chart.js 4.4.x UMD build to `src/aianalyzer/web/static/chart.umd.js`:
```bash
curl -fsSL https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.js \
  -o src/aianalyzer/web/static/chart.umd.js
```
(Note: v4 ships `.umd.js`, NOT `.umd.min.js`.) Verify the file is >100 KB and starts with `/*!` or `(function`.

- [ ] **Step 4: Write the failing skeleton test**

Create `tests/test_web_skeleton.py`:
```python
from fastapi.testclient import TestClient

from aianalyzer.web.app import create_app


def test_app_serves_health():
    client = TestClient(create_app())
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_app_serves_static_chart_js():
    client = TestClient(create_app())
    r = client.get("/static/chart.umd.js")
    assert r.status_code == 200
    assert "Chart" in r.text  # vendored Chart.js
```

- [ ] **Step 5: Run test, expect FAIL**

Run: `pytest tests/test_web_skeleton.py -v`
Expected: FAIL (`aianalyzer.web.app` missing).

- [ ] **Step 6: Implement the skeleton**

Create `src/aianalyzer/web/__init__.py` (empty).

Create `src/aianalyzer/web/app.py`:
```python
"""FastAPI app factory for the AIAnalyzer portal."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="AIAnalyzer Portal", version="0.2.0")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
```

- [ ] **Step 7: Run tests, expect PASS**

Run: `pytest tests/test_web_skeleton.py -v`
Expected: 2 PASS.

- [ ] **Step 8: Run full suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml src/aianalyzer/web/ tests/test_web_skeleton.py
git commit -m "feat(web): FastAPI skeleton + vendored Chart.js"
```

---

### Task 28: API endpoints — POST /api/scan, GET /api/jobs/{id}, GET /api/profile

**Files:**
- Create: `src/aianalyzer/web/jobs.py`
- Create: `src/aianalyzer/web/services.py`
- Modify: `src/aianalyzer/web/app.py`
- Create: `tests/test_web_api.py`

**Why:** Backend for the portal. Scan runs in a background thread (long for big mailbox-sized session sets); profile is recomputed synchronously from the FeatureStore cache.

- [ ] **Step 1: Failing tests**

Create `tests/test_web_api.py`:
```python
import time

from fastapi.testclient import TestClient

from aianalyzer.web.app import create_app


def test_scan_then_profile_end_to_end(tmp_path, monkeypatch):
    # Point the app at an empty cache dir so the scan finds 0 sessions but still succeeds.
    monkeypatch.setenv("AIANALYZER_CACHE_DIR", str(tmp_path))
    # Stub the collectors so we don't depend on the user's real sessions.
    from aianalyzer.web import services
    monkeypatch.setattr(services, "discover_all_sessions", lambda: [])

    client = TestClient(create_app())

    # Kick off a scan.
    r = client.post("/api/scan", json={})
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    # Poll until done (deterministic — the stub returns []).
    deadline = time.time() + 5
    while time.time() < deadline:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert j["status"] == "done", j

    # Profile is computable even from zero sessions.
    p = client.get("/api/profile").json()
    assert p["totals"]["sessions"] == 0
    assert "primary_archetype" in p
    assert "session_type_counts" in p


def test_jobs_returns_404_for_unknown_id():
    client = TestClient(create_app())
    r = client.get("/api/jobs/nope")
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests, expect FAIL**

Run: `pytest tests/test_web_api.py -v`
Expected: FAIL (routes don't exist).

- [ ] **Step 3: Implement the job registry**

Create `src/aianalyzer/web/jobs.py`:
```python
"""Thread-safe in-memory job registry (single-user, local-only)."""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Job:
    id: str
    status: str = "pending"  # pending | running | done | failed
    progress: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0
    result: Any = None
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, **meta: Any) -> Job:
        job = Job(id=uuid.uuid4().hex, meta=meta)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def run(self, job: Job, target: Callable[[Job], Any]) -> None:
        def _runner() -> None:
            job.status = "running"
            job.started_at = time.time()
            try:
                job.result = target(job)
                job.status = "done"
            except Exception as exc:  # noqa: BLE001
                job.error = f"{type(exc).__name__}: {exc}"
                job.status = "failed"
            finally:
                job.finished_at = time.time()
        threading.Thread(target=_runner, daemon=True).start()


REGISTRY = JobRegistry()
```

- [ ] **Step 4: Implement the services layer**

Create `src/aianalyzer/web/services.py`:
```python
"""Glue between FastAPI routes and the existing classifier pipeline."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from aianalyzer.classifier.archetypes import Archetype
from aianalyzer.classifier.rules import classify
from aianalyzer.collectors import discover_all_sessions  # MLP-era helper
from aianalyzer.features import aggregate_user_profile, extract_session_features
from aianalyzer.normalize import normalize_session
from aianalyzer.stats import compute_extended_profile
from aianalyzer.store import FeatureStore


def _cache_path() -> Path:
    override = os.environ.get("AIANALYZER_CACHE_DIR")
    base = Path(override) if override else Path.home() / ".aianalyzer"
    base.mkdir(parents=True, exist_ok=True)
    return base / "cache.duckdb"


def run_scan(progress_cb=None) -> dict[str, int]:
    """Discover -> normalize -> extract -> cache. Returns counts."""
    store = FeatureStore(_cache_path())
    discovered = list(discover_all_sessions())
    total = len(discovered)
    new = 0
    for i, ds in enumerate(discovered):
        cached = store.get(ds.client, ds.session_id, mtime=ds.mtime)
        if cached is None:
            ns = normalize_session(ds)
            sf = extract_session_features(ns)
            store.upsert(ds.client, sf, mtime=ds.mtime)
            new += 1
        if progress_cb:
            progress_cb((i + 1) / max(total, 1))
    return {"discovered": total, "new": new}


def load_profile_payload() -> dict[str, Any]:
    store = FeatureStore(_cache_path())
    features = list(store.iter_all())
    user_profile = aggregate_user_profile(features)
    classification = classify(user_profile)
    ext = compute_extended_profile(features)
    return {
        "primary_archetype": classification.primary.value,
        "secondary_archetype": classification.secondary.value if classification.secondary else None,
        "confidence": classification.confidence,
        "axes": classification.axes,
        "totals": {
            "sessions": ext.total_sessions,
            "turns": ext.total_turns,
            "hours": round(ext.total_hours, 2),
            "days_active": ext.days_active,
            "longest_streak_days": ext.longest_streak_days,
        },
        "averages": {
            "turns_per_session": round(ext.avg_turns_per_session, 2),
            "session_minutes": round(ext.avg_session_minutes, 2),
            "prompt_words": round(ext.avg_prompt_words, 2),
            "median_prompt_words": round(ext.median_prompt_words, 2),
            "p90_prompt_words": round(ext.p90_prompt_words, 2),
            "acceptance_rate": round(ext.acceptance_rate, 3),
        },
        "top_tools": ext.top_tools,
        "top_projects": ext.top_projects,
        "top_models": ext.top_models,
        "top_file_extensions": ext.top_file_extensions,
        "session_type_counts": ext.session_type_counts,
        "hour_histogram": ext.hour_histogram,
        "weekday_histogram": ext.weekday_histogram,
        "activity_per_day_last_90": ext.activity_per_day_last_90,
        "first_session_at": ext.first_session_at.isoformat() if ext.first_session_at else None,
        "last_session_at": ext.last_session_at.isoformat() if ext.last_session_at else None,
    }
```
NOTE: If `discover_all_sessions` is not the actual symbol used by the MLP CLI, open `src/aianalyzer/collectors/__init__.py` and re-export the discovery function (e.g. `from .copilot_cli import discover_copilot_cli_sessions`, then wrap a `discover_all_sessions` helper). The test stub monkeypatches `services.discover_all_sessions`, so the test still runs even if the real implementation is multi-client.

If `FeatureStore` doesn't yet have `iter_all()`, add it now to `src/aianalyzer/store.py`:
```python
def iter_all(self) -> Iterator[SessionFeatures]:
    with self._conn() as conn:
        rows = conn.execute(
            "SELECT json FROM session_features WHERE schema_version = ?",
            [SCHEMA_VERSION],
        ).fetchall()
    for (j,) in rows:
        yield SessionFeatures.model_validate_json(j)
```

- [ ] **Step 5: Wire routes in `app.py`**

Edit `src/aianalyzer/web/app.py`:
```python
from fastapi import HTTPException
from pydantic import BaseModel

from aianalyzer.web.jobs import REGISTRY
from aianalyzer.web import services


class ScanRequest(BaseModel):
    pass  # placeholder for future filters


def create_app() -> FastAPI:
    app = FastAPI(title="AIAnalyzer Portal", version="0.2.0")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/scan", status_code=202)
    def start_scan(_: ScanRequest) -> dict[str, str]:
        job = REGISTRY.create(kind="scan")

        def _do(j):
            return services.run_scan(progress_cb=lambda p: setattr(j, "progress", p))

        REGISTRY.run(job, _do)
        return {"job_id": job.id}

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict:
        j = REGISTRY.get(job_id)
        if j is None:
            raise HTTPException(404, detail="job not found")
        return {
            "id": j.id,
            "status": j.status,
            "progress": j.progress,
            "result": j.result,
            "error": j.error,
        }

    @app.get("/api/profile")
    def profile() -> dict:
        return services.load_profile_payload()

    return app
```

- [ ] **Step 6: Run API tests**

Run: `pytest tests/test_web_api.py -v`
Expected: 2 PASS. If `aggregate_user_profile` blows up on an empty list, add an `if not features: return UserProfile(...defaults...)` guard inside `aggregate_user_profile` (one-line fix). Then re-run.

- [ ] **Step 7: Run full suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/aianalyzer/web/ src/aianalyzer/store.py tests/test_web_api.py
git commit -m "feat(web): scan job + profile endpoints"
```

---

### Task 29: Narrative API endpoints (job-based, not streaming)

**Files:**
- Modify: `src/aianalyzer/web/app.py`
- Modify: `tests/test_web_api.py` (append)

**Why:** Narrative generation can take 30-180s. Run it in a background thread under the same job pattern as scan. Polling-based (Windows-friendly).

- [ ] **Step 1: Failing tests (append to `tests/test_web_api.py`)**

```python
def test_narrative_start_returns_job_and_completes(monkeypatch):
    from aianalyzer.web import services

    # Make /api/profile cheap and deterministic.
    monkeypatch.setattr(services, "load_profile_payload", lambda: {
        "primary_archetype": "architect", "secondary_archetype": None,
        "confidence": 0.5, "axes": {}, "totals": {"sessions": 1, "turns": 1, "hours": 0.1, "days_active": 1, "longest_streak_days": 1},
        "averages": {}, "top_tools": [], "top_projects": [], "top_models": [],
        "top_file_extensions": [], "session_type_counts": {}, "hour_histogram": [0]*24,
        "weekday_histogram": [0]*7, "activity_per_day_last_90": [],
        "first_session_at": None, "last_session_at": None,
    })

    # Stub the narrative generator to avoid invoking the real copilot binary.
    from aianalyzer import narrative as nar
    monkeypatch.setattr(nar, "generate_narrative", lambda facts, **_: "# Your AI Profile\n\nfake")

    client = TestClient(create_app())
    r = client.post("/api/narrative/start")
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    deadline = time.time() + 5
    while time.time() < deadline:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert j["status"] == "done", j
    assert j["result"]["markdown"].startswith("# Your AI Profile")


def test_narrative_job_reports_failure(monkeypatch):
    from aianalyzer.web import services
    monkeypatch.setattr(services, "load_profile_payload", lambda: {
        "primary_archetype": "architect", "secondary_archetype": None,
        "confidence": 0.5, "axes": {}, "totals": {"sessions": 0, "turns": 0, "hours": 0, "days_active": 0, "longest_streak_days": 0},
        "averages": {}, "top_tools": [], "top_projects": [], "top_models": [],
        "top_file_extensions": [], "session_type_counts": {}, "hour_histogram": [0]*24,
        "weekday_histogram": [0]*7, "activity_per_day_last_90": [],
        "first_session_at": None, "last_session_at": None,
    })

    from aianalyzer import narrative as nar
    def boom(*_a, **_kw):
        raise nar.NarrativeError("copilot exited 2")
    monkeypatch.setattr(nar, "generate_narrative", boom)

    client = TestClient(create_app())
    r = client.post("/api/narrative/start")
    job_id = r.json()["job_id"]

    deadline = time.time() + 5
    while time.time() < deadline:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert j["status"] == "failed"
    assert "copilot exited" in j["error"]
```

- [ ] **Step 2: Run tests, expect FAIL**

Run: `pytest tests/test_web_api.py -v`
Expected: FAIL (route 404).

- [ ] **Step 3: Add the narrative route to `app.py`**

In `src/aianalyzer/web/app.py`, inside `create_app()`:
```python
from aianalyzer import narrative as _narrative

@app.post("/api/narrative/start", status_code=202)
def start_narrative() -> dict[str, str]:
    job = REGISTRY.create(kind="narrative")

    def _do(_j):
        facts = services.load_profile_payload()
        md = _narrative.generate_narrative(facts)
        return {"markdown": md}

    REGISTRY.run(job, _do)
    return {"job_id": job.id}
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `pytest tests/test_web_api.py -v`
Expected: All 4 PASS (2 prior + 2 new).

- [ ] **Step 5: Run full suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/aianalyzer/web/app.py tests/test_web_api.py
git commit -m "feat(web): narrative job endpoint backed by copilot CLI"
```

---

### Task 30: Frontend skeleton — index.html + styles.css + served from `/`

**Files:**
- Create: `src/aianalyzer/web/static/index.html`
- Create: `src/aianalyzer/web/static/styles.css`
- Create: `src/aianalyzer/web/static/app.js` (empty stub)
- Modify: `src/aianalyzer/web/app.py` (serve index at `/`)
- Modify: `tests/test_web_skeleton.py` (append)

**Why:** A static SPA shell that gets wired up in Tasks 31-33. Keeping HTML/CSS minimal and dependency-free (only Chart.js + vanilla JS) makes the portal easy to read and trust.

- [ ] **Step 1: Append failing test**

In `tests/test_web_skeleton.py`:
```python
def test_root_serves_index_html():
    client = TestClient(create_app())
    r = client.get("/")
    assert r.status_code == 200
    assert "AIAnalyzer" in r.text
    assert "chart.umd.js" in r.text
```

- [ ] **Step 2: Run test, expect FAIL**

Run: `pytest tests/test_web_skeleton.py::test_root_serves_index_html -v`
Expected: FAIL (404).

- [ ] **Step 3: Create static assets**

Create `src/aianalyzer/web/static/index.html`:
```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AIAnalyzer — Your AI Profile</title>
  <link rel="stylesheet" href="/static/styles.css" />
</head>
<body>
  <header class="topbar">
    <div class="brand">AIAnalyzer</div>
    <div class="actions">
      <button id="scan-btn">Scan sessions</button>
      <button id="narrate-btn">Generate AI profile</button>
    </div>
  </header>

  <main id="app">
    <section id="hero" class="card">
      <h1 id="hero-archetype">Loading your profile…</h1>
      <p id="hero-summary"></p>
      <div id="hero-axes" class="axes"></div>
    </section>

    <section class="grid">
      <div class="card kpi" id="kpi-sessions"><h3>Sessions</h3><div class="big">–</div></div>
      <div class="card kpi" id="kpi-turns"><h3>Turns</h3><div class="big">–</div></div>
      <div class="card kpi" id="kpi-hours"><h3>Hours</h3><div class="big">–</div></div>
      <div class="card kpi" id="kpi-days"><h3>Active days</h3><div class="big">–</div></div>
      <div class="card kpi" id="kpi-avg-prompt"><h3>Avg prompt (words)</h3><div class="big">–</div></div>
      <div class="card kpi" id="kpi-acceptance"><h3>Acceptance</h3><div class="big">–</div></div>
    </section>

    <section class="charts">
      <div class="card"><h3>Session types</h3><canvas id="chart-session-types"></canvas></div>
      <div class="card"><h3>Top tools</h3><canvas id="chart-top-tools"></canvas></div>
      <div class="card"><h3>Activity (last 90 days)</h3><canvas id="chart-activity"></canvas></div>
      <div class="card"><h3>Time of day</h3><canvas id="chart-hour"></canvas></div>
    </section>

    <section class="tables">
      <div class="card"><h3>Top projects</h3><ol id="top-projects"></ol></div>
      <div class="card"><h3>Top models</h3><ol id="top-models"></ol></div>
      <div class="card"><h3>Top file types</h3><ol id="top-exts"></ol></div>
    </section>

    <section id="narrative-section" class="card hidden">
      <h2>Your AI Profile</h2>
      <div id="narrative-status"></div>
      <article id="narrative-md"></article>
    </section>
  </main>

  <script src="/static/chart.umd.js"></script>
  <script src="/static/app.js" type="module"></script>
</body>
</html>
```

Create `src/aianalyzer/web/static/styles.css`:
```css
:root {
  --bg: #0e1117;
  --card: #161b22;
  --fg: #e6edf3;
  --muted: #9aa4af;
  --accent: #58a6ff;
  --border: #30363d;
}
* { box-sizing: border-box; }
body { margin: 0; font: 14px/1.45 system-ui, sans-serif; background: var(--bg); color: var(--fg); }
.topbar { display: flex; justify-content: space-between; align-items: center;
  padding: 12px 24px; border-bottom: 1px solid var(--border); }
.brand { font-weight: 600; font-size: 18px; }
.actions button { background: var(--accent); color: #000; border: 0; padding: 8px 14px;
  border-radius: 6px; cursor: pointer; margin-left: 8px; font-weight: 600; }
.actions button:disabled { opacity: 0.5; cursor: wait; }
main { padding: 24px; max-width: 1200px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
.kpi h3 { margin: 0 0 6px; font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
.kpi .big { font-size: 28px; font-weight: 700; }
.charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }
.charts canvas { max-height: 260px; }
.tables { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
.tables ol { margin: 0; padding-left: 18px; color: var(--muted); }
.tables ol li span { color: var(--fg); }
.axes { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 12px; }
.axes .axis { background: #0a0e14; border: 1px solid var(--border); border-radius: 6px; padding: 8px; text-align: center; }
.axes .axis .name { color: var(--muted); font-size: 11px; text-transform: uppercase; }
.axes .axis .value { font-size: 18px; font-weight: 600; margin-top: 4px; }
.hidden { display: none; }
#narrative-md { white-space: pre-wrap; }
```

Create `src/aianalyzer/web/static/app.js` with a single line so the file ships:
```js
// Wired up in Task 31.
```

- [ ] **Step 4: Serve `index.html` from `/` in `app.py`**

In `src/aianalyzer/web/app.py`, before `return app`:
```python
from fastapi.responses import FileResponse

@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
```

- [ ] **Step 5: Run test, expect PASS**

Run: `pytest tests/test_web_skeleton.py -v`
Expected: 3 PASS.

- [ ] **Step 6: Visual smoke (manual, optional)**

Run: `python -m uvicorn aianalyzer.web.app:create_app --factory --reload --port 8765`
Open `http://127.0.0.1:8765/` in a browser. Expect: dark UI, header with two buttons, KPI placeholders showing `–`. No console errors except `app.js` is empty.
Stop with Ctrl+C.

- [ ] **Step 7: Run full suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/aianalyzer/web/static/index.html src/aianalyzer/web/static/styles.css \
        src/aianalyzer/web/static/app.js src/aianalyzer/web/app.py tests/test_web_skeleton.py
git commit -m "feat(web): static frontend skeleton (index, styles, root route)"
```

---

### Task 31: Frontend logic — fetch /api/profile + render hero + KPI grid + tables

**Files:**
- Modify: `src/aianalyzer/web/static/app.js`

**Why:** Make the page actually show data. No tests here — this is browser code that's exercised in Task 35's end-to-end smoke. Keep it tiny and readable.

- [ ] **Step 1: Replace `app.js` with the data-loading logic**

```js
// Tiny vanilla-JS app for AIAnalyzer portal.

const $ = (sel) => document.querySelector(sel);

const AXIS_LABEL = { planning: "Planning", control: "Control", depth: "Depth", speed: "Speed" };

async function fetchProfile() {
  const r = await fetch("/api/profile");
  if (!r.ok) throw new Error(`profile fetch failed: ${r.status}`);
  return r.json();
}

function renderHero(p) {
  const archetype = (p.primary_archetype || "unknown").replace(/^./, c => c.toUpperCase());
  const secondary = p.secondary_archetype ? ` · secondary ${p.secondary_archetype}` : "";
  $("#hero-archetype").textContent = `You are an ${archetype}${secondary}`;
  $("#hero-summary").textContent =
    `Confidence ${(p.confidence * 100).toFixed(0)}% · based on ${p.totals.sessions} sessions.`;

  const axesEl = $("#hero-axes");
  axesEl.innerHTML = "";
  for (const [key, label] of Object.entries(AXIS_LABEL)) {
    const v = p.axes?.[key];
    if (v === undefined) continue;
    const div = document.createElement("div");
    div.className = "axis";
    div.innerHTML = `<div class="name">${label}</div><div class="value">${v.toFixed(2)}</div>`;
    axesEl.appendChild(div);
  }
}

function renderKpis(p) {
  $("#kpi-sessions .big").textContent = p.totals.sessions ?? "–";
  $("#kpi-turns .big").textContent = p.totals.turns ?? "–";
  $("#kpi-hours .big").textContent = (p.totals.hours ?? 0).toFixed(1);
  $("#kpi-days .big").textContent = p.totals.days_active ?? "–";
  $("#kpi-avg-prompt .big").textContent = (p.averages?.prompt_words ?? 0).toFixed(0);
  $("#kpi-acceptance .big").textContent = ((p.averages?.acceptance_rate ?? 0) * 100).toFixed(0) + "%";
}

function renderList(elId, items, labelKey = null) {
  const el = $(elId);
  el.innerHTML = "";
  for (const [name, n] of (items ?? [])) {
    const li = document.createElement("li");
    li.innerHTML = `<span>${name}</span> &middot; ${n}`;
    el.appendChild(li);
  }
}

async function load() {
  try {
    const p = await fetchProfile();
    renderHero(p);
    renderKpis(p);
    renderList("#top-projects", p.top_projects);
    renderList("#top-models", p.top_models);
    renderList("#top-exts", p.top_file_extensions);
    window.__profile = p; // handed to Task 32 chart code
    window.dispatchEvent(new CustomEvent("profile-loaded", { detail: p }));
  } catch (e) {
    $("#hero-archetype").textContent = "Could not load profile";
    $("#hero-summary").textContent = String(e);
  }
}

$("#scan-btn").addEventListener("click", async () => {
  const btn = $("#scan-btn");
  btn.disabled = true;
  btn.textContent = "Scanning…";
  try {
    const { job_id } = await (await fetch("/api/scan", { method: "POST",
      headers: { "content-type": "application/json" }, body: "{}" })).json();
    await pollJob(job_id, (j) => { btn.textContent = `Scanning ${Math.round((j.progress || 0) * 100)}%…`; });
    await load();
  } finally {
    btn.disabled = false;
    btn.textContent = "Scan sessions";
  }
});

async function pollJob(id, onTick) {
  while (true) {
    const j = await (await fetch(`/api/jobs/${id}`)).json();
    onTick?.(j);
    if (j.status === "done" || j.status === "failed") return j;
    await new Promise(r => setTimeout(r, 400));
  }
}

window.pollJob = pollJob; // shared with narrative button in Task 33
load();
```

- [ ] **Step 2: Visual smoke (manual)**

Run: `python -m uvicorn aianalyzer.web.app:create_app --factory --reload --port 8765`
Open the page in a browser. Click **Scan sessions** — button shows progress, profile reloads, KPIs and tables populate.
Stop with Ctrl+C.

- [ ] **Step 3: Run full suite**

Run: `pytest -q`
Expected: PASS (no new tests; backend untouched).

- [ ] **Step 4: Commit**

```bash
git add src/aianalyzer/web/static/app.js
git commit -m "feat(web): render hero, KPIs, and top-N tables on load"
```

---

### Task 32: Frontend charts (session-type pie, top-tools bar, activity line, hour bar)

**Files:**
- Create: `src/aianalyzer/web/static/charts.js`
- Modify: `src/aianalyzer/web/static/index.html` (load `charts.js` after `app.js`)

**Why:** Charts make the data legible. Keep the chart code in its own file so `app.js` stays small and the chart wiring is easy to read.

- [ ] **Step 1: Create `charts.js`**

`src/aianalyzer/web/static/charts.js`:
```js
// Listens for the 'profile-loaded' event from app.js and renders Chart.js charts.

const COLOR_PALETTE = [
  "#58a6ff", "#3fb950", "#d29922", "#f85149", "#bc8cff",
  "#39c5cf", "#ff8c47", "#a371f7", "#7ee787", "#ffa657",
];

function makePieChart(ctx, labels, data) {
  return new Chart(ctx, {
    type: "doughnut",
    data: {
      labels,
      datasets: [{ data, backgroundColor: labels.map((_, i) => COLOR_PALETTE[i % COLOR_PALETTE.length]) }],
    },
    options: { plugins: { legend: { position: "right", labels: { color: "#e6edf3" } } } },
  });
}

function makeBarChart(ctx, labels, data, label) {
  return new Chart(ctx, {
    type: "bar",
    data: { labels, datasets: [{ label, data, backgroundColor: "#58a6ff" }] },
    options: {
      indexAxis: labels.length > 10 ? "y" : "x",
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: "#9aa4af" }, grid: { color: "#30363d" } },
        y: { ticks: { color: "#9aa4af" }, grid: { color: "#30363d" } },
      },
    },
  });
}

function makeLineChart(ctx, labels, data, label) {
  return new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [{ label, data, borderColor: "#58a6ff", backgroundColor: "rgba(88,166,255,0.2)", fill: true, tension: 0.2, pointRadius: 0 }],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: "#9aa4af", maxTicksLimit: 12 }, grid: { color: "#30363d" } },
        y: { ticks: { color: "#9aa4af" }, grid: { color: "#30363d" } },
      },
    },
  });
}

const _instances = {};
function reset(key) {
  if (_instances[key]) { _instances[key].destroy(); delete _instances[key]; }
}

window.addEventListener("profile-loaded", (e) => {
  const p = e.detail;

  // 1) Session types
  const stEntries = Object.entries(p.session_type_counts || {}).sort((a, b) => b[1] - a[1]);
  reset("st");
  _instances.st = makePieChart(
    document.getElementById("chart-session-types").getContext("2d"),
    stEntries.map(x => x[0]),
    stEntries.map(x => x[1]),
  );

  // 2) Top tools (already sorted)
  reset("tt");
  _instances.tt = makeBarChart(
    document.getElementById("chart-top-tools").getContext("2d"),
    (p.top_tools || []).map(x => x[0]),
    (p.top_tools || []).map(x => x[1]),
    "calls",
  );

  // 3) Activity per day (last 90)
  reset("act");
  _instances.act = makeLineChart(
    document.getElementById("chart-activity").getContext("2d"),
    (p.activity_per_day_last_90 || []).map(x => x[0].slice(5)),
    (p.activity_per_day_last_90 || []).map(x => x[1]),
    "sessions/day",
  );

  // 4) Hour-of-day
  reset("hr");
  _instances.hr = makeBarChart(
    document.getElementById("chart-hour").getContext("2d"),
    Array.from({ length: 24 }, (_, i) => `${i}`),
    p.hour_histogram || [],
    "sessions",
  );
});
```

- [ ] **Step 2: Load `charts.js` from `index.html`**

In `src/aianalyzer/web/static/index.html`, replace the existing `<script src="/static/app.js" ...>` block with these two scripts (order matters — Chart, then app, then charts):
```html
  <script src="/static/chart.umd.js"></script>
  <script src="/static/app.js" type="module"></script>
  <script src="/static/charts.js" type="module"></script>
```

- [ ] **Step 3: Visual smoke (manual)**

Run: `python -m uvicorn aianalyzer.web.app:create_app --factory --reload --port 8765`
Open the page → click **Scan sessions**. Expect: 4 charts populate (pie / horizontal bar / area / vertical bar). Resize the window — charts should reflow without errors.
Stop with Ctrl+C.

- [ ] **Step 4: Run full suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aianalyzer/web/static/charts.js src/aianalyzer/web/static/index.html
git commit -m "feat(web): Chart.js renderings for session types, tools, activity, hour"
```

---

### Task 33: Frontend narrative button + polling render + markdown rendering

**Files:**
- Modify: `src/aianalyzer/web/static/index.html` (vendor `marked`)
- Modify: `src/aianalyzer/web/static/app.js` (narrate button handler)
- Create: `src/aianalyzer/web/static/marked.min.js` (vendored)

**Why:** Tie the narrative API into the UI. We vendor `marked` so the narrative renders as HTML instead of raw Markdown, and stays offline-capable.

- [ ] **Step 1: Vendor `marked`**

```bash
curl -fsSL https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js \
  -o src/aianalyzer/web/static/marked.min.js
```
Verify the file is >20 KB and contains `Marked` or `marked`.

- [ ] **Step 2: Reference `marked` in `index.html`**

In `src/aianalyzer/web/static/index.html`, add the `marked` script *before* `app.js`:
```html
  <script src="/static/chart.umd.js"></script>
  <script src="/static/marked.min.js"></script>
  <script src="/static/app.js" type="module"></script>
  <script src="/static/charts.js" type="module"></script>
```

- [ ] **Step 3: Wire up `#narrate-btn` in `app.js`**

Append to `src/aianalyzer/web/static/app.js`:
```js
$("#narrate-btn").addEventListener("click", async () => {
  const btn = $("#narrate-btn");
  const sec = $("#narrative-section");
  const stat = $("#narrative-status");
  const out = $("#narrative-md");
  sec.classList.remove("hidden");
  out.innerHTML = "";
  stat.textContent = "Asking Copilot…";
  btn.disabled = true;
  btn.textContent = "Generating…";

  try {
    const { job_id } = await (await fetch("/api/narrative/start", { method: "POST" })).json();
    const j = await window.pollJob(job_id, (j) => {
      stat.textContent = j.status === "running" ? "Copilot is writing your profile…" : "Queued…";
    });
    if (j.status === "failed") {
      stat.textContent = `Failed: ${j.error}`;
    } else {
      stat.textContent = "";
      const md = j.result?.markdown ?? "";
      out.innerHTML = window.marked ? window.marked.parse(md) : md;
    }
  } catch (e) {
    stat.textContent = `Failed: ${e}`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Generate AI profile";
  }
});
```

- [ ] **Step 4: Visual smoke (manual, requires real `copilot` on PATH)**

Run: `python -m uvicorn aianalyzer.web.app:create_app --factory --port 8765`
Open the page, click **Generate AI profile**. The narrative section appears with "Copilot is writing your profile…" → after ~30-90s a rendered Markdown profile shows up.
Stop with Ctrl+C.

If `copilot` is missing or fails, the error appears in `#narrative-status` (expected behaviour).

- [ ] **Step 5: Run full suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/aianalyzer/web/static/index.html src/aianalyzer/web/static/app.js \
        src/aianalyzer/web/static/marked.min.js
git commit -m "feat(web): narrative button with polling and markdown rendering"
```

---

### Task 34: CLI `serve` command — launches Uvicorn, opens browser

**Files:**
- Modify: `src/aianalyzer/cli.py`
- Modify: `tests/test_cli.py` (append)

**Why:** One-command UX — `aianalyzer serve` and a browser tab opens. The flag `--no-browser` keeps headless/CI runs sane.

- [ ] **Step 1: Append failing test**

In `tests/test_cli.py`:
```python
def test_serve_help_lists_host_port_and_no_browser_flags():
    from typer.testing import CliRunner
    from aianalyzer.cli import app

    r = CliRunner().invoke(app, ["serve", "--help"])
    assert r.exit_code == 0, r.output
    assert "--host" in r.output
    assert "--port" in r.output
    assert "--no-browser" in r.output


def test_serve_no_browser_does_not_open(monkeypatch):
    """With --no-browser, webbrowser.open is never called."""
    from typer.testing import CliRunner
    import aianalyzer.cli as cli_mod

    calls = {"uvicorn": 0, "browser": 0}

    def fake_run(*args, **kwargs):
        calls["uvicorn"] += 1

    def fake_open(*args, **kwargs):
        calls["browser"] += 1
        return True

    monkeypatch.setattr(cli_mod.uvicorn, "run", fake_run)
    monkeypatch.setattr(cli_mod.webbrowser, "open", fake_open)

    r = CliRunner().invoke(cli_mod.app, ["serve", "--no-browser", "--port", "9999"])
    assert r.exit_code == 0, r.output
    assert calls["uvicorn"] == 1
    assert calls["browser"] == 0


def test_serve_default_opens_browser(monkeypatch):
    from typer.testing import CliRunner
    import aianalyzer.cli as cli_mod

    opened = []
    monkeypatch.setattr(cli_mod.uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(cli_mod.webbrowser, "open", lambda url, **k: opened.append(url) or True)

    r = CliRunner().invoke(cli_mod.app, ["serve", "--port", "9999"])
    assert r.exit_code == 0, r.output
    assert opened == ["http://127.0.0.1:9999"]
```

- [ ] **Step 2: Run tests, expect FAIL**

Run: `pytest tests/test_cli.py -v -k serve`
Expected: FAIL (no such command).

- [ ] **Step 3: Implement `serve` in `cli.py`**

At the top of `src/aianalyzer/cli.py`, add imports next to the existing ones:
```python
import webbrowser

import uvicorn
```

Then add the command alongside `scan` and `report`:
```python
@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address."),
    port: int = typer.Option(8765, help="TCP port."),
    no_browser: bool = typer.Option(False, "--no-browser", help="Do not open the browser."),
) -> None:
    """Run the AIAnalyzer web portal."""
    url = f"http://{host}:{port}"
    typer.echo(f"AIAnalyzer portal running at {url}")
    if not no_browser:
        webbrowser.open(url)
    uvicorn.run("aianalyzer.web.app:create_app", host=host, port=port, factory=True, log_level="warning")
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `pytest tests/test_cli.py -v -k serve`
Expected: 3 PASS.

- [ ] **Step 5: Real smoke (manual)**

Run: `aianalyzer serve --no-browser --port 8765` — confirm it prints the URL and serves `/`. Stop with Ctrl+C.
Then: `aianalyzer serve --port 8765` — a browser tab opens at the portal. Stop with Ctrl+C.

- [ ] **Step 6: Run full suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/aianalyzer/cli.py tests/test_cli.py
git commit -m "feat(cli): add 'serve' command (Uvicorn + browser launcher)"
```

---

### Task 35: README portal section + end-to-end smoke + tag `m4-portal`

**Files:**
- Modify: `README.md`

**Why:** Document the new entry-point and verify the whole stack works on the real corpus.

- [ ] **Step 1: Append a "Portal" section to `README.md`**

```markdown
## Portal (M4)

The portal is a local-only web UI for exploring your AI profile.

### Quick start

```bash
# 1. Build/refresh the feature cache for your sessions
aianalyzer scan

# 2. Launch the portal (binds to 127.0.0.1 only)
aianalyzer serve
```

Your browser opens at `http://127.0.0.1:8765` and shows:

- Your **archetype** (with secondary + confidence) and four axis scores.
- KPIs: sessions, turns, hours active, active days, average prompt length, acceptance rate.
- Charts: session-type mix, top tools, last-90-days activity, hour-of-day distribution.
- Top projects, models, and file extensions.
- A **Generate AI profile** button that asks the local `copilot` CLI to write
  a 4-section Markdown narrative about your collaboration style. This call
  stays on your machine; no session content leaves the box except to your own
  Copilot subscription via the local CLI.

### Flags

| Flag | Default | Meaning |
|------|---------|---------|
| `--host` | `127.0.0.1` | Bind address. Keep loopback for privacy. |
| `--port` | `8765` | TCP port. |
| `--no-browser` | off | Don't auto-open a browser tab. |

### Privacy

The portal binds to loopback only, never sends features to a remote service,
and only calls `copilot` with the aggregated, anonymous statistics shown on the
page (no raw prompts, no file contents, no paths).
```

- [ ] **Step 2: End-to-end smoke against real sessions**

Run in one terminal:
```bash
aianalyzer scan
aianalyzer serve --no-browser --port 8765
```

In another terminal:
```bash
curl -fsS http://127.0.0.1:8765/api/profile | python -c "import json,sys; d=json.load(sys.stdin); print(d['primary_archetype'], d['totals'])"
```
Expected: prints an archetype name (e.g. `architect`) and a totals dict with non-zero counts.

Open `http://127.0.0.1:8765` in a browser:
- Hero card shows your archetype + axes.
- All 4 charts render.
- Click **Generate AI profile** → after 30-90s a Markdown narrative renders.

Stop the server with Ctrl+C.

- [ ] **Step 3: Run full suite one more time**

Run: `pytest -q`
Expected: PASS (test count grew to ~75+ across M3 + M4).

- [ ] **Step 4: Commit + tag**

```bash
git add README.md
git commit -m "docs: README section for the M4 portal"
git tag m4-portal
```

Done — `m4-portal` is the shipped tag for this milestone.

---

