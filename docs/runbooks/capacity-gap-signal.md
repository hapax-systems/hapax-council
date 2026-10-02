# Capacity-gap signal: seat activation after merge

```bash
~/.local/bin/hapax-source-activate
install -m 0644 ~/.cache/hapax/source-activation/worktree/systemd/units/hapax-capacity-gap-signal.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now hapax-capacity-gap-signal.timer
systemctl --user start hapax-capacity-gap-signal.service
systemctl --user show hapax-capacity-gap-signal.service -p ExecStart -p Result
systemctl --user list-timers hapax-capacity-gap-signal.timer --no-pager
cat ~/.cache/hapax/capacity-gap-signal-state.json
```

The seat verifies the first real cycle's Result, state and mail.
