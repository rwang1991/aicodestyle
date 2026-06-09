"""Per-session feature extraction. All 18 signals from DESIGN.md §6."""
from __future__ import annotations

import math
from collections import Counter
from datetime import datetime
from statistics import mean
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from aianalyzer.classifier.session_types import SessionType, classify_session_type
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
_ACCEPT_TOKENS = {
    "yes", "ok", "okay", "go", "proceed", "continue",
    "do it", "ship it", "sounds good", "looks good", "lgtm",
}
_EDIT_TOOL_NAMES = {"edit", "create", "write"}


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

    # Portal-extended fields (M4)
    cwd: str | None = None
    avg_user_msg_words: float = 0.0
    tool_counts: dict[str, int] = Field(default_factory=dict)
    file_paths_touched: set[str] = Field(default_factory=set)
    started_hour_local: int = 0
    started_weekday: int = 0
    models_used: dict[str, int] = Field(default_factory=dict)
    session_type: SessionType = SessionType.MIXED


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


def _shannon_entropy(counts: list[int]) -> float:
    total = sum(counts)
    if total == 0:
        return 0.0
    entropy = 0.0
    for c in counts:
        if c == 0:
            continue
        p = c / total
        entropy -= p * math.log(p)
    return entropy


def _is_accept_and_go(text: str) -> bool:
    stripped = text.strip().lower().rstrip(".!?,")
    return stripped in _ACCEPT_TOKENS


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

    all_tool_calls = [c for t in turns for c in t.tool_calls]
    tool_name_counts = Counter(c.tool_name for c in all_tool_calls)
    tool_diversity = _shannon_entropy(list(tool_name_counts.values()))

    accept_and_go = _avg([1.0 if (t.user and _is_accept_and_go(t.user.content)) else 0.0 for t in turns])
    revision_depth = (len(all_tool_calls) / len(turns)) if turns else 0.0
    duration = (session.ended_at - session.started_at).total_seconds()
    tool_error_rate = (
        sum(1 for c in all_tool_calls if not c.success) / len(all_tool_calls)
        if all_tool_calls else 0.0
    )

    edited_per_turn: list[float] = []
    for t in turns:
        paths = {
            str(c.arguments.get("path"))
            for c in t.tool_calls
            if c.tool_name in _EDIT_TOOL_NAMES and c.arguments.get("path")
        }
        edited_per_turn.append(float(len(paths)))
    edited_avg = _avg(edited_per_turn) if turns else 0.0

    parallel_rate = (
        sum(1 for t in turns if len(t.tool_calls) > 1) / len(turns)
        if turns else 0.0
    )

    # S11: model_variety
    model_variety = len(session.models_used)

    # S12: reasoning_effort_distribution
    efforts = [
        t.assistant.reasoning_effort
        for t in turns
        if t.assistant and t.assistant.reasoning_effort
    ]
    if efforts:
        counts = Counter(efforts)
        total = sum(counts.values())
        reasoning_distribution = {k: v / total for k, v in counts.items()}
    else:
        reasoning_distribution = {}

    # S14: command_repetition_rate
    powershell_cmds = [
        str(c.arguments.get("command"))
        for c in all_tool_calls
        if c.tool_name == "powershell" and c.arguments.get("command") is not None
    ]
    if len(powershell_cmds) >= 2:
        cmd_counts = Counter(powershell_cmds)
        repeats = sum(c for c in cmd_counts.values() if c > 1)
        command_repetition = repeats / len(powershell_cmds)
    else:
        command_repetition = 0.0

    # S15: todo_count
    todo_count = len(session.todos)

    # S16: abort_rate
    abort_rate = _avg([1.0 if t.aborted else 0.0 for t in turns])

    # Portal-extended fields (M4)
    # P1: cwd
    cwd = session.cwd

    # P2: avg_user_msg_words
    if user_msgs:
        word_counts = [len(m.split()) for m in user_msgs]
        avg_user_msg_words = _avg([float(w) for w in word_counts])
    else:
        avg_user_msg_words = 0.0

    # P3: tool_counts
    tool_counts = dict(Counter(c.tool_name for c in all_tool_calls))

    # P4: file_paths_touched
    file_paths_touched = {
        str(c.arguments.get("path"))
        for c in all_tool_calls
        if c.arguments.get("path") and isinstance(c.arguments.get("path"), str)
    }

    # P5, P6: started_hour_local, started_weekday
    if session.started_at:
        local_start = session.started_at.astimezone()
        started_hour_local = local_start.hour
        started_weekday = local_start.weekday()
    else:
        started_hour_local = 0
        started_weekday = 0

    # P7: models_used (dict[str, int] = model → turn count)
    models_used_dict = dict(Counter(
        t.assistant.model for t in turns if t.assistant
    ))

    # P8: session_type classifier integration (Task 24)
    # Keyword vocabularies for the session-type classifier
    DEBUG_KW = ("error", "exception", "traceback", "stack trace", "fail", "bug", "crash")
    TEST_KW = ("test", "spec", "pytest", "unittest", "jest")
    DOC_EXTS = (".md", ".rst", ".txt")
    REFACTOR_KW = ("refactor", "rename", "cleanup", "tidy", "extract")
    REVIEW_KW = ("review", "look at", "what do you think", "feedback")
    PLAN_KW = ("plan", "design", "approach", "strategy", "outline")

    def _density(text: str, vocab: tuple[str, ...]) -> float:
        if not text:
            return 0.0
        low = text.lower()
        words = max(len(text.split()), 1)
        return sum(low.count(kw) for kw in vocab) / words

    all_user_text = " ".join(t.user.content for t in turns if t.user and t.user.content)
    debug_kw_density = _density(all_user_text, DEBUG_KW)
    refactor_kw_density = _density(all_user_text, REFACTOR_KW)
    review_kw_density = _density(all_user_text, REVIEW_KW)
    planning_language = _density(all_user_text, PLAN_KW)

    # question_ratio and test_or_spec_mention_rate already computed earlier
    # (variables `question` and `test_mention`)

    def _is_test_path(p: str) -> bool:
        low = p.lower()
        return (
            "/test" in low
            or low.startswith("test")
            or low.endswith(("_test.py", ".spec.ts", ".spec.js", ".test.ts", ".test.js"))
        )

    def _is_doc_path(p: str) -> bool:
        return p.lower().endswith(DOC_EXTS)

    paths = file_paths_touched
    majority_test_files = bool(paths) and sum(_is_test_path(p) for p in paths) / len(paths) >= 0.5
    majority_doc_files = bool(paths) and sum(_is_doc_path(p) for p in paths) / len(paths) >= 0.5

    edit_tool_calls = tool_counts.get("edit", 0) + tool_counts.get("str_replace_editor", 0)
    create_tool_calls = tool_counts.get("create", 0) + tool_counts.get("write", 0)

    session_type = classify_session_type(
        turns=len(turns),
        duration_seconds=duration,
        tool_error_rate=tool_error_rate,
        debug_kw_density=debug_kw_density,
        test_or_spec_mention_rate=test_mention,
        majority_test_files=majority_test_files,
        majority_doc_files=majority_doc_files,
        planning_language=planning_language,
        todos_count=len(session.todos),
        edited_files_per_turn=edited_avg,
        question_ratio=question,
        refactor_kw_density=refactor_kw_density,
        review_kw_density=review_kw_density,
        edit_tool_calls=edit_tool_calls,
        create_tool_calls=create_tool_calls,
    )

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
        tool_diversity=tool_diversity,
        accept_and_go_ratio=accept_and_go,
        revision_depth=revision_depth,
        session_duration_sec=duration,
        tool_error_rate=tool_error_rate,
        edited_files_per_turn_avg=edited_avg,
        parallel_tool_call_rate=parallel_rate,
        model_variety=model_variety,
        reasoning_effort_distribution=reasoning_distribution,
        cwd_switch_count=0,
        command_repetition_rate=command_repetition,
        todo_count=todo_count,
        abort_rate=abort_rate,
        cwd=cwd,
        avg_user_msg_words=avg_user_msg_words,
        tool_counts=tool_counts,
        file_paths_touched=file_paths_touched,
        started_hour_local=started_hour_local,
        started_weekday=started_weekday,
        models_used=models_used_dict,
        session_type=session_type,
    )


class UserProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_count: int = 0
    total_turns: int = 0
    total_todos: int = 0
    distinct_models_total: int = 0
    cwd_switch_count: int = 0

    avg_user_msg_chars: float = 0.0
    planning_language_ratio: float = 0.0
    question_ratio: float = 0.0
    thinks_before_prompt_sec_avg: float = 0.0
    test_or_spec_mention_rate: float = 0.0
    tool_diversity: float = 0.0
    accept_and_go_ratio: float = 0.0
    revision_depth: float = 0.0
    session_duration_sec: float = 0.0
    tool_error_rate: float = 0.0
    edited_files_per_turn_avg: float = 0.0
    parallel_tool_call_rate: float = 0.0
    abort_rate: float = 0.0
    reasoning_effort_distribution: dict[str, float] = Field(default_factory=dict)


_WEIGHTED_SCALARS = (
    "avg_user_msg_chars",
    "planning_language_ratio",
    "question_ratio",
    "thinks_before_prompt_sec_avg",
    "test_or_spec_mention_rate",
    "tool_diversity",
    "accept_and_go_ratio",
    "revision_depth",
    "session_duration_sec",
    "tool_error_rate",
    "edited_files_per_turn_avg",
    "parallel_tool_call_rate",
    "abort_rate",
)


def aggregate_user_profile(
    features: list[SessionFeatures],
    cwd_history: list[str | None],
) -> UserProfile:
    if not features:
        return UserProfile()

    total_turns = sum(f.turn_count for f in features) or 1
    weighted: dict[str, float] = {}
    for field in _WEIGHTED_SCALARS:
        weighted[field] = sum(getattr(f, field) * f.turn_count for f in features) / total_turns

    merged_efforts: Counter[str] = Counter()
    for f in features:
        for k, v in f.reasoning_effort_distribution.items():
            merged_efforts[k] += v * f.turn_count
    if merged_efforts:
        s = sum(merged_efforts.values())
        merged_distribution = {k: v / s for k, v in merged_efforts.items()}
    else:
        merged_distribution = {}

    distinct_cwds = {c for c in cwd_history if c}
    cwd_switches = max(len(distinct_cwds) - 1, 0)

    return UserProfile(
        session_count=len(features),
        total_turns=sum(f.turn_count for f in features),
        total_todos=sum(f.todo_count for f in features),
        distinct_models_total=max((f.model_variety for f in features), default=0),
        cwd_switch_count=cwd_switches,
        reasoning_effort_distribution=merged_distribution,
        **weighted,
    )
