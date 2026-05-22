You just started. Perform your first workspace scan:

1. Run `ls -1aR /app/workspace` to list all files.
2. Save the full listing in memory as your baseline:
   `{"action": "set", "key": "file-scan", "value": "<the listing>"}`
3. Initialize the change history:
   `{"action": "set", "key": "file-changes", "value": []}`
4. Count how many files and directories you found.

Then greet the user with:
- How many files/directories are in the workspace.
- Confirmation that periodic monitoring is active.
- Ask if they want to know anything about the workspace.
