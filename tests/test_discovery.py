from pathlib import Path

from aianalyzer.discovery import DiscoveredSession, discover_copilot_cli_sessions


def test_discover_returns_sessions(tmp_path: Path):
    home = tmp_path / "home"
    session_root = home / ".copilot" / "session-state"

    good = session_root / "11111111-2222-3333-4444-555555555555"
    good.mkdir(parents=True)
    (good / "events.jsonl").write_text("{}\n", encoding="utf-8")
    (good / "session.db").write_bytes(b"\x00")

    no_artifacts = session_root / "deadbeef-0000-0000-0000-000000000000"
    no_artifacts.mkdir(parents=True)

    not_a_session_id = session_root / "not-a-uuid"
    not_a_session_id.mkdir(parents=True)
    (not_a_session_id / "events.jsonl").write_text("{}\n", encoding="utf-8")

    found = list(discover_copilot_cli_sessions(home=home))
    assert len(found) == 1
    only = found[0]
    assert isinstance(only, DiscoveredSession)
    assert only.session_id == "11111111-2222-3333-4444-555555555555"
    assert only.events_path.name == "events.jsonl"
    assert only.db_path is not None and only.db_path.name == "session.db"
    assert only.client == "copilot-cli"
    assert only.mtime > 0


def test_discover_missing_root_returns_empty(tmp_path: Path):
    assert list(discover_copilot_cli_sessions(home=tmp_path / "nope")) == []
