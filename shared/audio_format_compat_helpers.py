"""Audio format/rate compatibility helpers (cc-task jr-broadcast-chain-integration-tier1-rate-format Phase 0).

Tier-1 of the broadcast-chain integration test matrix: an isolated test that
verifies no silent drops at format-negotiation time. Targets the regression
class behind PR #2228 (silent drop in the music-loudnorm → music-duck path
when the input format diverged from the chain's expectation).

Phase 0 (this module): pure-Python helpers + assertion machinery. No
PipeWire daemon, no actual subprocess; everything is bytes-level math
on int16 / float32 arrays. Phase 1 ships the pytest fixture that
spawns ephemeral PipeWire null sinks and pushes the synthesised signal
through the live chain.

Why factor it this way:
- The math (RMS dBFS, sine generation, format conversion) is testable
  standalone with deterministic numerical assertions. Pinning it once
  here means Phase 1 can swap the *signal source* (ephemeral PipeWire
  vs sandboxed graph vs live capture) without re-deriving the
  measurement contract.
- Assertion helpers (``assert_rms_within_attenuation``,
  ``assert_resample_did_not_silence``) are the consumer-facing API the
  Phase 1 fixture calls; pinning them now means a future fixture
  implementation can't quietly drift on the comparison semantics.
- Pure-stdlib pattern (no numpy / no scipy) per the project's
  bare-implementation convention from the broadcast-audio-health
  module + the receive-only rails.
"""

from __future__ import annotations

import array
import math
from typing import Final

#: Canonical broadcast sample rate. The L-12 / Studio 24c chain runs
#: at 48000 Hz; any source at 44.1k must be resampled before reaching
#: the chain.
DEFAULT_SAMPLE_RATE_HZ: Final[int] = 48000

#: Canonical broadcast bit depth: int16 is the L-12 line-driver native
#: format. Some upstream graphs run at f32; conversion happens in the
#: PipeWire negotiation layer.
DEFAULT_BIT_DEPTH: Final[int] = 16


def generate_sine_int16(
    frequency_hz: float,
    duration_s: float,
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
    *,
    amplitude: float = 0.5,
) -> bytes:
    """Generate a constant-amplitude sine tone as int16 little-endian PCM bytes.

    ``amplitude`` is in [0.0, 1.0] (1.0 = full-scale int16 = ±32767).
    The 0.5 default produces a -6 dBFS tone, comfortably below clipping
    and well above the silence floor (-55 dBFS per
    ``BroadcastAudioHealthThresholds.rms_dbfs_floor``).

    Pure stdlib; no numpy. Uses ``array.array("h")`` for fast int16
    conversion.
    """
    if frequency_hz <= 0:
        raise ValueError(f"frequency_hz must be > 0, got {frequency_hz}")
    if duration_s <= 0:
        raise ValueError(f"duration_s must be > 0, got {duration_s}")
    if sample_rate_hz <= 0:
        raise ValueError(f"sample_rate_hz must be > 0, got {sample_rate_hz}")
    if not 0.0 <= amplitude <= 1.0:
        raise ValueError(f"amplitude must be in [0.0, 1.0], got {amplitude}")

    n_samples = int(duration_s * sample_rate_hz)
    samples = array.array("h")
    omega = 2.0 * math.pi * frequency_hz / sample_rate_hz
    peak = int(amplitude * 32767)
    for n in range(n_samples):
        samples.append(int(peak * math.sin(omega * n)))
    return samples.tobytes()


def rms_dbfs_int16(pcm: bytes) -> float:
    """Compute RMS dBFS of int16 little-endian PCM bytes.

    Returns ``-inf`` for an empty buffer (no signal). Returns the value
    rounded to floating-point precision otherwise. Math:

        rms_lin = sqrt(mean(s^2)) / 32767
        rms_dbfs = 20 * log10(rms_lin)

    Matches the existing ``shared.audio_loudness`` RMS conventions plus
    the ``EgressLoopbackWitness.rms_dbfs`` semantics.
    """
    if not pcm:
        return float("-inf")
    samples = array.array("h")
    samples.frombytes(pcm)
    if not samples:
        return float("-inf")
    mean_sq = sum(s * s for s in samples) / len(samples)
    if mean_sq <= 0:
        return float("-inf")
    rms_lin = math.sqrt(mean_sq) / 32767.0
    if rms_lin <= 0:
        return float("-inf")
    return 20.0 * math.log10(rms_lin)


def int16_to_float32(pcm_int16: bytes) -> bytes:
    """Convert int16-LE PCM to float32-LE PCM.

    Each sample maps via ``s_f32 = s_i16 / 32768.0`` (asymmetric float
    range matches the int16 range; the standard convention used by
    PipeWire's format converter).

    Pure stdlib; no numpy. Uses two ``array.array`` views.
    """
    samples = array.array("h")
    samples.frombytes(pcm_int16)
    floats = array.array("f")
    for s in samples:
        floats.append(s / 32768.0)
    return floats.tobytes()


def float32_to_int16(pcm_float32: bytes) -> bytes:
    """Convert float32-LE PCM back to int16-LE PCM.

    Each sample maps via ``s_i16 = round(s_f32 * 32767)``, clamped to
    int16 range. Symmetric inverse of ``int16_to_float32`` modulo
    quantisation noise.
    """
    floats = array.array("f")
    floats.frombytes(pcm_float32)
    samples = array.array("h")
    for f in floats:
        # Clamp to [-1.0, 1.0] before scaling to handle out-of-range
        # float values from non-conformant producers.
        clamped = max(-1.0, min(1.0, f))
        samples.append(int(round(clamped * 32767)))
    return samples.tobytes()


