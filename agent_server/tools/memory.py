"""LangChain tool that exposes the memory store to the agent.

Provides a key-value interface where the agent can store, retrieve,
search, and delete entries with arbitrary JSON values.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import BaseTool

from agent_server.memory import MemoryStore


class MemoryTool(BaseTool):
    """Key-value memory store persisted across sessions.

    Input must be a JSON string with an ``"action"`` field:

    - ``{"action": "set", "key": "...", "value": ...}`` -- Create or update.
    - ``{"action": "get", "key": "..."}`` -- Get a single entry.
    - ``{"action": "search", "query": "..."}`` -- Find keys by substring.
    - ``{"action": "list"}`` -- List all entries.
    - ``{"action": "delete", "key": "..."}`` -- Remove an entry by key.
    """

    name: str = "memory"
    description: str = (
        "Persistent key-value store. Input is JSON: "
        "'set' with 'key' and 'value' to store (value can be any JSON type), "
        "'get' with 'key' to retrieve, "
        "'search' with 'query' to find keys by substring, "
        "'list' to see all entries, "
        "'delete' with 'key' to remove."
    )

    _store: MemoryStore

    def __init__(self, store: MemoryStore, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        object.__setattr__(self, "_store", store)

    def _run(self, tool_input: str, **kwargs: Any) -> str:
        try:
            params = json.loads(tool_input)
        except json.JSONDecodeError:
            return "Error: input must be valid JSON."

        action = params.get("action", "").lower()

        if action == "set":
            return self._set(params)
        elif action == "get":
            return self._get(params)
        elif action == "search":
            return self._search(params)
        elif action == "list":
            return self._list()
        elif action == "delete":
            return self._delete(params)
        else:
            return (
                f"Error: unknown action '{action}'. "
                "Use 'set', 'get', 'search', 'list', or 'delete'."
            )

    def _set(self, params: dict) -> str:
        key = params.get("key", "")
        if not isinstance(key, str) or not key.strip():
            return "Error: 'key' (string) is required."
        key = key.strip()
        if "value" not in params:
            return "Error: 'value' is required."
        value = params["value"]
        is_new = self._store.save(key, value)
        val_preview = json.dumps(value, ensure_ascii=False)
        if len(val_preview) > 120:
            val_preview = val_preview[:117] + "..."
        verb = "Created" if is_new else "Updated"
        return f"{verb} '{key}': {val_preview}"

    def _get(self, params: dict) -> str:
        key = params.get("key", "")
        if not isinstance(key, str) or not key.strip():
            return "Error: 'key' (string) is required."
        entry = self._store.get(key.strip())
        if entry is None:
            return f"No entry found for key '{key.strip()}'."
        return (
            f"[{entry['key']}] ({entry['timestamp']}): "
            f"{json.dumps(entry['value'], ensure_ascii=False)}"
        )

    def _search(self, params: dict) -> str:
        query = params.get("query", "")
        if not isinstance(query, str) or not query.strip():
            return "Error: 'query' (string) is required."
        results = self._store.search(query.strip())
        if not results:
            return f"No entries found matching '{query.strip()}'."
        lines = [
            f"  [{r['key']}] ({r['timestamp']}): "
            f"{json.dumps(r['value'], ensure_ascii=False)}"
            for r in results
        ]
        return f"Found {len(results)} entry(ies):\n" + "\n".join(lines)

    def _list(self) -> str:
        entries = self._store.list_all()
        if not entries:
            return "Memory is empty."
        lines = [
            f"  [{k}] ({v['timestamp']}): "
            f"{json.dumps(v['value'], ensure_ascii=False)}"
            for k, v in entries.items()
        ]
        return f"{len(entries)} entry(ies) in memory:\n" + "\n".join(lines)

    def _delete(self, params: dict) -> str:
        key = params.get("key", "")
        if not isinstance(key, str) or not key.strip():
            return "Error: 'key' (string) is required."
        key = key.strip()
        if self._store.remove(key):
            return f"Deleted '{key}'."
        return f"No entry found with key '{key}'."
