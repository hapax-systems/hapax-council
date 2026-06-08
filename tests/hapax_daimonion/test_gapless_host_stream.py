"""Tests for the gapless hosting TTS stream (segment-audio-remainder AC#3).

The hosting path historically synthesized one clause, played it with a
blocking ``time.sleep(duration_s)``, then synthesized the next — so every
clause boundary carried the synth latency as an audible gap. ``GaplessHostStream``
removes the gap by (a) keeping a SINGLE persistent stream and (b) synthesizing
clause N+1 while clause N plays (look-ahead). The envelope reactivity tap
(``tts-envelope.f32`` / ``speech-wave.bin``) must keep updating — it is fed at
the same write seam, BEFORE each write, and feed failures must never block
playback.

Collaborators (synth / write / feed / pace / executor) are injected so the
whole pipeline is exercised deterministically with no real audio device.
"""

from __future__ import annotations

from concurrent.futures import Future

from agents.hapax_daimonion.gapless_host_stream import (
    ClauseRequest,
    GaplessHostStream,
    build_gapless_host_stream,
    segment_clauses,
)


class _InlineExecutor:
    """Runs ``submit`` synchronously so look-ahead ordering is deterministic."""

    def submit(self, fn, *args, **kwargs):  # noqa: ANN001
        future: Future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001 — mirror executor semantics
            future.set_exception(exc)
        return future


def _pcm(marker: int, samples: int = 2400) -> bytes:
    """A distinguishable int16-mono PCM blob (``samples`` samples → bytes)."""
    return bytes([marker & 0xFF, (marker >> 8) & 0xFF]) * samples


# ── segment_clauses ──────────────────────────────────────────────────────────


def test_segment_clauses_splits_on_sentence_boundaries() -> None:
    assert segment_clauses("Hello world. This is a test.") == [
        "Hello world.",
        "This is a test.",
    ]


def test_segment_clauses_single_clause_is_one_unit() -> None:
    assert segment_clauses("Just one clause") == ["Just one clause"]


def test_segment_clauses_empty_or_whitespace_yields_nothing() -> None:
    assert segment_clauses("") == []
    assert segment_clauses("   \n  ") == []


# ── envelope tap preservation ────────────────────────────────────────────────


def test_each_clause_is_fed_to_envelope_before_being_written() -> None:
    events: list[tuple[str, bytes]] = []
    pcms = {0: _pcm(0xA1), 1: _pcm(0xB2)}

    stream = GaplessHostStream(
        synth_fn=lambda req: pcms[req.index],
        write_fn=lambda pcm: events.append(("write", pcm)),
        feed_fn=lambda pcm: events.append(("feed", pcm)),
        pace_fn=lambda _s: None,
        executor=_InlineExecutor(),
    )

    stream.speak("First clause. Second clause.")

    # feed of a clause must come immediately before its write (the tap leads
    # playback by exactly the buffer depth — same contract as the live path).
    assert events == [
        ("feed", pcms[0]),
        ("write", pcms[0]),
        ("feed", pcms[1]),
        ("write", pcms[1]),
    ]


def test_feed_failure_never_blocks_the_write() -> None:
    written: list[bytes] = []

    def _boom(_pcm: bytes) -> None:
        raise RuntimeError("envelope analysis exploded")

    stream = GaplessHostStream(
        synth_fn=lambda req: _pcm(req.index),
        write_fn=lambda pcm: written.append(pcm),
        feed_fn=_boom,
        pace_fn=lambda _s: None,
        executor=_InlineExecutor(),
    )

    played = stream.speak("Alpha. Beta.")

    assert played == 2
    assert written == [_pcm(0), _pcm(1)]


# ── single persistent stream (gaplessness) ───────────────────────────────────


def test_all_clauses_written_in_order_to_a_single_stream() -> None:
    written: list[bytes] = []

    stream = GaplessHostStream(
        synth_fn=lambda req: _pcm(req.index),
        write_fn=lambda pcm: written.append(pcm),
        pace_fn=lambda _s: None,
        executor=_InlineExecutor(),
    )

    stream.speak("One. Two. Three.")

    assert written == [_pcm(0), _pcm(1), _pcm(2)]


# ── look-ahead synthesis (synthesize N+1 while N plays) ───────────────────────


