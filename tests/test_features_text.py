from pathlib import Path

from aianalyzer.collectors.copilot_cli import CopilotCliCollector
from aianalyzer.discovery import DiscoveredSession
from aianalyzer.features import SessionFeatures, extract_session_features


def _parse(fixtures_dir: Path, name: str) -> SessionFeatures:
    src = fixtures_dir / name
    discovered = DiscoveredSession(
        client="copilot-cli",
        session_id="sp",
        root=src.parent,
        events_path=src,
        db_path=None,
        mtime=src.stat().st_mtime,
    )
    session = CopilotCliCollector().parse(discovered)
    return extract_session_features(session)


def test_text_signals_for_planner_session(fixtures_dir: Path):
    f = _parse(fixtures_dir, "events_planner.jsonl")

    assert isinstance(f, SessionFeatures)
    assert f.session_id == "sp"
    assert f.turn_count == 3
    # S1: messages = [73 chars, 64 chars, 8 chars] -> mean ~ 48-50
    assert 40 <= f.avg_user_msg_chars <= 60
    # S2: 1 of 3 messages contains a planning keyword (the first) -> 1/3
    assert abs(f.planning_language_ratio - (1 / 3)) < 1e-6
    # S3: question_ratio: m2 contains '?' and starts with "What" -> 1/3
    assert abs(f.question_ratio - (1 / 3)) < 1e-6
    # S9: gaps are (30 - 10) and (50 - 34) -> mean 18s
    assert abs(f.thinks_before_prompt_sec_avg - 18.0) < 1e-6
    # S17: m2 mentions test/pytest/fixture -> 1/3
    assert abs(f.test_or_spec_mention_rate - (1 / 3)) < 1e-6


def test_all_signal_fields_defined():
    expected_fields = {
        "session_id", "client", "started_at", "turn_count",
        "avg_user_msg_chars", "planning_language_ratio", "question_ratio",
        "tool_diversity", "accept_and_go_ratio", "revision_depth",
        "session_duration_sec", "tool_error_rate",
        "thinks_before_prompt_sec_avg", "edited_files_per_turn_avg",
        "model_variety", "reasoning_effort_distribution",
        "cwd_switch_count", "command_repetition_rate",
        "todo_count", "abort_rate",
        "test_or_spec_mention_rate", "parallel_tool_call_rate",
        # Portal-extended fields (M4)
        "cwd", "avg_user_msg_words", "tool_counts", "file_paths_touched",
        "started_hour_local", "started_weekday", "models_used",
    }
    assert set(SessionFeatures.model_fields.keys()) == expected_fields
