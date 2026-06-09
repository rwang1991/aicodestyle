from datetime import datetime, timezone
from pathlib import Path

from aianalyzer.features import SessionFeatures
from aianalyzer.store import FeatureStore


def _sf(session_id: str, turn_count: int = 1) -> SessionFeatures:
    return SessionFeatures(
        session_id=session_id,
        client="copilot-cli",
        started_at=datetime(2026, 6, 9, tzinfo=timezone.utc),
        turn_count=turn_count,
    )


def test_upsert_and_load_roundtrip(tmp_path: Path):
    store = FeatureStore(tmp_path / "cache.duckdb")
    store.upsert(_sf("a"), mtime=1.0)
    store.upsert(_sf("b", turn_count=5), mtime=2.0)

    loaded = sorted(store.load_all(), key=lambda f: f.session_id)
    assert [f.session_id for f in loaded] == ["a", "b"]
    assert loaded[1].turn_count == 5


def test_upsert_replaces_existing(tmp_path: Path):
    store = FeatureStore(tmp_path / "cache.duckdb")
    store.upsert(_sf("a", turn_count=1), mtime=1.0)
    store.upsert(_sf("a", turn_count=99), mtime=2.0)

    rows = list(store.load_all())
    assert len(rows) == 1
    assert rows[0].turn_count == 99


def test_has_fresh(tmp_path: Path):
    store = FeatureStore(tmp_path / "cache.duckdb")
    assert store.has_fresh("copilot-cli", "a", mtime=10.0) is False
    store.upsert(_sf("a"), mtime=10.0)
    assert store.has_fresh("copilot-cli", "a", mtime=10.0) is True
    assert store.has_fresh("copilot-cli", "a", mtime=11.0) is False


def test_store_invalidates_rows_with_older_schema_version(tmp_path: Path):
    store = FeatureStore(tmp_path / "cache.duckdb")

    sf = _sf(session_id="s1")
    store.upsert(sf, mtime=1.0)

    # Simulate an older schema version on disk
    store._con.execute("UPDATE features SET schema_version = schema_version - 1")

    # has_fresh should return False for rows with old schema_version
    assert store.has_fresh("copilot-cli", "s1", mtime=1.0) is False, \
        "rows from older schema must be treated as cache miss"


def test_store_migrates_legacy_db_without_schema_version_column(tmp_path: Path):
    """A DB created by an older codebase (no schema_version column) must upgrade cleanly."""
    import duckdb
    from aianalyzer.store import FeatureStore

    db_path = tmp_path / "legacy.duckdb"
    # Simulate a legacy schema (no schema_version column, with a sample row)
    con = duckdb.connect(str(db_path))
    con.execute(
        """
        CREATE TABLE features (
            client      VARCHAR NOT NULL,
            session_id  VARCHAR NOT NULL,
            mtime       DOUBLE  NOT NULL,
            json        VARCHAR NOT NULL,
            PRIMARY KEY (client, session_id)
        )
        """
    )
    con.execute(
        "INSERT INTO features VALUES (?, ?, ?, ?)",
        ["copilot_cli", "legacy-1", 1.0, "{}"],
    )
    con.close()

    # Re-opening with the current code must not raise.
    store = FeatureStore(db_path)
    # Legacy row got schema_version = 0, so it's invisible to has_fresh (which requires the current SCHEMA_VERSION).
    assert store.has_fresh("copilot_cli", "legacy-1", mtime=1.0) is False
    # And it doesn't appear in load_all() either.
    assert list(store.load_all()) == []
    store.close()