def test_next_clause_is_synthesized_before_current_clause_is_written() -> None:
    order: list[tuple[str, int]] = []

    def _synth(req: ClauseRequest) -> bytes:
        order.append(("synth", req.index))
        return _pcm(req.index)

    def _write(pcm: bytes) -> None:
        order.append(("write", pcm[0] | (pcm[1] << 8)))  # marker == clause index

    stream = GaplessHostStream(
        synth_fn=_synth,
        write_fn=_write,
        pace_fn=lambda _s: None,
        executor=_InlineExecutor(),
    )

    stream.speak("Aaa. Bbb. Ccc.")

    # The synth of clause 1 must be recorded before the write of clause 0 —
    # that is the look-ahead that hides synth latency under playback.
    assert order.index(("synth", 1)) < order.index(("write", 0))


# ── arc-level prosody plumbing (segment role + position-in-arc) ───────────────


def test_role_and_arc_position_threaded_into_every_clause_request() -> None:
    seen: list[ClauseRequest] = []

    stream = GaplessHostStream(
        synth_fn=lambda req: (seen.append(req), _pcm(req.index))[1],
        write_fn=lambda _pcm: None,
        pace_fn=lambda _s: None,
        executor=_InlineExecutor(),
    )

    stream.speak("First. Second.", role="lecture", arc_position=0.25)

    assert [r.text for r in seen] == ["First.", "Second."]
    assert all(r.role == "lecture" for r in seen)
    assert all(r.arc_position == 0.25 for r in seen)
    assert [(r.index, r.total) for r in seen] == [(0, 2), (1, 2)]


# ── robustness ───────────────────────────────────────────────────────────────


def test_empty_synth_output_is_skipped_without_breaking_the_stream() -> None:
    written: list[bytes] = []

    def _synth(req: ClauseRequest) -> bytes:
        return b"" if req.index == 0 else _pcm(req.index)

    stream = GaplessHostStream(
        synth_fn=_synth,
        write_fn=lambda pcm: written.append(pcm),
        pace_fn=lambda _s: None,
        executor=_InlineExecutor(),
    )

    played = stream.speak("Silent. Loud.")

    # Clause 0 produced no audio → not written; clause 1 still plays.
    assert written == [_pcm(1)]
    assert played == 1


def test_empty_text_plays_nothing() -> None:
    written: list[bytes] = []
    stream = GaplessHostStream(
        synth_fn=lambda req: _pcm(req.index),
        write_fn=lambda pcm: written.append(pcm),
        pace_fn=lambda _s: None,
        executor=_InlineExecutor(),
    )
    assert stream.speak("   ") == 0
    assert written == []


def test_each_clause_paces_by_its_audio_duration() -> None:
    paced: list[float] = []

    # 2400 samples @ 24 kHz mono = 0.1 s of audio per clause.
    stream = GaplessHostStream(
        synth_fn=lambda req: _pcm(req.index, samples=2400),
        write_fn=lambda _pcm: None,
        pace_fn=lambda seconds: paced.append(seconds),
        sample_rate=24000,
        executor=_InlineExecutor(),
    )

    stream.speak("Tick. Tock.")

    assert paced == [0.1, 0.1]


# ── production wiring factory (reachability) ─────────────────────────────────


class _FakeManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, float | None]] = []

    def synthesize(self, text, use_case="conversation", *, role=None, arc_position=None, **_kw):  # noqa: ANN001, ANN201
        self.calls.append((text, role, arc_position))
        return _pcm(len(self.calls))


class _FakeOutput:
    def __init__(self) -> None:
        self.calls: list[tuple[str | None, str | None, bool]] = []

    def write(self, pcm, *, target=None, media_role=None, pace=True):  # noqa: ANN001, ANN201
        self.calls.append((target, media_role, pace))


def test_factory_wires_manager_output_and_envelope_with_pace_false() -> None:
    mgr = _FakeManager()
    out = _FakeOutput()
    fed: list[bytes] = []

    class _Pub:
        def feed(self, pcm):  # noqa: ANN001, ANN201
            fed.append(pcm)

    stream = build_gapless_host_stream(
        mgr,
        out,
        envelope_publisher=_Pub(),
        media_role="Broadcast",
        pace_fn=lambda _s: None,
        executor=_InlineExecutor(),
    )

    stream.speak("Host clause one. Host clause two.", role="rant", arc_position=0.5)

    # synth adapter threads role + arc into the manager
    assert [(r, a) for (_t, r, a) in mgr.calls] == [("rant", 0.5), ("rant", 0.5)]
    # write adapter targets ONE persistent role with the non-blocking pace=False
    assert out.calls and all(
        role == "Broadcast" and pace is False for (_t, role, pace) in out.calls
    )
    # envelope tap is fed once per clause (oscilloscope preserved)
    assert len(fed) == 2
