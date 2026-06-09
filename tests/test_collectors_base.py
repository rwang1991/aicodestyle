from datetime import datetime, timezone
from pathlib import Path

from aianalyzer.collectors.base import Collector, iter_jsonl_events


def test_iter_jsonl_events_yields_typed_dicts(fixtures_dir: Path):
    events = list(iter_jsonl_events(fixtures_dir / "events_minimal.jsonl"))
    assert events[0]["type"] == "session.start"
    assert events[0]["ts"] == datetime(2026, 6, 9, 10, 0, 0, tzinfo=timezone.utc)
    assert events[-1]["type"] == "assistant.turn_end"
    assert len(events) == 6


def test_iter_jsonl_events_skips_blank_and_invalid_lines(tmp_path: Path):
    path = tmp_path / "evt.jsonl"
    path.write_text(
        '{"type":"a","ts":"2026-06-09T10:00:00Z","data":{}}\n'
        "\n"
        "not json\n"
        '{"type":"b","ts":"2026-06-09T10:00:01Z","data":{}}\n',
        encoding="utf-8",
    )
    types = [e["type"] for e in iter_jsonl_events(path)]
    assert types == ["a", "b"]


def test_collector_protocol_exists():
    assert hasattr(Collector, "parse")


def test_iter_jsonl_events_accepts_timestamp_key(tmp_path: Path):
    path = tmp_path / "evt.jsonl"
    path.write_text(
        '{"type":"a","timestamp":"2026-06-09T10:00:00Z","data":{}}\n'
        '{"type":"b","ts":"2026-06-09T10:00:01Z","data":{}}\n',
        encoding="utf-8",
    )
    events = list(iter_jsonl_events(path))
    assert events[0]["ts"] == datetime(2026, 6, 9, 10, 0, 0, tzinfo=timezone.utc)
    assert events[1]["ts"] == datetime(2026, 6, 9, 10, 0, 1, tzinfo=timezone.utc)


def test_iter_jsonl_events_drops_events_without_any_timestamp(tmp_path: Path):
    path = tmp_path / "evt.jsonl"
    path.write_text(
        '{"type":"no-ts","data":{}}\n'
        '{"type":"good","timestamp":"2026-06-09T10:00:01Z","data":{}}\n',
        encoding="utf-8",
    )
    types = [e["type"] for e in iter_jsonl_events(path)]
    assert types == ["good"]
