"""Gapless hosting TTS — a single persistent stream fed a look-ahead clause queue.

Segment-audio-remainder AC#3. Sustained hosting historically synthesized one
clause, played it with a blocking ``time.sleep(duration_s)``, then synthesized
the next — so every clause boundary carried the synth latency as an audible
gap. ``GaplessHostStream`` removes the gap two ways:

* **single persistent stream** — every clause is written to one ``write_fn``
  (in production, one ``PwAudioOutput`` ``(target, media_role)`` whose ``pw-cat``
  subprocess stays open), so there is no per-clause subprocess spawn gap; and
* **look-ahead synthesis** — clause ``N+1`` is submitted to the synth executor
  *before* clause ``N`` is written, so its synthesis overlaps ``N``'s playback
  and the next blob is ready the instant ``N`` finishes.

The **clause stays the prosody unit** (text is split with the same
``_CLAUSE_END`` boundary the interactive path uses); the **stream** is the
gapless unit. Segment ``role`` and ``arc_position`` ride on every
:class:`ClauseRequest` so the synth backend can shape arc-level prosody.

The ``tts-envelope.f32`` / ``speech-wave.bin`` reactivity tap (the
Sierpinski-centre oscilloscope) is preserved: each clause's PCM is handed to
``feed_fn`` *before* it is written, exactly as the live ``write()`` wrap does,
and a ``feed_fn`` failure never blocks playback.

All collaborators (synth / write / feed / pace / executor) are injected, so the
pipeline is exercised deterministically in tests with no real audio device.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass

from agents.hapax_daimonion.conversation_helpers import _CLAUSE_END
from agents.hapax_daimonion.pw_audio_output import _pcm_duration_s

log = logging.getLogger(__name__)

__all__ = ["ClauseRequest", "GaplessHostStream", "segment_clauses"]


@dataclass(frozen=True)
class ClauseRequest:
    """One prosody-unit clause plus the arc context the synth backend needs."""

    text: str
    role: str | None
    arc_position: float | None
    index: int
    total: int


def segment_clauses(text: str) -> list[str]:
    """Split hosting text into prosody-unit clauses.

    Reuses ``conversation_helpers._CLAUSE_END`` so hosting clauses match the
    interactive path's boundaries. Strips whitespace and drops empty fragments.
    """
    return [clause.strip() for clause in _CLAUSE_END.split(text) if clause and clause.strip()]


class GaplessHostStream:
    """Play sustained hosting speech gaplessly over a single persistent stream.

    Parameters
    ----------
    synth_fn:
        ``ClauseRequest -> bytes`` (int16 mono PCM). Synthesis backend.
    write_fn:
        ``bytes -> None``. Writes one clause's PCM to the single persistent
        stream WITHOUT blocking for the audio duration (pacing is owned here).
    feed_fn:
        Optional ``bytes -> None`` envelope tap, called before each write.
        A failure is swallowed so the oscilloscope can never stall playback.
    pace_fn:
        ``float -> None`` real-time pacing (default ``time.sleep``). Sleeping a
        clause's duration here — while the *next* clause synthesizes on the
        executor — is what bounds look-ahead to one clause and keeps the
        stream real-time without re-introducing an inter-clause synth gap.
    executor:
        Runs ``synth_fn`` for look-ahead. Default: a single-worker pool, which
        serializes synthesis (matching the TTS server's serialized synth).
    """

    def __init__(
        self,
        *,
        synth_fn: Callable[[ClauseRequest], bytes],
        write_fn: Callable[[bytes], None],
        feed_fn: Callable[[bytes], None] | None = None,
        pace_fn: Callable[[float], None] | None = None,
        sample_rate: int = 24000,
        channels: int = 1,
        executor: Executor | None = None,
    ) -> None:
        self._synth_fn = synth_fn
        self._write_fn = write_fn
        self._feed_fn = feed_fn
        self._pace_fn = pace_fn if pace_fn is not None else time.sleep
        self._sample_rate = sample_rate
        self._channels = channels
        self._owns_executor = executor is None
        self._executor: Executor = (
            executor
            if executor is not None
            else ThreadPoolExecutor(max_workers=1, thread_name_prefix="gapless-host-synth")
        )

    def speak(
        self,
        text: str,
        *,
        role: str | None = None,
        arc_position: float | None = None,
    ) -> int:
        """Synthesize + play ``text`` gaplessly. Returns clauses actually played.

        Blocks until the last clause has been handed to the stream and paced —
        callers run this from their own hosting thread (as the director already
        spawns a thread per spoken move).
        """
        clauses = segment_clauses(text)
        if not clauses:
            return 0
        total = len(clauses)
        requests = [
            ClauseRequest(text=clause, role=role, arc_position=arc_position, index=i, total=total)
            for i, clause in enumerate(clauses)
        ]

        played = 0
        ahead: Future | None = self._executor.submit(self._synth_fn, requests[0])
        for i, request in enumerate(requests):
            try:
                pcm = ahead.result() if ahead is not None else b""
            except Exception:  # noqa: BLE001 — a failed clause must not abort the rest
                log.warning("hosting clause synth failed (index=%d)", request.index, exc_info=True)
                pcm = b""

            # Look-ahead: start synthesizing the NEXT clause before playing this
            # one, so its latency hides under this clause's playback.
            ahead = (
                self._executor.submit(self._synth_fn, requests[i + 1]) if i + 1 < total else None
            )

            if not pcm:
                continue
            if self._feed_fn is not None:
                try:
                    self._feed_fn(pcm)  # envelope tap leads the write; never blocks playback
                except Exception:  # noqa: BLE001 — wave/feature ring must not stall voice
                    log.debug("envelope feed failed (index=%d)", request.index, exc_info=True)
            self._write_fn(pcm)
            self._pace_fn(_pcm_duration_s(pcm, rate=self._sample_rate, channels=self._channels))
            played += 1
        return played

    def close(self) -> None:
        """Shut down the synth executor if this stream created it."""
        if self._owns_executor:
            self._executor.shutdown(wait=False)


def build_gapless_host_stream(
    tts_manager: object,
    audio_output: object,
    *,
    envelope_publisher: object | None = None,
    target: str | None = None,
    media_role: str = "Broadcast",
    use_case: str = "conversation",
    sample_rate: int = 24000,
    channels: int = 1,
    pace_fn: Callable[[float], None] | None = None,
    executor: Executor | None = None,
) -> GaplessHostStream:
    """Assemble a production ``GaplessHostStream`` from the daimonion collaborators.

    The hosting caller (e.g. the director) constructs the stream once per
    segment and calls :meth:`GaplessHostStream.speak` per move. This factory is
    the single place that wires:

    * synth → ``tts_manager.synthesize(text, use_case, role=, arc_position=)``
      (so segment role + arc position reach the synth backend);
    * write → ``audio_output.write(pcm, target=, media_role=, pace=False)`` —
      one persistent ``(target, media_role)`` stream, fed back-to-back with the
      blocking per-write sleep suppressed (the stream owns pacing); and
    * feed → ``envelope_publisher.feed(pcm)`` so the ``tts-envelope.f32`` /
      ``speech-wave.bin`` oscilloscope keeps updating from the hosting PCM.
    """

    def _synth(request: ClauseRequest) -> bytes:
        return tts_manager.synthesize(  # type: ignore[attr-defined]
            request.text,
            use_case,
            role=request.role,
            arc_position=request.arc_position,
        )

    def _write(pcm: bytes) -> None:
        audio_output.write(  # type: ignore[attr-defined]
            pcm, target=target, media_role=media_role, pace=False
        )

    feed_fn = envelope_publisher.feed if envelope_publisher is not None else None  # type: ignore[attr-defined]

    return GaplessHostStream(
        synth_fn=_synth,
        write_fn=_write,
        feed_fn=feed_fn,
        pace_fn=pace_fn,
        sample_rate=sample_rate,
        channels=channels,
        executor=executor,
    )
