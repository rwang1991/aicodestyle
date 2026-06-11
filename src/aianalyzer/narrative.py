"""LLM narrative generator backed by the local GitHub Copilot CLI."""
from __future__ import annotations

import json
import subprocess
import tempfile
from typing import Any


class NarrativeError(RuntimeError):
    """Raised when the copilot subprocess fails or times out."""


_PROMPT_TEMPLATE = """\
You are writing an "AI Collaboration Profile" for a developer based on aggregated,
anonymised statistics from their local AI coding sessions. Do NOT invent any facts —
only use the JSON below.

**Output requirements (strict):**
- Print the Markdown profile directly to stdout. Your entire response must be the
  Markdown content itself — nothing before it, nothing after it.
- Do NOT call any tools. Do NOT write or read any files. In particular,
  do NOT create or modify a `profile.md` file. The caller captures your stdout
  and renders it inline in a web UI; any file you create is wasted I/O.
- Do NOT preface the answer with status text like "Here is the profile" or
  "The file has been written". Just output the Markdown.

The Markdown must have these sections, in this order:

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

    The subprocess runs in an isolated temp directory and is NOT given
    ``--allow-all-tools``, so even if the model decides to invoke a file-write
    tool it cannot pollute the user's working directory (e.g. dropping a
    stray ``profile.md`` next to the .exe).
    """
    prompt = build_narrative_prompt(facts)
    cmd = [
        copilot_binary,
        "-p", prompt,
        "--no-color",
        "-s",
        "--output-format", "text",
    ]
    try:
        # ``text=True`` alone falls back to the OS locale codepage on Windows
        # (cp1252 / cp936 / ...), which mangles em-dashes, smart quotes and
        # CJK characters that the Copilot CLI emits as UTF-8. Force UTF-8 and
        # replace any malformed sequences so we never propagate mojibake to
        # the portal.
        with tempfile.TemporaryDirectory(prefix="aicodestyle-narrative-") as tmp:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_sec,
                check=False,
                cwd=tmp,
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

