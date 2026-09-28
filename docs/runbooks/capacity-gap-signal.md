# Capacity-gap signal v1

The 15-minute timer writes `~/.cache/hapax/capacity-gap-signal-state.json` (`status_line` for Reins) and mails the §0 coordinator seat.
It reads the last 120 lines of provider tmux panes for quota walls (including Kimi's 403 and Fugu's dated reset) and the public OpenRouter and Featherless `/v1/models` catalogues. Space Bunny is available only while both token prices are exactly zero; no model call is made.

Idle requires a flat 15-minute request counter. Unserved GPU metal needs two samples and headroom; TP workers join their endpoint. MiMo backlog uses manifest minus DONE rows, including the seat's Talus completion readback when the local kit ledger is still blank. Changed gaps mail once, persistent gaps after 30 minutes, clear sets never. Stale inputs mail `INPUT_STALE`.

Read-only rechecks from the activated source tree:

```bash
cd ~/.cache/hapax/source-activation/worktree
uv run python -c 'from pathlib import Path; from scripts.capacity_gap_signal import _appliance_demand; print("MiMo pending:", _appliance_demand(Path.home() / "Documents/Personal/30-areas/hapax/lanebus"))'
tmux ls -F '#{session_name}' | rg '^hapax-(kimi|fugu)-'
tmux capture-pane -pt hapax-kimi-kimi-2 -S -120 | rg -i '403|usage limit|quota'
systemd-analyze verify systemd/units/hapax-capacity-gap-signal.service systemd/units/hapax-capacity-gap-signal.timer
```

The MiMo count reflects explicit pending ledger rows even when a prior Talus readback certified 2,000 DONE rows. An empty or unavailable tmux read becomes `INPUT_STALE:provider-panes` after two cycles; inspect the state file and seat mail after activation.

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
