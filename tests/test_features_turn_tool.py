import math
from pathlib import Path

from aianalyzer.collectors.copilot_cli import CopilotCliCollector
from aianalyzer.discovery import DiscoveredSession
from aianalyzer.features import extract_session_features


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

    # session duration: 11:00:25 - 11:00:00 = 25s
    assert f.session_duration_sec == 25.0

    # tool error rate: 1 of 4 calls failed
    assert abs(f.tool_error_rate - 0.25) < 1e-6

    # edited files per turn: t1 -> 2 (app.py, requirements.txt), t2 -> 0, t3 -> 1 (app.py)
    assert abs(f.edited_files_per_turn_avg - 1.0) < 1e-6

    # parallel tool calls: t1 has 2 calls (parallel), t2 and t3 have 1 each -> 1/3
    assert abs(f.parallel_tool_call_rate - (1 / 3)) < 1e-6
