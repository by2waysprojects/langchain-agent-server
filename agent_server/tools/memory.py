"""LangChain tool that exposes the memory store to the agent.

Allows the agent to explicitly remember facts, recall them by keyword,
and list everything it has stored.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import BaseTool

from agent_server.memory import MemoryStore


class MemoryTool(BaseTool):
    """Remember and recall facts across sessions.

    Input must be a JSON string with an ``"action"`` field:

    - ``{"action": "remember", "fact": "..."}`` -- Save a fact.
    - ``{"action": "recall", "query": "..."}`` -- Search stored facts.
    - ``{"action": "list"}`` -- List all stored facts.
    - ``{"action": "forget", "id": "..."}`` -- Remove a fact by id.
    """

    name: str = "memory"
    description: str = (
        "Long-term memory for facts, preferences, and context. "
        "Input is JSON: "
        "'remember' with 'fact' to store something, "
        "'recall' with 'query' to search by keywords, "
        "'list' to see everything, "
        "'forget' with 'id' to remove a fact."
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

        if action == "remember":
            return self._remember(params)
        elif action == "recall":
            return self._recall(params)
        elif action == "list":
            return self._list()
        elif action == "forget":
            return self._forget(params)
        else:
            return f"Error: unknown action '{action}'. Use 'remember', 'recall', 'list', or 'forget'."

    def _remember(self, params: dict) -> str:
        fact = params.get("fact", "").strip()
        if not fact:
            return "Error: 'fact' is required."
        fact_id = self._store.save(fact)
        return f"Remembered (id={fact_id}): {fact}"

    def _recall(self, params: dict) -> str:
        query = params.get("query", "").strip()
        if not query:
            return "Error: 'query' is required."
        results = self._store.recall(query)
        if not results:
            return f"No facts found matching '{query}'."
        lines = [f"  [{r['id']}] {r['fact']}" for r in results]
        return f"Found {len(results)} fact(s):\n" + "\n".join(lines)

    def _list(self) -> str:
        facts = self._store.list_all()
        if not facts:
            return "No facts stored yet."
        lines = [f"  [{f['id']}] {f['fact']}" for f in facts]
        return f"{len(facts)} fact(s) in memory:\n" + "\n".join(lines)

    def _forget(self, params: dict) -> str:
        fact_id = params.get("id", "").strip()
        if not fact_id:
            return "Error: 'id' is required."
        if self._store.remove(fact_id):
            return f"Forgot fact '{fact_id}'."
        return f"No fact found with id '{fact_id}'."
