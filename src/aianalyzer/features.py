"""Per-session feature extraction. All 18 signals from DESIGN.md §6."""
from __future__ import annotations

from datetime import datetime
from statistics import mean
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from aianalyzer.normalize import NormalizedSession, Turn

_PLANNING_TOKENS = (
    "plan", "design", "approach", "options", "tradeoff", "before we code",
    "propose", "outline", "architecture",
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
