# AIAnalyzer — Design Document

**Status:** Draft v0.1
**Owner:** @ruwang_microsoft
**Date:** 2026-06-09

---

## 1. Problem Statement

Developers now interact with multiple AI coding assistants — **Claude Code, OpenAI Codex CLI, GitHub Copilot CLI, VS Code GitHub Copilot Chat** — each leaving rich local session logs on disk. Today there is **no unified tool that reads those logs and tells the developer how they actually use AI**: do they design first, or jump to "make it work"? Do they read diffs, or accept blindly? Are they an **architect collaborating with an agent**, or a **vibe coder steering by feel**?

AIAnalyzer is a local‑first analyzer that:

1. **Discovers and ingests** sessions from all four supported clients.
2. **Normalizes** them into a single event/turn model.
3. **Extracts behavioral signals** (planning depth, steering frequency, tool‑use intensity, acceptance ratio, etc.).
4. **Classifies the developer into one or more archetypes** with evidence.
5. **Reports** trends over time, per‑project, per‑model.

Goals:
- All processing local; no telemetry leaves the machine by default.
- Transparent, rule‑based classification first; ML clustering as an optional second pass.
- One CLI command for the common case: `aianalyzer report`.

Non‑goals:
- Real‑time coaching during a session (future work).
- Team / org dashboards (future work; the export format is built to support it).
- Judging users — every archetype is a legitimate style.

---

## 2. Prior Art & Influences

