from datetime import datetime, timezone
from io import StringIO

from rich.console import Console

from aianalyzer.classifier.archetypes import Archetype, ClassificationResult
from aianalyzer.features import SessionFeatures, UserProfile
from aianalyzer.report.terminal import render_report


def _sf(idx: int, turn_count: int) -> SessionFeatures:
    return SessionFeatures(
        session_id=f"s{idx}",
        client="copilot-cli",
        started_at=datetime(2026, 6, idx + 1, tzinfo=timezone.utc),
        turn_count=turn_count,
    )


def test_render_report_contains_all_blocks():
    profile = UserProfile(
        session_count=3, total_turns=42, total_todos=5,
        distinct_models_total=2, cwd_switch_count=1,
        avg_user_msg_chars=120.5, planning_language_ratio=0.4,
        question_ratio=0.3, thinks_before_prompt_sec_avg=25.0,
        test_or_spec_mention_rate=0.1, tool_diversity=1.5,
        accept_and_go_ratio=0.2, revision_depth=1.7,
        session_duration_sec=900.0, tool_error_rate=0.1,
        edited_files_per_turn_avg=1.2, parallel_tool_call_rate=0.15,
        abort_rate=0.05,
        reasoning_effort_distribution={"high": 0.6, "xhigh": 0.4},
    )
    result = ClassificationResult(
        planning_score=0.3, control_score=0.4,
        primary=Archetype.ARCHITECT, secondary=None,
        tags=["questioner", "planner"],
        macro_label="Architect (questioner, planner)",
        secondary_margin=0.15,
    )
    sessions = [_sf(0, 5), _sf(1, 20), _sf(2, 17)]

    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=120, color_system=None)
    render_report(profile, result, sessions, console=console)
    out = buf.getvalue()

    assert "Architect (questioner, planner)" in out
    assert "planning" in out.lower()
    assert "control" in out.lower()
    assert "120.5" in out  # avg_user_msg_chars rendered
    assert "questioner" in out
    # sparkline line should appear (any block char)
    assert any(ch in out for ch in "▁▂▃▄▅▆▇█")


def test_render_report_handles_empty_session_list():
    profile = UserProfile()
    result = ClassificationResult(
        planning_score=0.0, control_score=0.0,
        primary=Archetype.VIBE_CODER, secondary=None,
        tags=[], macro_label="Vibe Coder", secondary_margin=0.15,
    )
    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=80, color_system=None)
    render_report(profile, result, [], console=console)
    out = buf.getvalue()
    assert "Vibe Coder" in out
    assert "0 sessions" in out


def test_render_report_falls_back_to_ascii_sparkline_on_cp1252():
    """On Windows the console codepage is cp1252, which has no glyphs for the
    U+2581..U+2588 block characters used by the unicode sparkline. The renderer
    must downgrade gracefully instead of raising UnicodeEncodeError.
    """

    class _Cp1252Buffer(StringIO):
        encoding = "cp1252"

    profile = UserProfile(session_count=3, total_turns=42)
    result = ClassificationResult(
        planning_score=0.3, control_score=0.4,
        primary=Archetype.ARCHITECT, secondary=None,
        tags=["planner"], macro_label="Architect", secondary_margin=0.15,
    )
    sessions = [_sf(0, 5), _sf(1, 20), _sf(2, 17)]
    buf = _Cp1252Buffer()
    console = Console(file=buf, force_terminal=False, width=120, color_system=None)
    render_report(profile, result, sessions, console=console)
    out = buf.getvalue()

    assert "timeline" in out
    # No unicode block chars (they would later crash flush on a real cp1252 stdout).
    assert not any(ch in out for ch in "▁▂▃▄▅▆▇█")
    # ASCII fallback chars appear instead.
    assert any(ch in out for ch in ".:-=+*#")
