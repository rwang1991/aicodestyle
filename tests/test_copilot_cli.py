import sqlite3
import textwrap
from pathlib import Path

from aianalyzer.collectors.copilot_cli import CopilotCliCollector
from aianalyzer.discovery import DiscoveredSession


def _bootstrap_db(db_path: Path, sql_file: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(sql_file.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def test_collector_parses_minimal_session(tmp_path: Path, fixtures_dir: Path):
    root = tmp_path / "session"
    root.mkdir()
    events = root / "events.jsonl"
    events.write_text(
        (fixtures_dir / "events_minimal.jsonl").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    db = root / "session.db"
    _bootstrap_db(db, fixtures_dir / "session_db_sample.sql")

    discovered = DiscoveredSession(
        client="copilot-cli",
        session_id="11111111-2222-3333-4444-555555555555",
        root=root,
        events_path=events,
        db_path=db,
        mtime=events.stat().st_mtime,
    )

    session = CopilotCliCollector().parse(discovered)
    assert session.client == "copilot-cli"
    assert session.session_id == "11111111-2222-3333-4444-555555555555"
    assert session.cwd == "C:/work/proj"
    assert session.models_used == ["claude-opus-4.7-xhigh"]
    assert len(session.turns) == 1
    turn = session.turns[0]
    assert turn.user.content == "Please plan the refactor."
    assert turn.assistant.content == "Here is the plan."
    assert turn.assistant.reasoning_effort == "xhigh"
    assert {t.title for t in session.todos} == {"Plan the refactor", "Implement parser"}


def test_collector_pairs_tool_start_with_complete(tmp_path: Path):
    events_text = textwrap.dedent(
        """\
        {"type":"session.start","ts":"2026-06-09T10:00:00Z","data":{"sessionId":"s","startTime":"2026-06-09T10:00:00Z","context":{"cwd":"."},"copilotVersion":"x"}}
        {"type":"user.message","ts":"2026-06-09T10:00:01Z","data":{"content":"go"}}
        {"type":"assistant.turn_start","ts":"2026-06-09T10:00:02Z","data":{"turnId":"t1","interactionId":"i1"}}
        {"type":"tool.execution_start","ts":"2026-06-09T10:00:03Z","data":{"toolCallId":"c1","toolName":"view","arguments":{"path":"README.md"},"turnId":"t1"}}
        {"type":"tool.execution_complete","ts":"2026-06-09T10:00:04Z","data":{"toolCallId":"c1","success":true,"model":"m","turnId":"t1"}}
        {"type":"assistant.message","ts":"2026-06-09T10:00:05Z","data":{"messageId":"m1","model":"m","content":"done","toolRequests":[],"turnId":"t1"}}
        {"type":"assistant.turn_end","ts":"2026-06-09T10:00:06Z","data":{"turnId":"t1"}}
        """
    )
    events = tmp_path / "events.jsonl"
    events.write_text(events_text, encoding="utf-8")
    discovered = DiscoveredSession(
        client="copilot-cli",
        session_id="s",
        root=tmp_path,
        events_path=events,
        db_path=None,
        mtime=events.stat().st_mtime,
    )
    session = CopilotCliCollector().parse(discovered)
    assert len(session.turns) == 1
    calls = session.turns[0].tool_calls
    assert len(calls) == 1
    assert calls[0].tool_name == "view"
    assert calls[0].duration_ms == 1000
    assert calls[0].success is True


def test_collector_normalizes_non_dict_arguments(tmp_path: Path):
    """Real copilot CLI emits tools (e.g. apply_patch) whose ``arguments`` is a
    raw string. The collector must coerce it into a dict so ToolCall validates
    and downstream ``arguments.get(...)`` lookups stay safe.
    """
    events_text = textwrap.dedent(
        """\
        {"type":"session.start","ts":"2026-06-09T10:00:00Z","data":{"sessionId":"s","startTime":"2026-06-09T10:00:00Z","context":{"cwd":"."},"copilotVersion":"x"}}
        {"type":"user.message","ts":"2026-06-09T10:00:01Z","data":{"content":"go"}}
        {"type":"assistant.turn_start","ts":"2026-06-09T10:00:02Z","data":{"turnId":"t1","interactionId":"i1"}}
        {"type":"tool.execution_start","ts":"2026-06-09T10:00:03Z","data":{"toolCallId":"c1","toolName":"apply_patch","arguments":"*** Begin Patch\\n*** Add File: hi.py\\n*** End Patch","turnId":"t1"}}
        {"type":"tool.execution_complete","ts":"2026-06-09T10:00:04Z","data":{"toolCallId":"c1","success":true,"model":"m","turnId":"t1"}}
        {"type":"assistant.message","ts":"2026-06-09T10:00:05Z","data":{"messageId":"m1","model":"m","content":"done","toolRequests":[],"turnId":"t1"}}
        {"type":"assistant.turn_end","ts":"2026-06-09T10:00:06Z","data":{"turnId":"t1"}}
        """
    )
    events = tmp_path / "events.jsonl"
    events.write_text(events_text, encoding="utf-8")
    discovered = DiscoveredSession(
        client="copilot-cli", session_id="s", root=tmp_path,
        events_path=events, db_path=None, mtime=events.stat().st_mtime,
    )
    session = CopilotCliCollector().parse(discovered)
    calls = session.turns[0].tool_calls
    assert len(calls) == 1
    assert calls[0].tool_name == "apply_patch"
    assert isinstance(calls[0].arguments, dict)
    assert "Begin Patch" in calls[0].arguments["_raw"]
    # Downstream code that does .get("path") must return None, not crash.
    assert calls[0].arguments.get("path") is None


def test_collector_aborted_turn_flagged(tmp_path: Path):
    events_text = textwrap.dedent(
        """\
        {"type":"session.start","ts":"2026-06-09T10:00:00Z","data":{"sessionId":"s","startTime":"2026-06-09T10:00:00Z","context":{"cwd":"."},"copilotVersion":"x"}}
        {"type":"user.message","ts":"2026-06-09T10:00:01Z","data":{"content":"go"}}
        {"type":"assistant.turn_start","ts":"2026-06-09T10:00:02Z","data":{"turnId":"t1","interactionId":"i1"}}
        {"type":"abort","ts":"2026-06-09T10:00:03Z","data":{"reason":"user_cancel"}}
        """
    )
    events = tmp_path / "events.jsonl"
    events.write_text(events_text, encoding="utf-8")
    discovered = DiscoveredSession(
        client="copilot-cli",
        session_id="s",
        root=tmp_path,
        events_path=events,
        db_path=None,
        mtime=events.stat().st_mtime,
    )
    session = CopilotCliCollector().parse(discovered)
    assert session.turns[0].aborted is True


def test_collector_recovers_cwd_from_session_resume(tmp_path: Path):
    events_text = textwrap.dedent(
        """\
        {"type":"session.start","timestamp":"2026-06-09T10:00:00Z","data":{"sessionId":"s","copilotVersion":"x"}}
        {"type":"session.resume","timestamp":"2026-06-09T10:00:01Z","data":{"context":{"cwd":"C:/from/resume"}}}
        {"type":"user.message","timestamp":"2026-06-09T10:00:02Z","data":{"content":"go"}}
        {"type":"assistant.turn_start","timestamp":"2026-06-09T10:00:03Z","data":{"turnId":"t1"}}
        {"type":"assistant.message","timestamp":"2026-06-09T10:00:04Z","data":{"messageId":"m","content":"ok","model":"m1"}}
        {"type":"assistant.turn_end","timestamp":"2026-06-09T10:00:05Z","data":{"turnId":"t1"}}
        """
    )
    events = tmp_path / "events.jsonl"
    events.write_text(events_text, encoding="utf-8")
    discovered = DiscoveredSession(
        client="copilot-cli", session_id="s", root=tmp_path,
        events_path=events, db_path=None, mtime=events.stat().st_mtime,
    )
    session = CopilotCliCollector().parse(discovered)
    assert session.cwd == "C:/from/resume"


def test_collector_recovers_model_from_tool_complete(tmp_path: Path):
    events_text = textwrap.dedent(
        """\
        {"type":"session.start","timestamp":"2026-06-09T10:00:00Z","data":{"sessionId":"s","context":{"cwd":"."},"copilotVersion":"x"}}
        {"type":"user.message","timestamp":"2026-06-09T10:00:01Z","data":{"content":"go"}}
        {"type":"assistant.turn_start","timestamp":"2026-06-09T10:00:02Z","data":{"turnId":"t1"}}
        {"type":"assistant.message","timestamp":"2026-06-09T10:00:03Z","data":{"messageId":"m","content":"","toolRequests":[{"toolCallId":"c1","name":"view","arguments":{}}]}}
        {"type":"tool.execution_start","timestamp":"2026-06-09T10:00:04Z","data":{"toolCallId":"c1","toolName":"view","arguments":{}}}
        {"type":"tool.execution_complete","timestamp":"2026-06-09T10:00:05Z","data":{"toolCallId":"c1","success":true,"model":"claude-opus-4.7"}}
        {"type":"assistant.turn_end","timestamp":"2026-06-09T10:00:06Z","data":{"turnId":"t1"}}
        """
    )
    events = tmp_path / "events.jsonl"
    events.write_text(events_text, encoding="utf-8")
    discovered = DiscoveredSession(
        client="copilot-cli", session_id="s", root=tmp_path,
        events_path=events, db_path=None, mtime=events.stat().st_mtime,
    )
    session = CopilotCliCollector().parse(discovered)
    assert session.turns[0].assistant.model == "claude-opus-4.7"
    assert "claude-opus-4.7" in session.models_used


def test_reasoning_effort_does_not_leak_backward(tmp_path: Path):
    events_text = textwrap.dedent(
        """\
        {"type":"session.start","timestamp":"2026-06-09T10:00:00Z","data":{"sessionId":"s","context":{"cwd":"."},"copilotVersion":"x"}}
        {"type":"session.model_change","timestamp":"2026-06-09T10:00:01Z","data":{"newModel":"m1","reasoningEffort":"high"}}
        {"type":"user.message","timestamp":"2026-06-09T10:00:02Z","data":{"content":"first"}}
        {"type":"assistant.turn_start","timestamp":"2026-06-09T10:00:03Z","data":{"turnId":"t1"}}
        {"type":"assistant.message","timestamp":"2026-06-09T10:00:04Z","data":{"messageId":"m","content":"ok","model":"m1"}}
        {"type":"assistant.turn_end","timestamp":"2026-06-09T10:00:05Z","data":{"turnId":"t1"}}
        {"type":"session.model_change","timestamp":"2026-06-09T10:00:06Z","data":{"newModel":"m1","reasoningEffort":"low"}}
        {"type":"user.message","timestamp":"2026-06-09T10:00:07Z","data":{"content":"second"}}
        {"type":"assistant.turn_start","timestamp":"2026-06-09T10:00:08Z","data":{"turnId":"t2"}}
        {"type":"assistant.message","timestamp":"2026-06-09T10:00:09Z","data":{"messageId":"m2","content":"ok","model":"m1"}}
        {"type":"assistant.turn_end","timestamp":"2026-06-09T10:00:10Z","data":{"turnId":"t2"}}
        """
    )
    events = tmp_path / "events.jsonl"
    events.write_text(events_text, encoding="utf-8")
    discovered = DiscoveredSession(
        client="copilot-cli", session_id="s", root=tmp_path,
        events_path=events, db_path=None, mtime=events.stat().st_mtime,
    )
    session = CopilotCliCollector().parse(discovered)
    # First turn must still see "high" — not "low".
    assert session.turns[0].assistant.reasoning_effort == "high"
    assert session.turns[1].assistant.reasoning_effort == "low"


def test_collector_handles_real_corpus_without_crash():
    """Smoke test: parsing every real local session must not crash."""
    from aianalyzer.discovery import discover_copilot_cli_sessions
    sessions = list(discover_copilot_cli_sessions())
    if not sessions:
        return  # skip if no real corpus present
    parser = CopilotCliCollector()
    crashes = []
    for d in sessions:
        try:
            parser.parse(d)
        except Exception as exc:  # noqa: BLE001
            crashes.append((d.session_id, type(exc).__name__, str(exc)[:120]))
    assert not crashes, f"Crashes on real corpus: {crashes[:5]}"
def test_collector_extracts_billed_usage_from_shutdown(tmp_path: Path):
    events_text = textwrap.dedent(
        """\
        {"type":"session.start","timestamp":"2026-06-09T10:00:00Z","data":{"sessionId":"s","context":{"cwd":"."}}}
        {"type":"session.shutdown","timestamp":"2026-06-09T10:00:01Z","data":{"shutdownType":"routine","totalPremiumRequests":1,"totalNanoAiu":75790800000,"tokenDetails":{"input":{"tokenCount":17},"cache_read":{"tokenCount":311321},"cache_write":{"tokenCount":82162},"output":{"tokenCount":3546}},"modelMetrics":{"claude-opus-4.7-xhigh":{"requests":{"count":7,"cost":1},"usage":{"inputTokens":393500,"outputTokens":3546,"cacheReadTokens":311321,"cacheWriteTokens":82162,"reasoningTokens":0},"totalNanoAiu":75790800000}}}}
        """
    )
    events = tmp_path / "events.jsonl"
    events.write_text(events_text, encoding="utf-8")
    discovered = DiscoveredSession(
        client="copilot-cli", session_id="s", root=tmp_path,
        events_path=events, db_path=None, mtime=events.stat().st_mtime,
    )

    session = CopilotCliCollector().parse(discovered)

    assert session.actual_usage is not None
    # 393500 = 17 uncached + 311321 cache_read + 82162 cache_write.
    # We normalise input_tokens to mean "uncached only" so pricing isn't double-charged.
    assert session.actual_usage.input_tokens == 17
    assert session.actual_usage.cache_read_tokens == 311321
    assert session.actual_usage.cache_write_tokens == 82162
    assert session.actual_usage.output_tokens == 3546
    assert session.actual_usage.premium_requests == 1.0
    assert session.actual_usage_by_model["claude-opus-4.7-xhigh"].requests == 7
    assert session.actual_usage_by_model["claude-opus-4.7-xhigh"].input_tokens == 17

