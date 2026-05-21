"""Agent factory -- builds a LangGraph agent wired to Claude and tools.

This is the single source of truth for agent construction.  All interface
layers (CLI, Clock, API) import from here instead of building their own.
"""

from __future__ import annotations

from pathlib import Path

from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic
from langchain_core.tools import BaseTool

from agent_server.config import AgentSettings
from agent_server.tools.filesystem import get_file_tools
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


def build_tools(settings: AgentSettings) -> list[BaseTool]:
    """Assemble the full tool list from settings.

    Override this function to register project-specific tools
    (e.g. API query tools, database tools, etc.).
    """
    file_tools = get_file_tools(settings.agent_workspace_dir)
    shell_tool = SecureShellTool()
    return [*file_tools, shell_tool]


def build_agent(
    tools: list[BaseTool],
    system_prompt: str,
    model_name: str = "claude-4.6-opus",
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
    )


def create_agent_from_settings(settings: AgentSettings | None = None):
    """One-call convenience: load config, build tools, build agent.

    Returns ``(agent, settings, system_prompt)`` so callers have
    everything they need.
    """
    if settings is None:
        settings = AgentSettings()

    system_prompt = load_system_prompt(settings.agent_instructions_path)
    tools = build_tools(settings)
    agent = build_agent(
        tools=tools,
        system_prompt=system_prompt,
        model_name=settings.agent_model,
    )
    return agent, settings, system_prompt


def invoke_agent(agent, messages: list[dict], config: dict) -> str | None:
    """Send messages to the agent and return the final AI response text."""
    result = agent.invoke({"messages": messages}, config=config)
    ai_messages = [
        m for m in result["messages"] if getattr(m, "type", None) == "ai"
    ]
    if ai_messages:
        return ai_messages[-1].content
    return None
