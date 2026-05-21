"""Periodic task scheduler for the agent server.

At startup, asks the agent to read the ``## Scheduled Tasks`` section of
its own system prompt and translate natural-language schedules into cron
expressions.  Then runs a loop that invokes the agent on each matching
tick as if a human had typed the instruction.

Uses the centralized agent factory in ``agent_server.agent``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Event, Lock, Thread

from agent_server.agent import invoke_agent
from agent_server.memory import MemoryStore

_fd_lock = Lock()


@contextmanager
def _suppress_fd():
    """Suppress stdout/stderr at OS fd level for the duration of the block.

    Uses a lock so only one clock task redirects fds at a time, avoiding
    races with the CLI thread's normal output.
    """
    with _fd_lock:
        devnull = os.open(os.devnull, os.O_WRONLY)
        saved_out = os.dup(1)
        saved_err = os.dup(2)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
    try:
        yield
    finally:
        with _fd_lock:
            os.dup2(saved_out, 1)
            os.dup2(saved_err, 2)
            os.close(saved_out)
            os.close(saved_err)
            os.close(devnull)

CLOCK_THREAD_ID = "2"

logger = logging.getLogger(__name__)

_SECTION_PATTERN = re.compile(
    r"^##\s+Scheduled\s+Tasks\s*$",
    re.MULTILINE | re.IGNORECASE,
)

_PARSE_PROMPT = """\
Your system prompt contains a "## Scheduled Tasks" section with the \
following content:

---
{section}
---

Convert each task into a JSON array. Each element must have:
- "cron": a standard 5-field cron expression (minute hour day-of-month month day-of-week)
- "instruction": the task description exactly as written

Reply with ONLY the JSON array, no markdown fences, no explanation.

Example output:
[{{"cron": "*/5 * * * *", "instruction": "Check system health and report issues"}}]
"""


@dataclass
class ScheduledTask:
    cron_expr: str
    instruction: str


def extract_tasks_section(content: str) -> str | None:
    """Extract the '## Scheduled Tasks' section from markdown content."""
    match = _SECTION_PATTERN.search(content)
    if not match:
        return None
    start = match.end()
    next_section = re.search(r"^##\s+", content[start:], re.MULTILINE)
    if next_section:
        return content[start:start + next_section.start()]
    return content[start:]


def resolve_tasks(agent, section: str) -> list[ScheduledTask]:
    """Ask the agent to translate natural-language schedules into cron."""
    config = {"configurable": {"thread_id": f"clock-init-{uuid.uuid4().hex[:8]}"}}
    prompt = _PARSE_PROMPT.format(section=section.strip())

    with _suppress_fd():
        response = invoke_agent(
            agent,
            [{"role": "user", "content": prompt}],
            config,
        )
    if not response:
        return []

    json_match = re.search(r"\[.*\]", response, re.DOTALL)
    if not json_match:
        logger.error("Clock: agent did not return valid JSON: %s", response[:200])
        return []

    try:
        items = json.loads(json_match.group())
    except json.JSONDecodeError:
        logger.error("Clock: could not parse agent response as JSON")
        return []

    tasks = []
    for item in items:
        cron = item.get("cron", "").strip()
        instruction = item.get("instruction", "").strip()
        if cron and instruction:
            tasks.append(ScheduledTask(cron_expr=cron, instruction=instruction))
    return tasks


def _parse_cron_field(field: str, min_val: int, max_val: int) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        if "/" in part:
            base, step = part.split("/", 1)
            step = int(step)
            start = min_val if base == "*" else int(base)
            values.update(range(start, max_val + 1, step))
        elif "-" in part:
            lo, hi = part.split("-", 1)
            values.update(range(int(lo), int(hi) + 1))
        elif part == "*":
            values.update(range(min_val, max_val + 1))
        else:
            values.add(int(part))
    return values


def cron_matches_now(cron_expr: str) -> bool:
    """Return True if *cron_expr* matches the current minute."""
    import datetime

    fields = cron_expr.split()
    if len(fields) != 5:
        return False

    now = datetime.datetime.now()
    minute, hour, dom, month, dow = fields

    return (
        now.minute in _parse_cron_field(minute, 0, 59)
        and now.hour in _parse_cron_field(hour, 0, 23)
        and now.day in _parse_cron_field(dom, 1, 31)
        and now.month in _parse_cron_field(month, 1, 12)
        and now.weekday() in _parse_cron_field(dow, 0, 6)
    )


def _run_task(agent, task: ScheduledTask, memory_store: MemoryStore | None) -> None:
    config = {"configurable": {"thread_id": CLOCK_THREAD_ID}}
    label = task.instruction[:50]
    logger.info("Running scheduled task: %s", label)
    try:
        with _suppress_fd():
            invoke_agent(
                agent,
                [{"role": "user", "content": task.instruction}],
                config,
                memory_store=memory_store,
            )
        logger.info("Task completed: %s", label)
    except Exception as exc:
        logger.error("Scheduled task failed: %s — %s", label, exc)


def _run_loop(
    agent,
    tasks: list[ScheduledTask],
    stop_event: Event,
    memory_store: MemoryStore | None,
) -> None:
    """Main clock loop -- checks every 60s if any task should run."""
    logger.info("Clock started with %d task(s)", len(tasks))
    for t in tasks:
        logger.info("  [%s] %s", t.cron_expr, t.instruction)

    while not stop_event.is_set():
        for task in tasks:
            if cron_matches_now(task.cron_expr):
                thread = Thread(
                    target=_run_task,
                    args=(agent, task, memory_store),
                    daemon=True,
                )
                thread.start()

        stop_event.wait(60)


def start_clock(
    agent, system_prompt: str, stop_event: Event,
    *, memory_store: MemoryStore | None = None,
) -> None:
    """Extract tasks, resolve schedules, and start the clock in a background thread.

    Does nothing if no ``## Scheduled Tasks`` section is found.
    """
    section = extract_tasks_section(system_prompt)
    if not section:
        return

    logger.info("Found scheduled tasks — resolving schedules...")
    tasks = resolve_tasks(agent, section)
    if not tasks:
        logger.warning("No tasks resolved.")
        return

    thread = Thread(
        target=_run_loop,
        args=(agent, tasks, stop_event, memory_store),
        daemon=True,
    )
    thread.start()
