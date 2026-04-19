# FINDING-V Deploy Status — Live Verification Contract

**Snapshot**: 2026-04-20 (end of autonomous sprint).
**Purpose**: a single-page checklist the operator can scan to verify
every orphan-ward producer + consumer is alive. Each entry lists the
SHM file, expected cadence, and the one-line bash invariant that
should return the expected value when the producer is healthy.

---

## Phase-by-phase status

| Phase | State | Commit | SHM output | Cadence |
|---|---|---|---|---|
| 1 — `chat_ambient.state()` | ✅ live | `534875a95` | reads `/dev/shm/hapax-chat-signals.json` | per-tick |
| 2 — chat-monitor fold | ✅ deployed | `22b0fcdb8` | writes `/dev/shm/hapax-chat-signals.json` | 30 s |
| 3 — broadcast resolver | ✅ shipped | `d2f23bac9` + `15e1c15a9` | library only | — |
| 4 — viewer count | ⏸️ blocked | — | `/dev/shm/hapax-compositor/youtube-viewer-count.txt` | — |
| 5 — video-id publisher | 🟡 parked | `24f226021` + `15e1c15a9` | `/dev/shm/hapax-compositor/youtube-video-id.txt` | 60 s |
| 6 — recent impingements | ✅ live | `aa010c9c9` | `/dev/shm/hapax-compositor/recent-impingements.json` | 2 s |
| 7 — deploy wrap | ✅ this doc | n/a | n/a | n/a |

### Phase 5 / 4 block (OAuth channel identity)

`liveBroadcasts.list(mine=true)` with the stored token returns only the
main `rylklee@gmail.com` channel (`UCcn1DzSiWOVXbpF6QWpBhDA`). The
streaming sub-channel is invisible to this token's identity.

**Two paths to unblock:**

1. **Re-auth on sub-channel identity.** Drop the token (`pass rm google/token`),
   sign out of all Google accounts in the browser, sign in on the sub-channel
   identity specifically (YouTube's account picker shows both as separate
   "channels" under the same Google account). Run `systemctl --user restart
   youtube-player.service`; the new OAuth consent URL will include the
   sub-channel scope. Cost: 1–2 min operator click.

2. **Manual video-id supply (zero OAuth).** When going live, write the
   broadcast id directly:
   ```fish
   echo YOUR_BROADCAST_ID > /dev/shm/hapax-compositor/youtube-video-id.txt
   systemctl --user restart chat-monitor.service
   ```
   chat-monitor's `_read_video_id` honours this path. Phase 4 viewer count
   is deferred.

Option 2 is the operational-minimum path. Option 1 is the full automation.

---

## Operator live-verification bash oneliner

Run during a live canary to confirm every producer is fresh:

```fish
for f in \
    /dev/shm/hapax-compositor/recent-impingements.json \
    /dev/shm/hapax-compositor/hardm-cell-signals.json \
    /dev/shm/hapax-compositor/homage-active-artefact.json \
    /dev/shm/hapax-compositor/yt-audio-state.json \
    /dev/shm/hapax-chat-signals.json
    if test -f $f
        set age (math (date +%s) - (stat -c %Y $f))
        echo "$age""s" $f
    else
        echo "MISSING" $f
    end
end
```

Expected: every line under 120 s when the system is running normally.
`hapax-chat-signals.json` MISSING until chat-monitor has a video id
(bypass above).

---

## Prometheus counters to watch

```
hapax_speech_safety_redactions_total{outcome="redacted"}
```
Should stay at 0 on clean streams; any increment = a TTS call hit the
N-word gate and redacted. Investigate if ≥ 1 per hour.

```
studio_compositor_source_render_duration_ms_bucket{source_id="hardm_dot_matrix"}
```
Most renders should fall in the 2.5–5 ms bucket. p99 > 25 ms = the CP437
/ RD rework is costing more than budgeted.

```
hapax_homage_active_artefact_rotation_total
```
Increments once per rotation cycle (Choreographer tick). If frozen,
`homage-active-artefact.json` is stale and the wards read it as muted.

---

## Bake-off calendar

24 h post-deploy (2026-04-21 ~13:00 local) operator should:
1. Run the oneliner above
2. `journalctl --user -u hapax-daimonion.service --since=-1d | grep -c "speech_safety.censor: redacted"` — confirm the gate is firing (or not) as expected
3. Visual inspection of HARDM on fullscreen compositor output — should
   read as CP437 grid with slow internal motion (RD underlay), bloom from
   Reverie post-FX, crisp block edges, event-driven ripples on cell
   transitions.

---

## Files

- Plan: `docs/superpowers/plans/2026-04-20-orphan-ward-producers-plan.md`
- Research docs:
  - `docs/research/2026-04-20-hardm-aesthetic-rehab.md` (HARDM rework)
  - `docs/research/2026-04-20-chat-keywords-ward-design.md` (Q4 future work)
- Systemd units (new):
  - `systemd/units/hapax-youtube-video-id.service` (Phase 5)
  - `systemd/units/hapax-recent-impingements.service` (Phase 6)
