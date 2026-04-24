# alpha night handoff — 2026-04-23 → next session

**Read first.** This is the most important context for picking up.

## What you (next-alpha) are picking up

**Audio epic** — operator's "one time forever" unified audio architecture. Started as one PR; turned into four shipped + one big framework. You're mid-arc, framework is in place, validation pending.

**Beta's YouTube autonomous-boost spec** — hand-off in `~/.cache/hapax/relay/beta-to-alpha-delta-2026-04-23-youtube-autonomous-boost.md`. Beta is drafting the spec; asks you for right-of-first-refusal on G1 + answers to A2/A3. **Not urgent.**

## What is LIVE on the broadcast right now

- Music: 67-track lo-fi/boom-bap pool flowing via `hapax-music-loudnorm` → `hapax-music-duck` → L-12 USB CH 11/12
- TTS: routes via `hapax-voice-fx` → `hapax-loudnorm-capture` → `hapax-tts-duck` → L-12 USB
- L-12 input: `-18 dBFS` clean (no clipping, no fader touch)
- Broadcast egress: `-24 LUFS-I` music-alone (operator-confirmed "perfect" at +1 dB master makeup)
- OBS: bound to `hapax-broadcast-normalized` (or `hapax-obs-broadcast-remap` — equivalent), reads through master safety-net limiter
- Splattribution: working again (album-identifier no longer nukes music-attribution.txt)
- `hapax-audio-ducker.service` running, fail-safe, default passthrough

## Audio epic — what shipped today

| Phase | PR | Headline |
|---|---|---|
| 1 — master safety net + spec/plan/research | #1269 | Replaced sc4m+hard_limiter at master with `fast_lookahead_limiter_1913` true-peak limiter. OBS rebound from `hapax-livestream:monitor` (orphaned-master finding) to `hapax-broadcast-normalized`. |
| 1.5 — true music limiter + master makeup | #1271 | Replaced `hard_limiter_1413` (sample CLIPPER) with `fast_lookahead_limiter_1913` true-peak in music chain. Master makeup gain calibrated live with operator. |
| 1.7 — TTS chain level parity | #1272 | TTS chain now within 2 dB of music at broadcast (was 9 dB difference). Same true-limiter shape as music. |
| 4 — sidechain ducking framework | #1273 | Duck mixer infrastructure (`hapax-music-duck`, `hapax-tts-duck`) + Python envelope-follower daemon. Default passthrough, fail-safe on daemon death. |

Plus also today: PRs #1256 #1259 #1262 (music programmer fallback, hot-reload, SC adapter source preservation).

## Audio architecture canonical refs

- **Spec:** `docs/superpowers/specs/2026-04-23-livestream-audio-unified-architecture-design.md`
- **Plan:** `docs/superpowers/plans/2026-04-23-livestream-audio-unified-architecture-plan.md`
- **Research:** `docs/research/2026-04-23-livestream-audio-unified-architecture.md` (945 lines, exhaustive)
- **Governance:** `docs/governance/audio-architecture-handoff.md` — read this BEFORE touching any audio config
- **Constants SSOT:** `shared/audio_loudness.py` — never hand-tune dB values outside this file

## Phase 4 — what works vs pending

**Verified live:**
- Duck mixers `hapax-music-duck` + `hapax-tts-duck` deployed, RUNNING, default Gain 1 = 1.0 (passthrough). Routing intact via `pw-link -l`.
- Manual mixer-gain write works: `pw-cli set-param hapax-music-duck Props '{ params = [ "duck_l:Gain 1" 0.398 "duck_r:Gain 1" 0.398 ] }'` applies + reverts cleanly.
- Daemon `hapax-audio-ducker.service` running, `Restart=always`, captures Rode (L-12 USB AUX4) + TTS (`hapax-loudnorm-capture.monitor`), publishes state to `/dev/shm/hapax-audio-ducker/state.json` every 20 ms.
- Daemon shutdown handler restores unity gain. Music + TTS NEVER silenced by daemon failure.

**Pending:**
1. **TTS-trigger detection unverified.** Daemon's TTS-monitor tap doesn't fire on synthetic `pw-cat` test stim because `pw-cat --target X` for filter-chain sinks doesn't propagate the same way as daimonion's `role.assistant` routing (WP role-based linking). Real daimonion TTS will route correctly. **Validation = wait for daimonion to fire a real utterance**, then check `/dev/shm/hapax-audio-ducker/state.json` to confirm `tts.active=true` + `music_duck_db ≈ -8.0`. If detection fires but mixer doesn't move, debug `write_mixer_gain()` in `agents/audio_ducker/__main__.py`.
2. **Operator-voice (Rode) trigger unverified.** Operator deferred Rode wireless RX calibration. When ready, the trigger source is L-12 USB capture AUX4 (CH5) — should auto-fire when Rode is calibrated and operator speaks.

## Operator-deferred items (do NOT pick up unless asked)

