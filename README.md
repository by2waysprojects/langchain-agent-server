# langchain-agent-server

A secure, containerized AI agent framework using LangChain and Anthropic Claude. Import it into your project to give an AI agent controlled access to your tools, APIs, and workflows -- with defense-in-depth security built in.

## How It Works

You bring your project code. This framework provides:

1. **A secure shell** with a whitelist-based command policy (free / confirm / everything else blocked).
2. **Sandboxed file operations** confined to a workspace directory.
3. **Two markdown files** that control the agent: `AGENTS.md` (system prompt + scheduled tasks) and `STARTUP.md` (boot behavior).
4. **An interactive REPL** where a human supervises the agent and approves write operations.
5. **A clock scheduler** that runs agent tasks on a cron schedule -- no human needed.
6. **Multi-step plan execution** -- the agent can break complex tasks into sequential or parallel steps.
7. **An HTTP API** for programmatic access from frontends, bots, CI/CD, and webhooks.
8. **A container** that runs as a non-root user with everything pre-installed.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Container (single process)                                                 │
│                                                                             │
│  ┌──────────────┐    ┌──────────────────────────┐  ┌──────────────────────┐ │
│  │ AGENTS.md    │───>│ Claude Agent             │  │ checkpoints.sqlite   │ │
│  │ (your prompt)│    │                          │  │                      │ │
│  └──────────────┘    │  tools:                  │  │ ┌──────────────────┐ │ │
│                      │  ├─ SecureShellTool      │  │ │ checkpoints      │ │ │
│  ┌──────────────┐    │  ├─ FileManagementToolkit│  │ │ (LangGraph)      │ │ │
│  │ Your project │<───│  ├─ MemoryTool ──────────┼─>│ ├──────────────────┤ │ │
│  │ code + CLIs  │    │  └─ Your custom tools    │  │ │ memory           │ │ │
│  └──────────────┘    └──┬──────────┬─────────┬──┘  │ │ (key-value)      │ │ │
│                         │          │         │     └─└──────────────────┘─┘ │
│           ┌─────────────┴┐ ┌───────┴─────┐ ┌─┴───────────┐                  │
│           │ CLI (REPL)   │ │ API (HTTP)  │ │ Clock       │                  │
│           │ human-in-    │ │ shell writes│ │ scheduled   │                  │
│           │ the-loop     │ │ auto-reject │ │ tasks       │                  │
│           │              │ │             │ │             │                  │
│           │ run_batch    │ │invoke_agent │ │ run_batch   │                  │
│           │ (multi-step) │ │(single-shot)│ │ (multi-step)│                  │
│           └──────────────┘ └──────┬──────┘ └─────────────┘                  │
│                                   │ :8080                                   │
└───────────────────────────────────┼─────────────────────────────────────────┘
                                    │                                       
                         ┌──────────┴─────────┐       
                         │ External clients   │
                         │ (web app, bot, CI) │
                         └────────────────────┘
```

## Integration Guide

### 1. Copy into your project

Copy the `agent_server/` directory and supporting files into your project:

```
your-project/
├── your_code/                  # Your existing code
└── langchain-agent-server/     # <-- copy this directory
    ├── agent_server/
    │   ├── __init__.py
    │   ├── __main__.py
    │   ├── config.py
    │   ├── agent.py
    │   ├── api/
    │   │   ├── __init__.py
    │   │   └── app.py           # HTTP API (FastAPI)
    │   ├── batch/
    │   │   ├── __init__.py
    │   │   └── main.py          # Multi-step plan execution
    │   ├── cli/
    │   │   ├── __init__.py
    │   │   └── main.py
    │   ├── clock/
    │   │   ├── __init__.py
    │   │   └── main.py          # Periodic task scheduler
    │   ├── memory/
    │   │   ├── __init__.py
    │   │   └── store.py         # Key-value store (SQLite)
    │   └── tools/
    │       ├── __init__.py
    │       ├── shell_policy.py
    │       ├── filesystem.py
    │       └── memory.py        # MemoryTool for the agent
    ├── AGENTS.md                # <-- edit this (instructions + scheduled tasks)
    ├── STARTUP.md               # <-- edit this (boot behavior)
    ├── Dockerfile.agent         # <-- customize this for your project
    └── requirements-agent.txt   # Framework dependencies
