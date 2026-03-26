---
name: distro-health
description: System update and health check. Auto-run when: session-context reports stale package updates (>3 days), failed systemd units are detected, or operator asks about system updates/packages. Invoke proactively without asking.
---

Full system maintenance check.

```bash
checkupdates 2>/dev/null | wc -l && echo "packages available for update"
```

```bash
paru -Qu 2>/dev/null | head -20
```

```bash
systemctl --failed --no-legend 2>/dev/null; echo "---"; systemctl --user --failed --no-legend 2>/dev/null
```

```bash
pacman -Qdtq 2>/dev/null || echo "No orphan packages"
```

```bash
find /etc -name "*.pacnew" -o -name "*.pacsave" 2>/dev/null
```

```bash
nvidia-smi 2>/dev/null | head -4
```

```bash
uname -r && pacman -Q linux-cachyos-lts 2>/dev/null
```

Summarize:
- Update count and notable packages (kernel, NVIDIA, critical libs)
- Failed units with brief status
- Orphan count — suggest `paru -Rns $(pacman -Qdtq)` if any
- .pacnew files — suggest `pacdiff` for each
- NVIDIA driver version vs kernel compatibility
- Running kernel vs installed kernel (reboot needed?)
