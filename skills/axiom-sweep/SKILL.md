---
name: axiom-sweep
description: Run retroactive axiom compliance sweep across all code repos. Use when the user wants to scan existing code for T0 violations or generate a baseline audit, or runs /axiom-sweep.
---

Run a retroactive T0 violation sweep across all code repositories.

```bash
~/projects/hapax-system/scripts/axiom-sweep.sh
```

Review the output. If violations are found:
1. Show each violation with file, line, and matched pattern
2. Assess whether each is a true violation or a false positive (test files, pattern files, comments)
3. For true violations: propose a fix
4. For false positives: note them for pattern tuning

If clean: confirm the baseline artifact was saved and report the sweep results.

The baseline JSON is saved to `~/.cache/axiom-audit/baseline-YYYY-MM-DD.json`.
