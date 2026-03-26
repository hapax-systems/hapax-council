name: working-mode
description: Check or switch working mode (research/rnd). Auto-run when: operator mentions switching modes, session-context shows stale mode (>24h without refresh), or user asks about working mode, timer schedules, or runs /working-mode. Invoke proactively without asking.

---

Check or switch the working mode (research/rnd).

**Default (no args):** Show current mode and age:

```bash
cat ~/.cache/hapax/working-mode 2>/dev/null || echo "rnd (default)"
```

Then show active timer schedules for the overridable timers:

```bash
systemctl --user show claude-code-sync.timer obsidian-sync.timer chrome-sync.timer profile-update.timer digest.timer daily-briefing.timer drift-detector.timer knowledge-maint.timer --property=TimersCalendar --no-pager 2>/dev/null
```

**Switch mode** (`/working-mode research` or `/working-mode rnd`):

```bash
hapax-working-mode {args}
```

Report the resulting mode and timer schedule summary.
