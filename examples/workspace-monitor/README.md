# Workspace Monitor

Periodic file scanner that detects additions and removals in `/app/workspace` and stores change history in memory. Demonstrates the Clock scheduler and MemoryStore.

## What it does

- **Clock** scans `/app/workspace` every 2 minutes, compares with the previous scan stored in memory, and records any changes.
- **CLI** lets you ask about file changes and current workspace state.
- **API** exposes the same functionality over HTTP.

## Build & Run

```bash
docker build -f examples/workspace-monitor/Dockerfile -t workspace-monitor .

docker run -it --rm \
  -e AGENT_API_KEY=your-key \
  -p 8080:8080 \
  -v /path/to/data:/app/workspace \
  workspace-monitor
```

## Usage

**CLI** -- ask about changes directly in the interactive REPL.

**API** -- query via HTTP:

```bash
curl -X POST localhost:8080/messages \
  -H 'Content-Type: application/json' \
  -d '{"content":"what files changed recently?"}'
```

**Memory** -- inspect stored facts:

```bash
curl -s localhost:8080/memory | jq
```
