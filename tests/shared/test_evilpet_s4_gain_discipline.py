"""Gain-discipline regression pins — evilpet-s4-routing Phase 3.

Spec §9 invariant: software gain stages stay at unity unless the
existing documented exceptions (currently the L6 main-mix +12 dB
makeup) are explicitly justified in the conf header. Any new
filter-chain gain stage must update this test to keep the invariant
enforceable.

Also pins the R1 routing spec invariants so a future spec edit
can't silently delete the TTS → Evil Pet → livestream documentation
that downstream wiring depends on.

Plan: docs/superpowers/plans/2026-04-20-evilpet-s4-routing-plan.md §Phase 3
Spec: docs/superpowers/specs/2026-04-20-evilpet-s4-routing-design.md §4 R1, §9
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPEWIRE_DIR = REPO_ROOT / "config" / "pipewire"
SPEC_PATH = REPO_ROOT / "docs" / "superpowers" / "specs" / "2026-04-20-evilpet-s4-routing-design.md"


# Map of conf file → expected `Gain 1` linear value for the mixer
# stage(s) it carries. Any conf NOT listed must not introduce a
# `Gain 1` mixer control without updating this dict (the test below
# enforces that). Linear 4.0 ≈ +12 dB; 1.0 ≈ unity.
EXPECTED_MIXER_GAINS: dict[str, set[float]] = {
    "hapax-l6-evilpet-capture.conf": {4.0},  # L6 main-mix +12 dB makeup (legacy)
    "hapax-livestream-duck.conf": {1.0},  # PR-3 ducker default = pass-through
    # L-12 v5 per-channel pre-fader/post-comp software gain stages:
    # contact mic +3.5 dB (1.5), evilpet/rode/sampler +6 dB (2.0),
    # PC line unity (1.0), L+R summing unity (1.0).
    # Phase A2 (PR #1115) routed vinyl through Evil Pet so the standalone
    # +12 dB (4.0) handytraxx stage was removed; vinyl now gets its
    # makeup gain inside Evil Pet's L6 chain (4.0 there).
    # NOTE 2026-04-24: per-channel pre-fader gains (1.5 contact mic, 2.0
    # evilpet/rode/sampler) were reverted to unity in commit d59368e76
    # ("fix(audio): revert l12-evilpet filter to unity — mixer sums, not
    # averages"). PipeWire's builtin mixer sums inputs (per
    # reference_pipewire_builtin_mixer_sums memory) so the v5 plan's
    # per-channel makeup gains were over-driving the bus. Now: every
    # input lands at unity; makeup happens downstream in the L12 sink
    # filter chain.
    # NOTE 2026-05-03: gain_samp default-muted (Gain 1 = 0.0) per task
    # audio-l12-bleed-mitigation-narrow-aware. AUX3 (CH4 sampler chain)
    # bleeds white-noise into broadcast at idle through the +14 dB
    # downstream master makeup; default-mute is the safe broadcast
    # posture. The accepted set is now {0.0, 1.0} — 1.0 for the
    # evilpet/contact/rode pre-fader stages plus the L+R sum-bus inputs,
    # 0.0 for the muted sampler stage. Operator manually re-enables
    # gain_samp to 1.0 when actively running the sampler chain.
    # Supersedes closed PR #2422's 14-channel widening attempt; this
    # mitigation preserves the constitutional narrow [AUX1 AUX3 AUX4 AUX5]
    # binding while removing the broadcast-noise leak path.
    "hapax-l12-evilpet-capture.conf": {0.0, 1.0},
    # Audio Phase 4 sidechain ducking (PRs #1271-#1273): two mono mixers
    # per chain with controllable Gain 1. Both default 1.0 (passthrough);
    # hapax-audio-ducker.service writes attenuated values at runtime
    # (music: 0.251 / 0.398; tts: 0.398) when the relevant channel is
    # active. Static-config inspection only sees the documented baseline,
    # which is the unity passthrough.
    "hapax-music-duck.conf": {1.0},
    "hapax-tts-duck.conf": {1.0},
    # MPC-first wet return sums MPC content and Hapax voice from L-12
    # AUX8-AUX11 into the livestream tap. Static gains stay at unity;
    # level responsibility belongs to the MPC/L-12 hardware stages and
    # downstream broadcast limiter.
    "hapax-l12-usb-return-capture.conf": {1.0},
}

GAIN_RE = re.compile(r'"Gain 1"\s*=\s*([\d.]+)')


@pytest.fixture(scope="module")
def conf_gains() -> dict[str, set[float]]:
    """Parse every config/pipewire/*.conf and collect its Gain-1 values."""
    out: dict[str, set[float]] = {}
    for conf in sorted(PIPEWIRE_DIR.glob("*.conf")):
        text = conf.read_text(encoding="utf-8")
        values = {float(m.group(1)) for m in GAIN_RE.finditer(text)}
        if values:
            out[conf.name] = values
    return out


def test_only_expected_confs_carry_mixer_gain(
    conf_gains: dict[str, set[float]],
) -> None:
    """Every conf with a `Gain 1` mixer must be in the expected map.

    A new conf adding a gain stage must update EXPECTED_MIXER_GAINS;
    the failure message tells the operator how to extend it.
    """
    actual = set(conf_gains.keys())
    expected = set(EXPECTED_MIXER_GAINS.keys())
    new = actual - expected
    assert not new, (
        f"new conf(s) introduced a `Gain 1` mixer stage: {sorted(new)}.\n"
        "Update EXPECTED_MIXER_GAINS in this test with the new file's\n"
        "expected linear gain value(s) and document the rationale in the\n"
        "conf header (per spec §9)."
    )


def test_documented_mixer_gain_values_unchanged(
    conf_gains: dict[str, set[float]],
) -> None:
    """The documented +12 dB makeup gain (L6) and unity duck default
    must not silently regress. If a value changes, update both this
    test and the conf header rationale together."""
    for conf_name, expected_values in EXPECTED_MIXER_GAINS.items():
        actual_values = conf_gains.get(conf_name, set())
        assert actual_values == expected_values, (
            f"{conf_name}: Gain 1 values changed.\n"
            f"  expected: {sorted(expected_values)}\n"
            f"  actual:   {sorted(actual_values)}"
        )


def test_no_new_gain_above_plus_12db_ceiling(
    conf_gains: dict[str, set[float]],
) -> None:
    """Spec §9 ceiling: no software gain stage above +12 dB (linear 4.0).

    Linear 4.0 ≈ +12 dB; 4.5 would be ~+13 dB. The existing L6 +12 dB
    makeup is the documented maximum — any value strictly above is an
    immediate regression flag (operator must explicitly justify and
    downstream-attenuate per spec §9).
    """
    for conf_name, values in conf_gains.items():
        for v in values:
            assert v <= 4.0, (
                f"{conf_name}: Gain 1 = {v} exceeds the +12 dB ceiling. "
                "Spec §9 requires explicit justification + downstream attenuation."
            )


# ── R1 spec-doc invariants (TTS → Evil Pet → livestream) ──────────────


@pytest.fixture(scope="module")
def spec_text() -> str:
    if not SPEC_PATH.exists():
        pytest.skip(f"spec missing: {SPEC_PATH}")
    return SPEC_PATH.read_text(encoding="utf-8")


def test_spec_documents_r1_routing(spec_text: str) -> None:
    """R1 (TTS → Evil Pet) must remain in the spec — it's the
    cornerstone routing the daimonion + filter-chain depend on."""
    assert "R1" in spec_text
    assert "Evil Pet" in spec_text
    assert "TTS" in spec_text or "Kokoro" in spec_text


def test_spec_documents_r3_routing(spec_text: str) -> None:
    """R3 (S-4 USB-direct, parallel to Evil Pet) — pinned because Phase 1
    config + this test depend on the R3 wording staying live."""
    assert "R3" in spec_text
    assert "S-4" in spec_text


def test_spec_documents_gain_discipline(spec_text: str) -> None:
    """Spec §9 (gain discipline / signal quality) — the rationale this
    test enforces. If §9 is removed from the spec, the operator must
    decide whether the regression pins still apply."""
    assert "§9" in spec_text or "Signal Quality" in spec_text or "gain discipline" in spec_text
