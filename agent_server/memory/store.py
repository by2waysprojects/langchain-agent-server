"""Long-term memory store backed by a JSON file on disk.

Generic key-value store where each entry has a unique string key and
an arbitrary JSON value.  The timestamp is managed automatically by
the framework.

Shared across all interfaces (CLI, clock, API) via a single instance.

Thread-safe: all reads/writes are protected by a lock.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


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
    """Key-value store persisted as a JSON file.

    On disk the file is a JSON object mapping string keys to entry dicts::

        {
            "stock": {"value": 10, "timestamp": "..."},
            "queue": {"value": [...], "timestamp": "..."}
        }
    """

    def __init__(
        self,
        path: str | Path = "/app/workspace/memory.json",
        ttl_days: int = 0,
    ) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._ttl_days = ttl_days
        self._entries: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self._path.is_file():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._entries = data if isinstance(data, dict) else {}
                logger.info(
                    "Loaded %d entries from %s", len(self._entries), self._path
                )
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not load memory file: %s", exc)
                self._entries = {}
        else:
            self._entries = {}
        removed = self._purge_expired()
        if removed:
            logger.info(
                "Purged %d expired entries (TTL=%d days)", removed, self._ttl_days
            )

    def _purge_expired(self) -> int:
        """Remove entries older than ``_ttl_days``. Returns count removed."""
        if self._ttl_days <= 0:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._ttl_days)
        expired = [
            k
            for k, v in self._entries.items()
            if _parse_ts(v.get("timestamp")) < cutoff
        ]
        for k in expired:
            del self._entries[k]
        if expired:
            self._flush()
        return len(expired)

    def _flush(self) -> None:
        os.makedirs(self._path.parent, exist_ok=True)
        self._path.write_text(
            json.dumps(self._entries, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def save(self, key: str, value: Any) -> bool:
        """Upsert an entry. Returns ``True`` if the key was created,
        ``False`` if an existing key was updated.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            is_new = key not in self._entries
            self._entries[key] = {"value": value, "timestamp": now}
            self._flush()
        verb = "Created" if is_new else "Updated"
        logger.info("%s key=%s", verb, key)
        return is_new

    def get(self, key: str) -> dict | None:
        """Return the full entry for *key*, or ``None``."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            return {"key": key, **entry}

    def search(self, query: str) -> list[dict]:
        """Find entries whose key contains *query* (case-insensitive)."""
        q = query.lower()
        with self._lock:
            return [
                {"key": k, **v}
                for k, v in self._entries.items()
                if q in k.lower()
            ]

    def list_all(self) -> dict[str, dict]:
        """Return all entries as ``{key: {value, timestamp}}``."""
        with self._lock:
            return dict(self._entries)

    def remove(self, key: str) -> bool:
        """Remove an entry by key. Returns ``True`` if found and removed."""
        with self._lock:
            if key in self._entries:
                del self._entries[key]
                self._flush()
                return True
        return False
