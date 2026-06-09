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
