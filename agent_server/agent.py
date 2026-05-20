"""Agent factory -- builds a LangGraph agent wired to Claude and tools.

The public entry-point is :func:`build_agent`.  It returns a compiled
LangGraph graph that can be driven by any interface layer (CLI today,
FastAPI / WebSocket tomorrow) by calling ``agent.invoke()`` or
``agent.stream()``.
"""

from __future__ import annotations

from pathlib import Path

from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic
from langchain_core.tools import BaseTool


def load_system_prompt(path: str | Path) -> str:
    """Read the system-prompt file (typically ``AGENTS.md``) from disk."""
    filepath = Path(path)
    if not filepath.is_file():
        raise FileNotFoundError(
            f"System-prompt file not found: {filepath}. "
            "Set AGENT_INSTRUCTIONS_PATH to a valid path."
        )
    return filepath.read_text(encoding="utf-8")


def build_agent(
    tools: list[BaseTool],
    system_prompt: str,
    model_name: str = "claude-4.6-opus",
):
    """Construct an agent backed by Anthropic Claude.

    Parameters
    ----------
    tools:
        LangChain tool instances the agent may invoke.
    system_prompt:
        Full text injected as the system message (e.g. contents of AGENTS.md).
    model_name:
        Anthropic model identifier passed to :class:`ChatAnthropic`.

    Returns
    -------
    CompiledStateGraph
        A LangGraph compiled graph.  Drive it with ``agent.invoke()`` for
        blocking calls or ``agent.stream()`` for streaming.
    """
    llm = ChatAnthropic(
        model=model_name,
        max_tokens=8192,
    )

    return create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
    )
