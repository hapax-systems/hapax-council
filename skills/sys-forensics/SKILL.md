---
name: sys-forensics
description: System freeze/crash investigation. Auto-run when: session-context detects boot age <1 hour (possible recent crash), operator reports a freeze or crash, system shows instability signs, or user runs /sys-forensics. Accepts optional --since argument. Invoke proactively without asking.
---

Investigate system freezes, crashes, and instability.

```bash
last -x reboot shutdown 2>/dev/null | head -5
```

```bash
journalctl -k -b -1 --no-pager -n 40 2>/dev/null || echo "No previous boot journal available"
```

```bash
journalctl -b -1 --grep="Xid" --no-pager -n 20 2>/dev/null || echo "No NVIDIA Xid errors in previous boot"
```

```bash
dmesg --level=err,crit,alert,emerg --time-format reltime 2>/dev/null | tail -30
```

```bash
journalctl -b 0 --priority=0..3 --no-pager -n 30 2>/dev/null
```

```bash
ls -la /var/lib/systemd/coredump/ 2>/dev/null | tail -5
```

```bash
journalctl -b -1 --grep="oom_reaper\|Out of memory\|invoked oom" --no-pager 2>/dev/null | tail -10
```

Correlate timestamps across sources. Common causes on this system:
- **NVIDIA Xid errors** (GPU crash) — most common. Check driver version, suggest downgrade if needed.
- **OOM kills** — check which process was killed, suggest memory limits.
- **Kernel panic** — check dmesg for panic trace.
- **SP5100 TCO watchdog timeout** — hardware watchdog triggered after 30s unresponsive.

Report: probable cause, affected services, and recommended mitigations.
