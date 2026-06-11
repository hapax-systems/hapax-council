"""Single source of truth for every loudness / dynamics constant in the
livestream broadcast audio chain.

Operator directive 2026-04-23:
    "I never want to worry about [audio levels] again."

Implementation rule: NEVER hand-tune a sc4m threshold, a hard_limiter
ceiling, or a sidechain depth outside this module. Change the constant
here and re-run the PipeWire conf generator (Phase 6 will automate this;
during Phase 1-5 the PipeWire confs mirror these constants by hand and
the comments inside each `.conf` cite the constant name).

Spec:    docs/superpowers/specs/2026-04-23-livestream-audio-unified-architecture-design.md
Plan:    docs/superpowers/plans/2026-04-23-livestream-audio-unified-architecture-plan.md
Research: docs/research/2026-04-23-livestream-audio-unified-architecture.md

Units:
    LUFS-I  : EBU R128 / ITU-R BS.1770-4 integrated loudness
    LUFS-S  : short-term (3 s window) loudness
    LUFS-M  : momentary (400 ms window) loudness
    dBTP    : decibels true-peak (inter-sample peak detection)
    dB      : sample-peak / signal-level decibels
    LU      : loudness units (relative)
    LRA     : loudness range (LU between 95th and 10th percentile)
"""

from __future__ import annotations

# ── Egress (broadcast bus → OBS → YouTube) ─────────────────────────────
#
# YouTube normalizes streams to roughly -14 LUFS-I; landing at this
# target keeps our broadcast at the platform ceiling without YouTube
# pulling level on us. Operator confirmed YouTube-aligned target on
# 2026-04-23 ("recommended").
EGRESS_TARGET_LUFS_I: float = -14.0

# True-peak ceiling on the master limiter. -1.0 dBTP is the EBU R128
# recommendation and YouTube's enforced ceiling. We use it as a
# brick-wall safety net, not as a primary loudness control.
EGRESS_TRUE_PEAK_DBTP: float = -1.0

# Loudness range cap. Broadcast-friendly LRA keeps quiet/loud passages
# within a tolerable spread for headphone + speaker listeners both.
EGRESS_LRA_MAX_LU: float = 11.0

# ── Per-source pre-normalization (Phase 3) ────────────────────────────
#
# Every source pre-normalizes to this target BEFORE entering the routing
# matrix and the master bus. Sources arrive at the master already
# loudness-shaped; the master limiter's job is then purely to catch peak
# overshoots from the simultaneous sum.
PRE_NORM_TARGET_LUFS_I: float = -18.0
PRE_NORM_TRUE_PEAK_DBTP: float = -1.0
PRE_NORM_LRA_MAX_LU: float = 7.0

# ── Sidechain ducking depths (Phase 4) ────────────────────────────────
#
# Two and only two ducking triggers exist in the unified system
# (mk5/S-4 baseline; rebuild design §ducking):
#   - operator_voice : PRE-WET mk5 Rode sidechain (`hapax-mic-rode-capture`,
#                      capture_AUX0 — the dry mic, never the S-4 wet return)
#   - tts            : broadcast TTS chain monitor (`hapax-loudnorm-capture`)
# Each ducks the music + non-voice sources at the depth below. Concurrent
# triggers compose in dB domain (shared/audio_duck_compose.py), never as
# min()/max() of linear gains.
DUCK_DEPTH_OPERATOR_VOICE_DB: float = -12.0
DUCK_DEPTH_TTS_DB: float = -8.0
DUCK_ATTACK_MS: float = 10.0
DUCK_RELEASE_MS: float = 400.0
DUCK_LOOKAHEAD_MS: float = 5.0

# Duck-handoff release hysteresis (voice-p2-duck-handoff, interview bar
# "no pumping under rapid turn alternation"). When the composed duck
# target rises toward unity, the deeper value HOLDS for this window
# before the release ramp may begin; deepening is always immediate.
# Derivation: rapid conversational turn gaps run ~200-500 ms. The VAD
# hold-open (200 ms, agents/audio_ducker) bridges intra-source syllable
# gaps; this window stacks on top of it, so the bed only starts
# releasing ~600 ms after true end-of-speech — beyond any rapid-
# alternation gap — and full recovery lands ~1 s out (+DUCK_RELEASE_MS).
# Matching DUCK_RELEASE_MS keeps one perceptual time constant for "the
# conversation is over".
DUCK_HANDOFF_HOLD_MS: float = 400.0

# ── Master safety-net limiter (Phase 1) ───────────────────────────────
#
# fast_lookahead_limiter_1913 has a built-in 5 ms lookahead. We expose
# the release time here for tunability. 50 ms = quick recovery on
# transient catches without audible pumping on sustained content.
MASTER_LIMITER_LOOKAHEAD_MS: float = 5.0
MASTER_LIMITER_RELEASE_MS: float = 50.0

