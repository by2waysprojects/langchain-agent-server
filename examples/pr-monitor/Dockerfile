FROM python:3.11-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl jq && \
    rm -rf /var/lib/apt/lists/*

ARG GH_VERSION=2.90.0
RUN curl -fsSL -o /tmp/gh.tar.gz \
        "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_amd64.tar.gz" && \
    tar xzf /tmp/gh.tar.gz --strip-components=1 -C /usr/local && \
    rm /tmp/gh.tar.gz

WORKDIR /app
COPY requirements-agent.txt ./
RUN pip install --no-cache-dir -r requirements-agent.txt

COPY agent_server/ agent_server/
COPY examples/pr-monitor/AGENTS.md .
COPY examples/pr-monitor/STARTUP.md .

RUN groupadd -r agentuser \
 && useradd -r -g agentuser -m -d /home/agentuser -s /bin/bash agentuser \
 && mkdir -p /app/workspace \
 && chown -R agentuser:agentuser /app /home/agentuser

USER agentuser

ENV AGENT_WORKSPACE_DIR=/app/workspace
ENV AGENT_INSTRUCTIONS_PATH=/app/AGENTS.md
ENV AGENT_STARTUP_PROMPT_PATH=/app/STARTUP.md
ENV AGENT_CHECKPOINTS_PATH=/app/workspace/checkpoints.sqlite
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

ENTRYPOINT ["python", "-m", "agent_server"]
