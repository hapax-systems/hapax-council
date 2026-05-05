"""Config-lint regression pin for the backing-mix sidechain reverse ducker — YT bundle Phase 3 (#145).

Spec: docs/superpowers/specs/2026-04-18-youtube-broadcast-bundle-design.md §3.
Plan: docs/superpowers/plans/2026-04-20-youtube-broadcast-bundle-plan.md Phase 3.

The conf file installs into ``~/.config/pipewire/pipewire.conf.d/`` and
declares the ``hapax-backing-ducked`` virtual sink. These tests pin the
file structure so an accidental edit (e.g. dropping the sink name,
changing the ducker direction) trips immediately.

Historical: previously named ``ytube-over-24c-duck.conf`` and exposed
``hapax-24c-ducked`` — renamed 2026-05 with the PreSonus Studio 24c
hardware retirement.

The "module-loaded assertion via pw-cli ls Module" path from the plan
is OPERATOR-WALKED (requires running PipeWire), not a unit test —
covered by the runbook + post-install verify step.
"""

from __future__ import annotations

from pathlib import Path

CONF_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "pipewire"
    / "hapax-backing-ducked-sidechain.conf"
)


def test_conf_file_exists() -> None:
    assert CONF_PATH.exists(), f"backing-ducked sidechain conf missing at {CONF_PATH}"


def test_conf_declares_backing_ducked_sink() -> None:
    """The sink name `hapax-backing-ducked` is the routing fixed point
    that backing capture binds to. Renaming it breaks the route silently."""
    text = CONF_PATH.read_text()
    assert "hapax-backing-ducked" in text


def test_conf_uses_filter_chain_module() -> None:
    text = CONF_PATH.read_text()
    assert "libpipewire-module-filter-chain" in text


def test_conf_uses_sc4m_ladspa_plugin() -> None:
    """sc4m (Steve Harris LADSPA sc4 mono sidechain) is the chosen
    compressor — pin to catch a future swap to a different plugin."""
    text = CONF_PATH.read_text()
    assert "sc4m" in text
    assert "ladspa" in text.lower()


def test_conf_attack_release_match_spec() -> None:
    """Plan §lines 158-159: attack 50 ms, release 200 ms."""
    text = CONF_PATH.read_text()
    assert '"Attack time (ms)" = 50.0' in text
    assert '"Release time (ms)" = 200.0' in text


def test_conf_threshold_in_expected_range() -> None:
    """Spec §3.4 calls for ~-12 dB attenuation; threshold should be in
    a sane range (-30 to -20 dBFS) so YT triggers the duck without
    over-attenuating quiet beds."""
    text = CONF_PATH.read_text()
    # Pin to the chosen value — change requires explicit test edit
    assert '"Threshold level (dB)" = -26.0' in text


def test_conf_stereo_audio_position() -> None:
    text = CONF_PATH.read_text()
    assert "audio.position = [ FL FR ]" in text
    assert "audio.channels = 2" in text


def test_conf_has_install_documentation() -> None:
    """Header comment must explain the install + verify pattern. Future
    operators reading the conf find the install one-liner without
    digging into the plan."""
    text = CONF_PATH.read_text()
    assert "# INSTALL" in text
    assert "# VERIFY" in text
    assert "pipewire.conf.d" in text


def test_conf_documents_pairs_with_voice_over() -> None:
    """The reverse ducker pairs with hapax-voice-over-ytube-duck.conf to form
    the bidirectional matrix. Pin the cross-reference so removing one
    side's documentation triggers the test."""
    text = CONF_PATH.read_text()
    assert "voice-over-ytube-duck" in text


def test_conf_documents_loudness_normalization() -> None:
    """Spec §3.4 line 179: pre-PiP loudness normalization at -23 LUFS.
    The conf header documents this; the actual normalizer module is
    deferred to operator install (PR-3.3 of the plan)."""
    text = CONF_PATH.read_text()
    assert "LUFS" in text or "loudness" in text.lower()
