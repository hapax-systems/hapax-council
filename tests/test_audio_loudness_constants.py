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

from shared.audio_loudness import MASTER_INPUT_MAKEUP_DB


def test_master_makeup_within_ladspa_range() -> None:
    assert -20 <= MASTER_INPUT_MAKEUP_DB <= 20