```

### 2. Add your CLIs to the shell policy

Edit `agent_server/tools/shell_policy.py` to whitelist your project's binaries:

```python
ALLOWED_BINARIES: frozenset[str] = frozenset(
    {
        # ... existing defaults (git, gh, curl, grep, etc.) ...

        # Your project CLIs
        "my-cli",
        "kubectl",
        "terraform",
    }
)
```

Any binary **not** in this set is automatically blocked. Additionally, blocked patterns (regex) catch dangerous constructs even inside allowed commands -- things like `sudo`, `rm`, pipe-to-shell, credential access, and cloud metadata SSRF.

For CLIs with mixed read/write subcommands, add subcommand rules:

```python
# Only allow read operations (block everything else)
READ_ONLY_SUBCOMMANDS: dict[str, frozenset[str]] = {
    "kubectl": frozenset({"get", "describe", "logs", "top", "version"}),
}

# Allow read freely, require user confirmation for writes
CONFIRM_WRITE_SUBCOMMANDS: dict[str, frozenset[str]] = {
    "my-cli": frozenset({"deploy", "rollback", "delete"}),
}
```

### 3. Add custom LangChain tools (optional)

If your project has APIs that are impractical to use via shell (e.g. REST APIs with auth, pagination, complex logic), wrap them as LangChain tools:

```python
# agent_server/tools/my_tools.py
from langchain_core.tools import BaseTool

class MyApiTool(BaseTool):
    name: str = "my_api"
    description: str = "Query my project's API. Input is JSON with 'action' and params."

    def _run(self, query: str, **kwargs) -> str:
        from my_project.client import MyClient
        # ... wrap your client logic here ...
```

Register them in `agent_server/agent.py`:

```python
from agent_server.tools.my_tools import MyApiTool

def build_tools(settings: AgentSettings, memory_store: MemoryStore) -> list[BaseTool]:
    file_tools = get_file_tools(settings.agent_workspace_dir)
    shell_tool = SecureShellTool()
    memory_tool = MemoryTool(store=memory_store)
    my_tool = MyApiTool()
    return [*file_tools, shell_tool, memory_tool, my_tool]
```

### 4. Write your AGENTS.md and STARTUP.md

**`AGENTS.md`** is the system prompt -- the agent's permanent instructions. It defines who the agent is, what tools it has, and how it should behave:

```markdown
# My Project Agent

## Your Role
You are an AI assistant that helps operate [my system].

## Workflow
1. First, check the current state by running ...
2. Then do X ...
3. Ask the user before doing Y ...

## Available Tools
### Shell Commands -- Free
| `my-cli status` | Check system status | `my-cli status --all` |

### Shell Commands -- Confirm
| `my-cli deploy` | Deploy changes | `CONFIRMED: my-cli deploy staging` |

## Error Handling
## Scheduled Tasks
- Every 5 minutes, check system health and report any issues
- Every weekday at 9am, review open PRs and summarize their status

## Error Handling
If X fails, do Y ...
```

The `## Scheduled Tasks` section is written in plain natural language. At startup, the agent reads it and translates each entry into a cron schedule automatically. Then it executes each task on schedule using all its tools.

**`STARTUP.md`** controls what the agent does on first launch -- typically inspect the environment and greet the user:

```markdown
You just started. Inspect your environment now:

1. Check which configs exist in /app/configs/
2. Verify cluster access with `kubectl cluster-info`

Then greet the user with a summary and ask what to do.
```

### 5. Build your Dockerfile

Use `Dockerfile.agent` as a base and add your project's dependencies and code:

```dockerfile
# ... (framework base: python, git, gh, jq) ...

# Install your project's dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Copy your project code
COPY my_project/ my_project/
COPY configs/ configs/

# Install project-specific CLIs (e.g. kubectl)
RUN curl -LO "https://dl.k8s.io/release/stable.txt" && ...

# ... (rest of framework: agent_server, AGENTS.md, STARTUP.md, non-root user) ...
```

### 6. Run

