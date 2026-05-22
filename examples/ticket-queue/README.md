# Ticket Sales Queue

A concert ticket sales system with **limited stock** and a **FIFO queue**. Demonstrates concurrency control, memory deduplication, and cross-thread coordination.

## How it works

- **10 tickets** available at startup.
- **API users** request a ticket and join a queue.
- **Clock** processes the queue every 30 seconds: sells one ticket to the next person in line, decrements stock.
- **CLI** lets the operator inspect stock, queue, and sales history.
- When stock hits 0, remaining users in the queue are told "sold out".
- If two users send the same request simultaneously, the dedup in `save` prevents duplicate queue entries.

## Build & Run

```bash
docker build -f examples/ticket-queue/Dockerfile -t ticket-queue .

docker run -it --rm \
  -e AGENT_API_KEY=your-key \
  -p 8080:8080 \
  ticket-queue
```

## Usage

**Buy a ticket (each user uses their own thread_id):**

```bash
curl -X POST localhost:8080/messages \
  -H 'Content-Type: application/json' \
  -d '{"content":"I want to buy a ticket","thread_id":"alice"}'
```

**Simulate multiple users queuing:**

```bash
for user in alice bob carol dave eve; do
  curl -s -X POST localhost:8080/messages \
    -H 'Content-Type: application/json' \
    -d "{\"content\":\"buy 1 ticket\",\"thread_id\":\"$user\"}" &
done
wait
```

Each user gets a position in the queue. Every 30 seconds the Clock sells one ticket to the next in line.

**Check stock from CLI:** ask "how many tickets left?"

**Check queue from CLI:** ask "who is in the queue?"

**Show sales from CLI:** ask "show sales"

**Inspect memory:**

```bash
curl -s localhost:8080/memory | jq
```

## Concurrency demo

Send the same user twice at once -- the second request detects the duplicate:

```bash
# Terminal 1
curl -X POST localhost:8080/messages -H 'Content-Type: application/json' \
  -d '{"content":"buy 1 ticket","thread_id":"alice"}'

# Terminal 2 (at the same time)
curl -X POST localhost:8080/messages -H 'Content-Type: application/json' \
  -d '{"content":"buy 1 ticket","thread_id":"alice"}'
```

The second request either finds the existing queue entry via `recall` or hits the dedup in `save` -- alice only gets queued once.
