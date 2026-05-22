"""Long-term memory store backed by SQLite.

Generic key-value store where each entry has a unique string key and
an arbitrary JSON value.  The timestamp is managed automatically by
the framework.

Shared across all interfaces (CLI, clock, API) via a single instance.

Thread-safe: all reads/writes are protected by a lock.
Multi-process safe: SQLite handles file-level locking natively.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS memory (
    key       TEXT PRIMARY KEY,
    value     TEXT NOT NULL,
    timestamp TEXT NOT NULL
)
"""


def _parse_ts(ts: str | None) -> datetime:
    """Parse an ISO timestamp, returning epoch if missing or malformed."""
    if not ts:
        return _EPOCH
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return _EPOCH


class MemoryStore:
    """Key-value store persisted in a SQLite table.

    The ``memory`` table has three columns::

        key       TEXT PRIMARY KEY
        value     TEXT  (JSON-serialised)
        timestamp TEXT  (ISO 8601)

    Can share the same SQLite file as the LangGraph checkpointer or
    use its own file.  Multi-process safe via SQLite file locking.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        ttl_days: int = 0,
    ) -> None:
        self._conn = conn
        self._lock = threading.Lock()
        self._ttl_days = ttl_days
        self._setup()

    def _setup(self) -> None:
        with self._lock:
            self._conn.execute(_CREATE_TABLE)
            self._conn.commit()
        removed = self._purge_expired()
        if removed:
            logger.info(
                "Purged %d expired entries (TTL=%d days)", removed, self._ttl_days
            )
        count = self._conn.execute("SELECT COUNT(*) FROM memory").fetchone()[0]
        logger.info("Memory store ready: %d entries", count)

    def _purge_expired(self) -> int:
        """Remove entries older than ``_ttl_days``. Returns count removed."""
        if self._ttl_days <= 0:
            return 0
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=self._ttl_days)
        ).isoformat()
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM memory WHERE timestamp < ?", (cutoff,)
            )
            self._conn.commit()
            return cursor.rowcount

    def save(self, key: str, value: Any) -> bool:
        """Create a new entry. Returns ``True`` if created, ``False`` if
        the key already exists (no modification is made).
        """
        now = datetime.now(timezone.utc).isoformat()
        val_json = json.dumps(value, ensure_ascii=False)
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO memory (key, value, timestamp) VALUES (?, ?, ?)",
                    (key, val_json, now),
                )
                self._conn.commit()
            except sqlite3.IntegrityError:
                logger.info("Key already exists: %s", key)
                return False
        logger.info("Created key=%s", key)
        return True

    def upsert(self, key: str, value: Any) -> bool:
        """Create or update an entry. Returns ``True`` if the key was
        created, ``False`` if an existing key was updated.
        """
        now = datetime.now(timezone.utc).isoformat()
        val_json = json.dumps(value, ensure_ascii=False)
        with self._lock:
            existing = self._conn.execute(
                "SELECT 1 FROM memory WHERE key = ?", (key,)
            ).fetchone()
            self._conn.execute(
                "INSERT OR REPLACE INTO memory (key, value, timestamp) VALUES (?, ?, ?)",
                (key, val_json, now),
            )
            self._conn.commit()
        is_new = existing is None
        verb = "Created" if is_new else "Updated"
        logger.info("%s key=%s", verb, key)
        return is_new

    def get(self, key: str) -> dict | None:
        """Return the full entry for *key*, or ``None``."""
        with self._lock:
            row = self._conn.execute(
                "SELECT value, timestamp FROM memory WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        return {"key": key, "value": json.loads(row[0]), "timestamp": row[1]}

    def search(self, query: str) -> list[dict]:
        """Find entries whose key contains *query* (case-insensitive)."""
        pattern = f"%{query}%"
        with self._lock:
            rows = self._conn.execute(
                "SELECT key, value, timestamp FROM memory WHERE key LIKE ? COLLATE NOCASE",
                (pattern,),
            ).fetchall()
        return [
            {"key": r[0], "value": json.loads(r[1]), "timestamp": r[2]}
            for r in rows
        ]

    def list_all(self) -> dict[str, dict]:
        """Return all entries as ``{key: {value, timestamp}}``."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT key, value, timestamp FROM memory"
            ).fetchall()
        return {
            r[0]: {"value": json.loads(r[1]), "timestamp": r[2]}
            for r in rows
        }

    def remove(self, key: str) -> bool:
        """Remove an entry by key. Returns ``True`` if found and removed."""
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM memory WHERE key = ?", (key,)
            )
            self._conn.commit()
            return cursor.rowcount > 0
