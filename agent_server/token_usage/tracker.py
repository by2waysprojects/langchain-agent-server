"""SQLite-backed token usage tracker.

Records input/output tokens per LLM invocation, grouped by thread and
session.  Provides aggregation queries by thread, session, day, and
arbitrary date range.

Thread-safe: all writes are protected by a lock.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS token_usage (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT    NOT NULL,
    session_id   TEXT,
    thread_id    TEXT    NOT NULL,
    model        TEXT    NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL
)
"""

_CREATE_INDEX_THREAD = """
CREATE INDEX IF NOT EXISTS idx_token_usage_thread
ON token_usage (thread_id)
"""

_CREATE_INDEX_SESSION = """
CREATE INDEX IF NOT EXISTS idx_token_usage_session
ON token_usage (session_id)
"""

_CREATE_INDEX_TIMESTAMP = """
CREATE INDEX IF NOT EXISTS idx_token_usage_ts
ON token_usage (timestamp)
"""


class TokenTracker:
    """Records and queries LLM token consumption.

    Parameters
    ----------
    conn : sqlite3.Connection
        Database connection (can share the same file as memory/checkpoints).
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.Lock()
        self._session_id: str | None = None
        self._setup()

    def _setup(self) -> None:
        with self._lock:
            self._conn.execute(_CREATE_TABLE)
            self._conn.execute(_CREATE_INDEX_THREAD)
            self._conn.execute(_CREATE_INDEX_SESSION)
            self._conn.execute(_CREATE_INDEX_TIMESTAMP)
            self._conn.commit()
        logger.info("Token usage tracker ready")

    def set_session(self, session_id: str) -> None:
        """Set the current session id (used to group batch steps)."""
        self._session_id = session_id

    def clear_session(self) -> None:
        self._session_id = None

    def record(
        self,
        thread_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        *,
        session_id: str | None = None,
    ) -> None:
        """Record a single LLM invocation."""
        now = datetime.now(timezone.utc).isoformat()
        sid = session_id or self._session_id
        with self._lock:
            self._conn.execute(
                "INSERT INTO token_usage "
                "(timestamp, session_id, thread_id, model, input_tokens, output_tokens) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (now, sid, thread_id, model, input_tokens, output_tokens),
            )
            self._conn.commit()
        total = input_tokens + output_tokens
        logger.debug(
            "Tokens: %d in + %d out = %d (thread=%s, session=%s)",
            input_tokens, output_tokens, total, thread_id, sid,
        )

    def _aggregate(self, where: str = "", params: tuple = ()) -> dict[str, Any]:
        """Run an aggregation query with optional WHERE clause."""
        sql = (
            "SELECT COUNT(*) as calls, "
            "COALESCE(SUM(input_tokens), 0) as input_tokens, "
            "COALESCE(SUM(output_tokens), 0) as output_tokens "
            f"FROM token_usage {where}"
        )
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        input_t, output_t = row[1], row[2]
        return {
            "calls": row[0],
            "input_tokens": input_t,
            "output_tokens": output_t,
            "total_tokens": input_t + output_t,
        }

    def totals(self) -> dict[str, Any]:
        """Lifetime totals across all invocations."""
        return self._aggregate()

    def by_thread(self, thread_id: str) -> dict[str, Any]:
        """Totals for a single thread."""
        return self._aggregate("WHERE thread_id = ?", (thread_id,))

    def by_session(self, session_id: str) -> dict[str, Any]:
        """Totals for a session (batch run)."""
        return self._aggregate("WHERE session_id = ?", (session_id,))

    def by_date_range(self, start: str, end: str) -> dict[str, Any]:
        """Totals for a date range (ISO 8601 strings)."""
        return self._aggregate(
            "WHERE timestamp >= ? AND timestamp < ?", (start, end),
        )

    def today(self) -> dict[str, Any]:
        """Totals for today (UTC)."""
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.by_date_range(day, day + "Z")

    def daily_breakdown(self, days: int = 7) -> list[dict[str, Any]]:
        """Per-day totals for the last *days* days."""
        sql = (
            "SELECT DATE(timestamp) as day, "
            "COUNT(*) as calls, "
            "SUM(input_tokens) as input_tokens, "
            "SUM(output_tokens) as output_tokens "
            "FROM token_usage "
            "WHERE timestamp >= DATE('now', ?) "
            "GROUP BY DATE(timestamp) "
            "ORDER BY day DESC"
        )
        with self._lock:
            rows = self._conn.execute(sql, (f"-{days} days",)).fetchall()
        return [
            {
                "date": r[0],
                "calls": r[1],
                "input_tokens": r[2],
                "output_tokens": r[3],
                "total_tokens": r[2] + r[3],
            }
            for r in rows
        ]

    def recent_sessions(self, limit: int = 10) -> list[dict[str, Any]]:
        """Most recent sessions with their totals."""
        sql = (
            "SELECT session_id, "
            "MIN(timestamp) as started, "
            "MAX(timestamp) as ended, "
            "COUNT(*) as calls, "
            "SUM(input_tokens) as input_tokens, "
            "SUM(output_tokens) as output_tokens "
            "FROM token_usage "
            "WHERE session_id IS NOT NULL "
            "GROUP BY session_id "
            "ORDER BY started DESC "
            "LIMIT ?"
        )
        with self._lock:
            rows = self._conn.execute(sql, (limit,)).fetchall()
        return [
            {
                "session_id": r[0],
                "started": r[1],
                "ended": r[2],
                "calls": r[3],
                "input_tokens": r[4],
                "output_tokens": r[5],
                "total_tokens": r[4] + r[5],
            }
            for r in rows
        ]
