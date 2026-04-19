"""Regression pin: Reverie retains its purpose despite being a ward.

CVS Task: #124 — reverie-as-substrate invariant.
Governance doc: ``docs/governance/reverie-substrate-invariant.md``.
Spec: ``docs/superpowers/specs/2026-04-18-reverie-substrate-preservation-design.md``.

This test is the normative pin for the four clauses in the governance
doc §1:

1. **Protocol conformance.** Reverie's backend satisfies
   ``HomageSubstrateSource``.
2. **FSM exemption.** ``transition_to_package`` (i.e. a package swap +
   a reconcile tick) does NOT trigger a Reverie teardown — no
   ``PlannedTransition`` is ever emitted for the substrate source.
3. **Palette broadcast.** Package hints propagate via the
   ``homage-substrate-package.json`` broadcast and the mirrored
   ``uniforms.custom[N]`` slot on every reconcile tick, including
   empty ticks.
4. **Consent-safe continuity.** With the consent-safe flag present,
   Reverie continues to be classified as substrate and the palette
   broadcast re-resolves to the consent-safe (muted) hue.

Broader coverage of the individual mechanism lives in
``tests/studio_compositor/homage/test_homage_substrate_preservation.py``;
this file is the governance-level regression pin referenced by the
CVS task and the governance doc.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.studio_compositor.homage import (
    BITCHX_CONSENT_SAFE_PACKAGE,
    BITCHX_PACKAGE,
)
from agents.studio_compositor.homage.choreographer import Choreographer
from agents.studio_compositor.homage.substrate_source import (
    SUBSTRATE_SOURCE_REGISTRY,
    HomageSubstrateSource,
)


@pytest.fixture
def homage_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAPAX_HOMAGE_ACTIVE", "1")


@pytest.fixture
def choreographer(tmp_path: Path) -> Choreographer:
    return Choreographer(
        pending_file=tmp_path / "homage-pending.json",
        uniforms_file=tmp_path / "uniforms.json",
        substrate_package_file=tmp_path / "homage-substrate-package.json",
        consent_safe_flag_file=tmp_path / "consent-safe.json",
    )


def _write_pending(path: Path, transitions: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"transitions": transitions}), encoding="utf-8")


def _reverie_backend():
    from agents.studio_compositor.shm_rgba_reader import ShmRgbaReader

    # Any path is fine; the test does not read pixels.
    return ShmRgbaReader(Path("/tmp/nonexistent-reverie.rgba"), is_substrate=True)


class TestClause1ProtocolConformance:
    """Clause 1: Reverie's backend satisfies the substrate Protocol."""

    def test_reverie_source_ids_present_in_registry(self) -> None:
        assert "reverie" in SUBSTRATE_SOURCE_REGISTRY
        assert "reverie_external_rgba" in SUBSTRATE_SOURCE_REGISTRY

    def test_reverie_backend_satisfies_protocol(self) -> None:
        backend = _reverie_backend()
        assert isinstance(backend, HomageSubstrateSource)
        assert backend.is_substrate is True


class TestClause2FsmExemption:
    """Clause 2: Package swap + reconcile does NOT teardown Reverie.

    The ``transition_to_package`` flow in production is a package swap
    followed by a reconcile tick. We simulate that by reconciling
    against ``BITCHX_PACKAGE`` with a pending Reverie exit, and assert
    the exit is neither planned nor rejected — it's filtered by the
    substrate gate before either list is consulted.
    """

    def test_package_swap_does_not_plan_reverie_teardown(
        self, homage_on: None, choreographer: Choreographer
    ) -> None:
        _write_pending(
            choreographer._pending_file,
            [
                {
                    "source_id": "reverie_external_rgba",
                    "transition": "ticker-scroll-out",
                    "enqueued_at": 1.0,
                },
                {
                    "source_id": "reverie",
                    "transition": "part-message",
                    "enqueued_at": 1.0,
                },
            ],
        )
        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        planned_ids = {p.source_id for p in result.planned}
        assert "reverie" not in planned_ids
        assert "reverie_external_rgba" not in planned_ids
        # Not a rejection either — substrate filter is outside the
        # entry/exit/modify vocabulary.
        rejected_ids = {r.source_id for r in result.rejections}
        assert "reverie" not in rejected_ids
        assert "reverie_external_rgba" not in rejected_ids


class TestClause3PaletteBroadcast:
    """Clause 3: Palette hints propagate every tick (custom[N])."""

    def test_broadcast_runs_on_empty_tick(
        self, homage_on: None, choreographer: Choreographer
    ) -> None:
        # No pending transitions, no plans. Broadcast must still run.
        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        assert result.planned == ()
        assert choreographer._substrate_package_file.exists()
        payload = json.loads(choreographer._substrate_package_file.read_text())
        assert payload["package"] == "bitchx"
        assert payload["palette_accent_hue_deg"] == pytest.approx(180.0)
        assert "reverie_external_rgba" in payload["substrate_source_ids"]

    def test_custom_slot_carries_package_hue(
        self, homage_on: None, choreographer: Choreographer
    ) -> None:
        """The uniforms.custom[N] slot is kept in sync with the broadcast.

        ``_publish_payload`` writes ``signal.homage_custom_{slot}_{i}``
        keys for i in 0..3. Slot 1 (``palette_accent_hue_deg``) is the
        canonical package-tint channel — Reverie's shader reads
        ``uniforms.custom[4]`` and maps slot 1 onto the colorgrade node.
        """
        choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        slot = BITCHX_PACKAGE.coupling_rules.custom_slot_index
        uniforms = json.loads(choreographer._uniforms_file.read_text())
        hue_key = f"signal.homage_custom_{slot}_1"
        assert hue_key in uniforms
        assert uniforms[hue_key] == pytest.approx(180.0)


class TestClause4ConsentSafeContinuity:
    """Clause 4: Consent-safe swap preserves Reverie + mutes palette."""

    def test_consent_safe_keeps_reverie_substrate_and_mutes_palette(
        self, homage_on: None, choreographer: Choreographer, tmp_path: Path
    ) -> None:
        # Engage consent-safe.
        choreographer._consent_safe_flag_file.write_text(
            json.dumps({"engaged_at": 1.0}), encoding="utf-8"
        )
        # Pending transition against Reverie during consent-safe swap.
        _write_pending(
            choreographer._pending_file,
            [
                {
                    "source_id": "reverie_external_rgba",
                    "transition": "zero-cut-out",
                    "enqueued_at": 1.0,
                }
            ],
        )
        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        # Substrate still filtered — Reverie keeps rendering.
        assert all(p.source_id != "reverie_external_rgba" for p in result.planned)
        # Broadcast re-resolved to the consent-safe variant.
        payload = json.loads(choreographer._substrate_package_file.read_text())
        assert payload["package"] == BITCHX_CONSENT_SAFE_PACKAGE.name
        # Muted hue (grey, 0°). The consent-safe variant is intentionally
        # non-cyan so the stream signal carries the consent-safe state
        # visually to any downstream viewer.
        assert payload["palette_accent_hue_deg"] == pytest.approx(0.0)
        # Registry still lists Reverie as substrate.
        assert "reverie_external_rgba" in payload["substrate_source_ids"]
