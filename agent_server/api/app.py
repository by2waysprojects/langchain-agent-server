"""FastAPI HTTP interface for the agent server.

Exposes the shared agent instance over REST endpoints so that both
humans (chat frontends) and systems (CI, webhooks, bots) can interact
with it programmatically.

Write operations (shell commands requiring confirmation) are
automatically rejected -- the API has no interactive prompt.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI
from pydantic import BaseModel, Field

from agent_server.agent import invoke_agent
from agent_server.memory import MemoryStore
from agent_server.tools.shell_policy import reject_writes_context

logger = logging.getLogger(__name__)

API_THREAD_PREFIX = "3_"


class MessageRequest(BaseModel):
    content: str = Field(..., min_length=1, description="The message to send to the agent")
    thread_id: str | None = Field(
        default=None,
        description="Optional client session ID for conversation persistence. Omit for one-shot.",
    )


class MessageResponse(BaseModel):
    response: str
    thread_id: str


class MemoryFactResponse(BaseModel):
    id: str
    fact: str
    source: str
    timestamp: str | None = None


def create_app(agent, *, memory_store: MemoryStore | None = None) -> FastAPI:
    """Build the FastAPI application wired to the shared *agent* instance."""
    app = FastAPI(title="Agent Server API", version="1.0.0")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/messages", response_model=MessageResponse)
    def send_message(req: MessageRequest):
        client_id = req.thread_id or uuid.uuid4().hex
        internal_thread_id = f"{API_THREAD_PREFIX}{client_id}"

        config = {"configurable": {"thread_id": internal_thread_id}}
        messages = [{"role": "user", "content": req.content}]

        with reject_writes_context():
            response = invoke_agent(
                agent, messages, config, memory_store=memory_store
            )

        return MessageResponse(
            response=response or "[No response from agent]",
            thread_id=client_id,
        )

    @app.get("/memory", response_model=list[MemoryFactResponse])
    def list_memory():
        if memory_store is None:
            return []
        facts = memory_store.list_all()
        return [
            MemoryFactResponse(
                id=f["id"],
                fact=f["fact"],
                source=f.get("source", "unknown"),
                timestamp=f.get("timestamp"),
            )
            for f in facts
        ]

    return app
