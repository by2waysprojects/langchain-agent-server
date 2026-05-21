"""Interactive CLI (REPL) for the agent server.

One of the interface layers to the agent.  Uses the centralized agent
factory in ``agent_server.agent`` -- no agent construction logic here.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

from agent_server.agent import invoke_agent

DEFAULT_STARTUP_PROMPT_PATH = "STARTUP.md"


def _load_startup_prompt(path: str | Path = DEFAULT_STARTUP_PROMPT_PATH) -> str:
    filepath = Path(path)
    if not filepath.is_file():
        raise FileNotFoundError(
            f"Startup prompt file not found: {filepath}. "
            "Create a STARTUP.md or set AGENT_STARTUP_PROMPT_PATH."
        )
    return filepath.read_text(encoding="utf-8").strip()


def run_cli(
    agent,
    *,
    thread_id: str | None = None,
    startup_prompt_path: str | Path = DEFAULT_STARTUP_PROMPT_PATH,
) -> None:
    """Run a blocking REPL loop, forwarding user input to *agent*."""
    tid = thread_id or uuid.uuid4().hex[:12]
    config = {"configurable": {"thread_id": tid}}

    try:
        print("\nInitializing — scanning environment...\n")
        startup_prompt = _load_startup_prompt(startup_prompt_path)
        response = invoke_agent(
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
            response = invoke_agent(
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
