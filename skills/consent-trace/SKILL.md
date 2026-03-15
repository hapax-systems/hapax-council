---
name: consent-trace
description: Trace consent provenance for a file or show overall consent coverage. Use when the user asks about consent, data protection, who can see what, or runs /consent-trace.
---

Check consent coverage across all stored data:

```bash
curl -s http://localhost:8051/consent/coverage | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"Consent coverage: {d.get('with_consent_label',0)}/{d.get('total_points',0)} points labeled ({d.get('coverage_pct',0)}%)\nWith provenance: {d.get('with_provenance',0)}\nUnlabeled (public): {d.get('unlabeled',0)}\")"
```

To trace consent for a specific file, use:
```bash
curl -s "http://localhost:8051/consent/trace?source=/path/to/file.md" | python3 -m json.tool
```

To list active consent contracts:
```bash
curl -s http://localhost:8051/consent/contracts | python3 -m json.tool
```

Explain the results: what consent labels mean, which contracts justify data storage, what would happen on revocation, and what data is unprotected (public by default).
