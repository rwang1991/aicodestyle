"""DuckDB cache for SessionFeatures."""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

import duckdb

from aianalyzer.features import SessionFeatures


class FeatureStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(str(self.db_path))
        self._con.execute(
            """
            CREATE TABLE IF NOT EXISTS features (
                client      VARCHAR NOT NULL,
                session_id  VARCHAR NOT NULL,
                mtime       DOUBLE  NOT NULL,
                json        VARCHAR NOT NULL,
                PRIMARY KEY (client, session_id)
            )
            """
        )

    def has_fresh(self, client: str, session_id: str, mtime: float) -> bool:
        row = self._con.execute(
            "SELECT mtime FROM features WHERE client = ? AND session_id = ?",
            [client, session_id],
        ).fetchone()
        return row is not None and row[0] >= mtime

    def upsert(self, features: SessionFeatures, mtime: float) -> None:
        self._con.execute(
            "DELETE FROM features WHERE client = ? AND session_id = ?",
            [features.client, features.session_id],
        )
        self._con.execute(
            "INSERT INTO features (client, session_id, mtime, json) VALUES (?, ?, ?, ?)",
            [features.client, features.session_id, mtime, features.model_dump_json()],
        )

    def load_all(self) -> Iterator[SessionFeatures]:
        rows = self._con.execute("SELECT json FROM features").fetchall()
        for (payload,) in rows:
            yield SessionFeatures.model_validate_json(payload)

    def close(self) -> None:
        self._con.close()
