"""Regression test: L-12 broadcast capture must drop vinyl + PC + MASTER channels.

Pins the post-2026-04-21 architecture where the only non-microphone source
reaching broadcast is the Evil Pet hardware return (AUX5). Direct vinyl
capture (AUX8/9), direct PC capture (AUX10/11), and MASTER capture (AUX12/13)
are all unbound from the capture node.

Trigger: 2026-04-23 ContentID warning during vinyl-through-Evil-Pet wet
processing motivated the broader content-source registry epic. This test
prevents accidental reintroduction of direct vinyl capture in any future PR.

Post-2026-04-25 (PR #1471): the capture node was further narrowed from
``audio.channels = 14`` (with null entries for unused AUX positions) to
``audio.channels = 4`` (only the AUX positions actually wired into the
filter graph: AUX1 contact / AUX3 sampler / AUX4 rode / AUX5 evilpet).
The forbidden AUX positions (8-13) now don't exist in the binding at
all — a stronger invariant than "bound but null". This test reflects
that structural shape.

Related: ``docs/governance/evil-pet-broadcast-source-policy.md``,
``config/pipewire/hapax-l12-evilpet-capture.conf``.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
L12_CAPTURE_CONF = REPO_ROOT / "config" / "pipewire" / "hapax-l12-evilpet-capture.conf"

# Per the post-PR-#1471 narrowing, exactly these 4 AUX positions are bound
# to the capture node. Order matters for positional inputs[] mapping.
EXPECTED_AUX_POSITIONS = ["AUX1", "AUX3", "AUX4", "AUX5"]

# AUX positions that MUST NOT appear in the capture binding because their
# inclusion would reintroduce known-bad broadcast paths (digital feedback
# loop on AUX10/11, vinyl-bypassing-Evil-Pet on AUX8/9, master-fader
# bleed on AUX12/13).
FORBIDDEN_AUX_POSITIONS = {
    "AUX8": "vinyl L (Korg Handytraxx) — must reach broadcast only via Evil Pet",
    "AUX9": "vinyl R (Korg Handytraxx) — must reach broadcast only via Evil Pet",
    "AUX10": "PC L (Ryzen line-out) — must reach broadcast only via Evil Pet (digital loop)",
    "AUX11": "PC R (Ryzen line-out) — must reach broadcast only via Evil Pet (digital loop)",
    "AUX12": "MASTER L — must not be captured (physical-fader bleeds into broadcast)",
    "AUX13": "MASTER R — must not be captured (physical-fader bleeds into broadcast)",
}


def _extract_audio_position(text: str) -> list[str]:
    """Pull the ``audio.position = [ ... ]`` list from capture.props."""
    # Match the audio.position inside the capture.props block specifically.
    capture_match = re.search(r"capture\.props\s*=\s*\{(.*?)\}", text, re.DOTALL)
    assert capture_match, "could not locate capture.props block in L-12 capture conf"
    capture_body = capture_match.group(1)
    pos_match = re.search(r"audio\.position\s*=\s*\[(.*?)\]", capture_body, re.DOTALL)
    assert pos_match, "could not locate audio.position in capture.props"
    return [tok for tok in pos_match.group(1).split() if tok]


def _extract_audio_channels(text: str) -> int:
    """Pull the ``audio.channels = N`` count from capture.props."""
    capture_match = re.search(r"capture\.props\s*=\s*\{(.*?)\}", text, re.DOTALL)
    assert capture_match, "could not locate capture.props block in L-12 capture conf"
    ch_match = re.search(r"audio\.channels\s*=\s*(\d+)", capture_match.group(1))
    assert ch_match, "could not locate audio.channels in capture.props"
    return int(ch_match.group(1))


def _extract_inputs_array(text: str) -> list[str]:
    """Pull the filter-graph ``inputs = [ ... ]`` array. Returns gain-stage
    names in positional order (one per AUX channel that's actually bound).
    """
    match = re.search(r"inputs\s*=\s*\[(.*?)\]", text, re.DOTALL)
    assert match, "could not locate inputs array in L-12 capture conf"
    body = match.group(1)
    entries: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line == "null":
            raise AssertionError(
                "post-PR-#1471 inputs[] must contain no nulls — every entry should "
                f"map positionally to an AUX position; found stray null in {raw_line!r}"
            )
        if line.startswith('"') and '"' in line[1:]:
            end = line.index('"', 1)
            entries.append(line[1:end])
        else:
            raise AssertionError(f"unrecognized inputs entry: {raw_line!r}")
    return entries


def test_l12_capture_conf_exists() -> None:
    assert L12_CAPTURE_CONF.is_file(), f"missing {L12_CAPTURE_CONF}"


def test_l12_capture_drops_vinyl_pc_master_channels() -> None:
    """Forbidden AUX positions (8-13: vinyl, PC, MASTER) MUST be unbound.

    Post-PR-#1471, "unbound" is enforced structurally — those AUX positions
    are absent from ``audio.position`` rather than bound-with-null-entry.
    Either form satisfies the architectural invariant; this test asserts
    the stronger structural form.
    """
    text = L12_CAPTURE_CONF.read_text(encoding="utf-8")
    positions = _extract_audio_position(text)

    violations = [
        (pos, FORBIDDEN_AUX_POSITIONS[pos]) for pos in positions if pos in FORBIDDEN_AUX_POSITIONS
    ]
    assert not violations, (
        "L-12 capture conf reintroduces forbidden broadcast inputs:\n"
        + "\n".join(f"  {pos} — {reason}" for pos, reason in violations)
    )


def test_l12_capture_keeps_evilpet_return_input() -> None:
    """AUX5 (Evil Pet return on CH6) is the architecturally-required input.

    If this is ever absent from ``audio.position`` or its corresponding
    inputs[] entry doesn't feed ``gain_evilpet``, the only non-microphone
    broadcast path is gone and operator can no longer route Evil Pet
    content to broadcast.
    """
    text = L12_CAPTURE_CONF.read_text(encoding="utf-8")
    positions = _extract_audio_position(text)
    inputs = _extract_inputs_array(text)

    assert "AUX5" in positions, (
        "AUX5 (Evil Pet return) was dropped from audio.position — "
        "broadcast loses its non-mic source"
    )
    assert len(inputs) == len(positions), (
        f"inputs[] length ({len(inputs)}) must match audio.position length "
        f"({len(positions)}) — positional mapping is the binding contract"
    )
    aux5_idx = positions.index("AUX5")
    aux5_input = inputs[aux5_idx]
    assert "evilpet" in aux5_input.lower(), f"AUX5 must feed gain_evilpet, got {aux5_input!r}"


def test_l12_capture_channels_count_matches_position_and_inputs() -> None:
    """``audio.channels`` MUST equal ``audio.position`` length AND ``inputs[]``
    length. Mismatch is the bug class PR #1471 fixed: bound-but-unwired
    positions silently capture phantom signal (digital feedback loop).
    """
    text = L12_CAPTURE_CONF.read_text(encoding="utf-8")
    channels = _extract_audio_channels(text)
    positions = _extract_audio_position(text)
    inputs = _extract_inputs_array(text)

    assert channels == len(positions), (
        f"audio.channels ({channels}) != len(audio.position) ({len(positions)}); "
        "this mismatch is the digital-loop bug class fixed in PR #1471"
    )
    assert channels == len(inputs), (
        f"audio.channels ({channels}) != len(inputs) ({len(inputs)}); "
        "filter graph must read every bound channel"
    )


def test_l12_capture_position_matches_expected_set() -> None:
    """The exact AUX position set is pinned to AUX1/AUX3/AUX4/AUX5 — the
    contact mic / sampler / rode / Evil-Pet-return quad. Any other set
    is a regression of PR #1471's narrowing.
    """
    text = L12_CAPTURE_CONF.read_text(encoding="utf-8")
    positions = _extract_audio_position(text)
    assert positions == EXPECTED_AUX_POSITIONS, (
        f"audio.position drifted from the post-PR-#1471 narrowed set "
        f"{EXPECTED_AUX_POSITIONS}; got {positions}"
    )


def test_l12_capture_pins_dont_remix_flag() -> None:
    """``stream.dont-remix = true`` MUST be set in capture.props.

    Per RCA #2441 (`docs/research/2026-05-03-l12-evilpet-channelmix-rca.md`),
    omitting this flag causes PipeWire's audioconvert adapter to apply a
    14→4 surround channelmix matrix when reducing the L-12's native
    14-channel USB-IN down to the 4 declared AUX positions. The matrix
    mapped CH3 USB-IN content (AUX2 — operator-declared "reserve") into
    the AUX5 capture slot at gain ~0.4, masquerading as Evil Pet return
    on the broadcast bus.

    Empirical evidence from the OBS-noise incident: AUX2 cross-correlation
    +0.998 vs AUX5 +0.386 against the broadcast-master signal — the
    AUX5 broadcast slot was carrying primarily AUX2 content, not Evil
    Pet return.

    Setting ``stream.dont-remix = true`` pins each declared AUX position
    1:1 to its corresponding USB-IN channel (no remix matrix), matching
    the working reference pattern in
    ``~/.config/pipewire/pipewire.conf.d/10-contact-mic.conf``.

    If this flag goes missing in any future revision, the channelmix
    leak reappears and OBS broadcast carries phantom signal again.
    """
    text = L12_CAPTURE_CONF.read_text(encoding="utf-8")
    capture_match = re.search(r"capture\.props\s*=\s*\{(.*?)\}", text, re.DOTALL)
    assert capture_match, "could not locate capture.props block in L-12 capture conf"
    capture_body = capture_match.group(1)
    assert re.search(r"stream\.dont-remix\s*=\s*true", capture_body), (
        "capture.props must declare `stream.dont-remix = true` to disable "
        "the PipeWire 14→4 channelmix matrix that leaks AUX2 into AUX5 "
        "(per RCA #2441 / cc-task audio-l12-evilpet-channelmix-stride-fix)"
    )