# Master input makeup gain (Phase 1.5 calibration, corrected 2026-05-10).
#
# Closes the egress-loudness gap at the public broadcast source
# (`hapax-broadcast-normalized`). The earlier 2026-05-02 audit measured
# -27.9 LUFS-I and justified +14 dB makeup, but the installed runtime had
# drifted back to +8 dB and the measurement script was sampling
# `hapax-broadcast-normalized.monitor` instead of the source OBS consumes. A
# first reboot-recovery pass tried +19 dB against a short quiet window, but a
# follow-up hot passage measured -9.1 LUFS-I and -0.1 dBTP, proving that +19
# made the master limiter carry programme loudness instead of acting as a
# safety net. The operational correction to +16 dB keeps the observed hot
# passage just inside the health band without relying on the peak limiter for
# routine level management. Phase 3 per-source pre-normalizers should replace
# this single master-makeup constant.
#
# Prior calibration narrative (subjective, music-alone, 2026-04-23):
# - +19 dB landed music alone at -15 LUFS-I → too hot (sums with voice/TTS
#   would push above target)
# - +14 dB landed music alone at -20 LUFS-I → still 5 dB too hot
#   subjectively
# - +9 dB lands music alone at -25 LUFS-I → operator confirmed "perfect"
#   under the music-duck stereo-split + FL/FR→RL/RR remap topology
# Those music-alone notes were not a public-egress calibration. They remain
# useful context, but broadcast safety follows the measured public source.
MASTER_INPUT_MAKEUP_DB: float = 16.0

# ── Per-source line-output ceiling for L-12 USB return (Phase 1.5) ────
#
# Music chain output ceiling so signal lands at L-12 LINE input + fader
# unity without clipping the channel preamp or driving Evil Pet into
# nonlinear range. -18 dBFS clean (true lookahead limiter, not sample
# clipper) maps to ~+4 dBu line-level reference at L-12.
# Operator confirmed L-12 channel meter at -18 dB with no audible
# distortion 2026-04-23 (after replacing hard_limiter_1413 sample-clipper
# with fast_lookahead_limiter_1913 true-peak limiter).
MUSIC_TO_L12_PEAK_DBFS: float = -18.0
MUSIC_LIMITER_RELEASE_MS: float = 200.0

# ── PC monitor and broadcast paths — QUARANTINED ──────
# Formerly Phase 3 PC volume isolation. Conf removed; topology nodes
# quarantined. Reactivation requires a new AuthorityCase.
# Constants retained for reference only — not consumed by any active path.
PC_MONITOR_TARGET_LUFS_I: float = -14.0
PC_MONITOR_TRUE_PEAK_DBTP: float = -1.0
PC_BROADCAST_TARGET_LUFS_I: float = -18.0
PC_BROADCAST_TRUE_PEAK_DBFS: float = -18.0
PC_BROADCAST_LIMITER_RELEASE_MS: float = 200.0

# NOTE (2026-05-02): the WET_PATH_USB_BIAS_* constants previously declared
# here have been removed. They encoded a +27 dB line-driver bias that the
# fast_lookahead_limiter_1913 LADSPA plugin silently rejected as out of
# range (its accepted Input gain (dB) range is [-20, +20]) — see audit B#4.
# The line-driver branch architecture has been superseded by the Evil Pet
# wet-only signal flow, with master-bus makeup now carrying the
# loudness-target compensation (see MASTER_INPUT_MAKEUP_DB above).

# ── Closed master LUFS-I loop (segment-audio-remainder AC#2) ──────────
#
# A SLOW, bounded controller nudges the broadcast master makeup toward
# EGRESS_TARGET_LUFS_I, measured as integrated LUFS-I on the public
# source `hapax-broadcast-normalized`. It replaces RELIANCE on the
# open-loop MASTER_INPUT_MAKEUP_DB while keeping that static makeup as
# the never-remove fallback (the controller is dark by default and only
# trims within a bounded band around it).
#
# Time-constant separation from the duck (DUCK_ATTACK_MS=10 /
# DUCK_RELEASE_MS=400) is the load-bearing invariant: the loop integrates
# over tens of seconds and nudges only every several seconds, ≥10× slower
# than the duck's release, and freezes entirely while the bus is ducked —
# so the slow makeup loop can never chase the fast duck up.
MASTER_LUFS_INTEGRATION_WINDOW_S: float = 30.0
MASTER_LUFS_UPDATE_INTERVAL_S: float = 8.0
MASTER_LUFS_MAX_STEP_DB: float = 0.5
# Makeup may trim ±this band around MASTER_INPUT_MAKEUP_DB. 16 ± 3 = [13, 19],
# inside the LADSPA fast_lookahead_limiter accepted range [-20, +20].
MASTER_LUFS_MAKEUP_BAND_DB: float = 3.0

# ── Headroom budget ───────────────────────────────────────────────────
#
# Reserved per stage for transients. Means: each stage's nominal output
# sits 6 dB below the next stage's clip point. Catches inter-stage
# signal-summing surprises without the master limiter having to work.
HEADROOM_PER_STAGE_DB: float = 6.0

# ── Synthetic-stimulus regression tolerances (Phase 8) ────────────────
#
# Acceptance criteria: integrated LUFS within ±LUFS_TOLERANCE_LU of
# target on a known-content reference clip. Tighter than typical
# broadcaster tolerance (±1 LU) to catch generator drift.
LUFS_TOLERANCE_LU: float = 1.0
TRUE_PEAK_TOLERANCE_DBTP: float = 0.5
DUCK_DEPTH_TOLERANCE_DB: float = 1.0