| Source | What we borrow |
|---|---|
| **GitHub Next — *Personas for Developer Tools*** | The idea of *behavior‑based* personas (not demographics) and the need for tool designers to know which one is at the keyboard. |
| **Microsoft — *The Copilot Experience* (PLATEAU '22)** | Empirical finding that satisfaction and productivity vary by interaction style, not by seniority. |
| **Roo Code modes** (*Architect / Code / Debug / Ask / QA / Docs*) | A precedent for treating archetypes as first‑class, switchable contexts inside the tool. We invert it: instead of letting the user *pick* a mode, we *infer* the mode from history. |
| **"AI‑native / AI‑augmented / AI‑skeptic"** (VC discourse) | Useful as a single‑axis macro label, but too coarse for individuals. We use it as a secondary tag. |
| **"Vibe coder vs. Architect"** (community framing) | The intuitive two‑pole baseline our 2‑axis model generalizes. |
| **Cline / Roo Code in‑editor stats** | Confirms users want token / cost / task‑type breakdowns. We include those as descriptive panels alongside the archetype. |

What's **missing** from existing products:
- All current dashboards (Cline, Roo, Qodo) operate **inside one tool**. None cross Claude Code + Codex + Copilot CLI + VS Code Copilot.
- They report **what the AI did** (tokens, files touched). They don't report **what the human's collaboration style was**.

AIAnalyzer fills both gaps.

---

## 3. Data Sources (verified on Windows host)

| Client | Path | Format | Contains |
|---|---|---|---|
| **GitHub Copilot CLI** | `~/.copilot/session-state/{sessionId}/events.jsonl` | JSON Lines, one event per line | `session.start`, `session.model_change`, `user.message`, `assistant.turn_start`, `assistant.message`, `assistant.turn_end`, `tool.execution_start`, `tool.execution_complete`, `hook.start`, `hook.end`, `system.message`, `system.notification`, `abort`, `session.shutdown` |
| | `~/.copilot/session-state/{sessionId}/session.db` | SQLite | `todos`, `todo_deps`, `inbox_entries` |
| | `~/.copilot/session-state/{sessionId}/checkpoints/`, `files/`, `research/`, `rewind-snapshots/` | files | artifacts, rewinds (signal of "tried again") |
| **Claude Code** | `~/.claude/projects/{escaped-cwd}/{sessionId}.jsonl` | JSON Lines | `user`, `assistant`, `tool_use`, `tool_result` messages with `parentUuid` (branch tracking) |
| **OpenAI Codex CLI** | `~/.codex/history.jsonl` | JSON Lines | `{session_id, ts, text}` per user prompt |
| | `~/.codex/sessions/YYYY/MM/DD/rollout-{ts}-{id}.jsonl` | JSON Lines | full request/response rollouts |
| **VS Code Copilot Chat** | `%APPDATA%\Code\User\globalStorage\github.copilot-chat\session-store.db` | SQLite | chat sessions, agent invocations (ask-agent, plan-agent, explore-agent subfolders) |
| | `%APPDATA%\Code\User\workspaceStorage\{hash}\github.copilot-chat\` | per‑workspace state | scoped chat threads |

Verified on this machine: **172 Copilot CLI sessions**, schema confirmed via direct inspection.

---

## 4. Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                          AIAnalyzer CLI                          │
│  (aianalyzer scan | report | classify | export | dashboard)      │
└──────────────────────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. Collectors  (one per client, pluggable)                       │
│ ───────────────────────────────────────────────────────────────  │
│  CopilotCLICollector   ClaudeCodeCollector                       │
│  CodexCollector        VSCodeCopilotCollector                    │
│  + DiscoveryService (locates paths cross‑platform)               │
└─────────────────────────────────────────────────────────────────┘
                 │  raw records
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. Normalizer  →  Canonical schema                               │
│    NormalizedSession { id, client, cwd, model, started, ended,   │
│                       turns: [Turn], tool_calls: [ToolCall],     │
│                       todos: [Todo], rewinds: int }              │
│    Turn { user_msg, assistant_msg, tool_calls, t_start, t_end }  │
└─────────────────────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. Feature Extractor  →  per‑session FeatureVector               │
│    + corpus‑level aggregates (per user, per project, per week)   │
│    Cache to DuckDB / SQLite under ~/.aianalyzer/cache.db         │
└─────────────────────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. Classifier                                                    │
│  v1 RuleBased  (transparent, every score has citations)          │
│  v2 ClusterBased (k‑means on features; optional labeled training)│
│  → PrimaryArchetype + ModifierTags + Confidence + Evidence       │
└─────────────────────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. Reporters                                                     │
│   • Terminal report (rich tables, sparklines)                    │
│   • HTML dashboard (single self‑contained file)                  │
│   • JSON export (for team aggregation / further analysis)        │
└─────────────────────────────────────────────────────────────────┘
```

### Tech stack (recommended)

| Concern | Choice | Why |
|---|---|---|
| Language | **Python 3.11+** | Strong JSONL/SQLite/regex/NLP tooling, `pandas`/`duckdb` for aggregation, `scikit-learn` for clustering, `rich`/`textual` for terminal UI. |
| CLI | `typer` | Click‑based, type‑hinted, zero‑boilerplate. |
| Storage | `duckdb` (analytical cache) + raw JSONL streamed | Fast aggregation over 100k+ events without loading all into memory. |
| Dashboard | Single‑file HTML via `jinja2` + `chart.js` (no server required) | Local‑first; openable in any browser. |
| Packaging | `pipx install aianalyzer` | One‑shot install, isolated venv. |

Alternative if a single binary is required: **Go** (read JSONL with `encoding/json`, SQLite via `modernc.org/sqlite`, ship as one `.exe`). Trade‑off: lose pandas/scikit‑learn ergonomics.

---

## 5. Canonical Schema

```python
@dataclass
class ToolCall:
    name: str                 # e.g. "edit", "powershell", "view", "grep"
    args_summary: str         # truncated, scrubbed
    success: bool
    duration_ms: int
    started_at: datetime

@dataclass
class Turn:
    index: int
    user_message: str         # may be empty (auto‑continued turn)
    assistant_message: str
    assistant_chars: int
    code_block_count: int
    tool_calls: list[ToolCall]
    was_aborted: bool
    started_at: datetime
    ended_at: datetime

@dataclass
class NormalizedSession:
    session_id: str
    client: Literal["copilot_cli", "claude_code", "codex", "vscode_copilot"]
    cwd: str | None
    repo: str | None          # inferred from cwd
    models_used: list[str]
    started_at: datetime
    ended_at: datetime | None
    turns: list[Turn]
    todos_created: int
    todos_completed: int
    rewinds: int              # checkpoint restores
    model_switches: int
    aborts: int
```

This is the only schema downstream stages depend on. Each collector's job is to produce a stream of `NormalizedSession`.

---

## 6. Signal Catalog

Each signal is computed per session, then aggregated per user. **Every signal is grounded in fields actually present in the data sources above** — no fabricated inputs.

| # | Signal | How it's computed | What it tells us |
|---|---|---|---|
| S1 | `planning_prelude_ratio` | Share of sessions whose first user message contains planning verbs (`plan`, `design`, `outline`, `approach`, `first, explain`, `think through`, `let's discuss`) **and** is followed by ≥1 turn before any code‑producing tool call. | High → Architect; Low → Vibe Coder |
| S2 | `architectural_lexicon_density` | Fraction of user messages containing words from a curated list (`architecture`, `tradeoff`, `coupling`, `invariant`, `boundary`, `abstraction`, `contract`, `interface`, `scalability`, `migration`). | High → Architect / Reviewer |
| S3 | `spec_length_p50` | Median user prompt length in characters. | High → Specifier; Low → Tab‑completer |
| S4 | `steering_rate` | (count of `abort` events + user messages matching `/^(no|wait|actually|stop|instead|rather|don't)\b/i`) / turn count | High → Tinkerer / Reviewer; Low → Delegator |
| S5 | `acceptance_ratio` | Turns where the next user message is approval (`/^(thanks|lgtm|looks good|ship it|perfect|great|nice)\b/i` or session ends within N seconds after the assistant turn) / total turns. | High → Vibe Coder / Pilot |
| S6 | `tool_use_intensity` | Mean tool calls per turn. | High → agentic / Pilot |
| S7 | `tool_diversity` | Unique tool names per session (Shannon entropy). | High → Integrator / Explorer |
| S8 | `verification_rate` | Fraction of code‑producing sessions that include a tool call matching `/^(powershell|bash|test|pytest|jest|npm test|cargo test|go test|build)/` after the last edit. | High → Architect / Reviewer |
| S9 | `context_provisioning` | Fraction of opening user messages that include a file path / glob / URL. | High → Architect; Low → Vibe Coder |
| S10 | `iteration_depth_p50` | Median turns per session. | High → Tinkerer; Low → Pilot |
| S11 | `rewind_frequency` | Rewinds per 10 sessions (Copilot CLI checkpoints; Claude `parentUuid` branching). | High → Skeptic / Tinkerer |
| S12 | `model_switching` | Model changes per session. | High → Explorer; Low → Loyalist |
| S13 | `reasoning_effort_preference` | Distribution of selected reasoning levels. | "High" → Architect tendency |
| S14 | `domain_breadth` | Distinct languages/cwds touched per week (entropy). | High → Integrator |
| S15 | `todo_planning_use` | Sessions that create ≥3 todos / total sessions. | High → Architect / Pilot |
| S16 | `time_of_day_profile` | 24‑bin histogram of `session.start` times. | Descriptive (not classifying); flags "nightly hacker" tag |
| S17 | `question_to_command_ratio` | Share of user messages that are questions (end with `?`, start with `why/how/what`). | High → Learner / Reviewer |
| S18 | `repro_loop_depth` | Mean turns between a failing tool call and a passing one. | High → Persistent Debugger |

Optional NLP layer (off by default for privacy): embed user messages with a small local model (e.g. `all-MiniLM-L6-v2`) and add `topic_cluster_id` as a feature.

---

## 7. Archetype Model

A **two‑axis primary classifier** plus **orthogonal modifier tags**. Chosen over a single‑label scheme because empirically users mix styles by project and by week.

### 7.1 Primary axes

```
                  HIGH PLANNING (designs first)
                            │
              Pilot /       │       Architect
              Orchestrator  │
                            │
   LOW CONTROL ─────────────┼────────────── HIGH CONTROL
   (delegates)              │              (steers each step)
                            │
              Vibe Coder    │       Tinkerer /
                            │       Pair Programmer
                            │
                  LOW PLANNING (jumps in)
```

| Archetype | Definition | Signature signals |
|---|---|---|
| **Architect** | Designs before coding, steers details, verifies. | S1↑, S2↑, S3↑, S8↑, S9↑, S15↑ |
| **Pilot / Orchestrator** | Writes a detailed spec, then lets the agent run; reviews at milestones. | S1↑, S3↑, S6↑, S10↓, S5↑ |
| **Tinkerer / Pair Programmer** | Tight back‑and‑forth, lots of small corrections, AI as smart autocomplete. | S4↑, S10↑, S3↓, S6 mid |
| **Vibe Coder** | "Make it work" prompts; accepts most output; iterates by re‑prompting on failure. | S1↓, S3↓, S5↑, S8↓, S11↑, S18↑ |

Each user gets a **(x, y)** position with confidence interval; the nearest quadrant is the *primary archetype*. If the point is within 15% of an axis, both adjacent archetypes are reported.

### 7.2 Modifier tags (non‑exclusive)

Stacked on top of the primary archetype, e.g. *"Architect · Reviewer · Multi‑Model Explorer"*.

| Tag | Trigger |
|---|---|
| **Reviewer / Auditor** | High S17 + user messages match `/\b(review|audit|check|critique|smell|lint)\b/` ≥ 15% |
| **Learner** | S17 ≥ 40% and median session ≤ 3 turns |
| **Integrator / Automator** | S14 high + dominant tool categories are shell/CI/infra |
| **Debugger** | S18 ≥ 4 turns and failing‑tool events ≥ 25% |
| **Multi‑Model Explorer** | S12 ≥ 0.5 model changes/session across ≥3 distinct models |
| **Skeptic** | S5 low + S11 high + S4 high |
| **Nightly Hacker** | ≥40% of sessions start 22:00–05:00 |
| **Cross‑Tool User** | Active in ≥3 of the 4 supported clients within 30 days |
| **AI‑Native / AI‑Augmented / AI‑Skeptic** | Macro tag from total sessions/week and S5+S6 composite (kept as a familiar coarse label) |

### 7.3 Why this model

- **Two axes are intuitive** ("how much do you plan" × "how much do you steer") and map cleanly to existing community vocabulary.
- **Modifier tags absorb the long tail** without diluting the four primaries.
- **Every classification cites the signals that drove it** → trustable, debuggable, and the user can disagree with evidence.

---

## 8. Classification Pipeline

### v1 — Rule‑based (ships first)

```
For each user (= owner of the machine):
    1. Compute FeatureVector over last N days (default 30, configurable).
    2. Normalize each Sk to [0,1] using a fixed reference distribution
       (calibrated on an anonymized seed corpus shipped with the tool).
    3. planning_score  = weighted_sum(S1, S2, S3, S9, S15)
       control_score   = weighted_sum(S4, S10, -S5, S6 inverse, S8)
    4. Place on (planning, control) plane → primary archetype.
    5. Evaluate each modifier rule independently → tag list.
    6. Emit Report with evidence (top 3 contributing sessions per signal).
```

Weights live in `aianalyzer/classifier/weights.yaml` — version‑controlled, easy to tune.

### v2 — Unsupervised clustering (opt‑in)

- k‑means (k=4..8) on the standardized feature vector across all sessions.
- For each cluster, surface the top discriminating features and let the user label it.
- Re‑run quarterly to detect new archetypes as AI tools and workflows evolve.

### v3 — Supervised (future)

Once enough users have confirmed/corrected their inferred archetype, train a small gradient‑boosted classifier on labeled feature vectors. Stored locally; never uploaded.

---

## 9. CLI UX

```
$ aianalyzer scan
  scanning ~/.copilot/session-state ... 172 sessions
  scanning ~/.claude/projects ... 0 sessions
  scanning ~/.codex/sessions ... 0 sessions
  scanning %APPDATA%/Code/.../github.copilot-chat ... 41 sessions
  cached 213 sessions to ~/.aianalyzer/cache.db (8.2 MB)

$ aianalyzer report --since 30d

  ▸ Primary archetype:  Architect  (confidence 0.78)
  ▸ Modifiers:          Reviewer · Multi-Model Explorer · Cross-Tool User
  ▸ Coarse label:       AI-Augmented

  Why?
   • S1 planning_prelude_ratio          0.61  (top 25% of reference)
   • S2 architectural_lexicon_density   0.18  (top 15%)
   • S9 context_provisioning            0.74  (top 10%)
   • S5 acceptance_ratio                0.22  (low — you steer)
   • S15 todo_planning_use              0.43

  Top 3 sessions illustrating "Architect":
   1. 2026-05-20  copilot_cli  cwd=…/AIAnalyzer   42 turns  → DESIGN.md
   2. 2026-05-18  vscode       cwd=…/portal       18 turns
   3. 2026-05-11  copilot_cli  cwd=…/aks-skill    27 turns

  Trends (last 4 weeks): planning_score ▁▃▅▇   control_score ▆▆▅▄

$ aianalyzer dashboard
  ▸ wrote report.html  (open in browser)

$ aianalyzer export --format json > me.json
```

---

## 10. Privacy & Security

- **Local‑first.** No network call by default. `aianalyzer --offline` is implied.
- **No prompt content leaves the box.** Reports show *aggregates* and *counts* of regex matches — never the matched text — unless the user opts in to evidence quotes.
- **Redaction pass** on ingestion: strip emails, GitHub tokens (`gh[oprs]_[A-Za-z0-9]{36}`), `AKIA…` keys, JWTs, file contents pasted into prompts.
- **`.aianalyzer/cache.db` is git‑ignored** by template; the tool refuses to write inside any directory containing `.git` to avoid accidental commits.
- **Per‑source opt‑in.** `aianalyzer config disable claude_code` removes that collector.
- **Export for sharing is explicit.** `--include-evidence` requires `--i-understand` and prints a summary of what's about to leave the machine.

---

## 11. Project Layout

```
aianalyzer/
├── pyproject.toml
├── README.md
├── DESIGN.md                  ← this file
├── src/aianalyzer/
│   ├── __init__.py
│   ├── cli.py                 (typer entrypoint)
│   ├── discovery.py           (cross‑platform path discovery)
│   ├── collectors/
│   │   ├── base.py            (Collector ABC)
│   │   ├── copilot_cli.py
│   │   ├── claude_code.py
│   │   ├── codex.py
│   │   └── vscode_copilot.py
│   ├── normalize.py
│   ├── features.py
│   ├── classifier/
│   │   ├── rules.py
│   │   ├── weights.yaml
│   │   └── cluster.py         (v2)
│   ├── redact.py
│   ├── store.py               (duckdb cache)
│   ├── report/
│   │   ├── terminal.py
│   │   ├── html.py
│   │   └── templates/report.html.j2
│   └── archetypes.py          (taxonomy as code)
└── tests/
    ├── fixtures/              (small redacted session samples per client)
    ├── test_collectors.py
    ├── test_features.py
    └── test_classifier.py
```

---

## 12. Milestones

| M | Scope | Exit criteria |
|---|---|---|
| **M0** | Repo scaffold, `pyproject.toml`, CI (lint+test), README | `pipx install -e .` works |
| **M1** | `CopilotCLICollector` + `Normalizer` + JSON dump | `aianalyzer scan` prints normalized sessions for the 172 local ones |
| **M2** | `FeatureExtractor` + DuckDB cache | `aianalyzer features --session ID` prints all 18 signals |
| **M3** | Rule‑based classifier + terminal report | `aianalyzer report` produces the UX in §9 on real data |
| **M4** | `ClaudeCodeCollector`, `CodexCollector`, `VSCodeCopilotCollector` | All four sources unified in one report |
| **M5** | HTML dashboard + JSON export + redaction tests | Self‑contained `report.html` opens; redaction suite green |
| **M6** | k‑means clustering (`v2`) + weights tuning UI | `aianalyzer cluster` proposes labels for inspection |

Each milestone is independently shippable; M3 is the **minimum lovable product**.

---

## 13. Open Questions

1. **Granularity of "user".** On a shared workstation we have only one home directory's data. Sufficient for v1; revisit if multi‑user becomes a need.
2. **Archetype labels.** Are *Architect / Pilot / Tinkerer / Vibe Coder* the right four, or should we rename to avoid loaded connotations? *(Suggested alternatives: Designer / Director / Collaborator / Improviser.)*
3. **Cross‑tool de‑duplication.** A long task may span Copilot CLI + VS Code Copilot Chat on the same repo at the same time. Do we merge them into one logical "work session"? Proposed v1: keep separate, surface as "Cross‑Tool User" tag.
4. **Should we score *teams* in v1?** Out of scope; export format is built to allow it later.
5. **Where to ship the seed corpus** used to calibrate signal percentiles in §8 without leaking real users' prompts.

---

## 14. Next Step

Once this design is approved, **M0 + M1** are ~1 day of work given the schemas are already confirmed. Recommended first PR: scaffold + `CopilotCLICollector` + normalized JSON dump, validated against the 172 local sessions on this machine.
