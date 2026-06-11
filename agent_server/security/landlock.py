"""Landlock filesystem sandboxing via direct syscalls.

Landlock (Linux 5.13+) allows a process to restrict its own filesystem access
before spawning children. Once activated, the restrictions cannot be lifted --
not even by root.

This module provides ``apply_landlock_policy()`` which reads the sandbox policy
YAML and activates kernel-level filesystem restrictions accordingly.

Reference: https://docs.kernel.org/userspace-api/landlock.html
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
import struct
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# ── Landlock ABI constants ───────────────────────────────────────────────────
# From include/uapi/linux/landlock.h
# Syscall numbers are architecture-independent (added after unified numbering).

_SYS_landlock_create_ruleset = 444
_SYS_landlock_add_rule = 445
_SYS_landlock_restrict_self = 446

# Access flags for files (ABI v1+)
LANDLOCK_ACCESS_FS_EXECUTE = 1 << 0
LANDLOCK_ACCESS_FS_WRITE_FILE = 1 << 1
LANDLOCK_ACCESS_FS_READ_FILE = 1 << 2
LANDLOCK_ACCESS_FS_READ_DIR = 1 << 3
LANDLOCK_ACCESS_FS_REMOVE_DIR = 1 << 4
LANDLOCK_ACCESS_FS_REMOVE_FILE = 1 << 5
LANDLOCK_ACCESS_FS_MAKE_CHAR = 1 << 6
LANDLOCK_ACCESS_FS_MAKE_DIR = 1 << 7
LANDLOCK_ACCESS_FS_MAKE_REG = 1 << 8
LANDLOCK_ACCESS_FS_MAKE_SOCK = 1 << 9
LANDLOCK_ACCESS_FS_MAKE_FIFO = 1 << 10
LANDLOCK_ACCESS_FS_MAKE_BLOCK = 1 << 11
LANDLOCK_ACCESS_FS_MAKE_SYM = 1 << 12
# ABI v2+
LANDLOCK_ACCESS_FS_REFER = 1 << 13
# ABI v3+
LANDLOCK_ACCESS_FS_TRUNCATE = 1 << 14

LANDLOCK_RULE_PATH_BENEATH = 1

# Combined access sets for convenience
_READ_ACCESS = (
    LANDLOCK_ACCESS_FS_READ_FILE
    | LANDLOCK_ACCESS_FS_READ_DIR
)

_WRITE_ACCESS = (
    LANDLOCK_ACCESS_FS_WRITE_FILE
    | LANDLOCK_ACCESS_FS_REMOVE_DIR
    | LANDLOCK_ACCESS_FS_REMOVE_FILE
    | LANDLOCK_ACCESS_FS_MAKE_CHAR
    | LANDLOCK_ACCESS_FS_MAKE_DIR
    | LANDLOCK_ACCESS_FS_MAKE_REG
    | LANDLOCK_ACCESS_FS_MAKE_SOCK
    | LANDLOCK_ACCESS_FS_MAKE_FIFO
    | LANDLOCK_ACCESS_FS_MAKE_BLOCK
    | LANDLOCK_ACCESS_FS_MAKE_SYM
    | LANDLOCK_ACCESS_FS_REFER
    | LANDLOCK_ACCESS_FS_TRUNCATE
)

_EXECUTE_ACCESS = LANDLOCK_ACCESS_FS_EXECUTE

_ALL_ACCESS = _READ_ACCESS | _WRITE_ACCESS | _EXECUTE_ACCESS


class LandlockError(Exception):
    """Raised when Landlock cannot be activated."""


@dataclass
class _PathRule:
    path: str
    access: int


@dataclass
class _LandlockPolicy:
    rules: list[_PathRule] = field(default_factory=list)
    handled_access: int = _ALL_ACCESS


# ── Low-level syscall wrappers ───────────────────────────────────────────────

_libc: ctypes.CDLL | None = None


def _get_libc() -> ctypes.CDLL:
    global _libc
    if _libc is None:
        libc_name = ctypes.util.find_library("c")
        if libc_name is None:
            raise LandlockError("Cannot find libc")
        _libc = ctypes.CDLL(libc_name, use_errno=True)
    return _libc


def _syscall(number: int, *args: int) -> int:
    libc = _get_libc()
    libc.syscall.restype = ctypes.c_long
    libc.syscall.argtypes = [ctypes.c_long] + [ctypes.c_long] * len(args)
    ret = libc.syscall(number, *args)
    if ret < 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno))
    return ret


def _landlock_create_ruleset(handled_access: int) -> int:
    """Create a Landlock ruleset and return its fd."""
    # struct landlock_ruleset_attr { __u64 handled_access_fs; }
    attr = struct.pack("Q", handled_access)
    buf = ctypes.create_string_buffer(attr)
    fd = _syscall(
        _SYS_landlock_create_ruleset,
        ctypes.addressof(buf),
        len(attr),
        0,
    )
    return fd


def _landlock_add_rule(ruleset_fd: int, path: str, access: int) -> None:
    """Add a path-beneath rule to an existing ruleset."""
    path_fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
    try:
        # struct landlock_path_beneath_attr { __u64 allowed_access; __s32 parent_fd; }
        # Padding to 16 bytes for alignment
        attr = struct.pack("Qi", access, path_fd) + b"\x00" * 4
        buf = ctypes.create_string_buffer(attr)
        _syscall(
            _SYS_landlock_add_rule,
            ruleset_fd,
            LANDLOCK_RULE_PATH_BENEATH,
            ctypes.addressof(buf),
            0,
        )
    finally:
        os.close(path_fd)


def _landlock_restrict_self(ruleset_fd: int) -> None:
    """Enforce the ruleset on the current process and all future children."""
    _syscall(_SYS_landlock_restrict_self, ruleset_fd, 0)


# ── Policy loading ───────────────────────────────────────────────────────────


def _parse_policy(policy_path: str) -> _LandlockPolicy:
    """Parse the sandbox-policy.yaml and build Landlock rules."""
    with open(policy_path) as f:
        data = yaml.safe_load(f)

    fs_section = data.get("filesystem", {})
    policy = _LandlockPolicy()

    read_write_paths = fs_section.get("read_write", [])
    read_only_paths = fs_section.get("read_only", [])
    execute_paths = fs_section.get("execute", [])

    for p in read_write_paths:
        if os.path.exists(p):
            policy.rules.append(_PathRule(
                path=p,
                access=_READ_ACCESS | _WRITE_ACCESS,
            ))
        else:
            logger.warning("Landlock: skipping non-existent read_write path: %s", p)

    for p in read_only_paths:
        if os.path.exists(p):
            policy.rules.append(_PathRule(path=p, access=_READ_ACCESS))
        else:
            logger.warning("Landlock: skipping non-existent read_only path: %s", p)

    for p in execute_paths:
        if os.path.exists(p):
            existing = next((r for r in policy.rules if r.path == p), None)
            if existing:
                existing.access |= _EXECUTE_ACCESS
            else:
                policy.rules.append(_PathRule(path=p, access=_EXECUTE_ACCESS))
        else:
            logger.warning("Landlock: skipping non-existent execute path: %s", p)

    return policy


# ── Public API ───────────────────────────────────────────────────────────────


def is_landlock_supported() -> bool:
    """Check if the running kernel supports Landlock."""
    try:
        fd = _landlock_create_ruleset(_ALL_ACCESS)
        os.close(fd)
        return True
    except OSError as e:
        if e.errno == 38:  # ENOSYS
            return False
        if e.errno == 1:  # EPERM -- kernel has it but user can't use it
            return False
        return False
    except Exception:
        return False


def apply_landlock_policy(
    policy_path: str | None = None,
    *,
    best_effort: bool = True,
) -> bool:
    """Activate Landlock filesystem restrictions from the sandbox policy.

    Args:
        policy_path: Path to the sandbox-policy.yaml. If None, uses the
            default at ``security/sandbox-policy.yaml`` relative to the
            project root.
        best_effort: If True, log a warning and return False when Landlock
            is not available instead of raising. If False, raise LandlockError.

    Returns:
        True if Landlock was successfully activated, False if skipped
        (only when best_effort=True).

    Raises:
        LandlockError: When Landlock cannot be activated and best_effort=False.
    """
    if policy_path is None:
        project_root = Path(__file__).resolve().parent.parent.parent
        policy_path = str(project_root / "security" / "sandbox-policy.yaml")

    if not os.path.exists(policy_path):
        msg = f"Sandbox policy not found: {policy_path}"
        if best_effort:
            logger.warning("Landlock: %s -- skipping", msg)
            return False
        raise LandlockError(msg)

    if not is_landlock_supported():
        msg = "Landlock not supported by this kernel (requires Linux >= 5.13)"
        if best_effort:
            logger.warning("Landlock: %s -- running without filesystem restrictions", msg)
            return False
        raise LandlockError(msg)

    policy = _parse_policy(policy_path)

    if not policy.rules:
        msg = "No valid filesystem rules found in policy"
        if best_effort:
            logger.warning("Landlock: %s -- skipping", msg)
            return False
        raise LandlockError(msg)

    logger.info("Landlock: activating with %d filesystem rules", len(policy.rules))

    try:
        ruleset_fd = _landlock_create_ruleset(policy.handled_access)
    except OSError as e:
        msg = f"Failed to create Landlock ruleset: {e}"
        if best_effort:
            logger.error("Landlock: %s", msg)
            return False
        raise LandlockError(msg) from e

    for rule in policy.rules:
        try:
            _landlock_add_rule(ruleset_fd, rule.path, rule.access)
            logger.debug("Landlock: added rule for %s (access=0x%x)", rule.path, rule.access)
        except OSError as e:
            logger.warning("Landlock: failed to add rule for %s: %s", rule.path, e)

    # Set NO_NEW_PRIVS (required for unprivileged Landlock enforcement)
    try:
        libc = _get_libc()
        PR_SET_NO_NEW_PRIVS = 38
        ret = libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)
        if ret != 0:
            logger.warning("Landlock: prctl(NO_NEW_PRIVS) failed, Landlock may not activate")
    except Exception as e:
        logger.warning("Landlock: could not set NO_NEW_PRIVS: %s", e)

    try:
        _landlock_restrict_self(ruleset_fd)
    except OSError as e:
        msg = f"Failed to enforce Landlock ruleset: {e}"
        os.close(ruleset_fd)
        if best_effort:
            logger.error("Landlock: %s", msg)
            return False
        raise LandlockError(msg) from e

    os.close(ruleset_fd)

    logger.info(
        "Landlock: ACTIVE -- filesystem restricted to %d allowed paths",
        len(policy.rules),
    )
    for rule in policy.rules:
        access_desc = []
        if rule.access & _READ_ACCESS:
            access_desc.append("read")
        if rule.access & _WRITE_ACCESS:
            access_desc.append("write")
        if rule.access & _EXECUTE_ACCESS:
            access_desc.append("execute")
        logger.info("  %s: %s", rule.path, "+".join(access_desc))

    return True
