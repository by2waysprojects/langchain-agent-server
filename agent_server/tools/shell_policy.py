"""Security-wrapped shell tool with command whitelist, subcommand rules, and
user-confirmation enforcement.

The agent runs inside a container as a non-root user, but we still apply
defense-in-depth:

1. **Binary whitelist** -- only approved first-token binaries are permitted.
2. **Blocked patterns** -- dangerous shell patterns are rejected.
3. **Subcommand rules** -- for tools like ``git``, ``gh`` the policy
   is aware of subcommands and enforces read-only or confirmation-required
   semantics.

The ``check_command`` function returns a *three-way verdict*:

- ``None``                -- allowed, execute immediately.
- ``"BLOCKED: <reason>"`` -- hard block, never execute.
- ``"CONFIRM: <reason>"`` -- needs user confirmation before execution.

Customize the constants below to fit your project:

- Add project-specific binaries to ``ALLOWED_BINARIES``.
- Add read-only subcommand rules to ``READ_ONLY_SUBCOMMANDS``.
- Add confirm-write subcommand rules to ``CONFIRM_WRITE_SUBCOMMANDS``.
"""

from __future__ import annotations

import logging
import re
import shlex
import threading
from typing import Any, ClassVar

from langchain_community.tools import ShellTool
from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

_reject_writes = threading.local()

# ── Allowed binaries ────────────────────────────────────────────────────
# Only these first-token binaries are permitted.
# Add your project-specific CLIs here.

ALLOWED_BINARIES: frozenset[str] = frozenset(
    {
        # Version control & collaboration
        "git",
        "gh",
        # Network (read-only fetching)
        "curl",
        "wget",
        # Text / data processing (read-only)
        "grep",
        "rg",
        "sed",
        "find",
        "ls",
        "cat",
        "head",
        "tail",
        "wc",
        "sort",
        "uniq",
        "diff",
        "jq",
        "yq",
        "awk",
        "tr",
        "cut",
        "xargs",
        # Shell builtins / coreutils (read-only)
        "echo",
        "printf",
        "date",
        "env",
        "printenv",
        "whoami",
        "which",
        "pwd",
        "basename",
        "dirname",
        "realpath",
        "test",
        "true",
        "false",
        # ── Add project-specific binaries below ──
    }
)


# ── Subcommand rules ─────────────────────────────────────────────────────
#
# READ_ONLY_SUBCOMMANDS: binary -> frozenset of allowed subcommands.
#   Any subcommand NOT in the set is hard-blocked.
#
# CONFIRM_WRITE_SUBCOMMANDS: binary -> frozenset of write subcommands.
#   Subcommands in this set require user confirmation; everything else
#   is treated as read-only and executes freely.

READ_ONLY_SUBCOMMANDS: dict[str, frozenset[str]] = {
    # Example: restrict kubectl to read-only operations
    # "kubectl": frozenset({"get", "describe", "logs", "top"}),
}

CONFIRM_WRITE_SUBCOMMANDS: dict[str, frozenset[str]] = {
    "git": frozenset({
        "push", "commit", "merge", "rebase", "reset", "checkout",
        "switch", "pull", "fetch", "add", "stash", "cherry-pick",
        "clone", "init",
    }),
    "gh": frozenset({
        "pr", "issue", "release", "repo",
    }),
}

# gh has two-level subcommands; write actions per resource.
_GH_WRITE_ACTIONS: dict[str, frozenset[str]] = {
    "pr": frozenset({"create", "merge", "close", "edit", "review"}),
    "issue": frozenset({"create", "close", "edit"}),
    "release": frozenset({"create", "delete", "edit"}),
    "repo": frozenset({"fork", "clone", "create", "delete"}),
}


# ── Blocked patterns ───────────────────────────────────────────────────
# Each tuple is (compiled_regex, human-readable reason).

BLOCKED_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bsudo\b"), "sudo is not permitted"),
    (re.compile(r"\bsu\s"), "su is not permitted"),
    (re.compile(r"\bchmod\s+[0-7]*[67][0-7]{2}\b"), "setting setuid/setgid bits is not permitted"),
    (re.compile(r"\brm\b"), "rm is not permitted"),
    (re.compile(r"169\.254\.169\.254"), "access to cloud metadata endpoint is blocked"),
    (re.compile(r"metadata\.google\.internal"), "access to cloud metadata endpoint is blocked"),
    (re.compile(r"\bncat?\b"), "netcat is not permitted"),
    (re.compile(r"\bnetcat\b"), "netcat is not permitted"),
    (re.compile(r"\bsocat\b"), "socat is not permitted"),
    (re.compile(r"\bmkfs\b"), "filesystem creation is not permitted"),
    (re.compile(r"\bfdisk\b"), "disk partitioning is not permitted"),
    (re.compile(r"\bmount\b"), "mount is not permitted"),
    (re.compile(r"\bumount\b"), "umount is not permitted"),
    (re.compile(r"\bapt(-get)?\b"), "system package manager is not permitted"),
    (re.compile(r"\byum\b"), "system package manager is not permitted"),
    (re.compile(r"\bdnf\b"), "system package manager is not permitted"),
    (re.compile(r"curl\b.*\|\s*(ba)?sh"), "piping downloads to a shell is not permitted"),
    (re.compile(r"wget\b.*\|\s*(ba)?sh"), "piping downloads to a shell is not permitted"),
    (re.compile(r"/etc/shadow"), "reading /etc/shadow is not permitted"),
    (re.compile(r"\.ssh/"), "accessing .ssh directory is not permitted"),
    (re.compile(r"\bkill\s+-9\b"), "kill -9 is not permitted"),
    (re.compile(r"\bkillall\b"), "killall is not permitted"),
    (re.compile(r"\bpkill\b"), "pkill is not permitted"),
    (re.compile(r"^docker\b|;\s*docker\b|&&\s*docker\b"), "docker is not permitted inside the agent container"),
    (re.compile(r"\bpodman\b.*--privileged"), "privileged podman is not permitted"),
]

