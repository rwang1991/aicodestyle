# AIAnalyzer M4 — Web Portal + Comprehensive AI Profile

> Extension to `DESIGN.md`. Reads on top of MLP (M0–M3). Status: **design**.

## 1. Goal

Turn the MLP's terminal report into a **comprehensive, browser-rendered AI profile** that any developer can run locally to understand how they collaborate with AI. The portal must:

- Trigger ingestion from a friendly UI (no shell needed after first install).
- Surface **substantially more insight** than the MLP: ~30 statistics, per-session purpose classification, time-of-day & project breakdowns, tool-usage rankings.
- Generate a **narrative AI profile** — a personalized markdown summary written by an LLM (the locally installed `copilot` CLI itself).
- Stay **local-first**: the only network call is whatever `copilot` itself does; AIAnalyzer makes none.

## 2. UX

`aianalyzer serve` starts a local HTTP server (`127.0.0.1:8765`) and opens the default browser to a single-page app:

```
┌──────────────────────────────────────────────────────────┐
│ AIAnalyzer                                  [⟳ Rescan]  │
├──────────────────────────────────────────────────────────┤
│ HERO — Archetype card                                    │
│   ⭐ Architect (questioner, planner)                     │
│   planning +0.32 · control +0.37                         │
│   168 sessions · 1,540 turns · 24h total                 │
│   [ Generate AI Profile Narrative ]                      │
├──────────────────────────────────────────────────────────┤
│ STAT GRID (4 columns) — total sessions, total turns,    │
│   total hours, acceptance rate, longest streak,         │
│   distinct projects, distinct models, days active …     │
├──────────────────────────────────────────────────────────┤
│ SESSION PURPOSES (pie chart) — debugging vs feature      │
│   work vs refactoring vs exploration vs … (10 types)    │
├──────────────────────────────────────────────────────────┤
│ ACTIVITY (line chart) — sessions per day, last 90 days   │
├──────────────────────────────────────────────────────────┤
│ TOP TOOLS (bar)            │ TOP PROJECTS (list)         │
│ Read 1240  Edit 850  …     │ /repos/Foo  42 sessions  …  │
├──────────────────────────────────────────────────────────┤
│ HOUR-OF-DAY (bar) · TOP MODELS · TOP FILE TYPES          │
├──────────────────────────────────────────────────────────┤
│ RECENT SESSIONS (table) — date, purpose, archetype,     │
│   turns, duration, dominant tool                        │
├──────────────────────────────────────────────────────────┤
│ AI PROFILE NARRATIVE (revealed after user clicks the    │
│   Generate button) — streamed markdown                   │
└──────────────────────────────────────────────────────────┘
```

No drill-down per session in M4 — the recent-sessions table is read-only. (M5+.)

## 3. New stats (≈ 18 beyond the 18 MLP signals)

Per-session — added to `SessionFeatures`:

| Field                       | Source                                          |
| --------------------------- | ----------------------------------------------- |
| `avg_user_msg_words`        | mean `len(content.split())` for user messages   |
| `tool_counts`               | `dict[tool_name, int]` — per session            |
| `file_paths_touched`        | `set[str]` of paths from edit/create tool args  |
| `started_hour_local`        | session start hour, 0–23, in local tz           |
| `started_weekday`           | 0=Mon … 6=Sun                                   |
| `models_used`               | `dict[model_name, turn_count]`                  |
| `session_type`              | `SessionType` enum — computed downstream        |

Aggregate — new `ExtendedProfile` dataclass alongside `UserProfile`:

| Field                       | Description                                     |
| --------------------------- | ----------------------------------------------- |
| `total_sessions`            | count                                           |
| `total_turns`               | sum                                             |
| `total_hours`               | sum of `session_duration_sec` / 3600            |
| `days_active`               | unique calendar days with ≥ 1 session           |
| `longest_streak_days`       | consecutive-day streak                          |
| `first_session_at`          | min started_at                                  |
| `last_session_at`           | max started_at                                  |
| `acceptance_rate`           | 1 − `abort_rate`                                |
| `avg_turns_per_session`     | mean                                            |
| `avg_session_minutes`       | mean                                            |
| `avg_prompt_words`          | corpus-weighted mean                            |
| `median_prompt_words`       | corpus median                                   |
| `p90_prompt_words`          | corpus 90th percentile                          |
| `top_tools`                 | `list[(name, count)]`, top 12                   |
| `top_projects`              | `list[(cwd, count)]`, top 12                    |
| `top_models`                | `list[(name, turn_count)]`                      |
| `top_file_extensions`       | `list[(ext, count)]`, top 12                    |
| `session_type_counts`       | `dict[SessionType, int]`                        |
| `hour_histogram`            | `list[int]` length 24                           |
| `weekday_histogram`         | `list[int]` length 7                            |
| `activity_per_day_last_90`  | `list[(date_iso, count)]` length ≤ 90           |

## 4. Session-purpose classifier

Per-session label, ordered first-match-wins. Rule-based; no ML. New module `classifier/session_types.py`:

| Order | Type            | Trigger                                                                 |
| ----- | --------------- | ----------------------------------------------------------------------- |
| 1     | `QuickTask`     | `turn_count <= 3` **and** `session_duration_sec < 300`                  |
| 2     | `Debugging`     | `tool_error_rate >= 0.25` **or** debug-keyword density ≥ 0.15           |
| 3     | `Testing`       | `test_or_spec_mention_rate >= 0.4` **or** majority of touched files are `test_*` / `_test.*` / `/tests/` |
| 4     | `Documentation` | majority of touched files have `.md` / `.rst` / `.txt` extension        |
| 5     | `Planning`      | `planning_language_ratio >= 0.3` **and** `todo_count >= 2` **and** `edited_files_per_turn_avg < 0.5` |
| 6     | `Exploration`   | `question_ratio >= 0.4` **and** `edited_files_per_turn_avg < 0.2`       |
| 7     | `Refactoring`   | refactor-keyword density ≥ 0.1 **and** mostly Edit (no Create) tools    |
| 8     | `CodeReview`    | review-keyword density ≥ 0.1 **and** no Edit/Create tools at all        |
| 9     | `FeatureWork`   | `edited_files_per_turn_avg >= 0.5`                                      |
| 10    | `Mixed`         | fallback                                                                |

Keyword sets are constants in the module; tuned later against the real corpus.

## 5. Narrative generator (Copilot subprocess)

Module `narrative.py` exposes:

```python
def generate_narrative(
    profile: UserProfile,
    extended: ExtendedProfile,
    result: ClassificationResult,
    *,
    copilot_binary: str = "copilot",
    timeout_sec: float = 180.0,
) -> str:
    """Spawn `copilot -p` with a templated prompt and return its stdout."""
```

The prompt is a single Markdown string built from a template:

```
You are an analyst writing a short, friendly "AI coding profile" for one
developer based on real usage statistics. Output 3 short paragraphs in
Markdown, no headers, no preamble. Be specific and reference concrete
numbers from the data; avoid generic praise. End with one actionable
suggestion.

FACTS (JSON):
{json.dumps(facts, indent=2)}
```

Subprocess invocation:

```
copilot -p <prompt> --allow-all-tools --no-color -s --output-format text
```

`-s` silences agent progress chatter so stdout is just the model's response. We capture and return that text. Streaming is implemented at the HTTP layer (line-buffered subprocess pipe forwarded as `text/plain` chunks).

## 6. Web layer

FastAPI + Uvicorn (new dependencies). Routes:

| Method | Path                | Returns                                                |
| ------ | ------------------- | ------------------------------------------------------ |
| GET    | `/`                 | `static/index.html`                                    |
| GET    | `/static/*`         | static asset (CSS/JS/Chart.js)                         |
| POST   | `/api/scan`         | `{ "job_id": "..." }` — kicks off background scan     |
| GET    | `/api/jobs/{id}`    | `{ "status": "pending|running|done|error", ... }`     |
| GET    | `/api/profile`      | `ProfileResponse` JSON (archetype + extended stats)   |
| POST   | `/api/narrative`    | streamed `text/plain` from `copilot -p`                |
| GET    | `/api/health`       | `{ "status": "ok" }`                                   |

`ProfileResponse` (Pydantic) is a serialized union of `UserProfile`, `ExtendedProfile`, `ClassificationResult`, and the per-session table rows.

Background scan jobs live in an in-memory `dict[job_id, JobStatus]` — single-user local server, no persistence needed.

## 7. Frontend

Single-page vanilla JS app. No build step. Three files in `src/aianalyzer/web/static/`:

- `index.html` — semantic layout, empty placeholders with IDs (`#hero`, `#stat-grid`, `#chart-types`, ...).
- `styles.css` — clean two-color theme, responsive grid, dark/light system-detect.
- `app.js` — on load: `GET /api/profile`, render each block; on click `[Rescan]` → `POST /api/scan` + poll; on click `[Generate Narrative]` → stream `POST /api/narrative` into a markdown card.
- `chart.umd.min.js` — Chart.js v4 UMD bundle, vendored (~85 KB). Used for pie, bar, line.

## 8. CLI

```
aianalyzer serve [--port 8765] [--host 127.0.0.1] [--no-browser] [--home ...]
```

Launches Uvicorn programmatically (not via shell), opens browser via `webbrowser.open(...)` unless `--no-browser`. Existing `scan` and `report` commands remain functional and unchanged.

## 9. Privacy & safety

- AIAnalyzer still makes **zero direct network calls**.
- The narrative endpoint shells out to `copilot` — that's the user's installed CLI, the same one they already use. The data sent to that subprocess is the structured facts JSON, NOT raw conversation content.
- `copilot` is invoked with `--allow-all-tools` only for non-interactive completion; we do not pass file/path/url permission flags.
- Bind address defaults to `127.0.0.1` (no LAN exposure).

## 10. Out of scope for M4

- Drill-down per-session detail page (read-only table only).
- Multi-user / hosted deployment.
- Auth.
- Trend lines week-over-week (just last-90-days totals).
- Exporting the profile as PDF / share image.
- Other collectors (still Copilot CLI only — see M5+ in `DESIGN.md`).
