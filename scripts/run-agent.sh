#!/usr/bin/env bash
# run-agent.sh -- Launch the agent container with full kernel security hardening.
#
# Usage:
#   ./scripts/run-agent.sh [additional podman args...]
#
# Environment variables:
#   AGENT_IMAGE        Container image (default: langchain-agent:latest)
#   AGENT_WORKSPACE    Host path for workspace volume (default: ./workspace)
#   AGENT_API_KEY      API key for the agent (passed to container)
#   AGENT_HTTP_PORT    Port to expose for the API (default: 8080)
#   AGENT_SECURITY_STRICT  Set to "true" to fail if security cannot activate
#
# This script applies:
#   - Custom seccomp profile (blocks raw sockets, ptrace, kernel modules, etc.)
#   - All capabilities dropped (CAP_DROP=ALL)
#   - No new privileges (--security-opt no-new-privileges)
#   - Read-only root filesystem
#   - Writable tmpfs for /tmp and /app/workspace
#   - Non-root user enforcement
#
# Inside the container, the agent supervisor additionally activates:
#   - Landlock filesystem restrictions (kernel-enforced path ACLs)
#   - NO_NEW_PRIVS flag on the agent process

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── Configuration ────────────────────────────────────────────────────────────

AGENT_IMAGE="${AGENT_IMAGE:-langchain-agent:latest}"
AGENT_WORKSPACE="${AGENT_WORKSPACE:-${PROJECT_ROOT}/workspace}"
AGENT_HTTP_PORT="${AGENT_HTTP_PORT:-8080}"
SECCOMP_PROFILE="${PROJECT_ROOT}/security/seccomp-profile.json"

# ── Validation ───────────────────────────────────────────────────────────────

if [[ ! -f "${SECCOMP_PROFILE}" ]]; then
    echo "ERROR: Seccomp profile not found: ${SECCOMP_PROFILE}" >&2
    exit 1
fi

mkdir -p "${AGENT_WORKSPACE}"

# ── Build environment args ───────────────────────────────────────────────────

ENV_ARGS=()

if [[ -n "${AGENT_API_KEY:-}" ]]; then
    ENV_ARGS+=(-e "AGENT_API_KEY=${AGENT_API_KEY}")
fi

if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
    ENV_ARGS+=(-e "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}")
fi

if [[ -n "${OPENAI_API_KEY:-}" ]]; then
    ENV_ARGS+=(-e "OPENAI_API_KEY=${OPENAI_API_KEY}")
fi

if [[ -n "${AGENT_SECURITY_STRICT:-}" ]]; then
    ENV_ARGS+=(-e "AGENT_SECURITY_STRICT=${AGENT_SECURITY_STRICT}")
fi

# ── Launch ───────────────────────────────────────────────────────────────────

echo "Launching agent with kernel security hardening..."
echo "  Image:    ${AGENT_IMAGE}"
echo "  Seccomp:  ${SECCOMP_PROFILE}"
echo "  Port:     ${AGENT_HTTP_PORT}"
echo "  Security: Landlock + seccomp + no-new-privs + read-only rootfs"
echo ""

exec podman run \
    --name agent-sandbox \
    --rm \
    -it \
    \
    --security-opt "seccomp=${SECCOMP_PROFILE}" \
    --security-opt no-new-privileges \
    --cap-drop ALL \
    \
    --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=256m \
    \
    --user agentuser:agentuser \
    \
    -v "${AGENT_WORKSPACE}:/app/workspace:rw,Z" \
    \
    -p "${AGENT_HTTP_PORT}:8080" \
    \
    -e "AGENT_SECURITY_ENABLED=true" \
    -e "AGENT_WORKSPACE_DIR=/app/workspace" \
    "${ENV_ARGS[@]}" \
    \
    "$@" \
    \
    "${AGENT_IMAGE}"
