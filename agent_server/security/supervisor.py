"""Security activation -- kernel protections for the agent sandbox.

Provides ``activate_security()`` which is called by ``__main__.py`` at
process startup, BEFORE any agent code runs.

Once Landlock is activated, it applies to ALL subsequent code -- including
the agent, its shell tool, and any child processes it spawns.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def activate_security(
    policy_path: str | None = None,
    *,
    best_effort: bool = True,
) -> dict[str, bool]:
    """Activate all kernel security layers.

    This should be called once at process startup, BEFORE any agent code runs.

    Args:
        policy_path: Path to sandbox-policy.yaml. Uses default if None.
        best_effort: If True, continue even if some layers fail (logs warnings).
            If False, raise on any failure.

    Returns:
        Dict with activation status of each security layer.
    """
    from agent_server.security.landlock import apply_landlock_policy, is_landlock_supported

    status: dict[str, bool] = {
        "landlock_supported": False,
        "landlock_active": False,
        "no_new_privs": False,
    }

    status["landlock_supported"] = is_landlock_supported()

    if not status["landlock_supported"]:
        logger.warning(
            "Kernel does not support Landlock (requires Linux >= 5.13). "
            "Filesystem restrictions will NOT be enforced at the kernel level. "
            "The agent will still use application-level path validation."
        )
        if not best_effort:
            from agent_server.security.landlock import LandlockError
            raise LandlockError("Landlock not supported")
    else:
        status["landlock_active"] = apply_landlock_policy(
            policy_path=policy_path,
            best_effort=best_effort,
        )

    # NO_NEW_PRIVS is set inside apply_landlock_policy, but we ensure it
    # even when Landlock wasn't activated (blocks execve privilege escalation)
    if not status["landlock_active"]:
        try:
            import ctypes
            import ctypes.util

            libc_name = ctypes.util.find_library("c")
            if libc_name:
                libc = ctypes.CDLL(libc_name, use_errno=True)
                PR_SET_NO_NEW_PRIVS = 38
                ret = libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)
                status["no_new_privs"] = (ret == 0)
                if ret == 0:
                    logger.info("NO_NEW_PRIVS set (even without Landlock)")
        except Exception as e:
            logger.warning("Could not set NO_NEW_PRIVS: %s", e)
    else:
        status["no_new_privs"] = True

    return status
