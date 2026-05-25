You just started. Set up the PR monitor:

1. Check if repos are already configured: `{"action": "get", "key": "repos"}`

2. **If no repos exist**, ask the operator:

   "Which GitHub repositories do you want to monitor?
   Give me a comma-separated list, e.g.: `org/repo-a, org/repo-b`"

   Then wait for the operator's response. Once they reply, parse the
   list, save it:
   `{"action": "set", "key": "repos", "value": ["org/repo-a", "org/repo-b"]}`

   Then do an initial PR scan for each repo using:
   `gh pr list --repo <owner/repo> --json number,title,author,url,updatedAt --limit 20`

   Save the results:
   `{"action": "set", "key": "prs", "value": { ... }}`

3. **If repos already exist**, show the list and do an initial PR scan.

Then greet the operator with:
- The list of monitored repos.
- How many open PRs each repo has.
- Confirmation that PRs are refreshed every 10 seconds.
- How to add/remove repos or view PRs.
