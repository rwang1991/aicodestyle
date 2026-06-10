"""Per-session feature extraction. All 18 signals from DESIGN.md §6."""
from __future__ import annotations

import math
import re
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

# Hands-on signal helpers (Phase A axis rework)
_CODE_FENCE_RE = re.compile(r"```")
_CODE_LINE_RE = re.compile(
    r"^\s*(?:def |class |import |from |return |if |for |while |[\{\}]|//|/\*|<\?|\$\(|>>>|\.\.\. )",
    re.MULTILINE,
)
# File path with extension OR explicit @file mention OR `name()` function call.
# Order matters: more specific patterns first so they "win" via overall regex match.
_FILE_REF_RE = re.compile(
    r"(?:[\w\-./\\]+\.(?:py|ts|tsx|js|jsx|go|rs|java|kt|cpp|c|h|hpp|cs|rb|php|swift|md|json|yaml|yml|toml|sh|ps1|html|css|sql|proto))(?::\d+)?"
    r"|@[\w\-./]+"
    r"|\b[a-z_][a-z0-9_]*\([^)]*\)",
    re.IGNORECASE,
)
_SPECIFICITY_MAX_WORDS = 200  # cap so a 5000-word essay doesn't dominate


def _has_code_content(msg: str) -> bool:
    """True if the message has a fenced code block OR >=3 code-looking lines."""
    if _CODE_FENCE_RE.search(msg):
        return True
    return len(_CODE_LINE_RE.findall(msg)) >= 3


def _has_file_reference(msg: str) -> bool:
    return bool(_FILE_REF_RE.search(msg))


def _specificity_score(msg: str) -> float:
    """Word count, capped at _SPECIFICITY_MAX_WORDS, normalised to [0, 1]."""
    words = len(msg.split())
    return min(words, _SPECIFICITY_MAX_WORDS) / _SPECIFICITY_MAX_WORDS


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

    # Hands-on signals (Phase A axis rework) - capture USER agency
    prompt_specificity_avg: float = 0.0
    code_block_density: float = 0.0
    file_reference_rate: float = 0.0
    ai_agency_rate: float = 0.0

    # Prompt-mined facts (Phase C vivid report)
    longest_prompt_words: int = 0
    total_user_words: int = 0
    first_user_msg_at: datetime | None = None
    last_user_msg_at: datetime | None = None
    first_words: list[str] = Field(default_factory=list)


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


# Inter-event gaps longer than this are treated as idle time and excluded from
# the engaged session duration. Copilot CLI sessions can stay open for hours
# while the user is at lunch, in a meeting, asleep, etc. Without capping, a
# typical user accrues thousands of "hours" of engagement that they never
# actually spent driving the AI.
_IDLE_CAP_SEC = 300.0  # 5 minutes


def _engaged_session_seconds(turns: list, idle_cap: float = _IDLE_CAP_SEC) -> float:
    """Sum inter-event gaps within a session, capping each gap at ``idle_cap``.

    This approximates "time the user was actively engaging with the assistant"
    rather than wall-clock duration. A session with two events four hours
    apart contributes ``min(4h, idle_cap)`` seconds to the total.
    """
    times: list = []
    for t in turns:
        if t.user is not None:
            times.append(t.user.ts)
        if t.assistant is not None:
            times.append(t.assistant.ts)
        for c in t.tool_calls:
            times.append(c.ts_start)
            times.append(c.ts_end)
    if len(times) < 2:
        return 0.0
    times.sort()
    engaged = 0.0
    for prev, curr in zip(times, times[1:]):
        delta = (curr - prev).total_seconds()
        if delta <= 0:
            continue
        engaged += min(delta, idle_cap)
    return engaged


