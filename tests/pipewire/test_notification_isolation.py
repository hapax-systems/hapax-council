"""Notification-private sink isolation (Phase A3).

Pins the governance contract that system / chat / desktop notifications
never reach the livestream broadcast. Surface-level verification: the
conf file exists, declares a dedicated sink, targets the L-12 MASTER
monitor output (not Ryzen, not any capture target, and explicitly not
``hapax-l12-evilpet-capture``).

Runtime verification (live graph check) is handled by the Phase B /
Phase C integration tests; this file is the static schema pin.
"""

from __future__ import annotations

from pathlib import Path

import pytest

CONF_REPO_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "pipewire" / "hapax-notification-private.conf"
)


@pytest.fixture()
def conf_text() -> str:
    if not CONF_REPO_PATH.exists():
        pytest.skip(f"conf missing from repo: {CONF_REPO_PATH}")
    return CONF_REPO_PATH.read_text(encoding="utf-8")


def test_conf_exists(conf_text: str) -> None:
    assert len(conf_text) > 0


def test_declares_dedicated_sink_name(conf_text: str) -> None:
    assert 'node.name       = "hapax-notification-private"' in conf_text, (
        "notification-private sink must declare the exact node.name"
    )


def test_uses_loopback_module(conf_text: str) -> None:
    assert "libpipewire-module-loopback" in conf_text


def test_targets_off_l12_broadcast_paths(conf_text: str) -> None:
    """Notifications MUST NOT reach any livestream / L-12 broadcast path.

    NOTE 2026-04-22 (lssh-014 directive): the prior revision targeted
    the L-12 MASTER analog-surround-40 monitor. This was retargeted
    OFF the L-12 entirely to the Blue Yeti headphone monitor — the
    operator's dedicated headphone path. The hard governance contract
    (no notifications on broadcast) holds; the specific destination
    moved. The test now pins the broadcast-isolation invariant
    without coupling to which specific off-broadcast sink the
    notification lands on.
    """
    # Strip comment lines so we only check active configuration.
    active_lines = [line for line in conf_text.splitlines() if not line.lstrip().startswith("#")]
    active = "\n".join(active_lines)

    # Forbidden: any L-12 capture / livestream-broadcast path.
    assert "hapax-l12-evilpet-capture" not in active, (
        "Notification sink must NEVER target the L-12 filter-chain capture; "
        "notifications forbidden on broadcast."
    )
    assert "hapax-livestream-tap" not in active, (
        "Notification sink must not route into the livestream tap directly."
    )
    assert "hapax-livestream" not in active, (
        "Notification sink must not target any livestream sink/source."
    )
    # Required: a target.object directive that lands somewhere
    # off-broadcast (operator monitor). The specific device is
    # operator-config — could be Yeti, iLoud, or future swap — so
    # only pin that target.object exists and isn't a broadcast path.
    assert "target.object" in active, (
        "Notification sink must declare an explicit target.object (off-broadcast operator monitor)."
    )


def test_declares_stereo(conf_text: str) -> None:
    assert "audio.channels  = 2" in conf_text or "audio.channels = 2" in conf_text
    assert "[ FL FR ]" in conf_text


def test_documents_governance_rationale(conf_text: str) -> None:
    assert "governance" in conf_text.lower() or "forbidden" in conf_text.lower(), (
        "Conf file must document WHY notifications are gated off broadcast."
    )
