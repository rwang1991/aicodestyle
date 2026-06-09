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
    response          - list of chunks; each chunk has an optional ``kind``:
                        * (no kind) / "markdownContent" -> prose, joined for ``content``
                        * "toolInvocationSerialized"   -> a finished tool call
                          (toolId, toolCallId, resultDetails.isError, ...)
                        * "textEditGroup"              -> a file edit applied to ``uri.fsPath``
                          with ``state.applied`` (0/1) and an ``edits`` array
                        * "thinking" / "undoStop" / "inlineReference" /
                          "codeblockUri" / "progressMessage" / ...   -> internal
                          control chunks; ignored for both prose and tool-call signal
    modelId           - e.g. "gpt-5" / "claude-sonnet-4"
    timestamp         - epoch milliseconds
    isCanceled        - true if the user aborted

The format is undocumented but observed stable across VS Code 1.86+ (v3 sessions).
We synthesize ToolCall objects from ``toolInvocationSerialized`` and
``textEditGroup`` chunks so VS Code sessions contribute the same kinds of
signals (tool diversity, tool error rate, files-edited-per-turn) that Copilot
CLI sessions do. The shared request ``timestamp`` is used for both
``ts_start`` and ``ts_end`` of each derived ToolCall (VS Code doesn't record
per-tool-call timings).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from aianalyzer.discovery import DiscoveredSession
from aianalyzer.normalize import (
    AssistantMessage,
    NormalizedSession,
    ToolCall,
    Turn,
    UserMessage,
)
from aianalyzer.redact import redact


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# Response-chunk kinds whose ``value`` is part of the assistant's prose reply.
# Treat the absence of a ``kind`` key as plain content too — many real
# sessions emit prose without an explicit kind.
_PROSE_KINDS = {None, "", "markdownContent"}


def _ts_from_ms(ms: Any) -> Optional[datetime]:
    if not isinstance(ms, (int, float)) or ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _join_response_text(response: Any) -> str:
    """Concatenate only prose chunks; skip thinking/control/tool chunks."""
    if not isinstance(response, list):
        return ""
    parts: list[str] = []
    for chunk in response:
        if not isinstance(chunk, dict):
            continue
        kind = chunk.get("kind")
        if kind not in _PROSE_KINDS:
            continue
        v = chunk.get("value")
        if isinstance(v, str):
            parts.append(v)
    return "".join(parts)


def _extract_fs_path(uri: Any) -> Optional[str]:
    """VS Code URIs serialize as ``{$mid, scheme, path, fsPath, ...}``; pick fsPath first."""
    if not isinstance(uri, dict):
        return None
    fs = uri.get("fsPath")
    if isinstance(fs, str) and fs:
        return fs
    p = uri.get("path")
    return p if isinstance(p, str) and p else None


def _tool_call_from_invocation(chunk: dict, ts: datetime) -> Optional[ToolCall]:
    """Turn a ``toolInvocationSerialized`` chunk into a ToolCall.

    Drops chunks without a usable ``toolId`` (rare but observed in
    half-written sessions). Success comes from ``resultDetails.isError``
    inverted; an unset/missing ``isError`` is treated as success because
    a missing field generally means the call finished cleanly.
    """
    tool_id = chunk.get("toolId")
    if not isinstance(tool_id, str) or not tool_id:
        return None
    result = chunk.get("resultDetails")
    if isinstance(result, dict):
        success = not bool(result.get("isError", False))
    else:
        success = True
    args: dict[str, Any] = {}
    tsd = chunk.get("toolSpecificData")
    if isinstance(tsd, dict):
        raw_input = tsd.get("rawInput")
        if raw_input is not None:
            args["input"] = raw_input
    return ToolCall(
        tool_name=tool_id,
        arguments=args,
        success=success,
        duration_ms=0,
        ts_start=ts,
        ts_end=ts,
        error=None,
    )


def _tool_call_from_text_edit_group(chunk: dict, ts: datetime) -> Optional[ToolCall]:
    """Turn a ``textEditGroup`` chunk into an ``edit`` ToolCall with file path.

    The ``edit`` tool_name (matching :data:`features._EDIT_TOOL_NAMES`) makes
    this contribute to the ``edited_files_per_turn_avg`` signal. Success is
    derived from ``state.applied`` (>=1 means VS Code accepted the edit).
    """
    path = _extract_fs_path(chunk.get("uri"))
    if not path:
        return None
    state = chunk.get("state")
    if isinstance(state, dict):
        applied = state.get("applied", 0)
        try:
            success = int(applied) >= 1
        except (TypeError, ValueError):
            success = False
    else:
        success = False
    return ToolCall(
        tool_name="edit",
        arguments={"path": path},
        success=success,
        duration_ms=0,
        ts_start=ts,
        ts_end=ts,
        error=None,
    )


def _extract_tool_calls(response: Any, ts: datetime) -> list[ToolCall]:
    if not isinstance(response, list):
        return []
    out: list[ToolCall] = []
    for chunk in response:
        if not isinstance(chunk, dict):
            continue
        kind = chunk.get("kind")
        if kind == "toolInvocationSerialized":
            tc = _tool_call_from_invocation(chunk, ts)
            if tc is not None:
                out.append(tc)
        elif kind == "textEditGroup":
            tc = _tool_call_from_text_edit_group(chunk, ts)
            if tc is not None:
                out.append(tc)
        # All other kinds (thinking, undoStop, inlineReference, codeblockUri,
        # progressMessage, mcpServersStarting, confirmation, warning, ...) are
        # intentionally ignored — they don't represent assistant tool calls.
    return out


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

            tool_calls = _extract_tool_calls(raw.get("response"), ts)

            turns.append(
                Turn(
                    index=idx,
                    user=user,
                    assistant=assistant,
                    tool_calls=tool_calls,
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
