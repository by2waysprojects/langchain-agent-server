# Ticket Queue

Support ticket system that demonstrates **concurrency control**. Multiple API users can submit tickets simultaneously -- the agent detects duplicates via memory recall and the `save` dedup safety net.

## What it does

- **API users** submit tickets by sending messages like `"report: database is down"`.
- **Clock** auto-assigns open unassigned tickets every 2 minutes.
- **CLI** lets the operator inspect the queue and close tickets.
- **Concurrency**: if two users report the same issue, the second sees `Already exists (src=3_user-a)` -- no duplicate is created.

## Build & Run

```bash
docker build -f examples/ticket-queue/Dockerfile -t ticket-queue .

docker run -it --rm \
  -e AGENT_API_KEY=your-key \
  -p 8080:8080 \
  -v /path/to/data:/app/workspace \
  ticket-queue
```

## Usage

**Create a ticket via API:**

```bash
curl -X POST localhost:8080/messages \
  -H 'Content-Type: application/json' \
  -d '{"content":"report: database is down","thread_id":"user-a"}'
```

**Test concurrency** -- send the same ticket from two terminals at once:

```bash
# Terminal 1
curl -X POST localhost:8080/messages -H 'Content-Type: application/json' \
  -d '{"content":"report: database is down","thread_id":"user-a"}'

# Terminal 2 (at the same time)
curl -X POST localhost:8080/messages -H 'Content-Type: application/json' \
  -d '{"content":"report: database is down","thread_id":"user-b"}'
```

The second request detects the duplicate (either via `recall` or the dedup in `save`) and tells user-b it was already reported by `3_user-a`.

**List tickets via CLI** -- in the interactive REPL, ask "what tickets are open?"

**Inspect memory:**

```bash
curl -s localhost:8080/memory | jq
```
