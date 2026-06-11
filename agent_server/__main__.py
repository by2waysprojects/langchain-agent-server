"""Entry point: ``python -m agent_server``

Builds a single agent and starts all available interfaces:

- **Security supervisor**: activates kernel protections (Landlock, NO_NEW_PRIVS)
  before any agent code runs.
- **API**: runs in a background thread (uvicorn) on ``AGENT_HTTP_PORT``.
- **Clock**: runs in a background thread if scheduled tasks are found
  in the ``## Scheduled Tasks`` section of AGENTS.md.
- **CLI**: runs in the foreground (blocking REPL).
"""

import logging
import os
import threading

from agent_server.agent import create_agent_from_settings
from agent_server.cli.main import run_cli
from agent_server.clock.main import start_clock

logger = logging.getLogger(__name__)


def _activate_security() -> None:
    """Activate kernel-level security before the agent starts.

    Reads AGENT_SECURITY_ENABLED (default: "true") to control activation.
    Set to "false" or "0" to disable (e.g., during local development).
    """
    enabled = os.environ.get("AGENT_SECURITY_ENABLED", "true").lower()
    if enabled in ("false", "0", "no"):
        logger.info("Kernel security disabled via AGENT_SECURITY_ENABLED=false")
        return

    from agent_server.security.supervisor import activate_security

    policy_path = os.environ.get("AGENT_SECURITY_POLICY")
    strict = os.environ.get("AGENT_SECURITY_STRICT", "").lower() in ("1", "true", "yes")

    status = activate_security(policy_path=policy_path, best_effort=not strict)

    for key, value in status.items():
        marker = "ACTIVE" if value else "inactive"
        logger.info("Security: %-25s %s", key, marker)


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


_activate_security()
main()
