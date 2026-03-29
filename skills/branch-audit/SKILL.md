---
name: branch-audit
description: "Audit branches across all repos and clean up. Auto-run when: session-context reports >3 non-main branches across repos, no-stale-branches hook blocks a branch create, after merging PRs, or user asks about branch cleanup. Invoke proactively without asking."
---

Audit all hapax repos for stale branches and clean up.

```bash
for repo in ~/projects/hapax-council ~/projects/hapax-officium ~/projects/hapax-constitution ~/projects/hapax-mcp ~/projects/hapax-watch; do
  [ -d "$repo/.git" ] || [ -f "$repo/.git" ] || continue
  echo "=== $(basename $repo) ==="
  cd "$repo"
  git fetch origin --quiet 2>/dev/null
  for branch in $(git for-each-ref --format='%(refname:short)' refs/heads/ | grep -vE '^(main|master)$'); do
    AHEAD=$(git rev-list --count main..$branch 2>/dev/null || echo '?')
    MERGED=$(git branch --merged main 2>/dev/null | grep -q "^ *$branch$" && echo "MERGED" || echo "unmerged")
    AGE=$(git log -1 --format='%cr' "$branch" 2>/dev/null)
    echo "  $branch: $AHEAD ahead, $MERGED, last commit $AGE"
  done
done
```

For each branch recommend:
- **MERGED** — delete with `git branch -d <name>` and `git push origin --delete <name>` if remote exists
- **Unmerged with valuable work** — create PR or discuss with operator
- **Unmerged but abandoned** — confirm with operator before deleting with `git branch -D`

Offer to execute cleanup after operator confirms each deletion.
