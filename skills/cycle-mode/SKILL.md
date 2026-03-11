---
name: cycle-mode
description: Check or switch the cycle mode (dev/prod). Use when the user asks about cycle mode, timer schedules, or runs /cycle-mode.
---

Check or switch the dev/prod cycle mode.

**Default (no args):** Show current mode and timer schedule:

```bash
cat ~/.cache/hapax/cycle-mode 2>/dev/null || echo "prod (default)"
```

Then show active timer schedules for the overridable timers:

```bash
systemctl --user show claude-code-sync.timer obsidian-sync.timer chrome-sync.timer profile-update.timer digest.timer daily-briefing.timer drift-detector.timer knowledge-maint.timer --property=TimersCalendar --no-pager 2>/dev/null
```

**Switch mode** (`/cycle-mode dev` or `/cycle-mode prod`):

```bash
~/.local/bin/hapax-mode <MODE>
```

Report the resulting mode and timer schedule summary.