def linear_resample_int16(
    pcm_int16: bytes,
    from_rate_hz: int,
    to_rate_hz: int,
) -> bytes:
    """Linear-interpolation resample of int16-LE PCM.

    Cheap nearest/linear interpolation — sufficient for the test harness
    (which only validates that resampling produced ≠ silence and that the
    RMS shifted by the expected attenuation envelope). Phase 1 uses
    PipeWire's native resampler; this helper exists for the bytes-only
    Phase 0 contract tests.

    Pure stdlib.
    """
    if from_rate_hz <= 0 or to_rate_hz <= 0:
        raise ValueError(f"sample rates must be > 0; got from={from_rate_hz}, to={to_rate_hz}")

    src = array.array("h")
    src.frombytes(pcm_int16)
    if from_rate_hz == to_rate_hz:
        return src.tobytes()

    n_src = len(src)
    if n_src == 0:
        return b""

    n_dst = int(n_src * to_rate_hz / from_rate_hz)
    dst = array.array("h")
    ratio = from_rate_hz / to_rate_hz

    for i in range(n_dst):
        src_pos = i * ratio
        src_idx = int(src_pos)
        frac = src_pos - src_idx
        if src_idx + 1 < n_src:
            interp = src[src_idx] * (1.0 - frac) + src[src_idx + 1] * frac
        elif src_idx < n_src:
            interp = float(src[src_idx])
        else:
            interp = 0.0
        dst.append(int(round(interp)))

    return dst.tobytes()


# Silence floor matches BroadcastAudioHealthThresholds.rms_dbfs_floor
# in shared.broadcast_audio_health. A resample that produces silence
# instead of resampling-with-loss is the audit #2228 regression.
SILENCE_FLOOR_DBFS: Final[float] = -55.0


def assert_rms_within_attenuation(
    *,
    input_pcm: bytes,
    output_pcm: bytes,
    declared_attenuation_db: float,
    tolerance_db: float = 1.0,
) -> None:
    """Assert that ``output_pcm`` RMS is within ±tolerance of input - attenuation.

    Audit acceptance: "output RMS dBFS at the chain endpoint is within ±1
    dB of input minus declared chain attenuation."

    Phase 1 fixture calls this after pushing the test tone through the
    real chain. Phase 0 tests exercise the helper directly with synthetic
    int16 buffers.
    """
    in_rms = rms_dbfs_int16(input_pcm)
    out_rms = rms_dbfs_int16(output_pcm)

    if math.isinf(in_rms) and in_rms < 0:
        raise AssertionError("input was silent; cannot validate attenuation")

    expected = in_rms - declared_attenuation_db
    delta = abs(out_rms - expected)
    if delta > tolerance_db:
        raise AssertionError(
            f"output RMS {out_rms:.2f} dBFS not within ±{tolerance_db} dB of "
            f"expected {expected:.2f} dBFS (input {in_rms:.2f} - "
            f"attenuation {declared_attenuation_db} dB); delta={delta:.2f}"
        )


def assert_resample_did_not_silence(
    *,
    input_pcm: bytes,
    output_pcm: bytes,
    silence_floor_dbfs: float = SILENCE_FLOOR_DBFS,
) -> None:
    """Assert that a rate-mismatch resample produced output above silence floor.

    Audit acceptance: "input at 44.1k, chain expects 48k — assert
    resampling happens (not silence)."

    Catches the audit #2228 regression: when format negotiation fails,
    PipeWire silently drops samples instead of resampling. The output
    RMS falls below the silence floor.
    """
    in_rms = rms_dbfs_int16(input_pcm)
    if math.isinf(in_rms) and in_rms < 0:
        raise AssertionError("input was silent; cannot validate resample")

    out_rms = rms_dbfs_int16(output_pcm)
    if math.isinf(out_rms) and out_rms < 0:
        raise AssertionError(
            "resample produced silence (output RMS = -inf dBFS); audit #2228 regression"
        )
    if out_rms < silence_floor_dbfs:
        raise AssertionError(
            f"resample produced near-silence: output RMS {out_rms:.2f} dBFS < "
            f"floor {silence_floor_dbfs} dBFS; audit #2228 regression class"
        )


def assert_format_conversion_did_not_silence(
    *,
    input_pcm: bytes,
    output_pcm: bytes,
    silence_floor_dbfs: float = SILENCE_FLOOR_DBFS,
) -> None:
    """Assert that a format-mismatch conversion produced output above silence floor.

    Audit acceptance: "input s16le, chain expects f32le — assert
    conversion happens."

    Same regression class as resample-silence: format negotiation failure
    drops samples instead of converting.
    """
    in_rms = rms_dbfs_int16(input_pcm)
    if math.isinf(in_rms) and in_rms < 0:
        raise AssertionError("input was silent; cannot validate format conversion")

    out_rms = rms_dbfs_int16(output_pcm)
    if math.isinf(out_rms) and out_rms < 0:
        raise AssertionError(
            "format conversion produced silence (output RMS = -inf dBFS); audit #2228 regression"
        )
    if out_rms < silence_floor_dbfs:
        raise AssertionError(
            f"format conversion produced near-silence: output RMS {out_rms:.2f} dBFS < "
            f"floor {silence_floor_dbfs} dBFS; audit #2228 regression class"
        )
