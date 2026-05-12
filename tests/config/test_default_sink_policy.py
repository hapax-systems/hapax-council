"""Default sink policy must not contradict the MPC/L-12 broadcast boundary."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SINK_CONF = REPO_ROOT / "config" / "wireplumber" / "10-default-sink-ryzen.conf"
USB_RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "usb-s4-l12-topology-hardening.md"
USB_WITNESS = REPO_ROOT / "scripts" / "hapax-usb-topology-witness"

L12_SINK = (
    "alsa_output.usb-ZOOM_Corporation_L-12_8253FFFFFFFFFFFF9B5FFFFFFFFFFFFF-00.analog-surround-40"
)
LOCAL_DEFAULT_SINK = "alsa_output.pci-0000_73_00.6.analog-stereo"


def test_wireplumber_default_sink_policy_prefers_local_and_deprioritizes_l12() -> None:
    text = DEFAULT_SINK_CONF.read_text(encoding="utf-8")
    assert LOCAL_DEFAULT_SINK in text
    assert L12_SINK in text
    assert "priority.session = 1500" in text
    assert "priority.session = 200" in text
    assert "NOT on L-12 or MPC" in text


def test_usb_witness_does_not_restore_l12_as_default_sink() -> None:
    text = USB_WITNESS.read_text(encoding="utf-8")
    assert 'LOCAL_DEFAULT_SINK = "alsa_output.pci-0000_73_00.6.analog-stereo"' in text
    assert "local_default_sink_restored" in text
    assert "l12_default_sink_restored" not in text


def test_usb_runbook_matches_default_sink_policy() -> None:
    text = USB_RUNBOOK.read_text(encoding="utf-8")
    assert "default sink is intentionally not" in text
    assert "not the L-12 or MPC" in text
    assert "Expected default sink/source" not in text
