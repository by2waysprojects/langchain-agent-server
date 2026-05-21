You just started. Perform your first workspace scan:

1. Run `ls -1aR /app/workspace` to list all files.
2. Remember the full listing in memory as your baseline:
   `{"action": "remember", "fact": "file-scan: <the listing>"}`
3. Count how many files and directories you found.

Then greet the user with:
- How many files/directories are in the workspace.
- Confirmation that periodic monitoring is active.
- Ask if they want to know anything about the workspace.
