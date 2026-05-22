You just started. Check the current ticket queue:

1. List all facts in memory: `{"action": "list"}`
2. Count tickets by status (open, assigned, closed).

Then greet the user with:
- Current queue summary (how many tickets in each status).
- Confirmation that periodic triage is active (the Clock assigns open tickets every 2 minutes).
- Explain that users can submit tickets via the API with: `"report: <description>"`
- Ask if they want to see details or close any ticket.
