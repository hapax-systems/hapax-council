"""Bayesian music-playing engine — pure-audio evidence on broadcast L-12.

Phase 2b of the AUDIT-07 hallucination structural fix (companion to
``vinyl_spinning_engine.py`` shipped Phase 2 in #1431). Where
VinylSpinningEngine fuses indirect-evidence signals (operator override,
cover-fresh AND hand-on-turntable conjunction) into a posterior on
"is the platter physically spinning," MusicPlayingEngine reads the
**broadcast L-12 audio bus directly** via PANNs (AudioSet ontology
classifier — same 527-class space as YAMNet) and produces a posterior
on "is music currently being heard by the audience."

## Why pure-audio evidence

The third hallucination axis the operator reported (audio-silent +
cover-fresh + hand-recent → still claims music) needs a signal that
is **structurally decoupled from upstream perception**. The album-
identifier pipeline (gemini-flash IR overhead → ALBUM_STATE_FILE)
and the IR perception pipeline (Pi-6 NoIR → perception-state.json)
both run on visual evidence; they cannot answer "is sound actually
audible right now." YAMNet/PANNs on the broadcast bus answers exactly
that — the audio reaching the audience is the ground truth for
"music is playing."

L-12 is the broadcast bus invariant per ``feedback_l12_equals_livestream_invariant``:
anything reaching L-12 IS what the audience hears. Tapping its
PipeWire monitor (``hapax-livestream-tap.monitor`` or
``hapax-livestream.monitor``) gives the canonical audio-evidence
ground truth.

## Signals

Single signal — pure-audio classification — to keep this engine
structurally orthogonal to VinylSpinningEngine. The director loop
composes the two posteriors at the consumer side (per AUDIT-07):
``MusicPlayingEngine.posterior`` answers "music is in the broadcast";
``VinylSpinningEngine.posterior`` answers "vinyl is the source."
Both can be true (vinyl playing audibly), one can be true without
the other (curated YouTube queue music = MusicPlaying without
VinylSpinning), or neither (silent dead-air or operator narration
only).

- ``yamnet_music_present``: PANNs/YAMNet posterior over music-class
  AudioSet labels exceeds threshold (default 0.45). Captured from
  the broadcast L-12 PipeWire monitor over a 3.0-second window.
  Strong positive (LR 0.92/0.08) — music in the audio is direct
  evidence of music playing; absence is direct evidence of silence
  or speech-only.

## Temporal profile (asymmetric — slow-enter / fast-exit)

Mirrors VinylSpinningEngine's profile but with looser thresholds
since the audio-evidence signal is much stronger:

- enter_threshold: 0.65 (audio is direct evidence; lower bar)
- exit_threshold: 0.35
- k_enter: 3 ticks (faster entry — audio responds quickly)
- k_exit: 2 ticks (fast retraction)
- decay_rate: 0.10 (faster than vinyl since audio cycles faster)

## Public API

::

    engine = MusicPlayingEngine()
    engine.tick()          # capture audio + classify + update posterior
    engine.posterior       # 0..1 calibrated probability
    engine.is_playing      # bool — True iff state == ASSERTED
    engine.state           # "ASSERTED" | "UNCERTAIN" | "RETRACTED"

## Bypass

When ``HAPAX_BAYESIAN_BYPASS=1`` is set, the underlying ``ClaimEngine``
``update`` is a no-op — posterior pinned to prior, state pinned to
UNCERTAIN. Combined with caller-side fallbacks at the music-framing
branch, this is the rollback knob for the entire MusicPlayingEngine
audio-evidence layer.

## Performance

PANNs CPU classification is ~2ms per call. The 3-second audio
capture is the dominant latency; consumers should not call ``tick()``
faster than ~1Hz. Scheduled at the daimonion perception cadence
(~5s) is comfortable; faster cadence requires a streaming audio
buffer (deferred — see Phase 2b.2 spec).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from shared.claim import (
    Claim,
    ClaimEngine,
    InferenceBroker,
    LRDerivation,
    TemporalProfile,
)

if TYPE_CHECKING:
    import numpy as np

log = logging.getLogger(__name__)

# ── Audio capture configuration ─────────────────────────────────────────

# PipeWire node name for the broadcast L-12 monitor. The "hapax-livestream-tap"
# node is a dedicated monitor sink; falls back to the main "hapax-livestream"
# node's monitor if the tap isn't present.
BROADCAST_L12_PIPEWIRE_NODE = "hapax-livestream-tap"
BROADCAST_L12_FALLBACK_NODE = "hapax-livestream"

# 3-second windows are the AudioSet/YAMNet/PANNs canonical input length.
CAPTURE_DURATION_S = 3.0

# Music posterior threshold — sum of music-class probabilities > this →
# yamnet_music_present=True. Calibrated against PANNs output range:
# silence/speech sessions tend to score < 0.20, music sessions > 0.60.
# 0.45 is a balanced cut for the bias-toward-no-evidence posture.
MUSIC_POSTERIOR_THRESHOLD = 0.45


# ── Signal LR weights (registered in shared/lr_registry.yaml) ───────────


def _default_signal_weights() -> dict[str, LRDerivation]:
    """Build the LRDerivation dict the engine consumes.

    Single signal — yamnet_music_present — keeps this engine
    structurally orthogonal to VinylSpinningEngine. Composition at
    the consumer side (director_loop._curated_music_framing) reads
    both engines' posteriors and decides the framing accordingly.
    """
    return {
        "yamnet_music_present": LRDerivation(
            signal_name="yamnet_music_present",
            claim_name="music_playing",
            source_category="calibrated_classifier",
            p_true_given_h1=0.92,
            p_true_given_h0=0.08,
            positive_only=False,
            estimation_reference=(
                "PANNs (CNN14, AudioSet 527-class) classification on "
                "3-second window from broadcast L-12 PipeWire monitor "
                "(hapax-livestream-tap.monitor); music-class posteriors "
                "summed (Music + Musical instrument + genre subclasses) "
                "with threshold 0.45 mapping to True/False. AudioSet "
                "ontology calibration baseline 2026-03-17 first-live-run "
                "+ Phase 2b Y-AUDIT-07 audio-evidence layer rationale. "
                "Bidirectional (positive_only=False) because audio "
                "absence IS direct evidence of music absence — distinct "
                "from cover/hand signals where absence is ambiguous."
            ),
            calibration_window_s=3.0,
        ),
    }


# ── Temporal profile (asymmetric — fast-enter, fast-exit on audio) ──────

DEFAULT_PROFILE = TemporalProfile(
    enter_threshold=0.65,
    exit_threshold=0.35,
    k_enter=3,
    k_exit=2,
    k_uncertain=4,
)

# Prior — music is more common than vinyl-spinning across a livestream
# window (much of the stream has SOME music, rarely silence). Reflect that
# in a less-asymmetric prior than VinylSpinning's 0.10.
DEFAULT_PRIOR = 0.50


# ── Engine ──────────────────────────────────────────────────────────────


class MusicPlayingEngine:
    """Bayesian music-playing posterior + 3-state hysteresis machine.

    Reads broadcast L-12 audio directly via PANNs/YAMNet classification.
    Constructor takes optional dependency-injection hooks for testing
    (capture function + classifier function); production defaults
    target the live PipeWire bus and the lazy-loaded PANNs model.

    Per AUDIT-07: composes alongside VinylSpinningEngine in the
    director_loop's music-framing branch — both engines' posteriors
    are read independently; consumer logic decides framing.
    """

    def __init__(
        self,
        *,
        capture_fn=None,  # type: ignore[no-untyped-def]
        classify_fn=None,  # type: ignore[no-untyped-def]
        prior: float = DEFAULT_PRIOR,
        profile: TemporalProfile | None = None,
        signal_weights: dict[str, LRDerivation] | None = None,
        music_threshold: float = MUSIC_POSTERIOR_THRESHOLD,
        inference_broker: InferenceBroker | None = None,
    ) -> None:
        self._capture_fn = capture_fn
        self._classify_fn = classify_fn
        self._music_threshold = music_threshold
        self._inference_broker = inference_broker or InferenceBroker()

        self._engine: ClaimEngine[bool] = ClaimEngine[bool](
            name="music_playing",
            prior=prior,
            temporal_profile=profile or DEFAULT_PROFILE,
            signal_weights=signal_weights or _default_signal_weights(),
            decay_rate=0.10,
        )

    # ── Public API ─────────────────────────────────────────────────

    def tick(self) -> None:
        """Capture audio + classify + update the underlying ClaimEngine."""
        prev_state = self._engine.state
        prev_posterior = self._engine.posterior
        observation = self._read_yamnet_music_present()
        self._engine.tick({"yamnet_music_present": observation})
        if self._engine.state != prev_state:
            from shared.bayesian_impingement_emitter import emit_state_transition_impingement

            emit_state_transition_impingement(
                source="audio.music_playing",
                claim_name="music-playing",
                from_state=prev_state,
                to_state=self._engine.state,
                posterior=self._engine.posterior,
                prev_posterior=prev_posterior,
                active_signals={"yamnet_music_present": observation},
            )

    @property
    def posterior(self) -> float:
        """Calibrated 0..1 probability music is currently in the broadcast."""
        return self._engine.posterior

    @property
    def state(self) -> str:
        """Discrete state: ASSERTED | UNCERTAIN | RETRACTED."""
        return self._engine.state

    @property
    def is_playing(self) -> bool:
        """True iff the engine has reached the ASSERTED hysteresis state.

        Drop-in companion to ``VinylSpinningEngine.is_spinning``;
        director_loop's music-framing branch reads both.
        """
        return self._engine.state == "ASSERTED"

    def to_claim(self, *, narration_floor: float = 0.60) -> Claim:
        """Render the current engine state as a Phase 4/5/6 ``Claim`` envelope.

        Companion to ``VinylSpinningEngine.to_claim()``; surfaces gather
        both for the director / persona / narrative prompt envelope. The
        proposition deliberately scopes to ``the broadcast audio`` so the
        LLM cannot conflate it with the upstream source attribution
        (which ``vinyl_spinning`` answers separately).
        """
        return Claim(
            name="music_playing",
            domain="audio",
            proposition="Music is audible in the broadcast audio.",
            posterior=self.posterior,
            prior_source="maximum_entropy",
            prior_provenance_ref="music_playing",
            evidence_sources=[],
            last_update_t=time.time(),
            temporal_profile=DEFAULT_PROFILE,
            composition=None,
            narration_floor=narration_floor,
            staleness_cutoff_s=60.0,
        )

    # ── Signal reader (private) ────────────────────────────────────

    def _read_yamnet_music_present(self) -> bool | None:
        """Capture broadcast L-12 audio + PANNs music-class posterior.

        Returns True iff the summed music-class posteriors exceed
        ``music_threshold``. Returns False on classification success
        with sub-threshold music posterior (bidirectional signal).
        Returns None on capture or classification failure (engine
        contributes no evidence — posterior drifts toward prior).
        """
        try:
            audio = self._capture_audio()
            if audio is None:
                return None
            music_score = self._classify_music_score(audio)
            if music_score is None:
                return None
            return bool(music_score >= self._music_threshold)
        except Exception:
            log.debug("yamnet_music_present signal read failed", exc_info=True)
            return None

    def _capture_audio(self) -> np.ndarray | None:  # type: ignore[no-untyped-def]
        """Capture a CAPTURE_DURATION_S window from broadcast L-12."""
        if self._capture_fn is not None:
            return self._capture_fn()
        return _default_capture_broadcast_l12(CAPTURE_DURATION_S)

    def _classify_music_score(self, audio):  # type: ignore[no-untyped-def]
        """Run PANNs classification + return summed music-class posterior."""
        if self._classify_fn is not None:
            classifier = self._classify_fn
        else:
            classifier = _default_classify_music

        def classify():  # type: ignore[no-untyped-def]
            return classifier(audio)

        if self._inference_broker is None:
            return classify()
        return self._inference_broker.run(
            "music_playing.panns",
            classify,
            estimated_vram_gb=0.0,
        )


# ── Default capture + classify (production paths, lazy imports) ─────────


def _default_capture_broadcast_l12(duration_s: float):  # type: ignore[no-untyped-def]
    """Capture audio from the broadcast L-12 PipeWire monitor.

    Targets ``hapax-livestream-tap.monitor`` (the dedicated broadcast
    monitor) with fallback to ``hapax-livestream.monitor`` if the tap
    isn't present. Returns float32 mono audio at the PANNs sample rate
    (32000), or None on failure.

    Reuses the same pw-record subprocess pattern as the existing
    ambient_classifier; only difference is the explicit
    ``--target hapax-livestream-tap`` rather than the default sink.
    """
    import subprocess

    import numpy as np

    sample_rate = 32000
    num_bytes = int(sample_rate * duration_s * 2)  # int16 = 2 bytes/sample

    for target in (
        BROADCAST_L12_PIPEWIRE_NODE + ".monitor",
        BROADCAST_L12_FALLBACK_NODE + ".monitor",
    ):
        cmd = [
            "pw-record",
            "--format",
            "s16",
            "--rate",
            str(sample_rate),
            "--channels",
            "1",
            "--target",
            target,
            "-",
        ]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            stdout = proc.stdout.read(num_bytes)  # type: ignore[union-attr]
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except (subprocess.TimeoutExpired, OSError):
                proc.kill()
            if not stdout or len(stdout) < num_bytes // 2:
                continue  # try fallback
            audio_int16 = np.frombuffer(stdout, dtype=np.int16)
            audio_float32 = audio_int16.astype(np.float32) / 32768.0
            return audio_float32
        except FileNotFoundError:
            log.warning("pw-record not found — PipeWire not available")
            return None
        except Exception:
            log.exception("broadcast L-12 capture failed for target=%s", target)
            continue
    return None


def _default_classify_music(audio):  # type: ignore[no-untyped-def]
    """Sum music-class posteriors from PANNs classification.

    Lazy-imports the PANNs ``AudioTagging`` model (~300MB on first
    use). Returns a float in [0, 1] representing the summed posterior
    over the music-cluster AudioSet labels (Music, Musical instrument,
    Singing, plus genre subclasses Rock, Pop, Hip hop, Jazz, etc.).
    Returns None on failure.

    The music-cluster label set mirrors the BLOCK_PATTERNS from
    ``ambient_classifier.py`` — same AudioSet semantics.
    """
    try:
        from agents.hapax_daimonion.ambient_classifier import (
            BLOCK_PATTERNS,
            _classify_panns_audio,
        )
    except ImportError:
        log.debug("PANNs classifier not importable; music classification skipped")
        return None

    try:
        labels_with_scores = _classify_panns_audio(audio)
        if not labels_with_scores:
            return None
    except Exception:
        log.exception("PANNs classification raised on broadcast L-12 audio")
        return None

    music_score = 0.0
    for label, score in labels_with_scores:
        for pattern in BLOCK_PATTERNS:
            if pattern.lower() in label.lower():
                music_score += float(score)
                break
    return min(music_score, 1.0)


__all__ = [
    "MusicPlayingEngine",
    "DEFAULT_PRIOR",
    "DEFAULT_PROFILE",
    "MUSIC_POSTERIOR_THRESHOLD",
    "BROADCAST_L12_PIPEWIRE_NODE",
]
