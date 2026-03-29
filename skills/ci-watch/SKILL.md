---
name: ci-watch
description: "Background CI monitor for a PR. Auto-run when: PostToolUse detects a PR was just created (suggests it with PR number), user asks to watch CI, or after pushing to a branch with an open PR. Takes PR number as argument. Invoke proactively without asking."
---

Monitor CI checks for a PR until they complete. Argument: PR number (e.g., `/ci-watch 42`).

**Step 1 — Check current status:**

```bash
gh pr checks {args} 2>/dev/null || gh pr view {args} --json statusCheckRollup --jq '.statusCheckRollup[] | "\(.name): \(.status) \(.conclusion // "")"'
```

**Step 2 — If checks are still running, poll:**

Use `gh pr checks {args} --watch --fail-fast` if available. Otherwise poll with:

```bash
gh pr checks {args} --json name,state,status --jq '.[] | select(.status != "COMPLETED") | "\(.name): \(.status)"'
```

Wait 30 seconds between polls. Report after each poll whether checks are still running.

**Step 3 — On completion:**

If all checks pass: report green and suggest `gh pr merge {args} --squash --delete-branch`.
If any check fails: fetch the failed job logs:

```bash
gh run list --branch "$(gh pr view {args} --json headRefName -q .headRefName)" --limit 3 --json databaseId,conclusion,name -q '.[] | select(.conclusion == "failure") | .databaseId' | head -1 | xargs -I{} gh run view {} --log-failed 2>/dev/null | tail -30
```

Summarize the failure and suggest a fix.
