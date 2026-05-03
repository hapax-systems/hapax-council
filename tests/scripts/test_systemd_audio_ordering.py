"""Tests for cc-task audio-audit-H2-systemd-leak-guard-After-ordering.

Pin: every audio-chain unit that interacts with the broadcast bus
must order After=hapax-private-broadcast-leak-guard.service so the
leak-guard's first tick lands before any private-content path becomes
addressable. Catches a race-window regression on first-boot or after
a `systemctl --user daemon-reload`.

Phase 0 scope (this PR): the units that exist as systemd unit files
in the repo. The H2 cc-task body also references
hapax-private-playback / hapax-private-monitor / hapax-music-duck —
those are PipeWire filter-chain configs (not systemd-unit-managed),
so they're out of scope for systemd ordering. Their leak-guard
guarantee is enforced at the filter-chain layer; the After= chain
defended here gives them a runtime that the leak-guard has already
validated.
"""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
LEAK_GUARD_UNIT = "hapax-private-broadcast-leak-guard.service"

# Units that ride the broadcast bus and therefore must order After=
# the leak-guard. Each entry is the bare unit filename (no path).
AUDIO_CHAIN_UNITS = (
    "hapax-broadcast-orchestrator.service",
    "hapax-music-player.service",
    "hapax-audio-ducker.service",
    "hapax-broadcast-audio-health.service",
    "hapax-broadcast-audio-health-producer.service",
)


def _read_unit(name: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.read(UNITS_DIR / name, encoding="utf-8")
    return parser


@pytest.mark.parametrize("unit", AUDIO_CHAIN_UNITS)
def test_audio_chain_unit_orders_after_leak_guard(unit: str) -> None:
    parsed = _read_unit(unit)
    after = parsed.get("Unit", "After", fallback="")
    assert LEAK_GUARD_UNIT in after, (
        f"{unit} [Unit] After= must include {LEAK_GUARD_UNIT!r} "
        f"so the leak-guard's first tick lands before this unit becomes "
        f"addressable on the broadcast bus. Current After= value: {after!r}"
    )


@pytest.mark.parametrize("unit", AUDIO_CHAIN_UNITS)
def test_audio_chain_unit_wants_leak_guard(unit: str) -> None:
    """After= alone is ordering-only; the unit must also Wants= the
    leak-guard so systemd starts the guard when this unit starts."""
    parsed = _read_unit(unit)
    wants = parsed.get("Unit", "Wants", fallback="")
    assert LEAK_GUARD_UNIT in wants, (
        f"{unit} [Unit] Wants= must include {LEAK_GUARD_UNIT!r} so the "
        f"leak-guard service is started alongside this unit. After= alone "
        f"only orders; Wants= triggers the start. Current Wants= value: {wants!r}"
    )


def test_leak_guard_unit_exists() -> None:
    """Sanity pin: the unit file the chain refers to must actually exist."""
    assert (UNITS_DIR / LEAK_GUARD_UNIT).is_file(), (
        f"audio chain orders After={LEAK_GUARD_UNIT} but the unit file "
        f"is missing from systemd/units/"
    )


class TestLeakGuardActiveMetric:
    """Pin the H2 metric: hapax_private_leak_guard_active emitted by the
    leak-guard on every successful tick. Operators alert on stale
    textfile mtime."""

    def test_leak_guard_script_emits_active_metric(self) -> None:
        script = REPO_ROOT / "scripts" / "hapax-private-broadcast-leak-guard"
        content = script.read_text(encoding="utf-8")
        assert "hapax_private_leak_guard_active" in content, (
            "leak-guard script must emit hapax_private_leak_guard_active "
            "metric per cc-task H2 acceptance criteria"
        )
