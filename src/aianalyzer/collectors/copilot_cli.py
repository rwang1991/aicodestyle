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
    UsageRecord,
    UserMessage,
)
from aianalyzer.redact import redact


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _usage_from_metrics_usage(u: dict) -> UsageRecord:
    """Convert Copilot CLI `modelMetrics.<model>.usage` into a canonical UsageRecord.

    Copilot CLI reports `inputTokens` as the AGGREGATE
    (uncached_input + cache_read + cache_write). We normalise here so
    `UsageRecord.input_tokens` always means "uncached input only", matching
    the rate-card semantics in pricing.estimate_cost_usd_v2.
    """
    cache_read = int(u.get("cacheReadTokens") or 0)
    cache_write = int(u.get("cacheWriteTokens") or 0)
    raw_input = int(u.get("inputTokens") or 0)
    uncached = max(0, raw_input - cache_read - cache_write)
    return UsageRecord(
        input_tokens=uncached,
        output_tokens=int(u.get("outputTokens") or 0),
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        reasoning_tokens=int(u.get("reasoningTokens") or 0),
    )


def _extract_usage(events: list[dict]) -> tuple[Optional[UsageRecord], dict[str, UsageRecord]]:
    """Find the session.shutdown event and pull billed numbers from tokenDetails + modelMetrics.

    Returns (session_total, by_model). Both empty if no shutdown event.
    """
    shutdown = next((e for e in events if e.get("type") == "session.shutdown"), None)
    if not shutdown:
        return None, {}
    data = shutdown.get("data") or {}

    by_model: dict[str, UsageRecord] = {}
    metrics = data.get("modelMetrics") or {}
    for model, m in metrics.items():
        if not isinstance(m, dict):
            continue
        usage = _usage_from_metrics_usage(m.get("usage") or {})
        req = m.get("requests") or {}
        by_model[model] = usage.model_copy(update={
            "requests": int(req.get("count") or 0),
            "premium_requests": float(req.get("cost") or 0.0),
            "nano_aiu": int(m.get("totalNanoAiu") or 0),
        })

    if by_model:
        total = UsageRecord(
            input_tokens=sum(u.input_tokens for u in by_model.values()),
            output_tokens=sum(u.output_tokens for u in by_model.values()),
            cache_read_tokens=sum(u.cache_read_tokens for u in by_model.values()),
            cache_write_tokens=sum(u.cache_write_tokens for u in by_model.values()),
            reasoning_tokens=sum(u.reasoning_tokens for u in by_model.values()),
            requests=sum(u.requests for u in by_model.values()),
            premium_requests=float(data.get("totalPremiumRequests") or sum(u.premium_requests for u in by_model.values())),
            nano_aiu=int(data.get("totalNanoAiu") or sum(u.nano_aiu for u in by_model.values())),
        )
    else:
        td = data.get("tokenDetails") or {}
        get = lambda k: int(((td.get(k) or {}).get("tokenCount")) or 0)
        total = UsageRecord(
            input_tokens=get("input"),
            output_tokens=get("output"),
            cache_read_tokens=get("cache_read"),
            cache_write_tokens=get("cache_write"),
            premium_requests=float(data.get("totalPremiumRequests") or 0.0),
            nano_aiu=int(data.get("totalNanoAiu") or 0),
        )
    return total, by_model


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
            if current_assistant is not None and not current_assistant.model:
                recovered = next(
                    (c["model"] for c in current_calls.values() if c.get("model")),
                    "",
                )
                if recovered:
                    current_assistant = current_assistant.model_copy(update={"model": recovered})
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

        for idx, event in enumerate(events):
            etype = event.get("type")
            data = event.get("data", {}) or {}
            ts = event.get("ts")

            if etype == "session.start":
                ctx = data.get("context") or {}
                cwd = ctx.get("cwd") or cwd
            elif etype == "session.resume":
                if cwd is None:
                    ctx = data.get("context") or {}
                    candidate = ctx.get("cwd")
                    if candidate:
                        cwd = candidate
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
                    reasoning_effort=_reasoning_effort_for(events, model, idx),
                    ts=ts,
                )
            elif etype == "tool.execution_start":
                call_id = data.get("toolCallId")
                if not call_id:
                    continue
                raw_args = data.get("arguments")
                if isinstance(raw_args, dict):
                    args = raw_args
                elif raw_args in (None, ""):
                    args = {}
                else:
                    # Some tools (e.g. apply_patch) emit raw string payloads.
                    args = {"_raw": str(raw_args)}
                current_calls[call_id] = {
                    "tool_name": data.get("toolName") or "unknown",
                    "arguments": args,
                    "ts_start": ts,
                }
            elif etype == "tool.execution_complete":
                call_id = data.get("toolCallId")
                if not call_id or call_id not in current_calls:
                    continue
                call = current_calls[call_id]
                call["ts_end"] = ts
                call["success"] = bool(data.get("success"))
                raw_error = data.get("error")
                if raw_error is not None and not isinstance(raw_error, str):
                    raw_error = str(raw_error)
                call["error"] = raw_error
                tc_model = data.get("model")
                if tc_model:
                    call["model"] = tc_model
                    if tc_model not in models_used:
                        models_used.append(tc_model)
            elif etype == "abort":
                current_aborted = True
                _flush_turn()
            elif etype == "assistant.turn_end":
                _flush_turn()

        if current_turn_id is not None or current_user is not None:
            _flush_turn()

        todos = _read_todos(discovered.db_path)
        actual_usage, actual_usage_by_model = _extract_usage(events)

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
            actual_usage=actual_usage,
            actual_usage_by_model=actual_usage_by_model,
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


def _reasoning_effort_for(events: list[dict], model: str, before_idx: int):
    """Return the most recent reasoning effort applicable to `model` BEFORE `before_idx`."""
    last_effort = None
    for i in range(before_idx):
        e = events[i]
        if e.get("type") == "session.model_change":
            d = e.get("data") or {}
            if d.get("newModel") == model or model == "":
                effort = d.get("reasoningEffort")
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
