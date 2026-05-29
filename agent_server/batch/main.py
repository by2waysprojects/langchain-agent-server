"""Batch execution for multi-step agent tasks.

When the LLM determines a task requires multiple steps (e.g. scanning all
components), it responds with a JSON plan object instead of executing
directly. This module detects that pattern, parses the plan, and executes
steps either in parallel or sequentially based on the plan's `parallel` flag.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock

from agent_server.agent import invoke_agent
from agent_server.memory import MemoryStore

logger = logging.getLogger(__name__)

_MAX_STEP_RETRIES = 2
_MAX_PARALLEL_WORKERS = 3
_fd_lock = Lock()


@contextmanager
def _suppress_fd():
    """Suppress stdout/stderr at OS fd level for the duration of the block."""
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


@dataclass
class _Plan:
    tasks: list[str]
    parallel: bool


def _try_parse_plan(resp: str | None) -> _Plan | None:
    """Try to parse a response as an execution plan.

    Supports two formats:
    - Object: {"parallel": true/false, "tasks": ["...", ...]}
    - Array (backward compat): ["...", ...] treated as parallel=false

    Handles cases where the LLM wraps the JSON in markdown fences or
    adds explanatory text around it.
    """
    if not resp:
        return None
    text = resp.strip()

    parsed = _try_json_parse(text)
    if parsed is None:
        match = re.search(r"[\[{].*[}\]]", text, re.DOTALL)
        if match:
            parsed = _try_json_parse(match.group())

    if parsed is None:
        return None

    if isinstance(parsed, dict):
        tasks = parsed.get("tasks", [])
        parallel = parsed.get("parallel", False)
        if isinstance(tasks, list) and tasks and all(isinstance(s, str) for s in tasks):
            return _Plan(tasks=tasks, parallel=bool(parallel))

    if isinstance(parsed, list) and parsed and all(isinstance(s, str) for s in parsed):
        return _Plan(tasks=parsed, parallel=False)

    return None


def _try_json_parse(text: str):
    """Attempt JSON parse, return None on failure."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def run_batch(
    agent,
    instruction: str,
    memory_store: MemoryStore | None,
    *,
    verbose: bool = False,
) -> None:
    """Send instruction to the LLM and execute plan steps if returned.

    If the LLM responds with a plan (JSON object or array), steps are
    executed in parallel or sequentially based on the plan's parallel flag.
    Otherwise the task was handled directly by the first invocation.
    """
    thread_id = f"invoke-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}

    logger.info("Executing: %s", instruction[:50])
    if verbose:
        print(f"  [{instruction[:60]}]...")

    try:
        if verbose:
            resp = invoke_agent(
                agent,
                [{"role": "user", "content": instruction}],
                config,
                memory_store=memory_store,
            )
        else:
            with _suppress_fd():
                resp = invoke_agent(
                    agent,
                    [{"role": "user", "content": instruction}],
                    config,
                    memory_store=memory_store,
                )
    except Exception as exc:
        logger.error("Execution failed: %s", exc)
        if verbose:
            print(f"  [ERROR] {exc}")
        return

    plan = _try_parse_plan(resp)
    if not plan:
        if verbose and resp:
            print(f"\n{resp}")
        return

    mode = "parallel" if plan.parallel else "sequential"
    if verbose:
        print(f"  Executing plan: {len(plan.tasks)} steps ({mode})")
    logger.info("Execution plan: %d steps (%s)", len(plan.tasks), mode)

    if plan.parallel:
        _execute_parallel(agent, plan.tasks, memory_store, verbose=verbose)
    else:
        _execute_sequential(agent, plan.tasks, memory_store, verbose=verbose)


def _execute_sequential(
    agent, steps: list[str], memory_store: MemoryStore | None, *, verbose: bool = False
) -> None:
    """Execute steps one after another."""
    for step in steps:
        if verbose:
            print(f"  [{step}]...")
        logger.info("Plan step: %s", step)
        _execute_step(agent, step, memory_store, verbose=verbose)


def _execute_parallel(
    agent, steps: list[str], memory_store: MemoryStore | None, *, verbose: bool = False
) -> None:
    """Execute steps concurrently with a thread pool."""
    if verbose:
        print(f"  (max {_MAX_PARALLEL_WORKERS} concurrent workers)")

    with ThreadPoolExecutor(max_workers=_MAX_PARALLEL_WORKERS) as executor:
        futures = {
            executor.submit(_execute_step, agent, step, memory_store, verbose=verbose): step
            for step in steps
        }
        for future in as_completed(futures):
            step = futures[future]
            try:
                future.result()
            except Exception as exc:
                logger.error("Parallel step raised (%s): %s", step, exc)
                if verbose:
                    print(f"  [ERROR] {step}: {exc}")


def _execute_step(
    agent, step: str, memory_store: MemoryStore | None, *, verbose: bool = False
) -> None:
    """Execute a single plan step with retries on failure."""
    if verbose:
        print(f"  [{step}]...")
    logger.info("Plan step: %s", step)

    for attempt in range(_MAX_STEP_RETRIES + 1):
        step_thread_id = f"step-{uuid.uuid4().hex[:8]}"
        step_config = {"configurable": {"thread_id": step_thread_id}}
        try:
            if verbose:
                step_resp = invoke_agent(
                    agent,
                    [{"role": "user", "content": step}],
                    step_config,
                    memory_store=memory_store,
                )
                if step_resp:
                    print(f"\n{step_resp}")
            else:
                with _suppress_fd():
                    invoke_agent(
                        agent,
                        [{"role": "user", "content": step}],
                        step_config,
                        memory_store=memory_store,
                    )
            return
        except Exception as exc:
            if attempt < _MAX_STEP_RETRIES:
                logger.warning(
                    "Plan step failed (%s), retrying (%d/%d): %s",
                    step, attempt + 1, _MAX_STEP_RETRIES, exc,
                )
                if verbose:
                    print(f"  [RETRY {attempt + 1}/{_MAX_STEP_RETRIES}] {step}: {exc}")
            else:
                logger.error("Plan step failed after %d retries (%s): %s", _MAX_STEP_RETRIES, step, exc)
                if verbose:
                    print(f"  [ERROR] {step}: {exc} (after {_MAX_STEP_RETRIES} retries)")
