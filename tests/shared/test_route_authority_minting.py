"""Tests for route-authority receipt minting + the dispatch receipt-dir default.

These cover the post-`--policy-rollback`-retirement opus reachability fix
(reform-fix-opus-reachability-20260531, CASE-CAPACITY-ROUTING-001):

  * the shared minting helpers that back ``scripts/hapax-mint-route-authority-receipt``
    (the executable form of OQ-5 — operator signs the entitlement), and
  * the live dispatch read-path defaulting ``receipt_dir`` to
    ``DEFAULT_PLATFORM_CAPABILITY_RECEIPT_DIR`` so un-degrade is not silently
    gated on an unset env var.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from shared.dispatcher_policy import (
    RouteAuthorityReceipt,
    _receipt_dir_from_env,
    _route_authority_removable_reasons,
    build_route_authority_receipt,
    route_authority_receipt_payload_hash,
    route_authority_receipt_reference,
    write_route_authority_receipt,
)
from shared.platform_capability_receipts import (
    DEFAULT_PLATFORM_CAPABILITY_RECEIPT_DIR,
    PLATFORM_CAPABILITY_RECEIPT_DIR_ENV,
)


def test_receipt_dir_defaults_to_platform_capability_dir_when_env_unset() -> None:
    env = {k: v for k, v in os.environ.items() if k != PLATFORM_CAPABILITY_RECEIPT_DIR_ENV}
    with patch.dict(os.environ, env, clear=True):
        assert _receipt_dir_from_env() == DEFAULT_PLATFORM_CAPABILITY_RECEIPT_DIR


def test_receipt_dir_disabled_by_sentinel_returns_none() -> None:
    for sentinel in ("0", "none", "None", "false", "False", ""):
        with patch.dict(os.environ, {PLATFORM_CAPABILITY_RECEIPT_DIR_ENV: sentinel}):
            assert _receipt_dir_from_env() is None


def test_receipt_dir_honors_explicit_env_path(tmp_path: Path) -> None:
    with patch.dict(os.environ, {PLATFORM_CAPABILITY_RECEIPT_DIR_ENV: str(tmp_path)}):
        assert _receipt_dir_from_env() == tmp_path


def test_build_opus_entitlement_receipt_round_trips_and_validates() -> None:
    receipt = build_route_authority_receipt(
        receipt_type="opus_model_entitlement",
        route_id="claude.headless.opus",
        evidence_refs=["operator-signed:oq-5"],
    )

    assert receipt.receipt_type == "opus_model_entitlement"
    assert receipt.route_id == "claude.headless.opus"
    assert receipt.signed_by == "operator"
    assert receipt.stale_after == "24h"
    # The signed hash is self-consistent: the model validator would have rejected
    # the build otherwise, but assert it explicitly so a regression is loud.
    assert receipt.signed_payload_sha256 == route_authority_receipt_payload_hash(receipt)
    # The on-disk JSON shape the dispatcher reads round-trips back to the model.
    reloaded = RouteAuthorityReceipt.model_validate(json.loads(receipt.model_dump_json()))
    assert reloaded == receipt
    assert route_authority_receipt_reference(receipt).startswith(
        "route-authority-receipt:opus_model_entitlement:claude.headless.opus:"
    )


def test_legacy_opus_receipt_without_runtime_fields_still_validates() -> None:
    payload = {
        "route_authority_receipt_schema": 1,
        "receipt_id": "legacy-opus",
        "receipt_type": "opus_model_entitlement",
        "route_id": "claude.headless.opus",
        "issued_at": "2026-06-01T00:00:00Z",
        "stale_after": "24h",
        "signed_by": "operator",
        "evidence_refs": ["operator-signed:oq-5"],
        "quality_floors": [],
    }
    payload["signed_payload_sha256"] = route_authority_receipt_payload_hash(payload)

    receipt = RouteAuthorityReceipt.model_validate(payload)

    assert receipt.task_ids == ()
    assert receipt.mutation_surfaces == ()
    assert receipt.signed_payload_sha256 == route_authority_receipt_payload_hash(receipt)


def test_build_quality_equivalence_receipt_round_trips_with_floors() -> None:
    receipt = build_route_authority_receipt(
        receipt_type="quality_equivalence",
        route_id="claude.headless.sonnet",
        evidence_refs=["operator-signed:equivalence"],
        quality_floors=["frontier_required"],
    )

    assert receipt.receipt_type == "quality_equivalence"
    assert receipt.quality_floors == ("frontier_required",)
    assert receipt.signed_payload_sha256 == route_authority_receipt_payload_hash(receipt)


def test_build_runtime_actuation_receipt_round_trips_with_task_scope() -> None:
    receipt = build_route_authority_receipt(
        receipt_type="runtime_actuation",
        route_id="codex.headless.full",
        evidence_refs=["operator-signed:minio-cleanup"],
        task_ids=["appendix-podium-minio-old-root-cleanup-20260605"],
        mutation_surfaces=["runtime"],
    )

    assert receipt.receipt_type == "runtime_actuation"
    assert receipt.task_ids == ("appendix-podium-minio-old-root-cleanup-20260605",)
    assert receipt.mutation_surfaces == ("runtime",)
    assert receipt.signed_payload_sha256 == route_authority_receipt_payload_hash(receipt)


def test_build_connector_mutation_receipt_round_trips_with_task_scope() -> None:
    receipt = build_route_authority_receipt(
        receipt_type="connector_mutation",
        route_id="codex.headless.full",
        evidence_refs=["operator-signed:gmail-send"],
        task_ids=["cc-task-mcp-mutator-route-resource-receipts-20260630"],
        mutation_surfaces=["connector", "external", "public"],
    )

    assert receipt.receipt_type == "connector_mutation"
    assert receipt.task_ids == ("cc-task-mcp-mutator-route-resource-receipts-20260630",)
    assert receipt.mutation_surfaces == ("connector", "external", "public")
    assert receipt.signed_payload_sha256 == route_authority_receipt_payload_hash(receipt)


def test_build_quality_equivalence_requires_quality_floors() -> None:
    with pytest.raises((ValidationError, ValueError)):
        build_route_authority_receipt(
            receipt_type="quality_equivalence",
            route_id="claude.headless.sonnet",
            evidence_refs=["operator-signed:equivalence"],
        )


def test_build_local_inference_entitlement_receipt_round_trips_and_validates() -> None:
    receipt = build_route_authority_receipt(
        receipt_type="local_inference_entitlement",
        route_id="local_tool.local.worker",
        evidence_refs=["operator-signed:local-inference-entitlement"],
    )

    assert receipt.receipt_type == "local_inference_entitlement"
    assert receipt.route_id == "local_tool.local.worker"
    assert receipt.signed_payload_sha256 == route_authority_receipt_payload_hash(receipt)
    reloaded = RouteAuthorityReceipt.model_validate(json.loads(receipt.model_dump_json()))
    assert reloaded == receipt


def test_build_local_inference_entitlement_requires_local_tool_route() -> None:
    with pytest.raises((ValidationError, ValueError)):
        build_route_authority_receipt(
            receipt_type="local_inference_entitlement",
            route_id="claude.headless.opus",
            evidence_refs=["operator-signed:local-inference-entitlement"],
        )


def test_local_inference_entitlement_clears_the_local_worker_blockers() -> None:
    """The entitlement receipt clears exactly the local worker's admission + capability-evidence
    + quota-telemetry blocked-reasons so apply_route_authority_receipts flips the route active."""
    receipt = build_route_authority_receipt(
        receipt_type="local_inference_entitlement",
        route_id="local_tool.local.worker",
        evidence_refs=["operator-signed:local-inference-entitlement"],
    )
    assert _route_authority_removable_reasons(receipt) == {
        "local_inference_worker_receipt_admission_required",
        "fresh_capability_evidence_absent",
        "quota_telemetry_unknown",
    }


def test_build_opus_entitlement_requires_opus_route() -> None:
    with pytest.raises((ValidationError, ValueError)):
        build_route_authority_receipt(
            receipt_type="opus_model_entitlement",
            route_id="claude.headless.sonnet",
            evidence_refs=["operator-signed:oq-5"],
        )


def test_build_runtime_actuation_requires_task_and_surface() -> None:
    with pytest.raises((ValidationError, ValueError)):
        build_route_authority_receipt(
            receipt_type="runtime_actuation",
            route_id="codex.headless.full",
            evidence_refs=["operator-signed:minio-cleanup"],
            mutation_surfaces=["runtime"],
        )
    with pytest.raises((ValidationError, ValueError)):
        build_route_authority_receipt(
            receipt_type="runtime_actuation",
            route_id="codex.headless.full",
            evidence_refs=["operator-signed:minio-cleanup"],
            task_ids=["appendix-podium-minio-old-root-cleanup-20260605"],
        )


def test_build_connector_mutation_requires_task_and_surface() -> None:
    with pytest.raises((ValidationError, ValueError)):
        build_route_authority_receipt(
            receipt_type="connector_mutation",
            route_id="codex.headless.full",
            evidence_refs=["operator-signed:gmail-send"],
            mutation_surfaces=["connector", "external"],
        )
    with pytest.raises((ValidationError, ValueError)):
        build_route_authority_receipt(
            receipt_type="connector_mutation",
            route_id="codex.headless.full",
            evidence_refs=["operator-signed:gmail-send"],
            task_ids=["cc-task-mcp-mutator-route-resource-receipts-20260630"],
        )


def test_write_route_authority_receipt_lands_in_route_authority_subdir(tmp_path: Path) -> None:
    receipt = build_route_authority_receipt(
        receipt_type="opus_model_entitlement",
        route_id="claude.headless.opus",
        receipt_id="opus-entitlement-fixture",
        evidence_refs=["operator-signed:oq-5"],
    )

    path = write_route_authority_receipt(receipt, receipt_dir=tmp_path)

    assert path == tmp_path / "route-authority" / "opus-entitlement-fixture.json"
    on_disk = RouteAuthorityReceipt.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert on_disk == receipt
