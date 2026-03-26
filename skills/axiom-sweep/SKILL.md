---
name: axiom-sweep
description: Run retroactive axiom compliance sweep. Auto-run when: session-context reports the last sweep was >7 days ago, after merging a large PR, after refactors touching auth/user/role patterns, or user asks for a T0 scan. Invoke proactively without asking.
---

Run a retroactive T0 violation sweep across all code repositories.

```bash
~/projects/hapax-council/hooks/scripts/axiom-scan.sh
```

Review the output. If violations are found:
1. Show each violation with file, line, and matched pattern
2. Assess whether each is a true violation or a false positive (test files, pattern files, comments)
3. For true violations: propose a fix
4. For false positives: note them for pattern tuning

If clean: confirm the baseline artifact was saved and report the sweep results.

The baseline JSON is saved to `~/.cache/axiom-audit/baseline-YYYY-MM-DD.json`.
