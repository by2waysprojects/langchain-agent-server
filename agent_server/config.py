"""Agent server configuration loaded from environment variables."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class AgentSettings(BaseSettings):
    """Settings for the agent server, sourced from environment variables.

    Required:
        AGENT_API_KEY  -- API key or Bearer token (never stored in code).

    Optional (with defaults):
        AGENT_API_URL            -- Base URL for the API endpoint.
        AGENT_API_PROVIDER       -- "anthropic" (standard) or "vertex" (Vertex-compatible proxy).
        AGENT_API_VERIFY_SSL     -- Verify SSL certificates (False for self-signed).
        AGENT_MODEL              -- Model identifier.
        AGENT_INSTRUCTIONS_PATH  -- Path to the system-prompt markdown file.
        AGENT_WORKSPACE_DIR      -- Root directory for sandboxed file operations.
        AGENT_MAX_ITERATIONS     -- Safety cap on agent reasoning loops.
    """

    agent_api_key: str = Field(
        ...,
        description="API key (Anthropic) or Bearer token (Vertex proxy)",
    )
    agent_api_url: str | None = Field(
        default=None,
        description="Base URL for the API endpoint (e.g. proxy or compatible endpoint)",
    )
    agent_api_provider: str = Field(
        default="anthropic",
        description="API provider: 'anthropic' (standard) or 'vertex' (Vertex-compatible proxy)",
    )
    agent_api_verify_ssl: bool = Field(
        default=True,
        description="Verify SSL certificates (set False for self-signed certs)",
    )
    agent_model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Model identifier (override with AGENT_MODEL env var)",
    )
    agent_instructions_path: str = Field(
        default="AGENTS.md",
        description="Path to the markdown file used as the agent system prompt",
    )
    agent_startup_prompt_path: str = Field(
        default="STARTUP.md",
        description="Path to the markdown file used as the agent startup prompt",
    )
    agent_memory_path: str = Field(
        default="/app/workspace/memory.json",
        description="Path to the JSON file for long-term memory storage",
    )
    agent_checkpoints_path: str = Field(
        default="/app/workspace/checkpoints.sqlite",
        description="Path to the SQLite file for LangGraph conversation checkpoints",
    )
    agent_workspace_dir: str = Field(
        default="/app/workspace",
        description="Root directory for sandboxed file operations",
    )
    agent_memory_ttl_days: int = Field(
        default=3,
        ge=0,
        description="Retention period in days for memory facts and checkpoints. 0 = keep forever.",
    )
    agent_http_enabled: bool = Field(
        default=True,
        description="Enable the HTTP API server (set False to disable)",
    )
    agent_http_port: int = Field(
        default=8080,
        ge=1,
        le=65535,
        description="Port for the HTTP API server",
    )
    agent_max_iterations: int = Field(
        default=50,
        ge=1,
        description="Maximum number of agent reasoning iterations",
    )

    model_config = {"env_prefix": "", "case_sensitive": False}
