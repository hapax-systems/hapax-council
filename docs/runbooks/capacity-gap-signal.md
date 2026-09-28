# Capacity-gap signal v1

The 15-minute timer writes `~/.cache/hapax/capacity-gap-signal-state.json` for Reins and mails the §0 seat on changed or 30-minute persistent gaps. Idle needs a flat request counter; unserved GPU metal needs two samples; TP workers share an endpoint. MiMo demand is manifest minus DONE. Clear cycles stay silent; stale inputs mail `INPUT_STALE`.

## Seat-owned post-merge activation

After independent acceptance and merge, run:

```bash
~/.local/bin/hapax-source-activate
release=~/.cache/hapax/source-activation/worktree
test -f "$release/scripts/capacity_gap_signal.py"
for suffix in service timer; do
  install -m 0644 "$release/systemd/units/hapax-capacity-gap-signal.$suffix" ~/.config/systemd/user/
done
systemctl --user daemon-reload
systemctl --user enable --now hapax-capacity-gap-signal.timer
systemctl --user start hapax-capacity-gap-signal.service
systemctl --user show hapax-capacity-gap-signal.service -p ExecStart -p Result
systemctl --user list-timers hapax-capacity-gap-signal.timer --no-pager
cat ~/.cache/hapax/capacity-gap-signal-state.json
```

Read back the first real cycle's Result, timer, state and seat mail. Hold the PR at creation.

## Follow-up

Use E1 #4743 and stage 2 when they land; v1 starts now.
