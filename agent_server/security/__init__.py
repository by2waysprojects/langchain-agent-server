"""Kernel-level security enforcement for the agent sandbox.

This package implements defense-in-depth using Linux kernel mechanisms:

- **Landlock**: Filesystem access restriction (which paths can be read/written)
- **Supervisor**: Process that activates security before spawning the agent

These complement the application-level checks in ``tools/shell_policy.py``
with enforcement that cannot be bypassed from within the agent process.
"""

from agent_server.security.landlock import apply_landlock_policy, LandlockError

__all__ = ["apply_landlock_policy", "LandlockError"]
