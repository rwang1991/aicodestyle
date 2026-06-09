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
