#!/usr/bin/env bash
# build-agent.sh -- Build the agent container image with Podman.
#
# Usage:
#   ./scripts/build-agent.sh [additional podman build args...]
#
# Environment variables:
#   AGENT_IMAGE   Image name:tag (default: langchain-agent:latest)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

AGENT_IMAGE="${AGENT_IMAGE:-langchain-agent:latest}"

echo "Building agent image: ${AGENT_IMAGE}"
echo "  Dockerfile: ${PROJECT_ROOT}/Dockerfile.agent"
echo ""

exec podman build \
    -f "${PROJECT_ROOT}/Dockerfile.agent" \
    -t "${AGENT_IMAGE}" \
    "$@" \
    "${PROJECT_ROOT}"
