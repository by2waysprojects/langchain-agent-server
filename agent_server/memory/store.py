"""Long-term memory store backed by a JSON file on disk.

Provides persistent storage for facts, preferences, and context that
the agent learns over time.  Shared across all interfaces (CLI, clock,
API) via a single instance.

Thread-safe: all reads/writes are protected by a lock.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_current_thread_id = threading.local()

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def set_current_thread_id(thread_id: str) -> None:
    """Set the thread ID for the current thread (used as source in save)."""
    _current_thread_id.value = thread_id


def get_current_thread_id() -> str:
    """Get the thread ID for the current thread, or 'unknown'."""
    return getattr(_current_thread_id, "value", "unknown")


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
    """Key-value fact store persisted as a JSON file."""

    def __init__(
        self,
        path: str | Path = "/app/workspace/memory.json",
        ttl_days: int = 0,
    ) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._ttl_days = ttl_days
        self._facts: list[dict] = []
        self._load()

    def _load(self) -> None:
        if self._path.is_file():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._facts = data if isinstance(data, list) else []
                logger.info("Loaded %d facts from %s", len(self._facts), self._path)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not load memory file: %s", exc)
                self._facts = []
        else:
            self._facts = []
        removed = self._purge_expired()
        if removed:
            logger.info("Purged %d expired facts (TTL=%d days)", removed, self._ttl_days)

    def _purge_expired(self) -> int:
        """Remove facts older than ``_ttl_days``. Returns count of removed facts."""
        if self._ttl_days <= 0:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._ttl_days)
        before = len(self._facts)
        self._facts = [
            f for f in self._facts
            if _parse_ts(f.get("timestamp")) >= cutoff
        ]
        removed = before - len(self._facts)
        if removed:
            self._flush()
        return removed

    def _flush(self) -> None:
        os.makedirs(self._path.parent, exist_ok=True)
        self._path.write_text(
            json.dumps(self._facts, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def save(self, fact: str, *, source: str | None = None) -> tuple[str, str, bool]:
        """Store a fact. Returns ``(id, source, is_new)``.

        If an identical fact already exists, returns its id and source
        with ``is_new=False`` so the caller can detect duplicates.
        """
        if source is None:
            source = get_current_thread_id()
        with self._lock:
            for f in self._facts:
                if f["fact"] == fact:
                    logger.info("Duplicate fact, returning existing id: %s", f["id"])
                    return f["id"], f.get("source", "unknown"), False
            entry = {
                "id": uuid.uuid4().hex[:10],
                "fact": fact,
                "source": source,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._facts.append(entry)
            self._flush()
        logger.info("Saved fact: %s", fact[:80])
        return entry["id"], source, True

    def recall(self, query: str) -> list[dict]:
        """Search facts by keyword match (case-insensitive)."""
        terms = query.lower().split()
        with self._lock:
            results = [
                f for f in self._facts
                if any(t in f["fact"].lower() for t in terms)
            ]
        return results

    def list_all(self) -> list[dict]:
        """Return all stored facts."""
        with self._lock:
            return list(self._facts)

    def remove(self, fact_id: str) -> bool:
        """Remove a fact by id. Returns True if found and removed."""
        with self._lock:
            before = len(self._facts)
            self._facts = [f for f in self._facts if f["id"] != fact_id]
            if len(self._facts) < before:
                self._flush()
                return True
        return False
