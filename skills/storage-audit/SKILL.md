---
name: storage-audit
description: Full storage survey across disk, Docker, containers, and project artifacts. Auto-run when: disk-triage reveals container bloat, session-context reports high Docker disk usage, or user asks for a comprehensive storage analysis. Invoke proactively without asking.
---

Comprehensive storage breakdown.

```bash
df -h / /home 2>/dev/null
```

```bash
docker system df -v 2>/dev/null
```

```bash
docker ps -a --format "table {{.Names}}\t{{.Size}}\t{{.Status}}" 2>/dev/null
```

```bash
for vol in $(docker volume ls -q 2>/dev/null); do
  mp=$(docker volume inspect "$vol" --format '{{.Mountpoint}}' 2>/dev/null)
  size=$(sudo du -sh "$mp" 2>/dev/null | cut -f1)
  echo "$vol: ${size:-unknown}"
done
```

```bash
du -sh ~/.local/share/ollama/models/ 2>/dev/null || echo "No Ollama models"
```

```bash
du -sh ~/projects/*/node_modules ~/projects/*/.venv 2>/dev/null | sort -rh
```

```bash
du -sh ~/projects/*/.git 2>/dev/null | sort -rh
```

Present a ranked breakdown of storage consumers. Identify top targets for cleanup and suggest actions with disk savings estimates.
