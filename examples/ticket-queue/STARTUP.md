You just started. Initialize the ticket sales system:

1. Check if stock already exists: `{"action": "recall", "query": "stock"}`
2. If no stock fact is found, initialize it:
   `{"action": "remember", "fact": "stock: 10 remaining"}`
3. Check for any existing queue entries: `{"action": "recall", "query": "queue"}`
4. Check for any past sales: `{"action": "recall", "query": "sold"}`

Then greet the operator with:
- Current stock level.
- Number of people in the queue (if any).
- Number of tickets already sold (if any).
- Confirmation that the queue is being processed every 30 seconds.
- Explain that users can buy tickets via the API.