```bash
# Build
docker build -f Dockerfile.agent -t my-agent .

# Run with standard Anthropic API
docker run -it --rm \
  -e AGENT_API_KEY=sk-ant-... \
  -v ./configs:/app/configs:ro \
  my-agent

# Run with Vertex-compatible proxy (e.g. corporate gateway)
docker run -it --rm \
  -e AGENT_API_KEY=your-bearer-token \
  -e AGENT_API_URL=https://your-proxy.example.com:443 \
  -e AGENT_API_PROVIDER=vertex \
  -e AGENT_API_VERIFY_SSL=false \
  -e AGENT_MODEL=claude-sonnet-4-6 \
  my-agent

```

The agent starts up, launches the API server and clock in background threads, then opens the CLI for the human. Everything in one process, one agent.

### 7. Use the HTTP API

The API starts automatically on port `8080` (configurable via `AGENT_HTTP_PORT`). Expose it with `-p`:

```bash
docker run -it --rm \
  -e AGENT_API_KEY=sk-ant-... \
  -p 8080:8080 \
  my-agent
```

**Send a message (one-shot):**

```bash
curl -X POST http://localhost:8080/messages \
  -H "Content-Type: application/json" \
  -d '{"content": "what is the system status?"}'
```

**Send a message (with session persistence):**

```bash
curl -X POST http://localhost:8080/messages \
  -H "Content-Type: application/json" \
  -d '{"content": "check the logs", "thread_id": "my-session-42"}'
```

**Health check:**

```bash
curl http://localhost:8080/health
```

**List stored memory entries:**

```bash
curl http://localhost:8080/memory
```

Write operations (commands requiring confirmation like `git push`) are automatically rejected via the API -- there is no human to approve them. Use the CLI for those.

To disable the API entirely, set `AGENT_HTTP_ENABLED=false`.

## Security Model

The shell uses defense-in-depth with two enforcement layers:

| Tier | Behavior | Examples |
|------|----------|---------|
| **Free** | Execute immediately | `git log`, `curl`, `grep`, `jq` |
| **Confirm** | Agent asks user, then retries with `CONFIRMED:` prefix | `git push`, `gh pr create` |

**Everything else is blocked.** Any binary not in the whitelist is rejected before execution. On top of that, blocked patterns (regex) catch dangerous constructs even inside allowed commands:

- `sudo`, `su` -- privilege escalation
- `rm` -- use file management tools instead
- `curl | bash`, `wget | sh` -- pipe-to-shell execution
- `docker`, `podman --privileged` -- container escape
- `apt`, `yum`, `dnf` -- system package managers
- `netcat`, `ncat`, `socat` -- reverse shell / exfiltration
- `kill -9`, `killall`, `pkill` -- process control
- `/etc/shadow`, `.ssh/` -- credential access
- `169.254.169.254`, `metadata.google.internal` -- cloud metadata SSRF
- `chmod` with setuid/setgid, `mkfs`, `fdisk`, `mount` -- system manipulation

All file operations go through LangChain's `FileManagementToolkit`, sandboxed to the workspace directory. The container runs as a non-root user (`agentuser`).

## Memory Model

The agent has a persistent **key-value store** (SQLite `memory` table) where each entry has a unique string key and an arbitrary JSON value. Metadata is managed automatically:

| Field | Type | Managed by |
|-------|------|------------|
| **key** | string (unique) | App (defined in AGENTS.md) |
| **value** | any JSON (int, string, array, object, bool, null) | App |
| **timestamp** | ISO 8601 | Framework (last update time) |

The memory table lives inside the same SQLite file as the conversation checkpoints (`checkpoints.sqlite`), so a single volume mount persists everything. Multi-process safe via SQLite file locking.

The MemoryTool exposes these actions to the agent:

| Action | Input | Description |
|--------|-------|-------------|
| `set` | `key`, `value` | Create a new entry (fails if key exists) |
| `upsert` | `key`, `value` | Create or update an entry |
| `get` | `key` | Retrieve one entry |
| `search` | `query` | Find entries by key substring |
| `list` | -- | List all entries |
| `delete` | `key` | Remove an entry |

## Memory Retention Policy

Both memory stores apply a TTL (Time-To-Live) policy controlled by `AGENT_MEMORY_TTL_DAYS` (default: 3 days, `0` to disable):

