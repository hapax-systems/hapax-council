---
name: conflict-resolve
description: "Scan for and resolve merge conflict markers. Auto-run when: conflict-marker-scan PostToolUse hook fires a warning, git merge/rebase/cherry-pick output shows CONFLICT (PostToolUse suggests it), or user asks to fix conflicts. Invoke proactively without asking."
---

Find and resolve all merge conflict markers.

```bash
git diff --name-only --diff-filter=U 2>/dev/null
```

```bash
git grep -l '^<<<<<<<\|^=======$\|^>>>>>>>' -- '*.py' '*.ts' '*.tsx' '*.js' '*.json' '*.yaml' '*.yml' '*.md' ':!node_modules' ':!.venv' ':!*.lock' 2>/dev/null
```

For each conflicted file:
1. Read the file and show the conflicting sections with context
2. Present both sides clearly — "ours" vs "theirs"
3. Propose a resolution based on understanding both changes
4. After operator approval, edit the file to resolve and remove all markers
5. Stage the resolved file with `git add <file>`
6. After all files resolved, run `git rebase --continue` or `git merge --continue` as appropriate

**Never** auto-resolve without showing the operator both sides first.
