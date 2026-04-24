# Livestream Audio Unified Architecture — Implementation Plan

**Spec:** `docs/superpowers/specs/2026-04-23-livestream-audio-unified-architecture-design.md`
**Research:** `docs/research/2026-04-23-livestream-audio-unified-architecture.md`

8-phase rollout. Risk-ordered: safety-net first (so subsequent phases have a place to fail safely), survivability second (so phases 3+ can ship without operator at the rig), then progressive replacement of ad-hoc dynamics with the unified system.

Each phase is one or more PRs, each ships with concrete dB / LUFS / ms acceptance criteria. Each phase is independently revertable. **No phase requires the operator's hands on a fader.**

---

## Phase 1 — Master safety net + OBS rebind + L-12 trim

**Risk:** Touches live PipeWire master chain. Operator MUST be present (5-min L-12 hardware action + verification listening).

**Scope:**
1. Add `shared/audio_loudness.py` with all numeric constants (egress LUFS, master TP ceiling, headroom).
2. Replace `config/pipewire/hapax-broadcast-master.conf`'s `sc4m + hardLimiter` chain with **`lsp-plugins.lv2 Limiter Stereo` configured as brick-wall true-peak limiter at −1.0 dBTP, 5 ms lookahead, 50 ms release.** No compression at master. Master is now safety net only.
3. Add `lsp-plugins.lv2 Loudness Meter Mono/Stereo` taps:
   - one on `hapax-broadcast-master` input (pre-limiter sum)
   - one on `hapax-broadcast-normalized` (post-limiter, what OBS will read)
   - both expose I/M/S/TP/LRA via LV2 plugin notification ports (read by Phase 7 sidecar; for Phase 1 they just exist).
4. Add `scripts/audio-measure.sh` — operator-runnable script that taps `hapax-broadcast-normalized.monitor` for 30 s and prints integrated LUFS via `ffmpeg -af ebur128=peak=true`. Manual verification tool until Phase 7 ships the live dashboard.
5. Operator action (one-time, supervised): rebind OBS audio source from `Monitor of Hapax Livestream` → `Monitor of Hapax Broadcast Normalized` (or `hapax-obs-broadcast-remap` if PulseAudio source-name list shows it cleaner). Confirmed via `pw-link -l | grep OBS`.
6. Operator action (one-time, supervised): on the L-12 mixer, switch CH11/12 input from `MIC` to `LINE`, set channel trim to 12 o'clock (unity), set CH11/12 fader to unity. Verify Evil Pet input meter is in green (no clip LED) on a representative loud passage.
7. Restart `pipewire pipewire-pulse wireplumber` after conf swap; reload OBS; play a loud passage; run `scripts/audio-measure.sh` to verify integrated LUFS in the −12 to −16 LUFS range and TP < −0.5 dBTP. (Per-source comp is still doing the level work; master is just protecting peaks.)

**Files changed:**
- `shared/audio_loudness.py` (new)
- `config/pipewire/hapax-broadcast-master.conf` (rewritten)
- `scripts/audio-measure.sh` (new)
- `docs/governance/audio-architecture-handoff.md` (new — for future Claude sessions to know where the SSOT is)

**Acceptance criteria:**
- `pactl list short sinks | grep hapax-broadcast-master` returns RUNNING.
- `pw-link -l | grep -A1 OBS` shows OBS reading `hapax-broadcast-normalized` (or its remap), NOT `hapax-livestream:monitor`.
- 30 s `scripts/audio-measure.sh` on a loud lo-fi passage: integrated LUFS-I in [−16, −12], peak TP ≤ −0.5 dBTP, no `ALERT` events in output.
- Evil Pet input level: green LEDs only, no clip LED, on a 0 dBFS test tone played through the music chain.
- Operator confirms broadcast sound is at least as loud as before (subjective check during the supervised window).

**Rollback:** `git revert` of the master conf change + `systemctl --user restart pipewire pipewire-pulse wireplumber`. Restores prior sc4m+limiter chain. OBS rebind survives revert (operator does NOT need to re-touch OBS).

