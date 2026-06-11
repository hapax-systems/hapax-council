"""TurnBudget — the single timing SSOT for the voice loop.

CASE-VOICE-FOUNDATION-20260610, audit v2 §5e (voice-p1-turnbudget): one
module holds every conversation-timing constant with its derivation, plus
the per-turn deadline object threaded STT→route→LLM→synth→playback.

Before this module the constants lived in ≥8 files with three direct
contradictions (two `_ECHO_TTL_S` values in one file; a "300ms" pre-roll
docstring over a 1500ms constant; a "cooldown removed" docstring over a
live 2s cooldown). Consumers now import from here; the old names survive
as aliases at the consuming sites so external readers don't break.

This module is a LEAF: it imports nothing from agents.hapax_daimonion at
module level (the witness import in :meth:`TurnBudget.emit` is local), so
any daimonion module can import it without cycles.

Calibration note (audit §5e): values are CONSOLIDATED here, not retuned.
Cooldown/half-duplex recalibration is explicitly deferred until the
substrate fix (Turbo TTS + streaming STT) lands — today's values are
tuned for the world we actually run, and each derivation says why.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# ── Capture frame geometry ───────────────────────────────────────────────
# 16kHz mono s16le, 30ms frames — the contract between audio_input, the
# conversation buffer, VAD, and the barge-in classifier.
SAMPLE_RATE = 16000
FRAME_SAMPLES = 480  # 30ms @ 16kHz
FRAME_DURATION_S = FRAME_SAMPLES / SAMPLE_RATE  # 0.03

# ── Pre-roll ─────────────────────────────────────────────────────────────
# Audio kept from BEFORE speech onset so word beginnings aren't clipped.
# 50 frames × 30ms = 1.5s — sized when wake-word phrases needed capturing.
# Wake word is RETIRED (audit §5d) but the window stays: it also covers
# slow VAD onset for an operator with dysfluent speech starts. The old
# conversation_buffer docstring claimed "300ms" — that was the lie this
# derivation kills.
PRE_ROLL_FRAMES = 50
PRE_ROLL_DURATION_S = PRE_ROLL_FRAMES * FRAME_DURATION_S  # 1.5s

# ── Session silence timeouts ─────────────────────────────────────────────
# How long a session stays open with no operator speech before closing.
# Default 30s; programmes get longer windows because considered answers
# in interviews/lectures legitimately go quiet for minutes.
SILENCE_TIMEOUT_S = 30.0
PROGRAMME_SILENCE_TIMEOUT_S: dict[str, float] = {
    "interview": 180.0,
    "lecture": 60.0,
    "tutorial": 45.0,
}
# DISTINCT concept, formerly the colliding name `_INTERVIEW_SILENCE_DEFAULT_S`
# in cpal/runner.py: after the system asks an interview question, suppress
# backchannels and T1/T2 corrections for this window so the interviewee can
# think without being talked over. NOT a session-close timeout.
INTERVIEW_QUESTION_SILENCE_S = 15.0

# ── Echo windows ─────────────────────────────────────────────────────────
# Both were defined as `_ECHO_TTL_S` in conversation_pipeline.py with
# different values — the audit's named contradiction. They are different
# concepts and now have different names:
#
# ECHO_DETECT_TTL_S — how long a TTS sentence stays eligible for whole-
# transcript echo REJECTION in `_is_echo`. 30s covers the autonomous-
# narrative worst case: synthesis (~3s) + playback (~6s) + holdover (3s)
# + room propagation (~5s) + buffer accumulation (~8s). Was 12s once and
# missed narrative echoes arriving 20+ seconds after emission.
ECHO_DETECT_TTL_S = 30.0
# ECHO_STRIP_TTL_S — how long a TTS sentence stays eligible for echo
# PREFIX-STRIPPING in `_strip_echo_prefix` (mic caught the tail of our
# own TTS immediately followed by real operator speech). Deliberately
# short: prefix-stripping a transcript against 30s of TTS history would
# eat legitimate operator phrasing that happens to echo our wording.
ECHO_STRIP_TTL_S = 8.0

# ── Post-TTS cooldown / speech-gate holdover ─────────────────────────────
# After TTS playback ends, the buffer stays deaf while room echo decays.
# Base 2s, +0.3s per second spoken (longer responses excite more room),
# capped at 5s. The old conversation_buffer docstring claimed the cooldown
# was "removed"; it never was — now the docstring and the code agree.
POST_TTS_COOLDOWN_S = 2.0
POST_TTS_COOLDOWN_SCALE = 0.3  # +s of cooldown per second of TTS playback
POST_TTS_COOLDOWN_MAX_S = 5.0
# Spontaneous/narrative paths in cpal/runner.py hold the speaking gate a
# fixed extra window past playback end (the two former bare
# `asyncio.sleep(3.0)` literals) so the Yeti mic doesn't transcribe the
# echo tail as operator speech.
SPEECH_GATE_HOLDOVER_S = 3.0


def dynamic_cooldown_s(speaking_duration_s: float) -> float:
    """Post-TTS cooldown scaled by how long we just spoke (see derivation above)."""
    return min(
        POST_TTS_COOLDOWN_MAX_S,
        POST_TTS_COOLDOWN_S + speaking_duration_s * POST_TTS_COOLDOWN_SCALE,
    )


# ── LLM leg bounds ───────────────────────────────────────────────────────
# Audit H2: litellm's default timeout is 600s — one wedged TabbyAPI request
# could silence a voice path for ten minutes. EVERY daimonion LLM call is
# bounded (regression-pinned in tests/hapax_daimonion/test_turn_budget.py).
#
# Spontaneous speech: worst measured local-fast TTFT under 5090 GPU
# contention is ~19s (foundation audit §3) plus a few seconds of generation
# for max_tokens=80 — 60s gives ~2x headroom while capping the hold.
SPONTANEOUS_LLM_TIMEOUT_S = 60.0
# Conversational streaming request: read-timeout between stream events.
# 15s fails fast on a dead route while staying above cloud-tier TTFT
# (FAST/STRONG/CAPABLE measure 0.5–3s). NOTE: podium local-fast TTFT under
# contention measures 8.7–18.7s (audit §3) — this bound truthfully surfaces
# those turns as timeouts instead of hiding them; the LLM-leg fix is the
# ratified appendix-fast cutover (§5c), not a looser bound here.
CONVERSATION_LLM_REQUEST_TIMEOUT_S = 15.0
# Whole interactive turn (STT→…→playback queued): the deadline carried by
# the TurnBudget object. Formerly a bare `timeout=90.0` on the LLM task
# that ignored time already spent in STT.
INTERACTIVE_TURN_BUDGET_S = 90.0
# Segment-prep / research enrichment calls (daily_segment_prep,
# angle_resolver): not on the hot path; Opus-class composition legitimately
# runs minutes. 20min bounds a wedge without strangling real work.
PREP_LLM_TIMEOUT_S = 1200.0
# Barge-in speculative STT classification — must resolve well inside one
# spoken clause or the classification is useless.
BARGE_IN_STT_TIMEOUT_S = 2.0
# Clause accumulation flush: max dead-air while waiting for a clause
# boundary in the LLM token stream before force-flushing to TTS.
MAX_CLAUSE_ACCUMULATION_S = 0.3


# ── The per-turn deadline object ─────────────────────────────────────────


@dataclass
class TurnBudget:
    """End-to-end deadline + per-leg accounting for one voice turn.

    Created at utterance start (interactive) or impingement acceptance
    (spontaneous), threaded through STT→route→LLM→synth→playback, and
    emitted as a one-line TIMING receipt (log always; witness for engaged
    turns) when the turn terminates.

    Overrun policy (audit §5e): interactive paths degrade to canned PCM;
    spontaneous/autonomous paths drop-with-witness — never spoken errors.
    """

    kind: str = "interactive"  # "interactive" | "spontaneous"
    budget_s: float = INTERACTIVE_TURN_BUDGET_S
    turn: int | None = None
    started: float = field(default_factory=time.monotonic)
    legs: dict[str, float] = field(default_factory=dict)  # leg name → ms
    notes: dict[str, str] = field(default_factory=dict)  # route/model/outcome

    def mark(self, leg: str, *, t0: float | None = None) -> float:
        """Record completion of ``leg``: ms elapsed since ``t0`` (default: turn start)."""
        ms = (time.monotonic() - (self.started if t0 is None else t0)) * 1000.0
        self.legs[leg] = ms
        return ms

    def add(self, leg: str, ms: float) -> float:
        """Accumulate ``ms`` into ``leg`` (e.g. per-clause synth times)."""
        self.legs[leg] = self.legs.get(leg, 0.0) + ms
        return self.legs[leg]

    def note(self, **kv: object) -> None:
        """Attach route/model/outcome annotations to the receipt."""
        self.notes.update({k: str(v) for k, v in kv.items()})

    def elapsed_s(self) -> float:
        return time.monotonic() - self.started

    def remaining_s(self) -> float:
        """Seconds left in the budget — feed this to wait_for/LLM timeouts."""
        return max(0.0, self.budget_s - self.elapsed_s())

    @property
    def overrun(self) -> bool:
        return self.elapsed_s() > self.budget_s

    def receipt(self) -> str:
        """One TIMING line proving each leg — the audit's acceptance artifact."""
        parts = [f"TIMING turn={'' if self.turn is None else self.turn}", f"kind={self.kind}"]
        parts += [f"{k}={v}" for k, v in self.notes.items()]
        parts += [f"{k}={v:.0f}ms" for k, v in self.legs.items()]
        parts += [
            f"total={self.elapsed_s() * 1000:.0f}ms",
            f"budget={self.budget_s * 1000:.0f}ms",
            f"overrun={'true' if self.overrun else 'false'}",
        ]
        return " ".join(parts)

    def emit(self, *, witness: bool = True, witness_path=None) -> None:
        """Log the receipt; for engaged turns, persist it to the voice witness.

        Early-rejected turns (no transcript, echo, duplicate) pass
        ``witness=False`` — they receipt to the log but don't churn the
        witness file the watchdog tails.
        """
        log.info("%s", self.receipt())
        if not witness:
            return
        try:
            kwargs = {} if witness_path is None else {"path": witness_path}
            record_turn_timing(
                kind=self.kind,
                turn=self.turn,
                legs=dict(self.legs),
                notes=dict(self.notes),
                total_ms=self.elapsed_s() * 1000.0,
                budget_ms=self.budget_s * 1000.0,
                overrun=self.overrun,
                **kwargs,
            )
        except Exception:  # noqa: BLE001 — accounting must never break the voice path
            log.debug("turn timing witness write failed", exc_info=True)


def record_turn_timing(**kwargs):
    """Indirection point so tests can patch the witness write at one seam."""
    from agents.hapax_daimonion.voice_output_witness import record_turn_timing as _record

    return _record(**kwargs)
