---
name: disk-triage
description: Emergency disk cleanup triage. Auto-run when: session-context reports root filesystem >85%, "No space left on device" errors appear (PostToolUse suggests it), or user mentions disk full. Prioritizes recovery over investigation. Invoke proactively without asking.
---

Emergency disk space recovery. Run the full survey, then suggest cleanup actions.

```bash
df -h / /home /tmp 2>/dev/null
```

```bash
du -hx --max-depth=1 ~ 2>/dev/null | sort -rh | head -15
```

```bash
du -sh ~/.cache/*/ 2>/dev/null | sort -rh | head -10
```

```bash
docker system df 2>/dev/null
```

```bash
journalctl --disk-usage 2>/dev/null
```

```bash
du -sh /var/cache/pacman/pkg/ 2>/dev/null
```

```bash
find ~ -name "*.mp4" -o -name "*.mkv" -o -name "*.avi" -o -name "*.wav" 2>/dev/null | xargs du -sh 2>/dev/null | sort -rh | head -10
```

Present findings ranked by recoverable space. Suggest cleanup commands but **confirm with operator before executing**:
- `docker system prune` (removes stopped containers, unused images)
- `journalctl --vacuum-size=500M`
- `paru -Sc` (clear package cache)
- Removing old video recordings
- `docker volume prune` (confirm — may remove data)

Never auto-delete without confirmation.
