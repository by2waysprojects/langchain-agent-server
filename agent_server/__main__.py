"""Entry point: ``python -m agent_server``

Builds a single agent and starts all available interfaces:

- **API**: runs in a background thread (uvicorn) on ``AGENT_HTTP_PORT``.
- **Clock**: runs in a background thread if scheduled tasks are found
  in the ``## Scheduled Tasks`` section of AGENTS.md.
- **CLI**: runs in the foreground (blocking REPL).
"""

import logging
import threading

from agent_server.agent import create_agent_from_settings
from agent_server.cli.main import run_cli
from agent_server.clock.main import start_clock

logger = logging.getLogger(__name__)


def _start_api(agent, settings, *, memory_store=None):
    """Launch the FastAPI server in a daemon thread."""
    import uvicorn

    from agent_server.api import create_app

    app = create_app(agent, memory_store=memory_store)
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=settings.agent_http_port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    logger.info("API server started on port %d", settings.agent_http_port)


def main() -> None:
    agent, settings, system_prompt, memory_store = create_agent_from_settings()

    stop_event = threading.Event()

    if settings.agent_http_enabled:
        _start_api(agent, settings, memory_store=memory_store)

    start_clock(agent, system_prompt, stop_event, memory_store=memory_store)

    try:
        run_cli(
            agent,
            startup_prompt_path=settings.agent_startup_prompt_path,
            memory_store=memory_store,
        )
    finally:
        stop_event.set()


main()
