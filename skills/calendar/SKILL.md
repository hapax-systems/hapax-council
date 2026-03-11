---
name: calendar
description: Check calendar, upcoming meetings, and prep status. Use when the user asks about meetings, schedule, or runs /calendar.
---

Show calendar context and meeting prep status.

**Default (no args):** Show today's meetings and prep status:

```bash
cd ~/projects/ai-agents && eval "$(<.envrc)" && uv run python -c "
from shared.calendar_context import CalendarContext
ctx = CalendarContext()
print(f'Meetings today: {ctx.meeting_count_today()}')
for m in ctx.meetings_in_range(hours=24):
    print(f'  {m.start:%H:%M} - {m.title} ({m.attendees_str})')
needs_prep = ctx.meetings_needing_prep()
if needs_prep:
    print(f'\nNeeding prep ({len(needs_prep)}):')
    for m in needs_prep:
        print(f'  {m.start:%H:%M} {m.title}')
else:
    print('\nAll meetings prepped.')
"
```

Also check the meeting-prep timer:

```bash
systemctl --user status meeting-prep.timer --no-pager 2>/dev/null | head -5
```

**With person arg** (e.g., `/calendar Alice`): Show next meeting with that person using `ctx.next_meeting_with('Alice')`.
