"""Agent server configuration loaded from environment variables."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class AgentSettings(BaseSettings):
    """Settings for the agent server, sourced from environment variables.

    Required:
        ANTHROPIC_API_KEY  -- Anthropic API key (never stored in code).

    Optional (with defaults):
        AGENT_MODEL              -- Model identifier for ChatAnthropic.
        AGENT_INSTRUCTIONS_PATH  -- Path to the system-prompt markdown file.
        AGENT_WORKSPACE_DIR      -- Root directory for sandboxed file operations.
        AGENT_MAX_ITERATIONS     -- Safety cap on agent reasoning loops.
    """

    anthropic_api_key: str = Field(
        ...,
        description="Anthropic API key",
    )
    agent_model: str = Field(
        default="claude-4.6-opus",
        description="Anthropic model identifier",
    )
    agent_instructions_path: str = Field(
        default="AGENTS.md",
        description="Path to the markdown file used as the agent system prompt",
    )
    agent_startup_prompt_path: str = Field(
        default="STARTUP.md",
        description="Path to the markdown file used as the agent startup prompt",
    )
    agent_workspace_dir: str = Field(
        default="/app/workspace",
        description="Root directory for sandboxed file operations",
    )
    agent_max_iterations: int = Field(
        default=50,
        ge=1,
        description="Maximum number of agent reasoning iterations",
    )

    model_config = {"env_prefix": "", "case_sensitive": False}
