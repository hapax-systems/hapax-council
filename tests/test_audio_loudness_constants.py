"""Regression pin: audio loudness constants must stay in LADSPA-accepted range.

Audit finding B#4 (2026-05-02): the prior +27 dB line-driver bias was
silently rejected by ``fast_lookahead_limiter_1913`` because that LADSPA
plugin's ``Input gain (dB)`` control accepts values in ``[-20, +20]`` only.
Out-of-range controls do not raise — they are dropped, leaving the chain
running without the intended gain. This pin ensures any future change to
``MASTER_INPUT_MAKEUP_DB`` stays inside the accepted range so the failure
mode cannot recur silently.

If a louder makeup is ever justified, split the gain across multiple
LADSPA stages (≤ +20 dB each) rather than pushing a single stage out of
range.
"""

from __future__ import annotations

import re
from pathlib import Path

from shared.audio_loudness import (
    EGRESS_TRUE_PEAK_DBTP,
    MASTER_INPUT_MAKEUP_DB,
    MASTER_LIMITER_RELEASE_MS,
)


def test_master_makeup_within_ladspa_range() -> None:
    assert -20 <= MASTER_INPUT_MAKEUP_DB <= 20


def test_broadcast_master_pipewire_config_matches_loudness_constants() -> None:
    conf = (
        Path(__file__).resolve().parents[1] / "config" / "pipewire" / "hapax-broadcast-master.conf"
    )
    text = "\n".join(
        line.split("#", 1)[0] for line in conf.read_text(encoding="utf-8").splitlines()
    )

    controls = {
        match.group("name"): float(match.group("value"))
        for match in re.finditer(
            r'"(?P<name>Input gain \(dB\)|Limit \(dB\)|Release time \(s\))"'
            r"\s*=\s*(?P<value>-?\d+(?:\.\d+)?)",
            text,
        )
    }

    assert controls["Input gain (dB)"] == MASTER_INPUT_MAKEUP_DB == 16.0
    assert controls["Limit (dB)"] == EGRESS_TRUE_PEAK_DBTP
    assert controls["Release time (s)"] == MASTER_LIMITER_RELEASE_MS / 1000.0