- **L-12 input clipping investigation.** Earlier today: music sink output measured `-9 dBFS` at master limiter input but Evil Pet was clipping. Operator: "wait until I get back" → resolved later in session by replacing music chain's sample-clipper. **Likely now-fixed by Phase 1.5 + Phase 4 work, but operator hasn't reconfirmed.** If they raise it, start by listening + measuring with `scripts/audio-measure.sh`.
- **Rode wireless mic calibration.** "We will do that sometime far later, low low priority. I'd be talking to the void right now." Don't bring it up.
- **`--music-trim` worktree.** Operator's stashed makeup-trim experiment (`fix/music-loudnorm-output-trim`, 1 commit ahead). Don't touch — it's their work-in-progress.

## Beta's YouTube autonomous-boost asks (not urgent)

Read full handoff: `~/.cache/hapax/relay/beta-to-alpha-delta-2026-04-23-youtube-autonomous-boost.md`

You committed to:
- **A1:** take G1 (Content-ID watcher loop, Ring-3 lane fit). G2/G3 to beta.
- **A2:** answer pending — "is Ring 3 the right attachment point for G1?" Look at content-source-registry Ring model fresh, then reply via relay file.
- **A3:** "no programme-layer in flight from me, defer to beta's audit."
- **D3 (for beta to see):** "unified-audio architecture has no opinion on CEA-608/708 GStreamer injection point; that's compositor encoder-pipe territory, no collision with master/duck chains."

Beta's not urgent: "if you're underwater keep shipping."

## Critical invariants from this session

- **Egress target = −14 LUFS-I, −1.0 dBTP.** Operator-confirmed YouTube-aligned.
- **All sources default-wet through Evil Pet.** Per-source `dry: true` override in future Phase 6 routing config.
- **L-12 faders sit at unity, never touched by operator.** `MIC` switch off / `LINE` switch on for CH 11/12, trim at 12 o'clock.
- **`hard_limiter_1413` is a SAMPLE CLIPPER, not a limiter.** Never use it. Always `fast_lookahead_limiter_1913`.
- **Music genre = lo-fi / lo-fi boom bap / boom bap hip hop only.** Operator-curated SoundCloud (oudepode) exempt. Saved to memory.
- **PipeWire restarts during livestream are FINE while operator is present.** When operator is away, OBS rebinding currently breaks (Phase 2 fixes — not yet shipped).

## Worktree state

3 non-cache worktrees:
- alpha primary (on `docs/geal-design`)
- `--music-trim` (operator's experiment, fix/music-loudnorm-output-trim)
- `--scrim-step1` (peer's branch)
- `--audio-epic` ← THIS handoff doc lives here on `docs/handoff-alpha-2026-04-23-night`

After this handoff PR merges, `--audio-epic` worktree can be cleaned up.

## What to do FIRST in next session

1. **Read this handoff.**
2. **Check broadcast is healthy:** `scripts/audio-measure.sh 30` — expect `I ≈ -24 LUFS / Peak ≤ -8 dBFS / no clip`. If hot, master makeup may need re-tuning.
3. **Check ducker daemon status:** `systemctl --user is-active hapax-audio-ducker.service` and `cat /dev/shm/hapax-audio-ducker/state.json`. Should show both Rode + TTS reading silence (RMS ≤ -80 dBFS), music_duck = 0.0 dB.
4. **If operator asks about TTS ducking:** wait for next real daimonion utterance, then verify state.json shows `tts.active=true` + `music_duck_db ≈ -8.0` during the utterance.
5. **If operator asks about beta's spec:** answer A2 (Ring 3 attachment point for G1) and pick up G1 implementation.

## What NOT to do

- **Don't restart PipeWire while operator is away.** OBS audio source breaks until they manually re-add. Phase 2 (OBS-restart resilience) is unshipped.
- **Don't hand-tune any audio constants outside `shared/audio_loudness.py`.** Comments inside each `.conf` cite which constant they mirror.
- **Don't touch `--music-trim` worktree.** Operator's work-in-progress.
- **Don't re-claim cc-task `lssh-014`** (the prior session's task) — see vault for current claim state.

## Stale tasks worth closing in vault

Per the audit during this session, these CC-tasks dated 2026-04-13 are likely stale:
- `3499-003 — CRITICAL: imagination-loop dead 36h — Qwen tool-call parser` — verified imagination loop is alive via markdown-fallback path.
- `3499-004 — CRITICAL: logos-api starved by gmail-sync inotify flood` — verified gmail-sync.timer is now inactive, logos-api responsive.

If you have time, close these via `cc-close <id>` after verifying they're still stale.

## Session phase-out notes

Session was very long (~7 h). Operator paused for daughter's piano recital midway, came back, deep-dived audio. End-state is **stable, deployed, operator-confirmed**. No outstanding pain. Sidechain validation is the natural next cycle when daimonion next speaks or operator calibrates Rode.

Music is flowing. Operator is satisfied. Ship is sailing.

— alpha (out)
