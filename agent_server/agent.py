"""Agent factory -- builds a LangGraph agent wired to Claude and tools.

This is the single source of truth for agent construction.  All interface
layers (CLI, Clock, API) import from here instead of building their own.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from functools import cached_property
from pathlib import Path

import anthropic
import httpx
from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic
from langchain_core.tools import BaseTool
from langgraph.checkpoint.sqlite import SqliteSaver

logger = logging.getLogger(__name__)

from agent_server.config import AgentSettings
from agent_server.memory import MemoryStore
from agent_server.tools.filesystem import get_file_tools
from agent_server.tools.memory import MemoryTool
from agent_server.tools.shell_policy import SecureShellTool


def load_system_prompt(path: str | Path) -> str:
    """Read the system-prompt file (typically ``AGENTS.md``) from disk."""
    filepath = Path(path)
    if not filepath.is_file():
        raise FileNotFoundError(
            f"System-prompt file not found: {filepath}. "
            "Set AGENT_INSTRUCTIONS_PATH to a valid path."
        )
    return filepath.read_text(encoding="utf-8")


def build_tools(settings: AgentSettings, memory_store: MemoryStore) -> list[BaseTool]:
    """Assemble the full tool list from settings.

    Override this function to register project-specific tools
    (e.g. API query tools, database tools, etc.).
    """
    file_tools = get_file_tools(settings.agent_workspace_dir)
    shell_tool = SecureShellTool()
    memory_tool = MemoryTool(store=memory_store)
    return [*file_tools, shell_tool, memory_tool]


# ---------------------------------------------------------------------------
# ChatAnthropic subclass for self-signed certs (standard Anthropic API)
# ---------------------------------------------------------------------------

class _ChatAnthropicSSL(ChatAnthropic):
    """ChatAnthropic with configurable SSL verification."""

    ssl_verify: bool | str = True

    @cached_property
    def _client(self) -> anthropic.Anthropic:
        return anthropic.Anthropic(
            **self._client_params,
            http_client=httpx.Client(verify=self.ssl_verify),
        )

    @cached_property
    def _async_client(self) -> anthropic.AsyncAnthropic:
        return anthropic.AsyncAnthropic(
            **self._client_params,
            http_client=httpx.AsyncClient(verify=self.ssl_verify),
        )


# ---------------------------------------------------------------------------
# ChatAnthropic subclass for Vertex-compatible proxies (custom URL + Bearer)
# ---------------------------------------------------------------------------

class _ChatAnthropicProxy(ChatAnthropic):
    """ChatAnthropic that calls a Vertex-compatible proxy directly.

    The proxy expects:
      POST {base_url}/sonnet/models/{model}:streamRawPredict
      Authorization: Bearer <token>
      Body: {"anthropic_version": "vertex-2023-10-16", "messages": [...], ...}
    """

    proxy_url: str = ""
    proxy_key: str = ""
    ssl_verify: bool = True

    def _create(self, payload: dict) -> anthropic.types.Message:
        model = payload.pop("model", self.model)
        payload["anthropic_version"] = "vertex-2023-10-16"

        url = f"{self.proxy_url.rstrip('/')}/sonnet/models/{model}:streamRawPredict"
        client = httpx.Client(verify=self.ssl_verify)
        resp = client.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {self.proxy_key}",
                "Content-Type": "application/json",
            },
            timeout=600,
        )
        resp.raise_for_status()
        return anthropic.types.Message(**resp.json())


# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------

def build_agent(
    tools: list[BaseTool],
    system_prompt: str,
    settings: AgentSettings,
    checkpointer=None,
):
    """Construct an agent backed by Anthropic Claude.

    Branches on ``settings.agent_api_provider``:
    - ``"anthropic"``: standard Anthropic API (``ChatAnthropic``)
    - ``"vertex"``: Vertex-compatible proxy (``ChatAnthropicVertex``)
    """
    provider = settings.agent_api_provider.lower()

    if provider == "vertex":
        if not settings.agent_api_url:
            raise ValueError("AGENT_API_URL is required when provider is 'vertex'")
        llm = _ChatAnthropicProxy(
            model=settings.agent_model,
            max_tokens=8192,
            api_key="unused",
            proxy_url=settings.agent_api_url,
            proxy_key=settings.agent_api_key,
            ssl_verify=settings.agent_api_verify_ssl,
        )
    elif provider == "anthropic":
        kwargs: dict = {
            "model": settings.agent_model,
            "max_tokens": 8192,
            "api_key": settings.agent_api_key,
        }
        if settings.agent_api_url:
            kwargs["base_url"] = settings.agent_api_url
        if not settings.agent_api_verify_ssl:
            kwargs["ssl_verify"] = False
            llm = _ChatAnthropicSSL(**kwargs)
        else:
            llm = ChatAnthropic(**kwargs)
    else:
        raise ValueError(
            f"Unknown provider '{provider}'. Use 'anthropic' or 'vertex'."
        )

    return create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=checkpointer,
    )


def _uuid1_timestamp(uid: str) -> datetime | None:
    """Extract the timestamp from a UUID-v1 checkpoint_id."""
    try:
        u = uuid.UUID(uid)
        if u.version != 1:
            return None
        # UUID-v1 timestamp is 100-ns intervals since 1582-10-15
        epoch_100ns = u.time - 0x01B21DD213814000
        return datetime.fromtimestamp(epoch_100ns / 1e7, tz=timezone.utc)
    except (ValueError, AttributeError, OverflowError):
        return None


def _purge_old_checkpoints(conn: sqlite3.Connection, ttl_days: int) -> None:
    """Delete checkpoint and write rows older than *ttl_days*."""
    if ttl_days <= 0:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
    cursor = conn.execute(
        "SELECT thread_id, checkpoint_ns, checkpoint_id FROM checkpoints"
    )
    to_delete: list[tuple[str, str, str]] = []
    for thread_id, ns, cid in cursor.fetchall():
        ts = _uuid1_timestamp(cid)
        if ts is not None and ts < cutoff:
            to_delete.append((thread_id, ns, cid))

    if not to_delete:
        return

    for thread_id, ns, cid in to_delete:
        conn.execute(
            "DELETE FROM writes WHERE thread_id=? AND checkpoint_ns=? AND checkpoint_id=?",
            (thread_id, ns, cid),
        )
        conn.execute(
            "DELETE FROM checkpoints WHERE thread_id=? AND checkpoint_ns=? AND checkpoint_id=?",
            (thread_id, ns, cid),
        )
    conn.commit()
    logger.info("Purged %d checkpoints older than %d days", len(to_delete), ttl_days)


def create_agent_from_settings(settings: AgentSettings | None = None):
    """One-call convenience: load config, build tools, build agent.

    Returns ``(agent, settings, system_prompt, memory_store)``.
    """
    if settings is None:
        settings = AgentSettings()

    system_prompt = load_system_prompt(settings.agent_instructions_path)
    os.makedirs(Path(settings.agent_checkpoints_path).parent, exist_ok=True)
    mem_conn = sqlite3.connect(settings.agent_checkpoints_path, check_same_thread=False)
    memory_store = MemoryStore(conn=mem_conn, ttl_days=settings.agent_memory_ttl_days)
    cp_conn = sqlite3.connect(settings.agent_checkpoints_path, check_same_thread=False)
    checkpointer = SqliteSaver(cp_conn)
    checkpointer.setup()
    _purge_old_checkpoints(cp_conn, settings.agent_memory_ttl_days)
    tools = build_tools(settings, memory_store)
    agent = build_agent(
        tools=tools,
        system_prompt=system_prompt,
        settings=settings,
        checkpointer=checkpointer,
    )
    return agent, settings, system_prompt, memory_store


def invoke_agent(
    agent,
    messages: list[dict],
    config: dict,
    *,
    memory_store: MemoryStore | None = None,
) -> str | None:
    """Send messages to the agent and return the final AI response text.

    If *memory_store* is provided, relevant long-term memories are injected
    as context.  Conversation history is handled automatically by LangGraph's
    SQLite checkpointer.
    """
    enriched = list(messages)

    if memory_store:
        user_content = ""
        for m in messages:
            if m.get("role") == "user":
                user_content = m.get("content", "")
        if user_content:
            results = memory_store.search(user_content)
            if results:
                entries_text = "\n".join(
                    f"- {r['key']}: {json.dumps(r['value'], ensure_ascii=False)}"
                    for r in results[:5]
                )
                context_msg = {
                    "role": "user",
                    "content": (
                        f"[Context from your long-term memory — do not repeat "
                        f"these verbatim, just use them as background knowledge]\n"
                        f"{entries_text}"
                    ),
                }
                enriched = [context_msg] + enriched

    result = agent.invoke({"messages": enriched}, config=config)
    ai_messages = [
        m for m in result["messages"] if getattr(m, "type", None) == "ai"
    ]
    if ai_messages:
        return ai_messages[-1].content
    return None
