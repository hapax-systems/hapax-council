"""Choreographer invariant tests.

Spec §4.9 — the choreographer reconciles pending transitions against
concurrency limits, publishes the shader-coupling payload, and emits
Prometheus observability.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agents.studio_compositor.homage import BITCHX_PACKAGE
from agents.studio_compositor.homage.choreographer import (
    Choreographer,
    CoupledPayload,
    PendingTransition,
)
from shared.action_receipt import ActionReceipt, ActionReceiptStatus


@pytest.fixture
def homage_on(monkeypatch):
    monkeypatch.setenv("HAPAX_HOMAGE_ACTIVE", "1")


@pytest.fixture
def homage_off(monkeypatch):
    # Phase 12 flipped the default-ON; explicit disable required now.
    monkeypatch.setenv("HAPAX_HOMAGE_ACTIVE", "0")


@pytest.fixture
def choreographer(tmp_path: Path) -> Choreographer:
    return Choreographer(
        pending_file=tmp_path / "homage-pending.json",
        uniforms_file=tmp_path / "uniforms.json",
        # Phase 12: isolate from any live /dev/shm consent-safe flag so
        # CI / dev-machine residue can't flip the reconciled package.
        consent_safe_flag_file=tmp_path / "consent-safe-none.json",
        # Belt-and-braces: isolate the rotation-mode reader from /dev/shm
        # residue. Other tests in the suite (e2e programme layer,
        # structural director programme tests) have historically written
        # `homage_rotation_mode: "paused"` to the default
        # /dev/shm/hapax-structural/intent.json path; without these
        # overrides the choreographer's _read_rotation_mode() picks up
        # the residue, takes the paused early-return branch, and every
        # invariant test below gets empty planned + empty rejections.
        structural_intent_file=tmp_path / "structural-intent.json",
        narrative_structural_intent_file=tmp_path / "narrative-structural-intent.json",
        action_receipts_file=tmp_path / "action-receipts.jsonl",
    )


def _write_pending(path: Path, transitions: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"transitions": transitions}),
        encoding="utf-8",
    )


def _read_action_receipts(path: Path) -> list[ActionReceipt]:
    return [
        ActionReceipt.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class TestFeatureFlagGate:
    def test_flag_off_produces_empty_plan(self, homage_off, choreographer):
        result = choreographer.reconcile(BITCHX_PACKAGE, now=0.0)
        assert result.planned == ()
        assert result.rejections == ()
        # Payload still zero-valued (emitter path is flag-gated too).
        assert result.coupled_payload == CoupledPayload(0.0, 0.0, 0.0, 0.0)


class TestEmptyPending:
    def test_no_pending_file_yields_empty_plan(self, homage_on, choreographer):
        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        assert result.planned == ()
        assert result.rejections == ()

    def test_malformed_pending_file_yields_empty_plan(self, homage_on, choreographer, tmp_path):
        (tmp_path / "homage-pending.json").write_text("not json", encoding="utf-8")
        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        assert result.planned == ()


class TestEntryConcurrency:
    def test_within_limit_all_entries_planned(self, homage_on, choreographer, tmp_path):
        _write_pending(
            tmp_path / "homage-pending.json",
            [
                {
                    "source_id": "a",
                    "transition": "ticker-scroll-in",
                    "enqueued_at": 0.0,
                },
                {
                    "source_id": "b",
                    "transition": "ticker-scroll-in",
                    "enqueued_at": 0.0,
                },
            ],
        )
        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        # BitchX max_simultaneous_entries = 2.
        assert len(result.planned) == 2
        assert result.rejections == ()

    def test_planned_entry_with_request_id_emits_applied_action_receipt(
        self,
        homage_on,
        choreographer,
        tmp_path,
    ):
        _write_pending(
            tmp_path / "homage-pending.json",
            [
                {
                    "source_id": "a",
                    "transition": "ticker-scroll-in",
                    "enqueued_at": 0.0,
                    "request_id": "homage:req:planned",
                }
            ],
        )

        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)

        assert len(result.planned) == 1
        receipt = ActionReceipt.model_validate_json(
            (tmp_path / "action-receipts.jsonl").read_text().splitlines()[0]
        )
        assert receipt.request_id == "homage:req:planned"
        assert receipt.status is ActionReceiptStatus.APPLIED
        assert receipt.learning_update_allowed is False

    def test_over_limit_excess_entries_rejected(self, homage_on, choreographer, tmp_path):
        entries = [
            {
                "source_id": f"w{i}",
                "transition": "ticker-scroll-in",
                "enqueued_at": 0.0,
                "request_id": f"homage:req:over-limit:{i}",
            }
            for i in range(5)
        ]
        _write_pending(tmp_path / "homage-pending.json", entries)
        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        # BitchX max_simultaneous_entries = 2 → 2 planned, 3 rejected.
        assert len(result.planned) == 2
        assert len(result.rejections) == 3
        assert all(r.reason == "concurrency-limit" for r in result.rejections)
        receipts = _read_action_receipts(tmp_path / "action-receipts.jsonl")
        blocked = [r for r in receipts if r.status is ActionReceiptStatus.BLOCKED]
        assert len(blocked) == 3
        assert all(r.blocked_reasons == ["concurrency-limit"] for r in blocked)


class TestExitConcurrency:
    def test_over_limit_excess_exits_rejected(self, homage_on, choreographer, tmp_path):
        entries = [
            {
                "source_id": f"w{i}",
                "transition": "ticker-scroll-out",
                "enqueued_at": 0.0,
            }
            for i in range(4)
        ]
        _write_pending(tmp_path / "homage-pending.json", entries)
        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        assert len(result.planned) == 2  # max_simultaneous_exits=2
        assert len(result.rejections) == 2


class TestUnknownTransition:
    def test_unknown_transition_rejected(self, homage_on, choreographer, tmp_path):
        _write_pending(
            tmp_path / "homage-pending.json",
            [{"source_id": "a", "transition": "not-a-transition", "enqueued_at": 0.0}],
        )
        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        assert len(result.rejections) == 1
        assert result.rejections[0].reason == "unknown-transition"

    def test_unknown_transition_with_request_id_emits_blocked_action_receipt(
        self,
        homage_on,
        choreographer,
        tmp_path,
    ):
        _write_pending(
            tmp_path / "homage-pending.json",
            [
                {
                    "source_id": "a",
                    "transition": "not-a-transition",
                    "enqueued_at": 0.0,
                    "request_id": "homage:req:unknown",
                }
            ],
        )

        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)

        assert len(result.rejections) == 1
        receipt = ActionReceipt.model_validate_json(
            (tmp_path / "action-receipts.jsonl").read_text().splitlines()[0]
        )
        assert receipt.request_id == "homage:req:unknown"
        assert receipt.status is ActionReceiptStatus.BLOCKED
        assert receipt.blocked_reasons == ["unknown-transition"]

    def test_malformed_pending_with_request_id_emits_blocked_action_receipt(
        self,
        homage_on,
        choreographer,
        tmp_path,
    ):
        _write_pending(
            tmp_path / "homage-pending.json",
            [
                {
                    "source_id": "a",
                    "enqueued_at": 0.0,
                    "request_id": "homage:req:malformed",
                }
            ],
        )

        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)

        assert result.planned == ()
        assert result.rejections == ()
        receipt = ActionReceipt.model_validate_json(
            (tmp_path / "action-receipts.jsonl").read_text().splitlines()[0]
        )
        assert receipt.request_id == "homage:req:malformed"
        assert receipt.status is ActionReceiptStatus.BLOCKED
        assert receipt.blocked_reasons == ["malformed-entry"]


class TestBlockedActionReceipts:
    def test_paused_rotation_with_request_id_emits_blocked_action_receipt(
        self,
        homage_on,
        choreographer,
        tmp_path,
    ):
        (tmp_path / "narrative-structural-intent.json").write_text(
            json.dumps({"homage_rotation_mode": "paused", "updated_at": time.time()}),
            encoding="utf-8",
        )
        _write_pending(
            tmp_path / "homage-pending.json",
            [
                {
                    "source_id": "a",
                    "transition": "ticker-scroll-in",
                    "enqueued_at": 0.0,
                    "request_id": "homage:req:paused",
                }
            ],
        )

        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)

        assert result.planned == ()
        receipt = ActionReceipt.model_validate_json(
            (tmp_path / "action-receipts.jsonl").read_text().splitlines()[0]
        )
        assert receipt.request_id == "homage:req:paused"
        assert receipt.status is ActionReceiptStatus.BLOCKED
        assert receipt.blocked_reasons == ["paused_rotation"]

    def test_substrate_skip_with_request_id_emits_blocked_action_receipt(
        self,
        homage_on,
        choreographer,
        tmp_path,
    ):
        _write_pending(
            tmp_path / "homage-pending.json",
            [
                {
                    "source_id": "reverie",
                    "transition": "ticker-scroll-in",
                    "enqueued_at": 0.0,
                    "request_id": "homage:req:substrate",
                }
            ],
        )

        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)

        assert result.planned == ()
        receipt = ActionReceipt.model_validate_json(
            (tmp_path / "action-receipts.jsonl").read_text().splitlines()[0]
        )
        assert receipt.request_id == "homage:req:substrate"
        assert receipt.status is ActionReceiptStatus.BLOCKED
        assert receipt.blocked_reasons == ["substrate_source_skip"]


class TestNetsplitBurstGating:
    def test_burst_allowed_on_first_call(self, homage_on, choreographer, tmp_path):
        _write_pending(
            tmp_path / "homage-pending.json",
            [{"source_id": "a", "transition": "netsplit-burst", "enqueued_at": 0.0}],
        )
        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        assert len(result.planned) == 1
        assert result.planned[0].transition == "netsplit-burst"

    def test_burst_rejected_within_min_interval(self, homage_on, choreographer, tmp_path):
        for t in (1.0, 2.0):
            _write_pending(
                tmp_path / "homage-pending.json",
                [
                    {
                        "source_id": f"a{t}",
                        "transition": "netsplit-burst",
                        "enqueued_at": t,
                    }
                ],
            )
            result = choreographer.reconcile(BITCHX_PACKAGE, now=t)
        # Second call was within netsplit_burst_min_interval_s (120s) of
        # the first → rejected.
        assert any(r.transition == "netsplit-burst" for r in result.rejections)

    def test_burst_allowed_after_min_interval(self, homage_on, choreographer, tmp_path):
        _write_pending(
            tmp_path / "homage-pending.json",
            [{"source_id": "a", "transition": "netsplit-burst", "enqueued_at": 0.0}],
        )
        choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        _write_pending(
            tmp_path / "homage-pending.json",
            [{"source_id": "b", "transition": "netsplit-burst", "enqueued_at": 200.0}],
        )
        result = choreographer.reconcile(BITCHX_PACKAGE, now=200.0)
        assert any(p.transition == "netsplit-burst" for p in result.planned)


class TestShaderCouplingPayload:
    def test_reconcile_writes_uniforms_payload(self, homage_on, choreographer, tmp_path):
        _write_pending(
            tmp_path / "homage-pending.json",
            [{"source_id": "a", "transition": "ticker-scroll-in", "enqueued_at": 0.0}],
        )
        choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        uniforms = json.loads((tmp_path / "uniforms.json").read_text(encoding="utf-8"))
        # BitchX custom slot = 4.
        assert "signal.homage_custom_4_0" in uniforms
        assert "signal.homage_custom_4_1" in uniforms
        assert "signal.homage_custom_4_2" in uniforms
        assert "signal.homage_custom_4_3" in uniforms

    def test_reconcile_preserves_existing_uniform_keys(self, homage_on, choreographer, tmp_path):
        (tmp_path / "uniforms.json").write_text(json.dumps({"existing.key": 0.5}), encoding="utf-8")
        _write_pending(
            tmp_path / "homage-pending.json",
            [{"source_id": "a", "transition": "ticker-scroll-in", "enqueued_at": 0.0}],
        )
        choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        uniforms = json.loads((tmp_path / "uniforms.json").read_text(encoding="utf-8"))
        assert uniforms["existing.key"] == 0.5
        assert "signal.homage_custom_4_0" in uniforms

    def test_active_transition_sets_energy_to_one(self, homage_on, choreographer, tmp_path):
        _write_pending(
            tmp_path / "homage-pending.json",
            [{"source_id": "a", "transition": "ticker-scroll-in", "enqueued_at": 0.0}],
        )
        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        assert result.coupled_payload.active_transition_energy == 1.0

    def test_no_active_transition_sets_energy_to_zero(self, homage_on, choreographer, tmp_path):
        result = choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        assert result.coupled_payload.active_transition_energy == 0.0


class TestPendingFileConsumed:
    def test_pending_file_cleared_after_reconcile(self, homage_on, choreographer, tmp_path):
        pending_path = tmp_path / "homage-pending.json"
        _write_pending(
            pending_path,
            [{"source_id": "a", "transition": "ticker-scroll-in", "enqueued_at": 0.0}],
        )
        assert pending_path.exists()
        choreographer.reconcile(BITCHX_PACKAGE, now=1.0)
        assert not pending_path.exists()


class TestPendingTransitionDataclass:
    def test_pending_transition_is_frozen(self):
        p = PendingTransition(source_id="a", transition="ticker-scroll-in", enqueued_at=0.0)
        with pytest.raises(AttributeError):
            p.source_id = "b"  # type: ignore[misc]
