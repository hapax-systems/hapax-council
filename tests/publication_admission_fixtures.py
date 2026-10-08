"""Synthetic route receipts for isolated publication transport tests; no live evidence."""

import json
from datetime import UTC, datetime

import pytest

from agents.publication_bus.surface_registry import SURFACE_REGISTRY
from shared.dispatcher_policy import build_route_authority_receipt


def install_publication_admission(monkeypatch, tmp_path, *, surfaces=()):
    root = tmp_path / "synthetic-publication-admission"
    receipt_dir = root / "route-authority"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    route = "api.headless.api_frontier"
    task = "cc-task-synthetic-publication"
    lane = "synthetic-publication"
    row = dict(
        decision_schema=1,
        decision_id="synthetic-publication-decision",
        task_id=task,
        lane=lane,
        route_id=route,
        created_at=now.isoformat(),
        action="launch",
        launch_allowed=True,
        prompt_allowed=True,
        route_policy_green=True,
        registry_freshness_green=True,
        authority_allowed=True,
        quality_floor_satisfied=True,
        quota_freshness_green=True,
        resource_freshness_green=True,
        quota_evidence_refs=["quota:synthetic"],
        resource_state_refs=["resource:synthetic"],
    )
    ledger = root / "route-decisions.jsonl"
    ledger.write_text(json.dumps(row) + "\n")
    scopes = ["connector", "external", "public", "provider_spend", "publication:review"]
    scopes.extend(
        "publication:" + name
        for name in sorted(
            set(SURFACE_REGISTRY)
            | set(surfaces)
            | {
                "test-surface",
                "fake",
                "s1",
                "s2",
                "bsky",
                "masto",
                "corrupt",
                "other",
                "unknown-surface",
                "nope",
                "nonexistent",
                "test-witness-ok",
                "test-witness-error",
                "test-witness-raises",
                "zenodo-community",
            }
        )
    )
    receipt = build_route_authority_receipt(
        receipt_type="connector_mutation",
        route_id=route,
        evidence_refs=["authority-case:SYNTHETIC-TEST"],
        task_ids=[task],
        mutation_surfaces=scopes,
        issued_at=now,
    )
    receipt_path = receipt_dir / "synthetic.json"
    receipt_path.write_text(receipt.model_dump_json())
    for name, value in {
        "HAPAX_PUBLICATION_TASK_ID": task,
        "HAPAX_PUBLICATION_ROLE": lane,
        "HAPAX_PUBLICATION_ROUTE_ID": route,
        "HAPAX_PUBLICATION_REVIEW_ROUTE_ID": route,
        "HAPAX_ROUTE_DECISION_LEDGER": str(ledger),
        "HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR": str(root),
    }.items():
        monkeypatch.setenv(name, value)
    return ledger, receipt_path, row, receipt


@pytest.fixture(autouse=True)
def publication_transport_admission(monkeypatch, tmp_path):
    """Opt-in fixture for mocked transport suites; never live admission."""
    return install_publication_admission(monkeypatch, tmp_path)
