"""Regression test: L-12 broadcast capture must drop vinyl + PC + MASTER channels.

Pins the post-2026-04-21 architecture where the only non-microphone source
reaching broadcast is the Evil Pet hardware return (AUX5). Direct vinyl
capture (AUX8/9), direct PC capture (AUX10/11), and MASTER capture (AUX12/13)
are all dropped from the filter-chain inputs.

Trigger: 2026-04-23 ContentID warning during vinyl-through-Evil-Pet wet
processing motivated the broader content-source registry epic. This test
prevents accidental reintroduction of direct vinyl capture in any future PR.

Related: `docs/governance/evil-pet-broadcast-source-policy.md`,
`config/pipewire/hapax-l12-evilpet-capture.conf`.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
L12_CAPTURE_CONF = REPO_ROOT / "config" / "pipewire" / "hapax-l12-evilpet-capture.conf"


def _extract_inputs_array(text: str) -> list[str | None]:
    """Pull the `inputs = [ ... ]` array literal from the filter-chain conf.

    Returns a 14-element list where each entry is either the gain-stage
    name (e.g. "gain_evilpet:In 1") or None for dropped channels. The
    parser is intentionally narrow — it understands only this file's
    layout, not arbitrary PipeWire SPA conf.
    """
    match = re.search(r"inputs\s*=\s*\[(.*?)\]", text, re.DOTALL)
    assert match, "could not locate inputs array in L-12 capture conf"
    body = match.group(1)
    entries: list[str | None] = []
    for raw_line in body.splitlines():
        # strip trailing comment
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line == "null":
            entries.append(None)
        elif line.startswith('"') and '"' in line[1:]:
            end = line.index('"', 1)
            entries.append(line[1:end])
        else:
            # unrecognized syntactic shape — treat as parse failure
            raise AssertionError(f"unrecognized inputs entry: {raw_line!r}")
    return entries


def test_l12_capture_conf_exists() -> None:
    assert L12_CAPTURE_CONF.is_file(), f"missing {L12_CAPTURE_CONF}"


def test_l12_capture_drops_vinyl_pc_master_channels() -> None:
    """AUX8/9 (vinyl), AUX10/11 (PC direct), AUX12/13 (MASTER) MUST be null.

    The broadcast capture filter sums per-channel gain stages; any non-null
    entry at these positions reintroduces a direct broadcast path that
    bypasses the Evil Pet hardware loop. Only Evil Pet return is the
    architecturally-correct non-mic source.
    """
    text = L12_CAPTURE_CONF.read_text(encoding="utf-8")
    inputs = _extract_inputs_array(text)
    assert len(inputs) == 14, f"expected 14 capture inputs (AUX0..AUX13), found {len(inputs)}"

    forbidden_aux = {
        8: "vinyl L (Korg Handytraxx) — must reach broadcast only via Evil Pet",
        9: "vinyl R (Korg Handytraxx) — must reach broadcast only via Evil Pet",
        10: "PC L (Ryzen line-out) — must reach broadcast only via Evil Pet",
        11: "PC R (Ryzen line-out) — must reach broadcast only via Evil Pet",
        12: "MASTER L — must not be captured (physical-fader bleeds into broadcast)",
        13: "MASTER R — must not be captured (physical-fader bleeds into broadcast)",
    }
    violations = [
        (aux, reason, inputs[aux])
        for aux, reason in forbidden_aux.items()
        if inputs[aux] is not None
    ]
    assert not violations, (
        "L-12 capture conf reintroduces forbidden broadcast inputs:\n"
        + "\n".join(f"  AUX{aux} = {value!r} — {reason}" for aux, reason, value in violations)
    )


def test_l12_capture_keeps_evilpet_return_input() -> None:
    """AUX5 (Evil Pet return on CH6) is the architecturally-required input.

    If this is ever null, the only non-microphone broadcast path is gone
    and operator can no longer route Evil Pet content to broadcast.
    Pinned defensively.
    """
    text = L12_CAPTURE_CONF.read_text(encoding="utf-8")
    inputs = _extract_inputs_array(text)
    assert inputs[5] is not None, (
        "AUX5 (Evil Pet return) was dropped — broadcast loses its non-mic source"
    )
    assert "evilpet" in inputs[5].lower(), f"AUX5 must feed gain_evilpet, got {inputs[5]!r}"
