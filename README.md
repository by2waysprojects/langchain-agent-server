# langchain-agent-server

A secure, containerized AI agent framework using LangChain and Anthropic Claude. Import it into your project to give an AI agent controlled access to your tools, APIs, and workflows -- with defense-in-depth security built in.

## How It Works

You bring your project code. This framework provides:

1. **A secure shell** with a whitelist-based command policy (free / confirm / everything else blocked).
2. **Sandboxed file operations** confined to a workspace directory.
3. **Two markdown files** that control the agent: `AGENTS.md` (system prompt + scheduled tasks) and `STARTUP.md` (boot behavior).
4. **An interactive REPL** where a human supervises the agent and approves write operations.
5. **A clock scheduler** that runs agent tasks on a cron schedule -- no human needed.
6. **A container** that runs as a non-root user with everything pre-installed.

```
┌───────────────────────────────────────────────────────────────────────────┐
│  Container                                                                │
│                                                                           │
│  ┌───────────────┐   ┌───────────────────────────┐  ┌──────────────────┐  │
│  │ AGENTS.md     │──>│ Claude Agent              │  │ Memory           │  │
│  │ (your prompt) │   │                           │  │                  │  │
│  └───────────────┘   │  tools:                   │  │ Checkpoints      │  │
│                      │  ├─ SecureShellTool       │  │ (SQLite)         │  │
│  ┌───────────────┐   │  ├─ FileManagementToolkit │  │                  │  │
│  │ Your project  │<──│  ├─ MemoryTool ───────────┼─>│ MemoryStore      │  │
│  │ code + CLIs   │   │  └─ Your custom tools     │  │ (memory.json)    │  │
│  └───────────────┘   └──┬──────────┬──────────┬──┘  └──────────────────┘  │
│                         │          │          │                           │
│           ┌─────────────┴┐ ┌───────┴───────┐ ┌┴────────────┐              │
│           │ CLI (REPL)   │ │ API (future)  │ │ Clock       │              │
│           │ human-in-    │ │ HTTP/WebSocket│ │ scheduled   │              │
│           │ the-loop     │ │ not yet impl. │ │ tasks       │              │
│           └──────────────┘ └───────┬───────┘ └─────────────┘              │
│                                    │ :port                                │
└────────────────────────────────────┼──────────────────────────────────────┘
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
    │   ├── cli/
    │   │   ├── __init__.py
    │   │   └── main.py
    │   ├── api/
    │   │   ├── __init__.py
    │   │   └── app.py           # Not yet implemented
    │   ├── clock/
    │   │   ├── __init__.py
    │   │   └── main.py          # Periodic task scheduler
    │   ├── memory/
    │   │   ├── __init__.py
    │   │   └── store.py             # Long-term memory (JSON on disk)
    │   └── tools/
    │       ├── __init__.py
    │       ├── shell_policy.py
    │       ├── filesystem.py
    │       └── memory.py            # MemoryTool for the agent
    ├── AGENTS.md                # <-- edit this (instructions + scheduled tasks)
    ├── STARTUP.md               # <-- edit this (boot behavior)
    ├── Dockerfile               # <-- customize this for your project
    └── requirements.txt         # Framework dependencies
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

Register them in `agent_server/cli/main.py`:

```python
from agent_server.tools.my_tools import MyApiTool

def _build_tools(settings: AgentSettings):
    file_tools = get_file_tools(settings.agent_workspace_dir)
    shell_tool = SecureShellTool()
    my_tool = MyApiTool()
    return [*file_tools, shell_tool, my_tool]
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

The agent starts up, resolves any scheduled tasks from `AGENTS.md`, launches the clock in the background, then opens the CLI for the human. Everything in one process, one agent.

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
| `AGENT_MEMORY_PATH` | No | `/app/workspace/memory.json` | Long-term memory file |
| `AGENT_CHECKPOINTS_PATH` | No | `/app/workspace/checkpoints.sqlite` | SQLite file for conversation checkpoints |
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
│   ├── cli/
│   │   ├── __init__.py
│   │   └── main.py              # Interactive REPL + startup prompt
│   ├── api/
│   │   ├── __init__.py
│   │   └── app.py               # HTTP API (not yet implemented)
│   ├── clock/
│   │   ├── __init__.py
│   │   └── main.py              # Periodic task scheduler
│   ├── memory/
│   │   ├── __init__.py
│   │   └── store.py                 # Long-term memory (JSON on disk)
│   └── tools/
│       ├── __init__.py
│       ├── shell_policy.py          # Whitelist + confirm + blocked patterns
│       ├── filesystem.py            # Sandboxed file management
│       └── memory.py                # MemoryTool for the agent
├── AGENTS.md                    # System prompt + scheduled tasks
├── STARTUP.md                   # Startup behavior (boot sequence)
├── Dockerfile                   # Container definition
└── requirements.txt             # Framework dependencies
```
