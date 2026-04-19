"""HOMAGE Phase 8 — StructuralIntent.homage_rotation_mode (task #114).

Spec §4.13 + task-114 scope. Covers:

* ``StructuralIntent`` default rotation mode is ``sequential`` so existing
  payloads deserialize unchanged.
* ``Choreographer.reconcile()`` honours ``paused`` by dropping every
  pending transition this tick while still publishing the coupling
  payload (substrate broadcast must keep running — Reverie depends on
  it).
* ``weighted_by_salience`` sorts pending entries by salience descending
  before the concurrency-limit slice so the most-salient ward wins
  under contention.
* ``random`` leaves all transitions eligible (not pre-ordered) — the
  choreographer does not filter, only its concurrency slice decides.
* Missing structural-intent file → default ``sequential`` behaviour
  (pre-Phase 8 parity).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.studio_compositor.homage import BITCHX_PACKAGE
from agents.studio_compositor.homage.choreographer import (
    Choreographer,
)
from agents.studio_compositor.structural_director import StructuralIntent


@pytest.fixture
def homage_on(monkeypatch):
    monkeypatch.setenv("HAPAX_HOMAGE_ACTIVE", "1")
    # Pin the missing-file default to ``sequential`` for these tests —
    # the cascade-delta default changed to ``weighted_by_salience`` for
    # live-surface aesthetics, but the Phase 8 tests pin pre-Phase-8
    # parity semantics on purpose.
    monkeypatch.setenv("HAPAX_HOMAGE_DEFAULT_ROTATION", "sequential")


@pytest.fixture
def choreographer(tmp_path: Path) -> Choreographer:
    return Choreographer(
        pending_file=tmp_path / "homage-pending.json",
        uniforms_file=tmp_path / "uniforms.json",
        consent_safe_flag_file=tmp_path / "consent-safe-none.json",
        structural_intent_file=tmp_path / "structural-intent.json",
        narrative_structural_intent_file=tmp_path / "narrative-structural-intent.json",
    )


def _write_pending(path: Path, transitions: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"transitions": transitions}),
        encoding="utf-8",
    )


def _write_structural_intent(path: Path, rotation_mode: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scene_mode": "mixed",
        "preset_family_hint": "calm-textural",
        "long_horizon_direction": "phase-8 test",
        "homage_rotation_mode": rotation_mode,
        "emitted_at": 0.0,
        "condition_id": "none",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class TestStructuralIntentDefault:
    def test_homage_rotation_mode_defaults_to_sequential(self) -> None:
        intent = StructuralIntent(
            scene_mode="desk-work",
            preset_family_hint="calm-textural",
            long_horizon_direction="default-path test",
        )
        assert intent.homage_rotation_mode == "sequential"

    def test_legacy_payload_without_field_deserializes(self) -> None:
        # Back-compat: a structural intent produced before Phase 8 must
        # still parse. Default sequential is the only safe posture.
        raw = json.dumps(
            {
                "scene_mode": "desk-work",
                "preset_family_hint": "calm-textural",
                "long_horizon_direction": "legacy",
                "emitted_at": 0.0,
                "condition_id": "none",
            }
        )
        intent = StructuralIntent.model_validate_json(raw)
        assert intent.homage_rotation_mode == "sequential"

    def test_all_four_modes_accepted(self) -> None:
        for mode in ("sequential", "random", "weighted_by_salience", "paused"):
            intent = StructuralIntent(
                scene_mode="mixed",
                preset_family_hint="calm-textural",
                long_horizon_direction="mode-accept test",
                homage_rotation_mode=mode,  # type: ignore[arg-type]
            )
            assert intent.homage_rotation_mode == mode


class TestPausedMode:
    def test_paused_mode_drops_all_transitions(self, homage_on, choreographer, tmp_path) -> None:
        _write_structural_intent(tmp_path / "structural-intent.json", "paused")
        _write_pending(
            tmp_path / "homage-pending.json",
            [
                {"source_id": "a", "transition": "ticker-scroll-in", "enqueued_at": 0.0},
                {"source_id": "b", "transition": "ticker-scroll-in", "enqueued_at": 0.0},
                {"source_id": "c", "transition": "ticker-scroll-out", "enqueued_at": 0.0},
            ],
        )
        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        # No transitions applied this tick; no rejections either (the
        # rejection set is reserved for concurrency / feature-flag axes,
        # not for "paused" as an operator-driven calm signal).
        assert result.planned == ()
        assert result.rejections == ()

    def test_paused_mode_still_publishes_coupling_payload(
        self, homage_on, choreographer, tmp_path
    ) -> None:
        # Reverie depends on the substrate broadcast — it can't be
        # starved when the operator asks ward rotation to pause.
        _write_structural_intent(tmp_path / "structural-intent.json", "paused")
        _write_pending(
            tmp_path / "homage-pending.json",
            [{"source_id": "a", "transition": "ticker-scroll-in", "enqueued_at": 0.0}],
        )
        choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        uniforms = json.loads((tmp_path / "uniforms.json").read_text(encoding="utf-8"))
        assert "signal.homage_custom_4_0" in uniforms


class TestWeightedBySalience:
    def test_highest_salience_wins_under_contention(
        self, homage_on, choreographer, tmp_path
    ) -> None:
        _write_structural_intent(tmp_path / "structural-intent.json", "weighted_by_salience")
        # BitchX max_simultaneous_entries = 2. Send 4 entries with
        # varied salience; the two highest must plan, the two lowest
        # must reject.
        _write_pending(
            tmp_path / "homage-pending.json",
            [
                {
                    "source_id": "low-a",
                    "transition": "ticker-scroll-in",
                    "enqueued_at": 0.0,
                    "salience": 0.10,
                },
                {
                    "source_id": "low-b",
                    "transition": "ticker-scroll-in",
                    "enqueued_at": 0.0,
                    "salience": 0.20,
                },
                {
                    "source_id": "high-a",
                    "transition": "ticker-scroll-in",
                    "enqueued_at": 0.0,
                    "salience": 0.95,
                },
                {
                    "source_id": "high-b",
                    "transition": "ticker-scroll-in",
                    "enqueued_at": 0.0,
                    "salience": 0.80,
                },
            ],
        )
        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        planned_ids = {p.source_id for p in result.planned}
        rejected_ids = {r.source_id for r in result.rejections}
        assert planned_ids == {"high-a", "high-b"}
        assert rejected_ids == {"low-a", "low-b"}

    def test_weighted_preserves_order_when_salience_equal(
        self, homage_on, choreographer, tmp_path
    ) -> None:
        # When salience ties, the queue order breaks the tie (stable
        # sort) — this is important so producers get predictable
        # behaviour even under weighted_by_salience.
        _write_structural_intent(tmp_path / "structural-intent.json", "weighted_by_salience")
        _write_pending(
            tmp_path / "homage-pending.json",
            [
                {
                    "source_id": f"ward-{i}",
                    "transition": "ticker-scroll-in",
                    "enqueued_at": float(i),
                    "salience": 0.5,
                }
                for i in range(4)
            ],
        )
        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        # First two by pending-queue order win.
        planned_ids = [p.source_id for p in result.planned]
        assert planned_ids == ["ward-0", "ward-1"]


class TestRandomMode:
    def test_random_leaves_all_transitions_eligible(
        self, homage_on, choreographer, tmp_path
    ) -> None:
        # ``random`` should neither drop transitions (that's ``paused``)
        # nor pre-sort them (that's ``weighted_by_salience``). Every
        # pending entry passes to the concurrency slice.
        _write_structural_intent(tmp_path / "structural-intent.json", "random")
        _write_pending(
            tmp_path / "homage-pending.json",
            [
                {
                    "source_id": "a",
                    "transition": "ticker-scroll-in",
                    "enqueued_at": 0.0,
                    "salience": 0.1,
                },
                {
                    "source_id": "b",
                    "transition": "ticker-scroll-in",
                    "enqueued_at": 0.0,
                    "salience": 0.9,
                },
            ],
        )
        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        # BitchX max_simultaneous_entries=2, both fit, neither rejected.
        assert len(result.planned) == 2
        assert result.rejections == ()

    def test_random_mode_does_not_sort_by_salience(
        self, homage_on, choreographer, tmp_path
    ) -> None:
        # With concurrency=2 and 3 entries where the highest salience
        # is LAST in the queue, ``random`` must NOT promote it — that
        # would be ``weighted_by_salience``. Instead the first two
        # queue entries should plan.
        _write_structural_intent(tmp_path / "structural-intent.json", "random")
        _write_pending(
            tmp_path / "homage-pending.json",
            [
                {
                    "source_id": "first",
                    "transition": "ticker-scroll-in",
                    "enqueued_at": 0.0,
                    "salience": 0.10,
                },
                {
                    "source_id": "second",
                    "transition": "ticker-scroll-in",
                    "enqueued_at": 0.0,
                    "salience": 0.20,
                },
                {
                    "source_id": "third-but-highest",
                    "transition": "ticker-scroll-in",
                    "enqueued_at": 0.0,
                    "salience": 0.99,
                },
            ],
        )
        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        planned_ids = [p.source_id for p in result.planned]
        assert planned_ids == ["first", "second"]


class TestMissingStructuralIntentFile:
    def test_missing_file_defaults_to_sequential(self, homage_on, choreographer, tmp_path) -> None:
        # No structural-intent file written — pre-Phase 8 parity.
        assert not (tmp_path / "structural-intent.json").exists()
        _write_pending(
            tmp_path / "homage-pending.json",
            [
                {
                    "source_id": "a",
                    "transition": "ticker-scroll-in",
                    "enqueued_at": 0.0,
                    "salience": 0.1,
                },
                {
                    "source_id": "b",
                    "transition": "ticker-scroll-in",
                    "enqueued_at": 0.0,
                    "salience": 0.9,
                },
            ],
        )
        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        planned_ids = [p.source_id for p in result.planned]
        # Sequential: queue order preserved, low-salience "a" still
        # planned first despite its lower score.
        assert planned_ids == ["a", "b"]

    def test_malformed_file_defaults_to_sequential(
        self, homage_on, choreographer, tmp_path
    ) -> None:
        (tmp_path / "structural-intent.json").write_text("not json", encoding="utf-8")
        _write_pending(
            tmp_path / "homage-pending.json",
            [
                {
                    "source_id": "a",
                    "transition": "ticker-scroll-in",
                    "enqueued_at": 0.0,
                    "salience": 0.1,
                },
                {
                    "source_id": "b",
                    "transition": "ticker-scroll-in",
                    "enqueued_at": 0.0,
                    "salience": 0.9,
                },
            ],
        )
        # Must not crash, must fall back to sequential.
        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        planned_ids = [p.source_id for p in result.planned]
        assert planned_ids == ["a", "b"]

    def test_unknown_mode_value_defaults_to_sequential(
        self, homage_on, choreographer, tmp_path
    ) -> None:
        # Forward-compat: if the structural director someday emits a
        # mode the choreographer doesn't understand, fail open to
        # sequential rather than deactivating HOMAGE.
        _write_structural_intent(tmp_path / "structural-intent.json", "from-the-future")
        _write_pending(
            tmp_path / "homage-pending.json",
            [{"source_id": "a", "transition": "ticker-scroll-in", "enqueued_at": 0.0}],
        )
        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        assert len(result.planned) == 1