**Time estimate:** 90 minutes including supervised operator window.

---

## Phase 2 — OBS-restart survivability (zero-touch PW restart)

**Risk:** Medium. Adds a stable named PipeWire object OBS binds to. Removes the fragile `Monitor of …` indirection.

**Scope:**
1. Add `config/pipewire/hapax-obs-ingest.conf` — a `pw-loopback` (or `module-null-sink` with explicit `node.name = "hapax-obs-ingest"` and stable description). Inputs from `hapax-broadcast-normalized.monitor`. Outputs presented to PulseAudio with a stable, never-changing name.
2. Generator script ensures the conf is regenerated identically across runs (no random suffixes).
3. Operator action (one-time, supervised in Phase 2 deploy window): in OBS, change audio source to `hapax-obs-ingest` source. Save scene collection.
4. Verify: `systemctl --user restart pipewire pipewire-pulse wireplumber` while OBS is open → wait 10 s → confirm OBS audio meters resume without operator touch and `pw-link -l | grep OBS` shows the binding intact.
5. Verify: `kill -9 $(pgrep -f "module-loopback")` (simulating WP recycling the loopback) → wait 10 s → confirm OBS still bound.
6. Add `scripts/test-obs-resilience.sh` — codifies the verification above as a one-line script the operator can run anytime.
7. Document in `docs/governance/audio-architecture-handoff.md` the binding name OBS must always target. New OBS profiles must use this name.

**Investigation note:** the research ID'd PA `Audio Output Capture` as the current best workaround but operator still loses OBS source on restart. Hypothesis: PA caches the **numeric source index** even though it persists the name. Mitigation: force name-based re-resolution by introducing a NEW source name (`hapax-obs-ingest` not `hapax-livestream`/`hapax-broadcast-normalized`). The renaming itself triggers OBS to rebind via the source-picker on the operator's one-time action, and from then on the name is stable.

**Files changed:**
- `config/pipewire/hapax-obs-ingest.conf` (new)
- `scripts/test-obs-resilience.sh` (new)
- `docs/governance/audio-architecture-handoff.md` (updated)

**Acceptance criteria:**
- Three consecutive `systemctl --user restart pipewire pipewire-pulse wireplumber` cycles → OBS audio meters resume each time, no operator touch.
- One simulated WP loopback kill → OBS resumes within 10 s (no operator touch).
- `scripts/test-obs-resilience.sh` exits 0 with all checks green.

**Rollback:** Revert the conf addition; OBS audio source goes back to whatever it was post-Phase-1. No data loss.

**Time estimate:** 2 hours.

---

## Phase 3 — Per-source pre-normalizers

**Risk:** Replaces the hand-tuned `sc4m + hardLimiter` chains on each per-source loudnorm. Per-source levels at the master bus may shift; the master safety-net (Phase 1) catches any TP overshoot. Operator does NOT need to be present.

**Scope:**
1. For each source loudnorm currently in the system (`hapax-music-loudnorm`, `hapax-pc-loudnorm`, `hapax-loudnorm-capture`, `hapax-yt-loudnorm`):
   - Replace the chain with `lsp-plugins.lv2 LUFS Limiter Stereo` (or equivalent — confirm at implementation time which LV2 plugin set has a true LUFS-targeting normalizer; `r128gain` is a CLI tool, not LV2; alternatives: `easyeffects` engine wraps similar). If no LV2 LUFS-target normalizer exists, fall back to `loudgate-stereo` (lsp-plugins) configured per `shared/audio_loudness.py.PRE_NORM_TARGET_LUFS_I`.
   - All control values come from `shared/audio_loudness.py`. Hand-tuning is removed.
2. Add `loudness_meter` LV2 tap on each source pre-norm output for telemetry (consumed by Phase 7).
3. Verify each source individually: play a known-loud sample through it, capture `audio-measure.sh` output, confirm integrated LUFS is within ±1 LU of `PRE_NORM_TARGET_LUFS_I`.

