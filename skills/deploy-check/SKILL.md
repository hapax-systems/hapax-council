---
name: deploy-check
description: Pre-push readiness verification. Auto-run when: operator says push/deploy/ship, before a PR is about to be created for main, or a git push command is about to run (PostToolUse suggests it). Invoke proactively without asking.
---

# Pre-Push Readiness Check

Run these checks before pushing to remote:

1. **Uncommitted changes**: `git status` — flag any unstaged or untracked files
2. **Tests pass**: `cd ~/projects/hapax-council && uv run pytest --tb=short -q`
3. **Health check**: `cd ~/projects/hapax-council && uv run python -m agents.health_monitor`
4. **Axiom compliance of branch diff**:
   ```bash
   BASE=$(git merge-base HEAD main 2>/dev/null || git merge-base HEAD master 2>/dev/null)
   git diff "$BASE"...HEAD | grep '^+[^+]' | grep -Ei 'class User(Manager|Service|Repository|Controller|Model)\b|class Auth(Manager|Service|Handler)\b|class (Role|Permission|ACL|RBAC|OAuth|Session)Manager\b|def (authenticate|authorize|login|logout|register)_user' && echo "AXIOM VIOLATION DETECTED" || echo "Axiom scan: clean"
   ```
5. **Branch is up to date**: `git fetch origin && git log HEAD..origin/main --oneline`

Report a go/no-go summary. Block on test failures or axiom violations. Warn on uncommitted changes.
