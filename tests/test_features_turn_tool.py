import math
import textwrap
from pathlib import Path

from aianalyzer.collectors.copilot_cli import CopilotCliCollector
from aianalyzer.discovery import DiscoveredSession
from aianalyzer.features import _engaged_session_seconds, extract_session_features


def _features(fixtures_dir: Path, name: str):
    src = fixtures_dir / name
    discovered = DiscoveredSession(
        client="copilot-cli",
        session_id="vibe",
        root=src.parent,
        events_path=src,
        db_path=None,
        mtime=src.stat().st_mtime,
    )
    return extract_session_features(CopilotCliCollector().parse(discovered))


def test_turn_tool_signals_for_vibe_session(fixtures_dir: Path):
    f = _features(fixtures_dir, "events_vibe.jsonl")

    # 4 tool calls total: create, create, powershell, edit
    expected_entropy = -(0.5 * math.log(0.5) + 0.25 * math.log(0.25) * 2)
    assert abs(f.tool_diversity - expected_entropy) < 1e-6

    # accept-and-go: messages = ["build me a todo app", "ok", "go"] -> 2/3
    assert abs(f.accept_and_go_ratio - (2 / 3)) < 1e-6

    # revision depth: 4 calls / 3 turns
    assert abs(f.revision_depth - (4 / 3)) < 1e-6

    # engaged duration: 14 events span 11:00:01 to 11:00:24 with all gaps
    # well under the 5-minute idle cap, so total engagement = 23s
    assert f.session_duration_sec == 23.0

    # tool error rate: 1 of 4 calls failed
    assert abs(f.tool_error_rate - 0.25) < 1e-6

    # edited files per turn: t1 -> 2 (app.py, requirements.txt), t2 -> 0, t3 -> 1 (app.py)
    assert abs(f.edited_files_per_turn_avg - 1.0) < 1e-6

    # parallel tool calls: t1 has 2 calls (parallel), t2 and t3 have 1 each -> 1/3
    assert abs(f.parallel_tool_call_rate - (1 / 3)) < 1e-6


def test_engaged_duration_caps_long_idle_gaps(tmp_path: Path):
    """A session left open over a 6-hour lunch break must not accrue 6 hours
    of engagement: each idle gap is capped at 5 minutes.
    """
    events_text = textwrap.dedent(
        """\
        {"type":"session.start","ts":"2026-06-09T09:00:00Z","data":{"sessionId":"s","startTime":"2026-06-09T09:00:00Z","context":{"cwd":"."},"copilotVersion":"x"}}
        {"type":"user.message","ts":"2026-06-09T09:00:01Z","data":{"content":"morning task"}}
        {"type":"assistant.turn_start","ts":"2026-06-09T09:00:02Z","data":{"turnId":"t1","interactionId":"i1"}}
        {"type":"assistant.message","ts":"2026-06-09T09:00:10Z","data":{"messageId":"m1","model":"m","content":"done","toolRequests":[],"turnId":"t1"}}
        {"type":"assistant.turn_end","ts":"2026-06-09T09:00:11Z","data":{"turnId":"t1"}}
        {"type":"user.message","ts":"2026-06-09T15:00:00Z","data":{"content":"afternoon task"}}
        {"type":"assistant.turn_start","ts":"2026-06-09T15:00:01Z","data":{"turnId":"t2","interactionId":"i2"}}
        {"type":"assistant.message","ts":"2026-06-09T15:00:05Z","data":{"messageId":"m2","model":"m","content":"ok","toolRequests":[],"turnId":"t2"}}
        {"type":"assistant.turn_end","ts":"2026-06-09T15:00:06Z","data":{"turnId":"t2"}}
        """
    )
    events = tmp_path / "events.jsonl"
    events.write_text(events_text, encoding="utf-8")
    discovered = DiscoveredSession(
        client="copilot-cli", session_id="s", root=tmp_path,
        events_path=events, db_path=None, mtime=events.stat().st_mtime,
    )
    f = extract_session_features(CopilotCliCollector().parse(discovered))
    # Within-turn gaps (09:00:01->09:00:10 = 9s, 15:00:00->15:00:05 = 5s) plus
    # the 6h cross-turn gap capped at 300s = 9 + 300 + 5 = 314s.
    # Wall-clock would have been 09:00:01..15:00:05 = 21604s.
    assert f.session_duration_sec == 314.0


def test_engaged_duration_helper_returns_zero_for_empty_turns():
    assert _engaged_session_seconds([]) == 0.0
