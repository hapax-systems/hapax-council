# W4 post-merge deploy notes (podium)

Repo-durable companion to `findings.json` recheck_cmds (review round 3:
the album-identifier unit swap sequence lived only in the vault prep
packet). Prometheus deploy is fully covered by
`config/prometheus/README.md`; this file covers the systemd side.

## 1. Unit sweep pickup (automatic)

The 46 modified `systemd/units/*.service` files reach podium via the
2-minute origin/main source-activation loop. Unit files are installed
from the repo dir; a `daemon-reload` is required before the new
`OnFailure=` lines take effect:

```bash
systemctl --user daemon-reload
```

No restarts needed for the OnFailure-only changes — the directive is
read at job-queue time, not at service start.

## 2. album-identifier unit swap (one-time, replaces unversioned unit)

The deployed unit at `~/.config/systemd/user/album-identifier.service`
was never versioned and runs from the mutable main clone. The repo unit
deliberately differs: release-root exec path + `ExecStartPre`
runtime-source-check + `OnFailure=`. Swap sequence:

```bash
# from the deployed main clone after merge
ln -sf ~/projects/hapax-council/systemd/units/album-identifier.service \
      ~/.config/systemd/user/album-identifier.service
mkdir -p ~/.config/systemd/user/album-identifier.service.d
ln -sf ~/projects/hapax-council/systemd/units/album-identifier.service.d/memory.conf \
      ~/.config/systemd/user/album-identifier.service.d/memory.conf
systemctl --user daemon-reload
systemctl --user restart album-identifier.service
systemctl --user status album-identifier.service   # confirm release-root ExecStart + drop-in listed
```

The repo drop-in carries the same MemoryHigh=3G/MemoryMax=4G/
MemorySwapMax=2G values as the previously-deployed local drop-in — the
swap changes provenance, not limits. The deployed unit's
`Environment=HOME=/home/hapax` line was dropped (user units always have
HOME) and `PI6_IP` is preserved.

## 3. Verification (storm rechecks)

```bash
journalctl --user -u album-identifier.service --since "-1h" \
  | grep -c "No album currently identified"        # expect < 10
journalctl --user -u hapax-private-broadcast-echo-probe.service --since "-24h" \
  | grep -c LEAK                                    # steady state < 50/day
```
