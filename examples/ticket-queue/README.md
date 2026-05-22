# Ticket Sales Queue

A concert ticket sales system with **limited stock** and a **FIFO queue**. Demonstrates key-value memory, periodic processing, and cross-thread coordination.

## How it works

- **10 tickets** available at startup.
- **API users** send "I want to buy a ticket" -- the agent assigns them a unique ID (e.g. `TK-001`) and adds them to the queue.
- **Clock** processes the queue every 30 seconds: sells one ticket to the next person in line, decrements stock.
- **CLI** lets the operator inspect stock, queue, and sales history.
- When stock hits 0, remaining users in the queue are told "sold out".
- Each request gets its own generated ID, so there are no duplicates.

## Build & Run

```bash
docker build -f examples/ticket-queue/Dockerfile -t ticket-queue .

docker run -it --rm \
  -e AGENT_API_KEY=your-key \
  -p 8080:8080 \
  ticket-queue
```

## Usage

**Buy a ticket:**

```bash
curl -X POST localhost:8080/messages \
  -H 'Content-Type: application/json' \
  -d '{"content":"I want to buy a ticket"}'
```

The agent responds with an assigned ID and queue position, e.g.:
> Your ticket ID is TK-001. You are #1 in the queue. Tickets are processed every 30 seconds.

**Simulate multiple buyers:**

```bash
for i in 1 2 3 4 5; do
  curl -s -X POST localhost:8080/messages \
    -H 'Content-Type: application/json' \
    -d '{"content":"buy 1 ticket"}' &
done
wait
```

Each buyer gets a unique ID and position. Every 30 seconds the Clock sells one ticket to the next in line.

**Check stock from CLI:** ask "how many tickets left?"

**Check queue from CLI:** ask "who is in the queue?"

**Show sales from CLI:** ask "show sales"

**Inspect memory:**

```bash
curl -s localhost:8080/memory | jq
```
