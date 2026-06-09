"""DuckDB cache for SessionFeatures."""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

import duckdb

from aianalyzer.features import SessionFeatures

# Bump whenever SessionFeatures shape changes meaningfully.
SCHEMA_VERSION = 4


class FeatureStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(str(self.db_path))
        self._con.execute(
            """
            CREATE TABLE IF NOT EXISTS features (
                client          VARCHAR NOT NULL,
                session_id      VARCHAR NOT NULL,
                mtime           DOUBLE  NOT NULL,
                schema_version  INTEGER NOT NULL,
                json            VARCHAR NOT NULL,
                PRIMARY KEY (client, session_id)
            )
            """
        )
        # Migration: add schema_version column to existing tables
        cols = {row[1] for row in self._con.execute("PRAGMA table_info('features')").fetchall()}
        if "schema_version" not in cols:
            self._con.execute("ALTER TABLE features ADD COLUMN schema_version INTEGER DEFAULT 0")

    def has_fresh(self, client: str, session_id: str, mtime: float) -> bool:
        row = self._con.execute(
            "SELECT mtime FROM features WHERE client = ? AND session_id = ? AND schema_version = ?",
            [client, session_id, SCHEMA_VERSION],
        ).fetchone()
        return row is not None and row[0] >= mtime

    def upsert(self, features: SessionFeatures, mtime: float) -> None:
        self._con.execute(
            "DELETE FROM features WHERE client = ? AND session_id = ?",
            [features.client, features.session_id],
        )
        self._con.execute(
            "INSERT INTO features (client, session_id, mtime, schema_version, json) VALUES (?, ?, ?, ?, ?)",
            [features.client, features.session_id, mtime, SCHEMA_VERSION, features.model_dump_json()],
        )

    def load_all(self) -> Iterator[SessionFeatures]:
        rows = self._con.execute(
            "SELECT json FROM features WHERE schema_version = ?",
            [SCHEMA_VERSION]
        ).fetchall()
        for (payload,) in rows:
            yield SessionFeatures.model_validate_json(payload)

    def close(self) -> None:
        self._con.close()
