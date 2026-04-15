# LRR Phase 2 operator activation runbook

**Date:** 2026-04-15
**Author:** alpha (refill 7 item #97)
**Target audience:** the operator
**Scope:** end-to-end activation of the LRR Phase 2 archive pipeline items that are intentionally deferred to manual operator action — specifically item #54 (archive services re-enable, ratified in PR #853) and item #58 (audio archive via pw-cat, deferred because live-hardware PipeWire sources cannot be CI-tested).
**Related specs:**
- `docs/superpowers/specs/2026-04-15-lrr-phase-2-archive-research-instrument-design.md` §3.1, §3.5
- `systemd/README.md § Disabled Services § LRR Phase 2 item 1 activation`
- `docs/research/2026-04-14-lrr-phase-2-hls-archive-dormant.md`

---

## 0. Why this needs operator action

These services record against live hardware. Starting them mid-session is an operational change that:

1. **Binds to hardware-specific PipeWire source names** that drift between reboots, USB replugs, and `pipewire-pulse` restarts. The unit files carry a specific source name; if the live source name doesn't match, `pw-record` fails silently (exit 0 no data) and the activation looks successful but produces zero bytes.
2. **Consumes ~2.8 GB/day** per active microphone (FLAC 48kHz mono). Starting both mics unattended could fill the home partition if `df -h ~/audio-recording/` has <10 GB headroom.
3. **Interacts with the daimonion voice loop**, which also holds PipeWire handles for STT input. Contention is possible if the operator is mid-conversation when a service starts.

For these reasons the `executive_function` axiom's "routine work automated" clause does NOT cover this activation. The operator runs the sequence at a moment of the operator's choosing.

## 1. Prerequisites

Before running this runbook:

- [ ] `~/projects/hapax-council` is on `main` and up to date
- [ ] `systemd/scripts/install-units.sh` has been run since PRs #853 + #859 merged (installs + enables unit files from the repo into `~/.config/systemd/user/`)
- [ ] PipeWire is running: `systemctl --user status pipewire.service` → active
- [ ] Neither service is currently active: `systemctl --user is-active audio-recorder.service contact-mic-recorder.service` → inactive/inactive
- [ ] At least 10 GB free on `~/audio-recording/` partition: `df -h ~/audio-recording`
- [ ] Operator is NOT in a live voice session (daimonion CPAL loop idle)

## 2. Step 1 — Verify the live PipeWire source names match unit files

The two unit files carry hardcoded source names. Real hardware names drift; verify first.

```bash
# List all PipeWire capture sources
pactl list short sources

# Expected substrings for audio-recorder (Blue Yeti):
#   alsa_input.usb-Blue_Microphones_Yeti_Stereo_Microphone_REV8-00.analog-stereo
# Expected name for contact-mic-recorder:
#   contact_mic  (named pipewire node alias for the Cortado on PreSonus Studio 24c input 2)
```

**If the Blue Yeti line is absent:** check USB connection (`lsusb | grep -i blue`). If USB is fine but the ALSA device name has changed (rare, happens when the Yeti firmware revision differs), the `audio-recorder.service` unit will need an ExecStart edit. Do not edit the unit file in place — create a drop-in override at `~/.config/systemd/user/audio-recorder.service.d/local-source.conf` with:

```ini
[Service]
ExecStart=
ExecStart=/bin/bash -c 'exec /usr/bin/pw-record --target <ACTUAL_SOURCE_NAME> --format s16 --rate 48000 --channels 1 - | /usr/bin/ffmpeg -nostdin -f s16le -ar 48000 -ac 1 -i pipe: -c:a flac -f segment -segment_time 900 -strftime 1 %h/audio-recording/raw/rec-%%Y%%m%%d-%%H%%M%%S.flac'
```

The empty `ExecStart=` clears the parent value, the second line replaces it. Reload the unit: `systemctl --user daemon-reload`.

**If `contact_mic` is absent:** the contact-mic named pipewire node is created by a wireplumber rule that aliases the PreSonus Studio 24c Input 2 channel. Check that the PreSonus is connected (`lsusb | grep PreSonus`) and that `wireplumber.service` is running. If the alias is missing, the rule at `~/.config/wireplumber/main.lua.d/51-contact-mic.lua` (or similar) needs to be reloaded via `systemctl --user restart wireplumber.service`.

## 3. Step 2 — Hardware headroom check

```bash
df -h ~/audio-recording  # want >= 10 GB free
df -h ~/hapax-state/stream-archive/audio  # want >= 10 GB free (same partition typically)
```

Each service writes ~2.8 GB/day at 48kHz FLAC mono. Both active = ~5.6 GB/day. 10 GB headroom is a conservative 1.5-day buffer; adjust up if the operator plans to run longer before the next rotation/cleanup cycle.

## 4. Step 3 — Enable + start the two services

```bash
# Enable + start (the services persist across reboots after this)
systemctl --user enable --now audio-recorder.service
systemctl --user enable --now contact-mic-recorder.service

# Verify both are active + running
systemctl --user status audio-recorder.service contact-mic-recorder.service
```

**Expected status output:**

```
● audio-recorder.service - Continuous ambient audio recording (Blue Yeti via PipeWire)
     Loaded: loaded (.../audio-recorder.service; enabled; preset: ...)
     Active: active (running) since ... ; Xs ago
   Main PID: NNNNN (bash)
      Tasks: 3
     Memory: 5-15M
        CPU: ~0.5%
     CGroup: /user.slice/user-1000.slice/user@1000.service/app.slice/audio-recorder.service
             ├─NNNNN /bin/bash -c exec /usr/bin/pw-record ...
             ├─NNNNN /usr/bin/pw-record ...
             └─NNNNN /usr/bin/ffmpeg ...
```

**If Active state is `failed` or `inactive`:**

```bash
# Tail the journal for the last 60 seconds of the failing unit
journalctl --user -u audio-recorder.service -n 100 --no-pager

# Common failure modes:
#   - "target not found" → source name mismatch; go back to step 1
#   - "Permission denied" on ~/audio-recording → chmod -R u+rwX ~/audio-recording
#   - "ffmpeg: No such file or directory" → pacman -S ffmpeg
#   - pw-record exits immediately → pipewire.service not active; restart wireplumber
```

## 5. Step 4 — Verify first segment write (60s smoke)

Wait 60 seconds after `systemctl start`, then check that FLAC files are being written:

```bash
# Should see files being created with ISO-like timestamps
ls -lht ~/audio-recording/raw/ | head -5
ls -lht ~/audio-recording/contact-mic/ | head -5

# Confirm non-zero file size (zero bytes = silent failure; see troubleshooting below)
find ~/audio-recording/raw/ ~/audio-recording/contact-mic/ -name '*.flac' -mmin -5 -size 0

# Play the most recent segment for sanity check (optional, needs headphones)
ffplay -nodisp -autoexit "$(ls -t ~/audio-recording/raw/*.flac 2>/dev/null | head -1)"
ffplay -nodisp -autoexit "$(ls -t ~/audio-recording/contact-mic/*.flac 2>/dev/null | head -1)"
```

**If files are being created but zero-byte:** pw-record is running but no samples are flowing. Check:
1. PipeWire loopback: `pw-link -l | grep -E 'Yeti|contact_mic'` — must show graph edges
2. Input level: `pavucontrol` → Input Devices tab → verify Yeti / Contact Mic channel meter moves with audio
3. Mute state: `pactl list sources | grep -A3 'Yeti\|contact_mic'` — Mute should be `no`

**If ffmpeg is consuming CPU but no files:** segment_time=900 means the first file doesn't flush until 15 minutes after start. Wait 15 minutes; then re-check.

## 6. Step 5 — Cross-check the HLS archive is still flowing

Item #58 overlaps with the item #55 HLS rotator fix (PR #859). Verify both streams are archiving:

```bash
# HLS: should have today's dated dir with .ts + .json sidecars from the last ~minute
ls ~/hapax-state/stream-archive/hls/$(date +%Y-%m-%d)/ | tail -10

# Verify hls-archive-rotate.timer is still active (PR #859 fix preserves it)
systemctl --user list-timers hls-archive-rotate.timer --no-pager

# Check compositor hasn't crashed from pw-record contention
systemctl --user is-active studio-compositor.service  # expected: active
```

If the compositor has died after the audio services started, contention for the Blue Yeti is the likely cause — both `audio-recorder.service` and the compositor's ambient-mic input may be requesting the same source exclusively. Resolve by routing one of them through `pw-loopback` (workaround documented in the Voice FX Chain section of the council CLAUDE.md).

## 7. Step 6 — Confirm segment boundaries are research-ready

The LRR Phase 2 spec §3.5 wants audio segments correlated to HLS video segments (~6s cadence) so per-segment sidecars can be joined. The current unit files use `segment_time 900` (15 min) which is NOT 6s-aligned.

**Decision point:** does the operator want:
- **Option A — 15 min FLAC segments** (current unit file): simpler, bigger files, correlation requires sub-segment timestamping at analysis time
- **Option B — 6s FLAC segments** (edit `segment_time 6`): aligns with HLS, but produces ~14,400 files/day per mic and requires a parallel `audio-archive-rotator.timer` analogous to `hls-archive-rotate.timer` to move segments into `~/hapax-state/stream-archive/audio/YYYY-MM-DD/`

Spec intent is Option B. This runbook does NOT switch to Option B automatically — the operator decides at activation time. If Option B is chosen, file a follow-up queue item to ship the audio-archive-rotator + unit file + tests before committing the `segment_time` edit.

## 8. Rollback path

If the activation causes problems (compositor crash, voice session distortion, disk fills, PipeWire contention), roll back cleanly:

```bash
# Stop + disable both services
systemctl --user disable --now audio-recorder.service
systemctl --user disable --now contact-mic-recorder.service

# Verify stopped
systemctl --user is-active audio-recorder.service contact-mic-recorder.service
# Expected: inactive / inactive

# The FLAC files from the partial run remain on disk at ~/audio-recording/raw/ and
# ~/audio-recording/contact-mic/. Decide whether to keep them (research data) or
# remove them (`rm ~/audio-recording/raw/rec-<ts>.flac`). They are NOT referenced
# by any other service after disable.
```

If the compositor crashed during activation, restart it separately:

```bash
systemctl --user restart studio-compositor.service
journalctl --user -u studio-compositor.service -n 50 --no-pager
```

## 9. Attach evidence to item #58 closure

After a successful 5-minute activation window:

1. Capture the journal tail:
   ```bash
   journalctl --user -u audio-recorder.service -u contact-mic-recorder.service --since='5 min ago' --no-pager > /tmp/lrr-phase-2-item-58-activation.log
   ```

2. Capture the file listing as evidence of non-zero FLAC writes:
   ```bash
   ls -lht ~/audio-recording/raw/ ~/audio-recording/contact-mic/ | head -20 > /tmp/lrr-phase-2-item-58-files.log
   ```

3. Attach both as a comment on PR #853 (or the next activation PR) so item #58 can be marked `completed` in `queue-state-alpha.yaml` with the activation evidence.

4. Update `queue-state-alpha.yaml::items[#58]`:
   - `status: completed`
   - `shipped: {at: <ISO8601>, notes: "operator-activated per runbook"}`
   - `notes:` point at the two /tmp evidence files or a proper archive location

## 10. Known issues + gotchas

- **Blue Yeti firmware rev drift:** the `REV8` suffix in the ALSA device name is a Blue Microphones firmware revision. If the operator ever replaces the Yeti with a different unit, the suffix will change (`REV7` or `REV9`) and the `pw-record --target` line will silently fail. The drop-in override pattern in §2 handles this.
- **PreSonus input routing:** contact mic is on the PreSonus Studio 24c **input 2** with 48V phantom. Input 1 carries the vocal mic for daimonion STT. Never swap the two inputs without also updating the wireplumber alias rule.
- **daimonion interference:** when daimonion is in active conversation mode, it holds an exclusive handle on the Yeti for STT. Starting `audio-recorder.service` mid-conversation will fail with "target busy". Wait for daimonion to return to idle (no active CPAL loop) before running step 3.
- **Disk cascading fill:** FLAC compresses ~2:1 on speech, closer to 1:1 on music/noise. A livestream session with heavy ambient music can push to ~5 GB/day per mic. Monitor `df -h` and set up a `tmpfiles.d` cleanup rule or a separate retention timer if the operator plans to run >1 week continuously.
- **Silent failure mode:** `pw-record` exits 0 when the target source produces no samples (e.g., muted source, wrong name, phantom power off on the PreSonus). The only reliable check is file size, not exit code. Step 5's zero-byte check is the canonical smoke.

## 11. Activation completeness checklist

Complete all before closing item #58:

- [ ] §2 source names verified against live `pactl list sources`
- [ ] §3 disk headroom ≥ 10 GB confirmed
- [ ] §4 `systemctl --user enable --now` for both services succeeded
- [ ] §4 `systemctl status` shows Active: running for both units
- [ ] §5 first FLAC files written with non-zero size within 15 minutes
- [ ] §5 `ffplay` smoke-check on at least one segment confirms audio content
- [ ] §6 HLS archive still flowing (hls-archive-rotate.timer active, compositor still active)
- [ ] §7 segment_time decision documented (Option A stay / Option B switch)
- [ ] §9 journal + file listing evidence captured
- [ ] queue-state-alpha.yaml `items[#58]` transitioned to `completed`

## 12. References

- LRR Phase 2 spec §3.1 (archive services re-enable, item 1)
- LRR Phase 2 spec §3.5 (audio archive via pw-cat, item 5 / queue item #58)
- `systemd/units/audio-recorder.service` (Blue Yeti unit)
- `systemd/units/contact-mic-recorder.service` (Cortado unit)
- `systemd/README.md § Disabled Services § LRR Phase 2 item 1 activation`
- PR #853 (item #54 archive services scope ratification + docs-only activation runbook stub)
- PR #859 (item #55 HLS cache delete-on-start removal, companion fix)
- `docs/research/2026-04-14-lrr-phase-2-hls-archive-dormant.md` (dormancy root cause)
- `queue-state-alpha.yaml::items[#58]` (deferred rationale by alpha 16:55Z closure)
