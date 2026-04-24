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
# Two and only two ducking triggers exist in the unified system:
#   - operator_voice : sidechain on `mixer_master` (L-12 AUX12)
#   - tts            : sidechain on `hapax-pn-tts.monitor`
# Each ducks the music + non-voice sources at the depth below.
DUCK_DEPTH_OPERATOR_VOICE_DB: float = -12.0
DUCK_DEPTH_TTS_DB: float = -8.0
DUCK_ATTACK_MS: float = 10.0
DUCK_RELEASE_MS: float = 400.0
DUCK_LOOKAHEAD_MS: float = 5.0

# ── Master safety-net limiter (Phase 1) ───────────────────────────────
#
# fast_lookahead_limiter_1913 has a built-in 5 ms lookahead. We expose
# the release time here for tunability. 50 ms = quick recovery on
# transient catches without audible pumping on sustained content.
MASTER_LIMITER_LOOKAHEAD_MS: float = 5.0
MASTER_LIMITER_RELEASE_MS: float = 50.0

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
