# Local Music Player — Deployment & Operator Workflow

**Date:** 2026-04-23
**Status:** Phase 4a shipped, deployment operator-confirmed
**Related:**
- `agents/local_music_player/` — daemon
- `scripts/hapax-music-play` — operator CLI
- `systemd/units/hapax-music-player.service` — systemd unit
- `docs/governance/evil-pet-broadcast-source-policy.md` — broadcast routing rules
- `docs/superpowers/plans/2026-04-23-content-source-registry-plan.md` — overall epic

## What this ships

Operator-approved tracks (written to `/dev/shm/hapax-compositor/music-selection.json`) play through PipeWire. Daemon watches the selection file; on change, kills any in-flight playback and starts the new track via `pw-cat` (local files) or `yt-dlp | pw-cat` (URLs — SoundCloud / YouTube). Splattribution flows to `/dev/shm/hapax-compositor/music-attribution.txt` for the existing `album_overlay` ward to render.

## Operator workflow

```
# 1. Find candidates (existing flow — surfacer fires on vinyl-stop transition)
$ ls /dev/shm/hapax-compositor/music-candidates.json

# 2. Approve a candidate by number
$ hapax-music-play 1

# OR play a specific track / URL directly
$ hapax-music-play --path ~/music/hapax-pool/operator-owned/track.flac \
                    --title "Direct Drive" --artist "Dusty Decks" --source operator-owned

$ hapax-music-play --path https://soundcloud.com/oudepode/unknowntron-1/s-token \
                    --title UNKNOWNTRON --artist Oudepode --source soundcloud-oudepode

# 3. Daemon picks up selection within ~1s and plays through default sink.
```

## Routing path to broadcast (operator-side, not enforced by daemon)

The daemon writes to PipeWire's default sink (or `HAPAX_MUSIC_PLAYER_SINK` env override). On the operator's box, default = `alsa_output.pci-0000_73_00.6.analog-stereo` = Ryzen line-out. From there:

```
Ryzen analog stereo → physical RCA → L-12 CH11/12 (AUX10/11)
                                    → AUX-B fader (operator opens for broadcast)
                                    → Evil Pet hardware input
                                    → Evil Pet output → L-12 CH1/CH6 (AUX5)
                                    → gain_evilpet → broadcast capture sum
                                    → /dev/video42 + RTMP
```

**Operator must open CH11/12 AUX-B sends on the L-12 for music to reach broadcast.** Per the Evil Pet broadcast source policy: only TIER 0 / TIER 1 sources may feed Evil Pet during a live stream. Local pool + Epidemic + oudepode SC tracks are tier_0 / tier_1 by default — safe.

## Sink override

```bash
# Send music to a dedicated sink instead of default Ryzen line-out
HAPAX_MUSIC_PLAYER_SINK="alsa_output.usb-..." \
  systemctl --user start hapax-music-player.service
```

Useful when:
- Operator wants to monitor music on headphones without stream impact
- Routing changes (e.g. dedicated music aux-bus appears)
- Testing a new playback chain off-broadcast

## Deployment

```bash
# Symlink unit to user systemd
ln -sf ~/projects/hapax-council/systemd/units/hapax-music-player.service \
       ~/.config/systemd/user/hapax-music-player.service

# Reload + enable + start
systemctl --user daemon-reload
systemctl --user enable --now hapax-music-player.service

# Verify
systemctl --user status hapax-music-player.service
journalctl --user -u hapax-music-player.service -f
```

## Live verification

```bash
# Pre-conditions: hapax-music-player.service running, broadcast offline
# (or operator's CH11/12 AUX-B closed if you don't want to test on live broadcast).

# Pick a candidate file from the SC repo
$ python3 -c "import json; print(json.dumps([json.loads(l) for l in open('~/hapax-state/music-repo/soundcloud.jsonl')], indent=2))" | head -30

# Trigger playback
$ hapax-music-play --path 'https://soundcloud.com/oudepode/unknowntron-1/s-v87rzbBID6n' \
                    --title UNKNOWNTRON --artist Oudepode --source soundcloud-oudepode

# Within ~1s: hear audio on default sink, see splattribution updated
$ cat /dev/shm/hapax-compositor/music-attribution.txt
UNKNOWNTRON — Oudepode

$ journalctl --user -u hapax-music-player.service --since=10s | tail -10
... playing URL via yt-dlp → pw-cat: https://soundcloud.com/...
```

## What's NOT in Phase 4a

- **Sidechat `play N` parser**: operator runs `hapax-music-play <n>` directly. Wiring "play N" recognition into the daimonion sidechat consumer is Phase 4b.
- **Oudepode rate-limit gate (1-in-30)**: not yet — Phase 4b.
- **Chat-request volitional impingement**: not yet — Phase 4b.
- **Programme-driven auto-recruitment**: deferred to Phase 5+ when programmes layer is wired.

## Rollback

```bash
systemctl --user disable --now hapax-music-player.service
rm ~/.config/systemd/user/hapax-music-player.service
systemctl --user daemon-reload
```

The selection file at `/dev/shm/hapax-compositor/music-selection.json` is read-only consumed; nothing else writes it (except the operator CLI). Removing the daemon means selections sit unconsumed — no broadcast effect.
