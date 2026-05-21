"""Entry point: ``python -m agent_server``

Builds a single agent and starts all available interfaces:

- **Clock**: runs in a background thread if scheduled tasks are found
  in the ``## Scheduled Tasks`` section of AGENTS.md.
- **CLI**: runs in the foreground (blocking REPL).
- **API**: (future) will run in a background thread.
"""

from threading import Event, Thread

from agent_server.agent import create_agent_from_settings
from agent_server.cli.main import run_cli
from agent_server.clock.main import start_clock


def main() -> None:
    agent, settings, system_prompt = create_agent_from_settings()

    stop_event = Event()
    start_clock(agent, system_prompt, stop_event)

    try:
        run_cli(agent, startup_prompt_path=settings.agent_startup_prompt_path)
    finally:
        stop_event.set()


main()
