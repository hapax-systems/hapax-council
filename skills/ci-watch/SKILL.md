---
name: ci-watch
description: "Background CI monitor for a PR. Auto-run when: PostToolUse detects a PR was just created (suggests it with PR number), user asks to watch CI, or after pushing to a branch with an open PR. Takes PR number as argument. Invoke proactively without asking."
---

Monitor CI checks for a PR until they complete. Argument: PR number (e.g., `/ci-watch 42`).

Use REST/core endpoints for PR metadata and checks. Avoid GitHub CLI PR-check
watchers and PR status-rollup JSON fields; those paths are GraphQL-backed and
can exhaust the shared GraphQL quota.

**Step 1 — Check current status:**

```bash
repo="${GH_REPO:-hapax-systems/hapax-council}"
sha="$(gh api --method GET -H 'Accept: application/vnd.github+json' "repos/$repo/pulls/{args}" --jq '.head.sha')"
gh api --paginate --method GET -H 'Accept: application/vnd.github+json' "repos/$repo/commits/$sha/check-runs?per_page=100" --jq '.check_runs[] | "\(.name): \(.status) \(.conclusion // "")"'
gh api --method GET -H 'Accept: application/vnd.github+json' "repos/$repo/commits/$sha/status" --jq '.statuses[] | "\(.context): \(.state)"'
```

**Step 2 — If checks are still running, poll sparingly:**

Re-run the REST commands from Step 1 at most once per minute. Stop after 10
polls and report that CI is still pending instead of tightening the loop.

Report after each poll whether checks are still running.

**Step 3 — On completion:**

If all checks pass: report green and suggest `gh pr merge {args} --squash --delete-branch`.
If any check fails: fetch the failed job logs:

```bash
repo="${GH_REPO:-hapax-systems/hapax-council}"
branch="$(gh api --method GET -H 'Accept: application/vnd.github+json' "repos/$repo/pulls/{args}" --jq '.head.ref')"
gh run list --repo "$repo" --branch "$branch" --limit 3 --json databaseId,conclusion,name -q '.[] | select(.conclusion == "failure") | .databaseId' | head -1 | xargs -I{} gh run view --repo "$repo" {} --log-failed 2>/dev/null | tail -30
```

Summarize the failure and suggest a fix.