_CONFIRMED_PREFIX = "CONFIRMED: "


def reject_writes_context():
    """Context manager that causes CONFIRM commands to be auto-rejected.

    Used by the API interface where there is no human to approve writes.
    Thread-safe: only affects the current thread.

    Usage::

        with reject_writes_context():
            invoke_agent(agent, messages, config)
    """
    class _RejectCtx:
        def __enter__(self):
            _reject_writes.active = True
            return self
        def __exit__(self, *exc):
            _reject_writes.active = False
    return _RejectCtx()


def _is_reject_writes() -> bool:
    return getattr(_reject_writes, "active", False)


# ── Helpers ───────────────────────────────────────────────────────────────

def _extract_tokens(command: str) -> list[str] | None:
    """Parse *command* into tokens, skipping env prefixes and var assignments.

    Handles ``env VAR=val cmd ...`` prefixes: strips leading ``env`` and
    ``KEY=VALUE`` tokens so the returned list starts with the real binary.
    When ``env`` is the *only* token (or followed only by var assignments),
    it is kept as the binary itself.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None

    meaningful: list[str] = []
    skip_prefix = True
    for token in tokens:
        if skip_prefix:
            if "=" in token:
                continue
            if token == "env" and not meaningful:
                continue
            skip_prefix = False
        meaningful.append(token)

    if not meaningful and tokens:
        return [tokens[0]]
    return meaningful or None


def _extract_binary(tokens: list[str]) -> str:
    return tokens[0].split("/")[-1]


def _extract_subcommand(tokens: list[str]) -> str | None:
    """Return the first non-flag token after the binary."""
    for token in tokens[1:]:
        if not token.startswith("-"):
            return token
    return None


def _check_gh_write(tokens: list[str]) -> bool:
    """Return True if a ``gh`` command is a write operation."""
    if len(tokens) < 3:
        return False
    resource = tokens[1]
    action = tokens[2]
    write_actions = _GH_WRITE_ACTIONS.get(resource)
    if write_actions is None:
        return False
    return action in write_actions


# ── Core policy ───────────────────────────────────────────────────────────

def _check_single_command(command: str, *, confirmed: bool = False) -> str | None:
    """Validate a single (non-piped) command segment."""
    tokens = _extract_tokens(command)
    if tokens is None:
        return "BLOCKED: could not parse command"

    binary = _extract_binary(tokens)

    if binary not in ALLOWED_BINARIES:
        return f"BLOCKED: '{binary}' is not an allowed command"

    for pattern, reason in BLOCKED_PATTERNS:
        if pattern.search(command):
            return f"BLOCKED: {reason}"

    # -- Read-only subcommand enforcement --
    if binary in READ_ONLY_SUBCOMMANDS:
        allowed_subs = READ_ONLY_SUBCOMMANDS[binary]
        subcmd = _extract_subcommand(tokens)
        if subcmd is None:
            return f"BLOCKED: '{binary}' requires a subcommand"
        if subcmd not in allowed_subs:
            return (
                f"BLOCKED: '{binary} {subcmd}' is a write operation — "
                f"only read subcommands are allowed: {', '.join(sorted(allowed_subs))}"
            )
        return None

    # -- Confirm-write subcommand enforcement (git, gh) --
    if binary in CONFIRM_WRITE_SUBCOMMANDS:
        subcmd = _extract_subcommand(tokens)
        if subcmd is None:
            return None

        needs_confirm = False
        if binary == "gh":
            needs_confirm = _check_gh_write(tokens)
        elif subcmd in CONFIRM_WRITE_SUBCOMMANDS[binary]:
            needs_confirm = True

        if needs_confirm and not confirmed:
            cmd_preview = " ".join(tokens[:4]) + ("..." if len(tokens) > 4 else "")
            return (
                f"CONFIRM: '{cmd_preview}' is a write operation and "
                f"requires user confirmation"
            )
        return None

    return None


_PIPE_RE = re.compile(
    r"""'[^']*'|"[^"]*"|(\|)""",
    re.VERBOSE,
)


