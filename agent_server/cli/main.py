"""Interactive CLI (REPL) for the agent server.

This module wires together configuration, tools, and the agent factory,
then starts a terminal loop.  The architecture is intentionally modular:
swap ``run_cli`` for a FastAPI or WebSocket handler without touching the
agent construction logic in ``agent_server.agent``.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

from agent_server.agent import build_agent, load_system_prompt
from agent_server.config import AgentSettings
from agent_server.tools.filesystem import get_file_tools
from agent_server.tools.shell_policy import SecureShellTool

DEFAULT_STARTUP_PROMPT_PATH = "STARTUP.md"


def _load_startup_prompt(path: str | Path = DEFAULT_STARTUP_PROMPT_PATH) -> str:
    """Load the startup prompt from a markdown file."""
    filepath = Path(path)
    if not filepath.is_file():
        raise FileNotFoundError(
            f"Startup prompt file not found: {filepath}. "
            "Create a STARTUP.md or set AGENT_STARTUP_PROMPT_PATH."
        )
    return filepath.read_text(encoding="utf-8").strip()


def _build_tools(settings: AgentSettings):
    """Assemble the full tool list from settings.

    Override this function to register project-specific tools
    (e.g. API query tools, database tools, etc.).
    """
    file_tools = get_file_tools(settings.agent_workspace_dir)
    shell_tool = SecureShellTool()
    return [*file_tools, shell_tool]


def _invoke_agent(agent, messages: list[dict], config: dict) -> str | None:
    """Send messages to the agent and return the final AI response text."""
    result = agent.invoke({"messages": messages}, config=config)
    ai_messages = [
        m for m in result["messages"] if getattr(m, "type", None) == "ai"
    ]
    if ai_messages:
        return ai_messages[-1].content
    return None


def run_cli(
    agent,
    *,
    thread_id: str | None = None,
    startup_prompt_path: str | Path = DEFAULT_STARTUP_PROMPT_PATH,
) -> None:
    """Run a blocking REPL loop, forwarding user input to *agent*.

    On first invocation the agent inspects the environment and presents
    a summary before waiting for user input.
    """
    tid = thread_id or uuid.uuid4().hex[:12]
    config = {"configurable": {"thread_id": tid}}

    try:
        print("\nInitializing — scanning environment...\n")
        startup_prompt = _load_startup_prompt(startup_prompt_path)
        response = _invoke_agent(
            agent,
            [{"role": "user", "content": startup_prompt}],
            config,
        )
        if response:
            print(response)
    except Exception as exc:
        print(f"[Agent error during startup] {exc}", file=sys.stderr)

    while True:
        try:
            user_input = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            print("Goodbye.")
            break

        try:
            response = _invoke_agent(
                agent,
                [{"role": "user", "content": user_input}],
                config,
            )
            if response:
                print(f"\n{response}")
            else:
                print("\n[No response from agent]")
        except Exception as exc:
            print(f"\n[Agent error] {exc}", file=sys.stderr)


def main() -> None:
    """Entrypoint: load config, build agent, start REPL."""
    settings = AgentSettings()

    system_prompt = load_system_prompt(settings.agent_instructions_path)
    tools = _build_tools(settings)
    agent = build_agent(
        tools=tools,
        system_prompt=system_prompt,
        model_name=settings.agent_model,
    )

    run_cli(agent, startup_prompt_path=settings.agent_startup_prompt_path)