**Files changed:**
- `config/pipewire/hapax-music-loudnorm.conf` (rewritten)
- `config/pipewire/hapax-pc-loudnorm.conf` (rewritten)
- `config/pipewire/hapax-loudnorm-capture.conf` (rewritten)
- `config/pipewire/hapax-yt-loudnorm.conf` (rewritten)

**Acceptance criteria:**
- For each source: `audio-measure.sh` integrated LUFS = `PRE_NORM_TARGET_LUFS_I` ± 1.0 LU.
- For each source: TP ≤ `PRE_NORM_TRUE_PEAK_DBTP` + 0.5 dB (no per-source overshoot).
- Master sum: still in [−16, −12] LUFS-I, TP ≤ −0.5 dBTP.
- No drum-pumping audible on a kick-heavy lo-fi passage (operator subjective + `audio-measure.sh` short-term LUFS-S range ≤ 4 LU on a 30 s window of stable music).

**Rollback:** `git revert` of each conf, restart PipeWire. Restores prior chain.

**Time estimate:** 4 hours.

---

## Phase 4 — Sidechain ducking (operator-VAD + TTS-active)

**Risk:** Replaces three competing ducking implementations with one canonical one. May initially over-duck or under-duck; constants in `shared/audio_loudness.py` are tunable.

**Scope:**
1. Add `config/pipewire/hapax-broadcast-duck.conf` — two `lsp-plugins.lv2 Sidechain Compressor` instances on the master bus pre-limiter:
   - Comp A: trigger = `hapax-pn-tts.monitor` (envelope detection on the TTS chain output, no Python publisher coupling). Duck depth = `DUCK_DEPTH_TTS_DB`. Attack/release = `DUCK_ATTACK_MS` / `DUCK_RELEASE_MS`.
   - Comp B: trigger = `mixer_master` source (the L-12 AUX12 master capture, which contains the operator Rode mic pre-broadcast). Duck depth = `DUCK_DEPTH_OPERATOR_VOICE_DB`.
   - Both ducks act on the music + non-voice sources only (sidechain destination = `hapax-broadcast-master` minus voice/TTS sources).
2. Add `scripts/test-ducking.sh` — synthetic stimulus harness: plays a 30 s sine on the music path, then triggers a 5 s burst on the trigger source, then verifies the music path's RMS dropped by `DUCK_DEPTH_*_DB` ± 1 dB during the trigger window.
3. Operator listens to a representative segment with TTS firing over music + voice firing over music; confirms duck timing feels natural (no pumping, no missed ducks, no consent-latency degradation).

**Files changed:**
- `config/pipewire/hapax-broadcast-duck.conf` (new)
- `scripts/test-ducking.sh` (new)

**Acceptance criteria:**
- `scripts/test-ducking.sh` reports both A and B ducks within ±1 dB of target depth.
- Voice latency unchanged (consent-flow invariant — tested via existing voice-latency benchmark).
- No new pumping artifacts on a kick-heavy passage (operator subjective + LUFS-S range ≤ 4 LU).

**Rollback:** `git revert` of the duck conf; restart PipeWire. WP role-based duck (legacy) takes over again.

**Time estimate:** 3 hours.

---

## Phase 5 — Retire `audio_ducking.py` + ducked sinks

**Risk:** Low. Phase 4's sidechain ducker subsumes everything `audio_ducking.py` does. Operator confirmed 2026-04-23.

