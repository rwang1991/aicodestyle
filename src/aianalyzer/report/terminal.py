"""Terminal rendering for analyzer output."""
from __future__ import annotations

from typing import Sequence

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from aianalyzer.classifier.archetypes import ClassificationResult
from aianalyzer.features import SessionFeatures, UserProfile

_SPARK_CHARS_UNICODE = "▁▂▃▄▅▆▇█"
_SPARK_CHARS_ASCII = " .:-=+*#"


def _spark_chars_for(console: Console) -> str:
    """Return the block-drawing characters safe to print to ``console``.

    Windows consoles default to cp1252, which has no glyphs for U+2581..U+2588;
    rich raises UnicodeEncodeError when it flushes them. Fall back to ASCII
    whenever the console's underlying file cannot encode the block characters.
    Files with no ``encoding`` (e.g. StringIO buffers used in tests) carry
    arbitrary text and keep the prettier Unicode glyphs.
    """
    enc = getattr(console.file, "encoding", None)
    if not enc:
        return _SPARK_CHARS_UNICODE
    if "utf" in enc.lower():
        return _SPARK_CHARS_UNICODE
    try:
        _SPARK_CHARS_UNICODE.encode(enc)
        return _SPARK_CHARS_UNICODE
    except (UnicodeEncodeError, LookupError):
        return _SPARK_CHARS_ASCII


def _sparkline(values: Sequence[float], chars: str = _SPARK_CHARS_UNICODE) -> str:
    if not values:
        return ""
    hi = max(values)
    if hi <= 0:
        return chars[0] * len(values)
    step = hi / (len(chars) - 1)
    return "".join(chars[min(len(chars) - 1, int(v / step))] for v in values)


_SIGNAL_LABELS: list[tuple[str, str]] = [
    ("avg_user_msg_chars", "S1 Avg user message length (chars)"),
    ("planning_language_ratio", "S2 Planning-language ratio"),
    ("question_ratio", "S3 Question ratio"),
    ("tool_diversity", "S4 Tool diversity (entropy)"),
    ("accept_and_go_ratio", "S5 Accept-and-go ratio"),
    ("revision_depth", "S6 Revision depth (tool calls/turn)"),
    ("session_duration_sec", "S7 Avg session duration (sec)"),
    ("tool_error_rate", "S8 Tool error rate"),
    ("thinks_before_prompt_sec_avg", "S9 Think time before prompt (sec)"),
    ("edited_files_per_turn_avg", "S10 Edited files per turn"),
    ("distinct_models_total", "S11 Distinct models used"),
    ("cwd_switch_count", "S13 cwd switches across sessions"),
    ("total_todos", "S15 Total todos created"),
    ("abort_rate", "S16 Abort rate"),
    ("test_or_spec_mention_rate", "S17 Test/spec mention rate"),
    ("parallel_tool_call_rate", "S18 Parallel tool-call rate"),
]


def render_report(
    profile: UserProfile,
    result: ClassificationResult,
    sessions: Sequence[SessionFeatures],
    console: Console,
) -> None:
    panel_body = (
        f"[bold]{result.macro_label}[/bold]\n"
        f"planning axis: {result.planning_score:+.2f}    "
        f"control axis: {result.control_score:+.2f}\n"
        f"{len(sessions)} sessions, {profile.total_turns} turns total"
    )
    console.print(Panel(panel_body, title="AI archetype", expand=False))

    table = Table(title="Signals", show_lines=False)
    table.add_column("Signal")
    table.add_column("Value", justify="right")
    for field, label in _SIGNAL_LABELS:
        value = getattr(profile, field, 0)
        if isinstance(value, float):
            cell = f"{value:.2f}" if value != 0 else "0.00"
        else:
            cell = str(value)
        table.add_row(label, cell)
    console.print(table)

    if profile.reasoning_effort_distribution:
        effort_line = "  ".join(
            f"{k}={v:.0%}" for k, v in sorted(profile.reasoning_effort_distribution.items())
        )
        console.print(f"reasoning effort: {effort_line}")

    if sessions:
        ordered = sorted(sessions, key=lambda s: s.started_at)
        spark = _sparkline(
            [float(s.turn_count) for s in ordered],
            chars=_spark_chars_for(console),
        )
        console.print(f"timeline (turns/session): {spark}")