def _split_pipeline(command: str) -> list[str]:
    """Split *command* on un-quoted ``|`` characters.

    Pipes inside single- or double-quoted strings are preserved as literal
    characters and do NOT act as segment separators.
    """
    segments: list[str] = []
    last = 0
    for m in _PIPE_RE.finditer(command):
        if m.group(1) is not None:
            segments.append(command[last:m.start()])
            last = m.end()
    segments.append(command[last:])
    return [s.strip() for s in segments if s.strip()]


def check_command(command: str, *, confirmed: bool = False) -> str | None:
    """Validate *command* against the security policy.

    Supports pipelines (``cmd1 | cmd2 | ...``).  Each segment is validated
    independently; the overall command is allowed only if every segment
    passes.

    Returns:
        ``None`` -- allowed, execute immediately.
        ``"BLOCKED: ..."`` -- hard block, never execute.
        ``"CONFIRM: ..."`` -- needs user confirmation before execution.
    """
    segments = _split_pipeline(command)
    confirm_result: str | None = None

    for segment in segments:
        verdict = _check_single_command(segment, confirmed=confirmed)
        if verdict is not None:
            if verdict.startswith("BLOCKED:"):
                return verdict
            if verdict.startswith("CONFIRM:") and confirm_result is None:
                confirm_result = verdict

    return confirm_result


# ── Tool class ────────────────────────────────────────────────────────────

class SecureShellTool(BaseTool):
    """Drop-in replacement for ``ShellTool`` that enforces a command policy.

    Every invocation is validated against :data:`ALLOWED_BINARIES`,
    :data:`BLOCKED_PATTERNS`, and subcommand rules before being forwarded
    to the real shell.

    Write commands for ``git``/``gh`` require user confirmation.
    The agent must ask the user, then re-invoke with the command
    prefixed by ``CONFIRMED: `` to proceed.
    """

    name: str = "terminal"
    description: str = (
        "Execute a shell command on the server. "
        "The command is validated against a security policy before execution. "
        "Only whitelisted binaries are permitted and dangerous patterns are blocked. "
        "Write operations (git push, gh pr create, etc.) "
        "require user confirmation — prefix the command with 'CONFIRMED: ' "
        "after the user approves."
    )

    _shell: ClassVar[ShellTool] = ShellTool()

    def _run(self, command: str, **kwargs: Any) -> str:
        confirmed = command.startswith(_CONFIRMED_PREFIX)
        raw_command = command[len(_CONFIRMED_PREFIX):] if confirmed else command

        verdict = check_command(raw_command, confirmed=confirmed)

        if verdict is None:
            logger.info("ALLOWED command: %r", raw_command)
            return self._shell._run(raw_command, **kwargs)

        if verdict.startswith("CONFIRM:"):
            if _is_reject_writes():
                logger.warning("AUTO-REJECTED (API): %r", raw_command)
                return (
                    f"Command rejected: write operations are not permitted "
                    f"via the API. Use the CLI for commands that require confirmation."
                )
            reason = verdict[len("CONFIRM:"):].strip()
            logger.info("NEEDS CONFIRMATION: %r — %s", raw_command, reason)
            return (
                f"This command requires user confirmation before execution.\n"
                f"Reason: {reason}\n"
                f"Ask the user to approve this command: `{raw_command}`\n"
                f"Once they confirm, re-run with: CONFIRMED: {raw_command}"
            )

        reason = verdict[len("BLOCKED:"):].strip() if verdict.startswith("BLOCKED:") else verdict
        logger.warning("BLOCKED command: %r — reason: %s", raw_command, reason)
        return f"Command blocked by security policy: {reason}"

    async def _arun(self, command: str, **kwargs: Any) -> str:
        confirmed = command.startswith(_CONFIRMED_PREFIX)
        raw_command = command[len(_CONFIRMED_PREFIX):] if confirmed else command

        verdict = check_command(raw_command, confirmed=confirmed)

        if verdict is None:
            logger.info("ALLOWED command: %r", raw_command)
            return await self._shell._arun(raw_command, **kwargs)

        if verdict.startswith("CONFIRM:"):
            if _is_reject_writes():
                logger.warning("AUTO-REJECTED (API): %r", raw_command)
                return (
                    f"Command rejected: write operations are not permitted "
                    f"via the API. Use the CLI for commands that require confirmation."
                )
            reason = verdict[len("CONFIRM:"):].strip()
            logger.info("NEEDS CONFIRMATION: %r — %s", raw_command, reason)
            return (
                f"This command requires user confirmation before execution.\n"
                f"Reason: {reason}\n"
                f"Ask the user to approve this command: `{raw_command}`\n"
                f"Once they confirm, re-run with: CONFIRMED: {raw_command}"
            )

        reason = verdict[len("BLOCKED:"):].strip() if verdict.startswith("BLOCKED:") else verdict
        logger.warning("BLOCKED command: %r — reason: %s", raw_command, reason)
        return f"Command blocked by security policy: {reason}"