def _first_token(msg: str) -> str:
    """Return the first alphanumeric token in `msg`, lowercased.

    Keeps an internal apostrophe (so ``Let's`` -> ``let's``, ``don't`` ->
    ``don't``) but strips leading/trailing punctuation (``/refactor`` ->
    ``refactor``). Returns "" if the message has no alphanumeric characters.
    """
    for tok in msg.lower().split():
        # Strip leading/trailing punctuation but keep internal apostrophes.
        cleaned = tok.strip(".,!?;:()[]{}\"`/\\<>*#-_=+|~")
        # Drop anything that's still not alphanumeric or apostrophe.
        cleaned = "".join(ch for ch in cleaned if ch.isalnum() or ch == "'")
        # Make sure the result has at least one alphanumeric character.
        if any(ch.isalnum() for ch in cleaned):
            return cleaned
    return ""


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

    # Hands-on signals (Phase A axis rework) - all derived from user-typed text
    prompt_specificity = _avg([_specificity_score(m) for m in user_msgs])
    code_block_density = _avg([1.0 if _has_code_content(m) else 0.0 for m in user_msgs])
    file_reference_rate = _avg([1.0 if _has_file_reference(m) else 0.0 for m in user_msgs])

    # Prompt-mined facts (Phase C vivid report). Per-session aggregates that
    # `stats.py` rolls up into vivid did-you-know callouts ("your longest
    # prompt", "your latest hour", etc.).
    word_counts = [len(m.split()) for m in user_msgs]
    longest_prompt_words = max(word_counts) if word_counts else 0
    total_user_words = sum(word_counts)
    user_turn_times = [t.user.ts for t in turns if t.user is not None]
    first_user_msg_at = min(user_turn_times) if user_turn_times else None
    last_user_msg_at = max(user_turn_times) if user_turn_times else None
    first_words = [w for w in (_first_token(m) for m in user_msgs) if w]
    # S9: thinks_before_prompt_sec_avg.
    # Cap each (assistant -> next user) gap at ``_IDLE_CAP_SEC`` so an overnight
    # session left open (12h+ between turns) doesn't drag the average into the
    # hours. Pauses longer than the cap are interpreted as "user walked away"
    # rather than "user is thinking deeply", consistent with how engaged session
    # duration is computed above in ``_engaged_session_seconds``.
    gaps: list[float] = []
    for prev, nxt in zip(turns, turns[1:]):
        if prev.assistant and nxt.user:
            raw = (nxt.user.ts - prev.assistant.ts).total_seconds()
            if raw > 0:
                gaps.append(min(raw, _IDLE_CAP_SEC))
    thinks_avg = _avg(gaps)

    all_tool_calls = [c for t in turns for c in t.tool_calls]
    tool_name_counts = Counter(c.tool_name for c in all_tool_calls)
    tool_diversity = _shannon_entropy(list(tool_name_counts.values()))

    # ai_agency_rate: how many tool calls the AI made per user prompt.
    # High = AI is doing the work autonomously (user is hands-off).
    ai_agency_rate = (
        len(all_tool_calls) / len(user_msgs) if user_msgs else 0.0
    )

    accept_and_go = _avg([1.0 if (t.user and _is_accept_and_go(t.user.content)) else 0.0 for t in turns])
    revision_depth = (len(all_tool_calls) / len(turns)) if turns else 0.0
    duration = _engaged_session_seconds(turns)
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

    # P7: models_used (dict[str, int] = model → turn count). Skip empty model
    # strings, which appear when assistant.message events arrived without a
    # ``model`` field (mainly the very first turn of older Copilot CLI builds).
    models_used_dict = dict(Counter(
        t.assistant.model for t in turns if t.assistant and t.assistant.model
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
        low = p.lower().replace("\\", "/")
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
        prompt_specificity_avg=prompt_specificity,
        code_block_density=code_block_density,
        file_reference_rate=file_reference_rate,
        ai_agency_rate=ai_agency_rate,
        longest_prompt_words=longest_prompt_words,
        total_user_words=total_user_words,
        first_user_msg_at=first_user_msg_at,
        last_user_msg_at=last_user_msg_at,
        first_words=first_words,
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

    # Hands-on signals (Phase A axis rework)
    prompt_specificity_avg: float = 0.0
    code_block_density: float = 0.0
    file_reference_rate: float = 0.0
    ai_agency_rate: float = 0.0


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
    "prompt_specificity_avg",
    "code_block_density",
    "file_reference_rate",
    "ai_agency_rate",
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
