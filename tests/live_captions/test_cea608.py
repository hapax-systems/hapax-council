"""Tests for ``agents.live_captions.cea608``.

Coverage:

- Odd-parity invariants (every emitted byte has odd one-count).
- ASCII folding for non-encodable Unicode.
- Roll-Up init sequence ordering (ENM → EDM → RU3 → CR).
- Carriage-return / line-budget / truncation behavior.
- Filler-pair shape.
- Stateful encoder workflow: idempotent init, line counter resets,
  RuntimeError on add_text before begin_line.
"""

from __future__ import annotations

import pytest

from agents.live_captions.cea608 import (
    CEA608_LINE_WIDTH,
    CEA608_NULL_BYTE,
    CR,
    EDM,
    ENM,
    RU3,
    CaptionFrame,
    RollUpEncoder,
    RollUpEncoderState,
    filler_pair,
    fold_to_ascii,
    odd_parity,
    text_to_byte_pairs,
    with_parity,
)

# ── Parity ───────────────────────────────────────────────────────────────


class TestOddParity:
    @pytest.mark.parametrize(
        "byte,expected",
        [
            (0x00, 0x80),  # 0 ones → set high bit
            (0x01, 0x01),  # 1 one (odd) → leave alone
            (0x03, 0x83),  # 2 ones → set high bit
            (0x07, 0x07),  # 3 ones (odd) → leave alone
            (0x41, 0xC1),  # 'A' = 01000001 (2 ones) → set high bit
            (0x4D, 0x4D),  # 'M' = 01001101 (4 ones) → wait, even → set
            # 'M' is 0x4D = 0100_1101, ones = 4 (even) → 0xCD
        ],
    )
    def test_specific_values(self, byte: int, expected: int) -> None:
        # Recompute expected from definition for safety.
        ones = bin(byte).count("1")
        canonical = byte if ones % 2 == 1 else byte | 0x80
        assert odd_parity(byte) == canonical

    def test_all_low_bytes_emit_odd_parity(self) -> None:
        """For every byte in [0, 0x7F], the parity-applied byte has an
        odd number of set bits across all 8 bits."""
        for b in range(0x80):
            out = odd_parity(b)
            assert bin(out).count("1") % 2 == 1, f"byte 0x{b:02X} → 0x{out:02X} has even parity"

    @pytest.mark.parametrize("byte", [0x80, 0xFF, -1, 256])
    def test_rejects_out_of_range(self, byte: int) -> None:
        with pytest.raises(ValueError):
            odd_parity(byte)


class TestWithParity:
    def test_applies_to_both_bytes(self) -> None:
        assert with_parity((0x14, 0x26)) == (odd_parity(0x14), odd_parity(0x26))


# ── Fold to ASCII ────────────────────────────────────────────────────────


class TestFoldToAscii:
    def test_printable_passes_through(self) -> None:
        assert fold_to_ascii("Hello, world!") == "Hello, world!"

    def test_non_ascii_replaced_with_question_mark(self) -> None:
        assert fold_to_ascii("café") == "caf?"

    def test_em_dash_replaced(self) -> None:
        assert fold_to_ascii("yes — no") == "yes ? no"

    def test_tab_becomes_space(self) -> None:
        assert fold_to_ascii("a\tb") == "a b"

    def test_other_controls_dropped(self) -> None:
        assert fold_to_ascii("a\x00\x01b") == "ab"

    def test_empty_string(self) -> None:
        assert fold_to_ascii("") == ""


# ── Text → byte pairs ────────────────────────────────────────────────────


class TestTextToBytePairs:
    def test_empty_text_yields_no_pairs(self) -> None:
        assert text_to_byte_pairs("") == []

    def test_single_char_pads_with_null(self) -> None:
        pairs = text_to_byte_pairs("A")
        assert len(pairs) == 1
        # First byte: 'A' with parity applied.
        # Second byte: NULL with parity (0x80 high bit alone is odd parity).
        assert pairs[0] == (odd_parity(ord("A")), odd_parity(CEA608_NULL_BYTE & 0x7F))

    def test_two_chars_one_pair(self) -> None:
        pairs = text_to_byte_pairs("AB")
        assert len(pairs) == 1
        assert pairs[0] == (odd_parity(ord("A")), odd_parity(ord("B")))

    def test_odd_length_pads_trailing(self) -> None:
        pairs = text_to_byte_pairs("ABC")
        assert len(pairs) == 2
        assert pairs[0] == (odd_parity(ord("A")), odd_parity(ord("B")))
        # Trailing 'C' + NULL filler.
        assert pairs[1][0] == odd_parity(ord("C"))

    def test_every_byte_has_odd_parity(self) -> None:
        for pair in text_to_byte_pairs("Hello, captions!"):
            for byte in pair:
                assert bin(byte).count("1") % 2 == 1


# ── Filler pair ──────────────────────────────────────────────────────────


