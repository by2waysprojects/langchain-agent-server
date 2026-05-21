"""Agent factory -- builds a LangGraph agent wired to Claude and tools.

This is the single source of truth for agent construction.  All interface
layers (CLI, Clock, API) import from here instead of building their own.
"""

from __future__ import annotations

from pathlib import Path

from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic
from langchain_core.tools import BaseTool
from langgraph.checkpoint.sqlite import SqliteSaver

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


def build_agent(
    tools: list[BaseTool],
    system_prompt: str,
    model_name: str = "claude-4.6-opus",
    checkpointer=None,
):
    """Construct an agent backed by Anthropic Claude.

    Returns a LangGraph compiled graph.  Drive it with ``agent.invoke()``
    for blocking calls or ``agent.stream()`` for streaming.
    """
    llm = ChatAnthropic(
        model=model_name,
        max_tokens=8192,
    )

    return create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=checkpointer,
    )


def create_agent_from_settings(settings: AgentSettings | None = None):
    """One-call convenience: load config, build tools, build agent.

    Returns ``(agent, settings, system_prompt, memory_store)``.
    """
    if settings is None:
        settings = AgentSettings()

    system_prompt = load_system_prompt(settings.agent_instructions_path)
    memory_store = MemoryStore(path=settings.agent_memory_path)
    checkpointer = SqliteSaver.from_conn_string(settings.agent_checkpoints_path)
    tools = build_tools(settings, memory_store)
    agent = build_agent(
        tools=tools,
        system_prompt=system_prompt,
        model_name=settings.agent_model,
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
            recalls = memory_store.recall(user_content)
            if recalls:
                facts_text = "\n".join(f"- {r['fact']}" for r in recalls[:5])
                context_msg = {
                    "role": "user",
                    "content": (
                        f"[Context from your long-term memory — do not repeat "
                        f"these verbatim, just use them as background knowledge]\n"
                        f"{facts_text}"
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
