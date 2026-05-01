"""CEA-608 Roll-Up byte-pair encoder for live captions.

Pure-logic encoder that converts caption events (text + timing) into
the 2-byte-per-video-frame stream that the GStreamer ``cccombiner``
element accepts on its ``caption`` sink pad. Targeted at CC1 (Field 1,
Channel 1) Roll-Up mode — the standard for English live captions per
the FCC CEA-608 specification.

Scope (this module)
-------------------

- Odd-parity byte conversion (CEA-608 requires the high bit to make
  each byte have an odd count of ones).
- Roll-Up mode control sequences (RU3 + ENM/EDM/RCL/CR).
- Text-to-byte-pair encoding with non-ASCII fallback.
- Stateful :class:`RollUpEncoder` that emits the init sequence once,
  tracks the current line, and produces a frame-synchronous byte-pair
  stream when fed :class:`agents.live_captions.reader.CaptionEvent`-
  shaped records.

Out of scope (deferred to follow-up PRs in this train)
------------------------------------------------------

- GStreamer ``appsrc`` integration / ``cccombiner`` wiring
  (next-slice ``gst_injector.py``).
- ``rtmp_output.py`` pipeline modification.
- Audio↔video clock alignment (next-slice ``timing_aligner.py``).
- NVENC SEI passthrough verification (live-hardware smoke).
- End-to-end YouTube live smoke (operator action).

The encoder is deterministic and side-effect-free: a single tick
takes (state, event) and returns (new state, byte pairs to emit).
This makes it fully unit-testable offline without GStreamer or NVENC.

References
----------

- CEA-608 specification (FCC 47 CFR §15.119 incorporates by reference)
- ``gst-plugins-bad`` ``cccombiner`` element documentation
  (``gst-inspect-1.0 cccombiner``)
- R5 spec at
  ``~/.cache/hapax/relay/context/2026-04-23-youtube-boost-R5-in-band-live-captions-spec.md``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

# ── Constants ───────────────────────────────────────────────────────────

#: Per-row character budget for CEA-608 captions (32 columns × 2 rows
#: typical, but only 32 wide is used by single-line Roll-Up).
CEA608_LINE_WIDTH: Final[int] = 32

#: Frame-synchronous null byte (no character, no control code). When
#: nothing else needs to land on a frame, encoders emit ``(0x80, 0x80)``
#: which decodes to "no caption data".
CEA608_NULL_BYTE: Final[int] = 0x80

#: NTSC video frame rate the CEA-608 byte-pair stream synchronizes to.
#: Each video frame carries one byte-pair. PAL targets 25 fps and uses
#: a different per-frame budget; this encoder targets NTSC 30 fps which
#: matches the council's 30 fps RTMP encode.
NTSC_FRAME_RATE: Final[float] = 30.0


# ── Control codes (CC1 / Field 1) ───────────────────────────────────────
#
# Control codes are 2-byte pairs whose first byte sits in 0x10-0x1F
# (before parity is applied). The CC1 channel uses 0x14 / 0x15. The
# second byte selects the operation. See CEA-608 §6 for the full table.

#: Resume Caption Loading — switch to Pop-On mode (we do NOT use this
#: in Roll-Up flow; included so Pop-On callers can opt in later).
RCL: Final[tuple[int, int]] = (0x14, 0x20)

#: Backspace — erase the previous character on the current row.
BS: Final[tuple[int, int]] = (0x14, 0x21)

#: Delete to End of Row — erase from cursor to end of row.
DER: Final[tuple[int, int]] = (0x14, 0x24)

#: Roll-Up captions, 2 rows. Sets caption mode to Roll-Up and confines
#: rolling area to 2 rows.
RU2: Final[tuple[int, int]] = (0x14, 0x25)

#: Roll-Up captions, 3 rows — typical for live broadcast (FCC reference).
RU3: Final[tuple[int, int]] = (0x14, 0x26)

#: Roll-Up captions, 4 rows.
RU4: Final[tuple[int, int]] = (0x14, 0x27)

#: Erase Non-Displayed Memory — clear the off-screen buffer.
ENM: Final[tuple[int, int]] = (0x14, 0x2E)

#: Erase Displayed Memory — clear the on-screen rolling text.
EDM: Final[tuple[int, int]] = (0x14, 0x2C)

#: Carriage Return — in Roll-Up mode, scrolls existing rows up by one
#: and clears the bottom row for the next line.
CR: Final[tuple[int, int]] = (0x14, 0x2D)

#: End of Caption — used in Pop-On mode (not needed for Roll-Up).
EOC: Final[tuple[int, int]] = (0x14, 0x2F)


# ── Parity ──────────────────────────────────────────────────────────────


def odd_parity(byte: int) -> int:
    """Return ``byte`` with its high bit set to ensure odd parity.

    CEA-608 requires every transmitted byte to have an odd number of
    set bits across all 8 bits. The low 7 bits carry the data; the
    high bit is computed.

    Raises ``ValueError`` if ``byte`` is outside ``[0, 0x7F]`` — the
    high bit is reserved for parity and must not be set by callers.
    """
    if not 0 <= byte <= 0x7F:
        raise ValueError(f"byte must be 7-bit clean (0..0x7F), got 0x{byte:02X}")
    ones = bin(byte).count("1")
    return byte if ones % 2 == 1 else byte | 0x80


def with_parity(pair: tuple[int, int]) -> tuple[int, int]:
    """Apply :func:`odd_parity` to both bytes of a control or text pair."""
    return odd_parity(pair[0]), odd_parity(pair[1])


# ── Text encoding ───────────────────────────────────────────────────────
#
# CEA-608 supports the printable ASCII range plus a small set of special
# characters via the Standard Character Set + Extended Western European
# tables. For a first slice we restrict to ASCII printable (0x20-0x7E)
# and fold any non-representable Unicode to a single "?" replacement.
# A future slice can add the Spanish/French/etc. extended-character
# bridging via the 0x12/0x13 0x20-0x3F escape pairs.

#: Replacement character for non-encodable Unicode codepoints.
CEA608_REPLACEMENT_CHAR: Final[str] = "?"


def fold_to_ascii(text: str) -> str:
    """Replace any character outside printable ASCII with ``?``.

    Tabs are expanded to single spaces; all other control characters
    are dropped (they would interfere with caption byte-pair framing).
    """
    out_chars: list[str] = []
    for ch in text:
        cp = ord(ch)
        if cp == 0x09:
            out_chars.append(" ")
            continue
        if 0x20 <= cp <= 0x7E:
            out_chars.append(ch)
        elif cp < 0x20:
            continue  # skip other C0 controls
        else:
            out_chars.append(CEA608_REPLACEMENT_CHAR)
    return "".join(out_chars)


def text_to_byte_pairs(text: str) -> list[tuple[int, int]]:
    """Encode ``text`` into a stream of 2-byte pairs with odd parity.

    Each pair carries either two character bytes (for even-length runs)
    or one character byte plus a null filler (for the trailing odd
    character). Non-ASCII input is folded through :func:`fold_to_ascii`.
    """
    folded = fold_to_ascii(text)
    pairs: list[tuple[int, int]] = []
    i = 0
    while i + 1 < len(folded):
        pairs.append(with_parity((ord(folded[i]), ord(folded[i + 1]))))
        i += 2
    if i < len(folded):
        pairs.append(with_parity((ord(folded[i]), CEA608_NULL_BYTE & 0x7F)))
    return pairs


# ── Roll-Up encoder ─────────────────────────────────────────────────────


@dataclass
class RollUpEncoderState:
    """Mutable state for :class:`RollUpEncoder`.

    ``initialized`` flips True after the encoder has emitted the
    one-shot init sequence (ENM + RU3 + CR). ``current_line_chars``
    counts how many characters have been emitted on the current line
    so the encoder can refuse over-budget input rather than wrapping
    silently.
    """

    initialized: bool = False
    current_line_chars: int = 0
    pending_pairs: list[tuple[int, int]] = field(default_factory=list)


@dataclass(frozen=True)
class CaptionFrame:
    """One frame's worth of caption byte-pair output.

    ``ts`` is the wall-clock timestamp the encoder advanced to (audio
    domain — the consumer aligns this onto the video PTS via the
    timing aligner). ``byte_pair`` is exactly two bytes (parity
    applied). ``is_filler`` is ``True`` when this frame's pair is the
    null/filler ``(0x80, 0x80)`` — the consumer may drop fillers if
    the GStreamer element accepts gaps, or include them as no-ops.
    """

    ts: float
    byte_pair: tuple[int, int]
    is_filler: bool


class RollUpEncoder:
    """Stateful Roll-Up CEA-608 encoder.

    Use :meth:`begin_line` to mark the start of a new caption line,
    :meth:`add_text` to accumulate characters, and :meth:`commit_line`
    to flush the pending bytes plus the carriage-return that scrolls
    the row.

    The encoder produces byte pairs, not framed output. A consumer
    (the GStreamer injector in a follow-up slice) decides which video
    frame each pair lands on based on the audio→video PTS offset.
    """

    def __init__(self, state: RollUpEncoderState | None = None) -> None:
        self.state = state if state is not None else RollUpEncoderState()

    @property
    def initialized(self) -> bool:
        return self.state.initialized

    def begin_line(self) -> list[tuple[int, int]]:
        """Emit the init sequence (once) and start a new line.

        Returns the byte pairs that must be sent on the wire BEFORE any
        text from the new line. Subsequent calls (after the first)
        return an empty list — Roll-Up only needs the init sequence
        once per stream.

        This is idempotent in the sense that repeated calls without
        intermediate :meth:`commit_line` calls do not re-emit the
        init sequence.
        """
        out: list[tuple[int, int]] = []
        if not self.state.initialized:
            out.append(with_parity(ENM))
            out.append(with_parity(EDM))
            out.append(with_parity(RU3))
            out.append(with_parity(CR))
            self.state.initialized = True
        self.state.current_line_chars = 0
        return out

    def add_text(self, text: str) -> list[tuple[int, int]]:
        """Encode ``text`` into byte pairs and append to the pending queue.

        Returns the byte pairs that should be emitted (in order) before
        the next :meth:`commit_line`. Text that would push the line
        past :data:`CEA608_LINE_WIDTH` is truncated with a trailing
        ``…`` indicator (folded to ``...`` since ``…`` is non-ASCII).
        """
        if not self.state.initialized:
            raise RuntimeError(
                "RollUpEncoder.add_text called before begin_line — "
                "init sequence has not been emitted"
            )
        folded = fold_to_ascii(text)
        budget = CEA608_LINE_WIDTH - self.state.current_line_chars
        if budget <= 0:
            return []
        if len(folded) > budget:
            # Reserve 3 chars for "..." truncation marker.
            keep = max(0, budget - 3)
            folded = folded[:keep] + "..."
            folded = folded[:budget]
        pairs = text_to_byte_pairs(folded)
        self.state.pending_pairs.extend(pairs)
        self.state.current_line_chars += len(folded)
        return pairs

    def commit_line(self) -> list[tuple[int, int]]:
        """Append the carriage-return pair and reset the line counter.

        Returns the CR pair (which scrolls the rolling area). Pending
        text pairs are NOT re-emitted — they were already returned by
        :meth:`add_text`. The returned list always has exactly one
        element (the CR pair with parity applied).
        """
        if not self.state.initialized:
            raise RuntimeError(
                "RollUpEncoder.commit_line called before begin_line — "
                "init sequence has not been emitted"
            )
        self.state.current_line_chars = 0
        self.state.pending_pairs.clear()
        return [with_parity(CR)]

    def encode_line(self, text: str) -> list[tuple[int, int]]:
        """Convenience: ``begin_line`` + ``add_text`` + ``commit_line``.

        Returns the full byte-pair sequence the consumer should emit
        for a single new caption line, in order. The init sequence is
        included only on the first call (Roll-Up is one-shot).
        """
        out = self.begin_line()
        out.extend(self.add_text(text))
        out.extend(self.commit_line())
        return out


def filler_pair() -> tuple[int, int]:
    """Return the standard CEA-608 null byte pair ``(0x80, 0x80)``.

    Frames that have no caption activity emit this pair so the
    cccombiner element receives one byte-pair per video frame as it
    requires (``schedule=true`` mode).
    """
    return CEA608_NULL_BYTE, CEA608_NULL_BYTE