**Scope:**
1. Delete `agents/studio_compositor/audio_ducking.py`.
2. Delete `config/pipewire/hapax-ytube-ducked.conf`, `config/pipewire/hapax-24c-ducked.conf`.
3. Remove `HAPAX_AUDIO_DUCKING_ACTIVE` env-flag handling.
4. Delete `agents/studio_compositor/vad_state_publisher.py` (dead code per `2026-04-22-vad-ducking-pipeline-dead-finding.md`).
5. Delete `config/pipewire/hapax-livestream-duck.conf` (deployed but idle per surprise #3 from research doc).
6. Remove imports + tests; leave a single deprecation note in CHANGELOG.
7. Verify Phase 4 ducker still passes acceptance.

**Files changed:**
- `agents/studio_compositor/audio_ducking.py` (deleted)
- `agents/studio_compositor/vad_state_publisher.py` (deleted)
- `config/pipewire/hapax-{ytube,24c,livestream}-duck.conf` (deleted)
- `tests/studio_compositor/test_audio_ducking*.py` (deleted)

**Acceptance criteria:**
- Phase 4 acceptance still passes.
- `grep -r 'audio_ducking\|vad_state_publisher\|HAPAX_AUDIO_DUCKING_ACTIVE' agents/ config/ scripts/` returns 0 hits (except CHANGELOG).

**Rollback:** `git revert` restores the dead code. (Trivial, since we're confident Phase 4 covers it.)

**Time estimate:** 1 hour.

---

## Phase 6 — Routing-as-code (`config/audio-routing.yaml` + generator)

**Risk:** Medium. Introduces the declarative SSOT and the generator. From this point forward, hand-edits to PipeWire confs are a regression.

**Scope:**
1. Define the YAML schema (per spec §5).
2. Build `config/audio-routing.yaml` reflecting the current post-Phase-5 topology.
3. Build `scripts/generate-pipewire-audio-confs.py`:
   - reads `audio-routing.yaml` + `shared/audio_loudness.py`
   - emits PipeWire confs to `config/pipewire/generated/`
   - `--apply` writes them into `~/.config/pipewire/pipewire.conf.d/` and triggers `systemctl --user reload pipewire`
   - `--dry-run` diffs against current state
4. Build `hapax-audio-route` CLI (operator-facing convenience):
   - `hapax-audio-route list` — show current sources + routing
   - `hapax-audio-route set <source> wet|dry` — flip routing in YAML + apply
   - `hapax-audio-route ducked-by <source> <triggers...>` — edit duck list + apply
5. Add `tests/scripts/test_generate_audio_confs.py` — golden-file regression on the generator.
6. Move existing hand-edited confs (`hapax-broadcast-master.conf`, `hapax-music-loudnorm.conf`, etc.) under `config/pipewire/generated/`. Delete the old hand-edited ones; they're now generated.
7. Operator can now flip a source `wet → dry` without touching PipeWire confs.

**Files changed:**
- `config/audio-routing.yaml` (new)
- `scripts/generate-pipewire-audio-confs.py` (new)
- `scripts/hapax-audio-route` (new CLI)
- `config/pipewire/generated/*.conf` (moved)
- `config/pipewire/*.conf` (deleted, now generated)
- `tests/scripts/test_generate_audio_confs.py` (new)

**Acceptance criteria:**
- `scripts/generate-pipewire-audio-confs.py --dry-run` shows zero diff against current confs (round-trip is identity).
- `hapax-audio-route set music dry` → music bypasses Evil Pet → LUFS still hits target → operator confirms music sounds right (dry).
- `hapax-audio-route set music wet` → music is back through Evil Pet → operator confirms.
- `pytest tests/scripts/test_generate_audio_confs.py` green.

**Rollback:** Generator can emit the pre-Phase-6 confs by reverting the YAML.

**Time estimate:** 6 hours.

---

## Phase 7 — Loudness telemetry (libebur128 → Prometheus)

**Risk:** Low. Pure observability addition.

**Scope:**
1. Build `agents/audio_metering/__main__.py`:
   - subscribes to LV2 notification ports (or taps `.monitor` of each pre-norm + master via `pw-cat`)
   - feeds samples to `libebur128` (Python binding `pyloudnorm` or direct C library)
   - exports `audio_lufs_i{stage="<name>"}`, `audio_lufs_s{stage="<name>"}`, `audio_lufs_m{stage="<name>"}`, `audio_dbtp{stage="<name>"}`, `audio_lra{stage="<name>"}` to Prometheus on `:9483`
2. systemd user service: `hapax-audio-metering.service` (always-on, low CPU).
3. Grafana dashboard: `hapax-audio` — per-stage I/M/S/TP/LRA over time, master-bus headroom, alert thresholds (TP > −0.5 dBTP for 5+ s = yellow; TP > −0.1 dBTP = red).
4. Alert rules: prometheus alert `AudioMasterClippingRisk` when master TP > −0.5 dBTP for 5+ s in the last minute.
5. `hapax-audio-route status` (CLI, Phase 6 extension) reads from Prometheus and prints current LUFS/TP per stage.

**Files changed:**
- `agents/audio_metering/__init__.py`, `__main__.py` (new package)
- `systemd/units/hapax-audio-metering.service` (new)
- `config/grafana/dashboards/hapax-audio.json` (new)
- `config/prometheus/rules/hapax-audio.yml` (new)
- `scripts/hapax-audio-route` (extended with `status`)

**Acceptance criteria:**
- Prometheus query `audio_lufs_i{stage="master"}` returns a value within ±1 LU of `EGRESS_TARGET_LUFS_I` over a 60 s window of representative content.
- Grafana dashboard renders all stages with live updates.
- A synthetic over-loud injection (1 kHz at 0 dBFS for 2 s through the music path) fires the `AudioMasterClippingRisk` alert.

**Rollback:** Disable the metering service; nothing in the audio path depends on it.

**Time estimate:** 4 hours.

---

## Phase 8 — Regression harness (synthetic stimulus tests)

**Risk:** Low. Pure CI / dev-tooling addition. Prevents future Claude sessions from regressing the dynamics by editing a constant.

**Scope:**
1. `tests/audio/test_loudness_regression.py`:
   - Spawns a `pw-cat` synthetic stimulus (sine, kick, voice clip) through each source pre-norm.
   - Captures master output via `pw-cat --record` + `ffmpeg ebur128`.
   - Asserts integrated LUFS, TP, LRA against `shared/audio_loudness.py` constants.
2. `tests/audio/test_ducking_regression.py`:
   - Plays music + triggers operator-VAD + TTS-active stimuli.
   - Asserts duck depths match `DUCK_DEPTH_*_DB` ± 1 dB.
3. CI integration: `audio-regression` job in `.github/workflows/audio-regression.yml`, runs on changes to `config/pipewire/`, `config/audio-routing.yaml`, `shared/audio_loudness.py`, `scripts/generate-pipewire-audio-confs.py`. (Job needs a runner with PipeWire — investigate if this is feasible in CI; otherwise local-pre-merge only via a `make audio-regress` target.)
4. `docs/governance/audio-architecture-handoff.md` updated with: "before changing any audio constant, run `make audio-regress` locally; on merge CI re-validates."

**Files changed:**
- `tests/audio/__init__.py`, `test_loudness_regression.py`, `test_ducking_regression.py` (new)
- `.github/workflows/audio-regression.yml` (new, if CI feasibility)
- `Makefile` audio-regress target (new)
- `docs/governance/audio-architecture-handoff.md` (updated)

**Acceptance criteria:**
- All regression tests pass locally on a known-good system.
- CI either runs them or fails informatively (with a clear "run locally and paste output" instruction) until CI runner gains PipeWire.

**Rollback:** Trivial; tests are isolated.

**Time estimate:** 4 hours.

---

## Total time budget

~24 hours of focused implementation across phases. Phase 1 is the only one needing operator-at-rig; subsequent phases ship hands-off.

## Dependencies + ordering

Phase 1 → 2 (must have safety net before relying on PW restart resilience).
Phase 2 → 3+ (don't ship per-source replacements until OBS survives PW restart).
Phase 3 → 4 (sidechain duck targets the new pre-normalized sum).
Phase 4 → 5 (don't retire old ducker until new one is proven).
Phase 5 → 6 (clean state before introducing the SSOT generator).
Phase 6 → 7 (routing config drives metering scope).
Phase 7 → 8 (regression tests assert against live metering).

Each phase is a single PR (or small bundle), each independently revertable, each gated on its acceptance criteria.

## Phase 1 — kicking off NOW

Operator is present (2026-04-23, ~02:00 UTC). Starting Phase 1 implementation in the next commit.
