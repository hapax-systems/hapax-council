---
name: weekly-review
description: Aggregate the week's system data into a structured review. Use on Sunday evenings or Monday mornings, when the user asks for a weekly summary, or runs /weekly-review.
---

# Weekly System Review

Aggregate data from the past 7 days:

1. **Audit trail**: `cat ~/.cache/axiom-audit/*.jsonl 2>/dev/null | wc -l` total edits, `grep -c '"blocked":true' ~/.cache/axiom-audit/*.jsonl 2>/dev/null || echo 0` blocked
2. **Health history**: `cd ~/projects/ai-agents && uv run python -m agents.health_monitor --history`
3. **Drift report** (if recent): `cat ~/projects/ai-agents/profiles/drift-report.json 2>/dev/null | jq '.drift_items | length'`
4. **Scout report** (if recent): `cat ~/projects/ai-agents/profiles/scout-report.json 2>/dev/null | jq '.evaluations | length'`
5. **Briefing** (latest): `head -30 ~/projects/ai-agents/profiles/briefing.md`
6. **Timer status**: `systemctl --user list-timers --no-pager`

Synthesize into a 5-line summary: overall health, notable incidents, drift status, axiom compliance, recommended actions for the coming week.
