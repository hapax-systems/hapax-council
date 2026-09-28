# Capacity-gap signal v1

The 15-minute timer writes `~/.cache/hapax/capacity-gap-signal-state.json` (`status_line` for Reins) and mails the §0 coordinator seat.

Idle requires a flat 15-minute request counter. Unserved GPU metal needs two samples and headroom; TP workers join their endpoint. MiMo backlog uses manifest minus DONE rows. Changed gaps mail once, persistent gaps after 30 minutes, clear sets never. Stale inputs mail `INPUT_STALE`.

## Seat-owned post-merge activation

After independent acceptance and merge, run:

```bash
~/.local/bin/hapax-source-activate
release=~/.cache/hapax/source-activation/worktree
test -f "$release/scripts/capacity_gap_signal.py"
install -m 0644 "$release/systemd/units/hapax-capacity-gap-signal.service" ~/.config/systemd/user/
install -m 0644 "$release/systemd/units/hapax-capacity-gap-signal.timer" ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now hapax-capacity-gap-signal.timer
systemctl --user start hapax-capacity-gap-signal.service
systemctl --user show hapax-capacity-gap-signal.service -p ExecStart -p Result
systemctl --user list-timers hapax-capacity-gap-signal.timer --no-pager
cat ~/.cache/hapax/capacity-gap-signal-state.json
```

Read back the first real cycle's exit and status: one mail for a real gap, none for a clear set. Create the PR as draft with `hold`.

## Follow-up

Switch discovery/utilization to E1 #4743 and stage 2 when landed; v1 does not wait.