| Store | Table | Purge trigger | What gets deleted |
|-------|-------|---------------|-------------------|
| **MemoryStore** | `memory` | On startup | Entries whose `timestamp` is older than TTL |
| **Checkpoints** | `checkpoints` | On startup | Checkpoint rows whose UUID-v1 timestamp is older than TTL |

Both tables live in the same SQLite file (`checkpoints.sqlite`).

The purge runs automatically at agent startup. No manual cleanup is needed.

## Execution Model

The framework has two ways of running tasks:

| Interface | Method | Behavior |
|-----------|--------|----------|
| **CLI** | `run_batch` | Sends user input to the LLM. If the LLM responds with a JSON plan (`{"tasks": [...], "parallel": true/false}`), each step is executed automatically -- in parallel or sequentially. Otherwise the response is printed directly. |
| **Clock** | `run_batch` | Same as CLI but runs silently (stdout/stderr suppressed). |
| **API** | `invoke_agent` | Single-shot: sends the message, returns the response. No plan execution -- the agent handles everything in one invocation. |

This means CLI and Clock tasks can be multi-step: the LLM decides whether a task needs to be broken down and returns a plan. Each step runs in its own thread with up to 2 retries on failure.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AGENT_API_KEY` | Yes | -- | API key (Anthropic) or Bearer token (Vertex proxy) |
| `AGENT_API_URL` | No | -- | Base URL for the API endpoint |
| `AGENT_API_PROVIDER` | No | `anthropic` | `anthropic` (standard) or `vertex` (Vertex-compatible proxy) |
| `AGENT_API_VERIFY_SSL` | No | `true` | Verify SSL certs (set `false` for self-signed) |
| `AGENT_MODEL` | No | `claude-sonnet-4-20250514` | Model identifier |
| `AGENT_INSTRUCTIONS_PATH` | No | `AGENTS.md` | Path to system prompt (also contains scheduled tasks) |
| `AGENT_STARTUP_PROMPT_PATH` | No | `STARTUP.md` | Path to startup prompt |
| `AGENT_CHECKPOINTS_PATH` | No | `/app/workspace/checkpoints.sqlite` | SQLite file for checkpoints and long-term memory |
| `AGENT_MEMORY_TTL_DAYS` | No | `3` | Retention period in days for memory facts and checkpoints. `0` = keep forever |
| `AGENT_HTTP_ENABLED` | No | `true` | Enable the HTTP API server |
| `AGENT_HTTP_PORT` | No | `8080` | Port for the HTTP API server |
| `AGENT_WORKSPACE_DIR` | No | `/app/workspace` | Sandboxed file root |
| `AGENT_MAX_ITERATIONS` | No | `50` | Max reasoning loops |

## Project Structure

```
langchain-agent-server/
├── agent_server/
│   ├── __init__.py
│   ├── __main__.py              # python -m agent_server
│   ├── config.py                # Pydantic settings from env vars
│   ├── agent.py                 # Agent factory (LangChain + Claude)
│   ├── api/
│   │   ├── __init__.py
│   │   └── app.py               # HTTP API (FastAPI)
│   ├── batch/
│   │   ├── __init__.py
│   │   └── main.py              # Multi-step plan execution
│   ├── cli/
│   │   ├── __init__.py
│   │   └── main.py              # Interactive REPL + startup prompt
│   ├── clock/
│   │   ├── __init__.py
│   │   └── main.py              # Periodic task scheduler
│   ├── memory/
│   │   ├── __init__.py
│   │   └── store.py             # Key-value store (SQLite)
│   └── tools/
│       ├── __init__.py
│       ├── shell_policy.py      # Whitelist + confirm + blocked patterns
│       ├── filesystem.py        # Sandboxed file management
│       └── memory.py            # MemoryTool for the agent
├── examples/
│   ├── workspace-monitor/       # Periodic file scanning example
│   ├── ticket-queue/            # Concurrent ticket management example
│   └── pr-monitor/              # GitHub PR tracking with human-in-the-loop
├── AGENTS.md                    # System prompt + scheduled tasks (template)
├── STARTUP.md                   # Startup behavior (template)
├── Dockerfile.agent             # Container definition
└── requirements-agent.txt       # Framework dependencies
```

See `examples/` for working demos (each has its own README).
