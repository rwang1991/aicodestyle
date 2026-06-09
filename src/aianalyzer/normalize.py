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
