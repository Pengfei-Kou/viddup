"""
SQLite fingerprint cache layer.

Uses WAL journal mode for better concurrent read performance.
Schema is versioned via a `schema_version` pragma for future migrations.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA_VERSION = 1

_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS schema_info (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS fingerprints (
    path          TEXT    PRIMARY KEY,
    file_size     INTEGER NOT NULL,
    file_mtime    REAL    NOT NULL,
    file_hash     TEXT,
    duration      REAL,
    width         INTEGER,
    height        INTEGER,
    codec         TEXT,
    frame_hashes  TEXT,
    indexed_at    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_file_hash ON fingerprints(file_hash);
CREATE INDEX IF NOT EXISTS idx_duration  ON fingerprints(duration);
"""


class FingerprintRecord:
    """One row from the fingerprints table."""

    __slots__ = (
        "path", "file_size", "file_mtime", "file_hash",
        "duration", "width", "height", "codec", "frame_hashes", "indexed_at",
    )

    def __init__(
        self,
        path: str,
        file_size: int,
        file_mtime: float,
        file_hash: str | None,
        duration: float | None,
        width: int | None,
        height: int | None,
        codec: str | None,
        frame_hashes: list[str] | None,
        indexed_at: str,
    ) -> None:
        self.path = path
        self.file_size = file_size
        self.file_mtime = file_mtime
        self.file_hash = file_hash
        self.duration = duration
        self.width = width
        self.height = height
        self.codec = codec
        self.frame_hashes = frame_hashes
        self.indexed_at = indexed_at

    @property
    def resolution(self) -> str:
        if self.width and self.height:
            return f"{self.width}x{self.height}"
        return "unknown"

    @property
    def pixel_count(self) -> int:
        return (self.width or 0) * (self.height or 0)


class Database:
    """SQLite wrapper for fingerprint storage."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_DDL)
        self._ensure_schema_version()
        self._conn.commit()

    # ── Schema version ──────────────────────────────────────────────────────

    def _ensure_schema_version(self) -> None:
        row = self._conn.execute("SELECT version FROM schema_info LIMIT 1").fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO schema_info(version) VALUES (?)", (_SCHEMA_VERSION,)
            )
        # Future: run migrations if row["version"] < _SCHEMA_VERSION

    # ── Read ─────────────────────────────────────────────────────────────────

    def get(self, path: Path) -> FingerprintRecord | None:
        cur = self._conn.execute(
            "SELECT * FROM fingerprints WHERE path = ?", (str(path),)
        )
        row = cur.fetchone()
        return self._row_to_record(row) if row else None

    def get_all(self) -> list[FingerprintRecord]:
        cur = self._conn.execute("SELECT * FROM fingerprints")
        return [self._row_to_record(r) for r in cur.fetchall()]

    def count(self) -> int:
        return int(
            self._conn.execute("SELECT COUNT(*) FROM fingerprints").fetchone()[0]
        )

    def db_size_bytes(self) -> int:
        return self.db_path.stat().st_size if self.db_path.exists() else 0

    def latest_indexed_at(self) -> str | None:
        row = self._conn.execute(
            "SELECT MAX(indexed_at) FROM fingerprints"
        ).fetchone()
        return row[0] if row else None

    # ── Write ─────────────────────────────────────────────────────────────────

    def upsert(self, record: FingerprintRecord) -> None:
        self._conn.execute(
            """
            INSERT INTO fingerprints VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(path) DO UPDATE SET
                file_size    = excluded.file_size,
                file_mtime   = excluded.file_mtime,
                file_hash    = excluded.file_hash,
                duration     = excluded.duration,
                width        = excluded.width,
                height       = excluded.height,
                codec        = excluded.codec,
                frame_hashes = excluded.frame_hashes,
                indexed_at   = excluded.indexed_at
            """,
            (
                record.path,
                record.file_size,
                record.file_mtime,
                record.file_hash,
                record.duration,
                record.width,
                record.height,
                record.codec,
                json.dumps(record.frame_hashes) if record.frame_hashes else None,
                record.indexed_at,
            ),
        )
        self._conn.commit()

    def delete(self, path: Path) -> None:
        self._conn.execute(
            "DELETE FROM fingerprints WHERE path = ?", (str(path),)
        )
        self._conn.commit()

    def purge_orphans(self) -> int:
        """Delete records whose file no longer exists. Returns count deleted."""
        deleted = 0
        for rec in self.get_all():
            if not Path(rec.path).exists():
                self.delete(Path(rec.path))
                deleted += 1
        return deleted

    def clear(self) -> None:
        self._conn.execute("DELETE FROM fingerprints")
        self._conn.commit()

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> FingerprintRecord:
        raw_hashes = row["frame_hashes"]
        frame_hashes: list[str] | None = (
            json.loads(raw_hashes) if raw_hashes else None
        )
        return FingerprintRecord(
            path=row["path"],
            file_size=row["file_size"],
            file_mtime=row["file_mtime"],
            file_hash=row["file_hash"],
            duration=row["duration"],
            width=row["width"],
            height=row["height"],
            codec=row["codec"],
            frame_hashes=frame_hashes,
            indexed_at=row["indexed_at"],
        )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
