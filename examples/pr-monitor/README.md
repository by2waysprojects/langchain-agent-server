# PR Monitor

Tracks open pull requests across multiple GitHub repositories. Demonstrates **human-in-the-loop** interaction (agent asks which repos to monitor), periodic scanning via the Clock, and key-value memory for state.

## How it works

- On first launch, the agent **asks the operator** which repos to monitor.
- The operator provides a comma-separated list (e.g. `org/repo-a, org/repo-b`).
- The agent saves the list to memory and does an initial PR scan.
- Every **10 seconds**, the Clock refreshes open PRs for all monitored repos.
- The operator can add/remove repos, view PRs, or inspect memory at any time via CLI.

## Prerequisites

A GitHub personal access token with `repo` scope (or fine-grained with read access to PRs).

## Build & Run

```bash
docker build -f examples/pr-monitor/Dockerfile -t pr-monitor .

docker run -it --rm \
  -e AGENT_API_KEY=your-anthropic-key \
  -e GH_TOKEN=your-github-token \
  -p 8080:8080 \
  pr-monitor
```

For a Vertex-compatible proxy:

```bash
docker run -it --rm \
  -e AGENT_API_KEY=your-bearer-token \
  -e AGENT_API_URL=https://your-proxy:443 \
  -e AGENT_API_PROVIDER=vertex \
  -e AGENT_API_VERIFY_SSL=false \
  -e AGENT_MODEL=claude-sonnet-4-6 \
  -e GH_TOKEN=your-github-token \
  -p 8080:8080 \
  pr-monitor
```

## Usage

### First launch (interactive setup)

The agent will ask:

> Which GitHub repositories do you want to monitor?
> Give me a comma-separated list, e.g.: `org/repo-a, org/repo-b`

Type your repos and press Enter. The agent saves them and starts scanning.

### CLI commands

| Command | What it does |
|---------|-------------|
| "show PRs" | Display all open PRs across all repos |
| "show PRs for org/repo-a" | Display PRs for a specific repo |
| "list repos" | Show monitored repos |
| "add repo org/repo-c" | Add a repo to the monitor list |
| "remove repo org/repo-a" | Stop monitoring a repo |

### API

```bash
curl -s localhost:8080/memory | jq
```

### Persist data across restarts

```bash
docker run -it --rm \
  -e AGENT_API_KEY=your-key \
  -e GH_TOKEN=your-github-token \
  -v /path/to/data:/app/workspace \
  -p 8080:8080 \
  pr-monitor
```

The repo list and PR cache persist in `checkpoints.sqlite` inside the mounted volume.
