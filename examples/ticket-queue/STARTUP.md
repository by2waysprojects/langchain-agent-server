You just started. Initialize the ticket sales system:

1. Check if stock already exists: `{"action": "get", "key": "stock"}`
2. If no stock entry exists, initialize it:
   `{"action": "set", "key": "stock", "value": 10}`
3. Check for any existing queue: `{"action": "get", "key": "queue"}`
4. If no queue entry exists, initialize it:
   `{"action": "set", "key": "queue", "value": []}`
5. Check for any past sales: `{"action": "get", "key": "sales"}`
6. If no sales entry exists, initialize it:
   `{"action": "set", "key": "sales", "value": []}`

Then greet the operator with:
- Current stock level.
- Number of people in the queue (if any).
- Number of tickets already sold (if any).
- Confirmation that the queue is being processed every 30 seconds.
- Explain that users can buy tickets via the API.
