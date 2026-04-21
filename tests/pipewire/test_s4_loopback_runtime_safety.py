"""Runtime-safety pins for the S-4 loopback config (B8 / audit High #12).

The existing `test_s4_loopback_conf.py` pins the descriptor shape
(node names, module choice, channel position, format) so a future edit
can't silently break R3 routing. This file adds a second line of defence:
the values must also be *accepted by PipeWire at load time*. Without
these pins, a fresh clone could boot with S-4 audio silently missing
because a typo slipped past the shape tests — e.g. `audio.format = S34`
(off-by-one from S32) parses fine but PipeWire rejects it with a log
error most operators never read.

The tests here parse the conf and validate each risky value against the
finite set PipeWire actually accepts. Kept deliberately narrow so they
document *why* the value is pinned, not just *that* it is.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "pipewire" / "hapax-s4-loopback.conf"


@pytest.fixture()
def raw_config() -> str:
    if not CONFIG_PATH.exists():
        pytest.skip("hapax-s4-loopback.conf missing from repo checkout")
    return CONFIG_PATH.read_text(encoding="utf-8")


# PipeWire `audio.format` accepts this exact vocabulary (see spa/param/audio/format.h).
# Anything else logs "invalid format" and the loopback silently fails to bind
# its adapter — the hazard this file guards against.
_VALID_AUDIO_FORMATS = frozenset(
    {
        "U8",
        "S8",
        "U16",
        "S16",
        "S16LE",
        "S16BE",
        "U24",
        "S24",
        "S24LE",
        "S24BE",
        "U24_32",
        "S24_32",
        "S24_32LE",
        "S24_32BE",
        "U32",
        "S32",
        "S32LE",
        "S32BE",
        "F32",
        "F32LE",
        "F32BE",
        "F64",
        "F64LE",
        "F64BE",
    }
)

# PipeWire channel-position tokens (narrow set — S-4 is stereo; exhaustive list
# lives in spa/param/audio/raw.h). If a future edit adds surround positions,
# extend this set rather than relaxing the test.
_VALID_CHANNEL_POSITIONS = frozenset({"FL", "FR", "FC", "LFE", "SL", "SR", "RL", "RR", "MONO"})


def test_audio_format_is_accepted_by_pipewire(raw_config: str) -> None:
    """audio.format must be in PipeWire's accepted set — not just 'looks right'."""
    matches = re.findall(r"audio\.format\s*=\s*(\S+)", raw_config)
    assert matches, "conf declares no audio.format — loopback can't bind without one"
    for fmt in matches:
        assert fmt in _VALID_AUDIO_FORMATS, (
            f"audio.format={fmt!r} is not in PipeWire's accepted vocabulary. "
            f"Typos here produce silent runtime failure (adapter never binds)."
        )


def test_audio_rate_is_common_sample_rate(raw_config: str) -> None:
    """audio.rate must be one of the rates the S-4 + downstream graph share.

    48 kHz is the native S-4 USB rate and the graph-wide quantum alignment.
    If this drifts, the loopback resamples silently (CPU hit) or fails to
    bind if the downstream tap can't renegotiate.
    """
    matches = re.findall(r"audio\.rate\s*=\s*(\d+)", raw_config)
    assert matches, "conf declares no audio.rate"
    for rate in matches:
        assert int(rate) in {44100, 48000, 88200, 96000}, (
            f"audio.rate={rate} is unusual — if intentional, widen this test, "
            f"but first confirm the rest of the graph can align."
        )


def test_channel_positions_are_valid(raw_config: str) -> None:
    """audio.position tokens must be recognised by PipeWire's position parser."""
    # Find each `audio.position = [ ... ]` list in the conf.
    position_blocks = re.findall(r"audio\.position\s*=\s*\[([^\]]+)\]", raw_config)
    assert position_blocks, "conf declares no audio.position list"
    for block in position_blocks:
        tokens = [t for t in block.split() if t]
        for tok in tokens:
            assert tok in _VALID_CHANNEL_POSITIONS, (
                f"audio.position token {tok!r} not recognised. PipeWire will "
                f"drop the channel silently if the token doesn't parse."
            )


def test_position_lists_are_internally_consistent(raw_config: str) -> None:
    """All audio.position lists must have the same length, and if audio.channels
    is declared anywhere, it must equal that length. Mismatch = bind failure.

    PipeWire permits either side of a loopback to omit audio.channels (it's
    inferred from audio.position), but the two sides must agree — otherwise
    the adapter refuses to bridge them.
    """
    position_blocks = re.findall(r"audio\.position\s*=\s*\[([^\]]+)\]", raw_config)
    assert position_blocks, "conf declares no audio.position lists"
    lengths = {len([t for t in block.split() if t]) for block in position_blocks}
    assert len(lengths) == 1, (
        f"audio.position lists have inconsistent lengths {lengths} — "
        f"the two sides of the loopback will not bridge."
    )
    (expected,) = lengths
    channel_matches = re.findall(r"audio\.channels\s*=\s*(\d+)", raw_config)
    for count_str in channel_matches:
        assert int(count_str) == expected, (
            f"audio.channels={count_str} but audio.position has {expected} "
            f"tokens — PipeWire will refuse the adapter."
        )


def test_loopback_module_exists_in_pipewire(raw_config: str) -> None:
    """The named module must actually exist in the PipeWire install.

    `libpipewire-module-loopback` is the canonical name; historical variants
    like `pipewire-module-loopback` (without 'lib') don't load. This pin
    catches the copy-paste error class.
    """
    module_names = re.findall(r"name\s*=\s*(libpipewire-module-\S+)", raw_config)
    assert module_names, "no libpipewire-module-* referenced"
    for name in module_names:
        # Deterministic set — expand as we adopt new modules.
        assert name in {
            "libpipewire-module-loopback",
            "libpipewire-module-filter-chain",
            "libpipewire-module-echo-cancel",
            "libpipewire-module-combine-stream",
            "libpipewire-module-roc-source",
            "libpipewire-module-rt",
        }, f"module {name!r} not in the known-good PipeWire module set"
