"""VS Code GitHub Copilot Chat collector.

VS Code persists each Copilot Chat session as a JSON file under, per workspace:

    <userDataDir>/User/workspaceStorage/<wsHash>/chatSessions/<sessionGuid>.json

Top-level fields we care about:
    sessionId         - GUID matching the filename stem
    creationDate      - epoch milliseconds (session started)
    lastMessageDate   - epoch milliseconds (last assistant reply landed)
    requests          - list of {requestId, message, response, modelId, timestamp, isCanceled}

Per request:
    message.text      - the user prompt
    response          - list of {value, ...} chunks; concatenate `.value` for full markdown
    modelId           - e.g. "gpt-5" / "claude-sonnet-4"
    timestamp         - epoch milliseconds
    isCanceled        - true if the user aborted

The format is undocumented but observed stable across VS Code 1.86+ (v3 sessions).
Tool-call activity (file edits, terminal runs) is encoded inside `response.value`
and `contentReferences` as markdown; we don't synthesize ToolCall objects from it
because the round-trip metadata (start/end ts, success) isn't preserved.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from aianalyzer.discovery import DiscoveredSession
from aianalyzer.normalize import (
    AssistantMessage,
    NormalizedSession,
    Turn,
    UserMessage,
)
from aianalyzer.redact import redact


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _ts_from_ms(ms: Any) -> Optional[datetime]:
    if not isinstance(ms, (int, float)) or ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _join_response_text(response: Any) -> str:
    if not isinstance(response, list):
        return ""
    parts: list[str] = []
    for chunk in response:
        if not isinstance(chunk, dict):
            continue
        v = chunk.get("value")
        if isinstance(v, str):
            parts.append(v)
    return "".join(parts)


class VsCodeCopilotCollector:
    client = "vscode-copilot"

    def parse(self, discovered: DiscoveredSession) -> NormalizedSession:
        try:
            with discovered.events_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return self._empty(discovered)

        if not isinstance(data, dict):
            return self._empty(discovered)

        started_at = _ts_from_ms(data.get("creationDate")) or _EPOCH
        ended_at = _ts_from_ms(data.get("lastMessageDate")) or started_at

        models_used: list[str] = []
        turns: list[Turn] = []
        requests = data.get("requests")
        if not isinstance(requests, list):
            requests = []

        for idx, raw in enumerate(requests):
            if not isinstance(raw, dict):
                continue
            ts = _ts_from_ms(raw.get("timestamp")) or started_at

            user: Optional[UserMessage] = None
            msg = raw.get("message")
            if isinstance(msg, dict):
                text = msg.get("text")
                if isinstance(text, str) and text:
                    user = UserMessage(content=redact(text), ts=ts)

            response_text = _join_response_text(raw.get("response"))
            model = raw.get("modelId") or ""
            if isinstance(model, str) and model and model not in models_used:
                models_used.append(model)

            assistant: Optional[AssistantMessage] = None
            if response_text:
                assistant = AssistantMessage(
                    turn_id=str(raw.get("requestId") or idx),
                    content=redact(response_text),
                    model=model if isinstance(model, str) else "",
                    reasoning_effort=None,
                    ts=ts,
                )

            turns.append(
                Turn(
                    index=idx,
                    user=user,
                    assistant=assistant,
                    tool_calls=[],
                    aborted=bool(raw.get("isCanceled", False)),
                )
            )

        mtime = discovered.mtime or discovered.events_path.stat().st_mtime
        return NormalizedSession(
            client="vscode-copilot",
            session_id=discovered.session_id,
            started_at=started_at,
            ended_at=ended_at,
            cwd=None,
            models_used=models_used,
            turns=turns,
            todos=[],
            raw_mtime=mtime,
        )

    def _empty(self, d: DiscoveredSession) -> NormalizedSession:
        return NormalizedSession(
            client="vscode-copilot",
            session_id=d.session_id,
            started_at=_EPOCH,
            ended_at=_EPOCH,
            raw_mtime=d.mtime,
        )
