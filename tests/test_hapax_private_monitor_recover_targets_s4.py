"""Pin Option C target string in `scripts/hapax-private-monitor-recover`.

This regression test enforces the constitutional invariant that the private
monitor recovery script targets the S-4 USB IN multichannel-output sink (not
the Blue Yeti) per the Option C spec amendment of 2026-05-02. Pinning the
exact string at module load time prevents a silent regression where someone
flips it back to the Yeti string (which would re-introduce the L-12 leak path
because the Yeti pin lives outside the audited Track-1-fenced architecture).

Privacy invariant reference:
    feedback_l12_equals_livestream_invariant — anything entering L-12 reaches
    broadcast. Private monitor streams MUST route to a private-fenced
    destination outside L-12.

Spec amendment:
    docs/superpowers/specs/2026-05-02-hapax-private-monitor-track-fenced-via-s4.md
"""

from __future__ import annotations

import importlib.util
import sys
import types
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "hapax-private-monitor-recover"

S4_USB_SINK = "alsa_output.usb-Torso_Electronics_S-4_fedcba9876543220-03.multichannel-output"
YETI_TARGET_LEGACY = "alsa_output.usb-Blue_Microphones_Yeti_Stereo_Microphone_REV8-00.analog-stereo"


def _load_recover_script() -> types.ModuleType:
    """Load the extension-less recover script as an importable module."""
    loader = SourceFileLoader("_recover_option_c_target_pin", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def recover() -> types.ModuleType:
    return _load_recover_script()


def test_exact_target_pins_to_s4_usb_in_sink(recover: types.ModuleType) -> None:
    """`EXACT_PRIVATE_MONITOR_TARGET` must be the S-4 USB IN sink, not Yeti."""
    assert recover.EXACT_PRIVATE_MONITOR_TARGET == S4_USB_SINK, (
        f"recover script must target S-4 USB IN sink under Option C; "
        f"got {recover.EXACT_PRIVATE_MONITOR_TARGET!r}"
    )


def test_exact_target_is_not_the_legacy_yeti_string(recover: types.ModuleType) -> None:
    """Defense-in-depth: pin the negative as well so a flip back is loud."""
    assert recover.EXACT_PRIVATE_MONITOR_TARGET != YETI_TARGET_LEGACY


def test_sanitized_refs_indicate_s4_route(recover: types.ModuleType) -> None:
    """Sanitized refs in the status JSON must reflect Option C, not Yeti."""
    assert recover.ROUTE_REF == "route:private.s4_track_fenced"
    assert recover.SANITIZED_TARGET_REF == "audio.s4_private_monitor"
    # The legacy yeti_monitor refs must be GONE.
    assert "yeti_monitor" not in recover.ROUTE_REF
    assert "yeti_monitor" not in recover.SANITIZED_TARGET_REF


def test_script_source_does_not_carry_yeti_target_string() -> None:
    """The recover script source must not contain the literal Yeti sink.

    Pinning the source-level absence catches a regression in either the
    constant or in supporting helper code (e.g. validation strings).
    The Yeti pin is preserved on disk under
    `config/wireplumber/56-hapax-private-pin-yeti.conf.disabled-2026-05-02-option-c`
    for revert capability — the recover script does NOT mention it.
    """
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert YETI_TARGET_LEGACY not in text, (
        "Recover script must not carry the legacy Yeti sink string under Option C"
    )
    assert S4_USB_SINK in text


def test_script_validate_repo_bridge_requires_s4_target(
    recover: types.ModuleType, tmp_path: Path
) -> None:
    """`_validate_repo_bridge` must accept S-4 bridge content + reject pre-Option-C
    bridge content that still hardcodes the Yeti target."""
    repo_bridge = tmp_path / "hapax-private-monitor-bridge.conf"

    # Synthesize a minimally-valid Option C bridge: includes the S-4 sink
    # string AND the fail-closed pins the validator requires.
    valid_bridge = (
        f'target.object = "{S4_USB_SINK}"\n'
        "node.dont-fallback = true\n"
        "node.dont-reconnect = true\n"
        "node.dont-move = true\n"
        "node.linger = true\n"
        "state.restore = false\n"
        'target.object = "hapax-private"\n'
        'target.object = "hapax-notification-private"\n'
    )
    repo_bridge.write_text(valid_bridge, encoding="utf-8")
    # Should not raise.
    recover._validate_repo_bridge(repo_bridge)

    # Pre-Option C bridge (Yeti target only) is now invalid because
    # EXACT_PRIVATE_MONITOR_TARGET is the S-4 string.
    invalid_bridge = valid_bridge.replace(S4_USB_SINK, YETI_TARGET_LEGACY)
    repo_bridge.write_text(invalid_bridge, encoding="utf-8")
    with pytest.raises(ValueError, match="missing required fail-closed pin"):
        recover._validate_repo_bridge(repo_bridge)