class TestFillerPair:
    def test_returns_canonical_null_pair(self) -> None:
        assert filler_pair() == (CEA608_NULL_BYTE, CEA608_NULL_BYTE)


# ── Roll-Up encoder ──────────────────────────────────────────────────────


class TestRollUpEncoderInit:
    def test_init_sequence_is_enm_edm_ru3_cr(self) -> None:
        """First begin_line must emit ENM → EDM → RU3 → CR in order."""
        enc = RollUpEncoder()
        seq = enc.begin_line()
        assert seq == [
            with_parity(ENM),
            with_parity(EDM),
            with_parity(RU3),
            with_parity(CR),
        ]
        assert enc.initialized

    def test_init_sequence_emitted_only_once(self) -> None:
        enc = RollUpEncoder()
        first = enc.begin_line()
        enc.add_text("hi")
        enc.commit_line()
        second = enc.begin_line()
        assert len(first) == 4
        assert second == []  # init not re-emitted

    def test_state_can_be_injected(self) -> None:
        state = RollUpEncoderState(initialized=True, current_line_chars=0)
        enc = RollUpEncoder(state)
        assert enc.begin_line() == []  # already initialized


class TestRollUpEncoderTextFlow:
    def test_add_text_before_init_raises(self) -> None:
        enc = RollUpEncoder()
        with pytest.raises(RuntimeError, match="begin_line"):
            enc.add_text("hi")

    def test_commit_line_before_init_raises(self) -> None:
        enc = RollUpEncoder()
        with pytest.raises(RuntimeError, match="begin_line"):
            enc.commit_line()

    def test_add_text_returns_byte_pairs(self) -> None:
        enc = RollUpEncoder()
        enc.begin_line()
        pairs = enc.add_text("hi")
        assert pairs == [(odd_parity(ord("h")), odd_parity(ord("i")))]

    def test_commit_line_emits_cr_pair(self) -> None:
        enc = RollUpEncoder()
        enc.begin_line()
        enc.add_text("ok")
        cr = enc.commit_line()
        assert cr == [with_parity(CR)]

    def test_line_chars_reset_after_commit(self) -> None:
        enc = RollUpEncoder()
        enc.begin_line()
        enc.add_text("hi")
        assert enc.state.current_line_chars == 2
        enc.commit_line()
        assert enc.state.current_line_chars == 0

    def test_truncates_when_over_budget(self) -> None:
        enc = RollUpEncoder()
        enc.begin_line()
        text = "x" * (CEA608_LINE_WIDTH + 10)
        pairs = enc.add_text(text)
        # Exactly LINE_WIDTH characters land on the wire (last 3 are "...").
        # Each pair carries 2 chars, so pair count is ceil(LINE_WIDTH/2).
        assert len(pairs) == (CEA608_LINE_WIDTH + 1) // 2

    def test_truncation_includes_ellipsis(self) -> None:
        enc = RollUpEncoder()
        enc.begin_line()
        text = "abcdefghij" * 4  # 40 chars
        enc.add_text(text)
        # Reconstruct emitted characters from byte pairs.
        emitted = bytearray()
        for pair in enc.state.pending_pairs:
            emitted.extend(p & 0x7F for p in pair)
        emitted_text = emitted.decode("ascii", errors="replace").rstrip("\x00")
        assert emitted_text.endswith("...")
        assert len(emitted_text) <= CEA608_LINE_WIDTH

    def test_drops_input_after_full_budget(self) -> None:
        enc = RollUpEncoder()
        enc.begin_line()
        enc.add_text("x" * CEA608_LINE_WIDTH)
        # No room left.
        assert enc.add_text("more") == []


class TestRollUpEncoderConvenience:
    def test_encode_line_round_trip(self) -> None:
        enc = RollUpEncoder()
        seq = enc.encode_line("HELLO")
        # Init (4) + text pairs (3 = "HE", "LL", "O\x00") + CR (1) = 8.
        assert len(seq) == 4 + 3 + 1
        assert seq[0] == with_parity(ENM)
        assert seq[-1] == with_parity(CR)

    def test_second_line_skips_init(self) -> None:
        enc = RollUpEncoder()
        first = enc.encode_line("ONE")
        second = enc.encode_line("TWO")
        # First call: init (4) + text + CR.
        # Second call: just text + CR (no init).
        assert first[0] == with_parity(ENM)
        assert second[0] != with_parity(ENM)


# ── CaptionFrame shape ───────────────────────────────────────────────────


class TestCaptionFrame:
    def test_filler_flag_recorded(self) -> None:
        frame = CaptionFrame(ts=1.0, byte_pair=(0x80, 0x80), is_filler=True)
        assert frame.is_filler
        assert frame.byte_pair == (0x80, 0x80)

    def test_dataclass_is_frozen(self) -> None:
        frame = CaptionFrame(ts=1.0, byte_pair=(0x41, 0x42), is_filler=False)
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            frame.ts = 2.0  # type: ignore[misc]
