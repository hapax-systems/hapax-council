"""Tests for the claude-cloud review route (``claude.review.cloud``).

The cloud route seats review family ``claude`` through Anthropic-managed cloud
sessions billed to the promotional cloud credit (``ccr_promotional``), never
the Max subscription pool and never pay-as-you-go. Its route id keeps outage
latching and pacing separate from the ``claude -p`` route
(``claude.review.opus``): family ``claude`` recovery is witnessed only by
post-outage admission receipts for ``claude.review.cloud``.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from shared.quota_spend_ledger import SubscriptionQuotaState

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / "config" / "review-lenses" / "registry.yaml"
PLATFORM_REGISTRY_PATH = REPO_ROOT / "config" / "platform-capability-registry.json"
CLOUD_ROUTE_ID = "claude.review.cloud"
LEGACY_POOL_ROUTE_ID = "claude.review.opus"
CLOUD_WRAPPER = "scripts/hapax-claude-cloud-reviewer"


def _load(name: str, filename: str) -> ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def rt() -> ModuleType:
    return _load("review_team", "review_team.py")


@pytest.fixture()
def dispatch() -> ModuleType:
    return _load("dispatch", "cc-pr-review-dispatch.py")


def _registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def _platform_registry_payload() -> dict:
    return json.loads(PLATFORM_REGISTRY_PATH.read_text(encoding="utf-8"))


def _mark_route_fresh(route: dict, *, checked_at: str = "2026-09-25T20:55:00Z") -> None:
    route["route_state"] = "active"
    route["blocked_reasons"] = []
    route["freshness"]["capability_checked_at"] = checked_at
    route["freshness"]["quota_checked_at"] = checked_at
    route["freshness"]["resource_checked_at"] = checked_at
    route["freshness"]["provider_docs_checked_at"] = checked_at
    route["freshness"]["capability_stale_after"] = "365d"
    route["freshness"]["quota_stale_after"] = "365d"
    route["freshness"]["resource_stale_after"] = "365d"
    route["freshness"]["provider_docs_stale_after"] = "365d"
    route["freshness"]["evidence"] = {
        "capability": {"evidence_refs": ["test:fresh-capability"], "blocked_reasons": []},
        "quota": {"evidence_refs": ["test:fresh-quota"], "blocked_reasons": []},
        "resource": {"evidence_refs": ["test:fresh-resource"], "blocked_reasons": []},
        "provider_docs": {"evidence_refs": ["test:fresh-provider-docs"], "blocked_reasons": []},
    }
    route["telemetry"]["quota_source"] = "manual"
    route["telemetry"]["resource_source"] = "local_probe"
    for score in route["capability_scores"].values():
        score["observed_at"] = checked_at
        score["stale_after"] = "365d"
        if not score.get("evidence_refs"):
            score["evidence_refs"] = ["test:fresh-score"]
    for tool in route["tool_state"]:
        tool["observed_at"] = checked_at
        tool["stale_after"] = "365d"


def test_review_family_route_ids_binds_claude_to_cloud_route(rt: ModuleType) -> None:
    route_ids = rt.review_family_route_ids(_registry())
    assert route_ids["claude"] == CLOUD_ROUTE_ID


def test_claude_family_seats_through_cloud_wrapper(rt: ModuleType) -> None:
    """The claude family's command is the cloud wrapper, never a raw CLI, and the
    wrapper declares the cloud route and the bare-fence output contract (a lost
    vote class of its own: prose around the fence is invalid-output)."""

    claude = next(
        entry for entry in rt.review_family_entries(_registry()) if entry["family"] == "claude"
    )
    assert claude["reviewer_command"] == [CLOUD_WRAPPER]
    assert claude["route_id"] == CLOUD_ROUTE_ID
    wrapper_path = REPO_ROOT / CLOUD_WRAPPER
    assert wrapper_path.is_file()
    wrapper = wrapper_path.read_text(encoding="utf-8")
    assert f'REVIEW_EXECUTION_ROUTE = "{CLOUD_ROUTE_ID}"' in wrapper
    assert "exactly one fenced yaml" in wrapper
    assert "invalid-output" in wrapper


def test_cloud_review_route_declaration_is_review_safe_and_receipt_bounded(
    rt: ModuleType,
) -> None:
    payload = _platform_registry_payload()
    route = next(row for row in payload["routes"] if row["route_id"] == CLOUD_ROUTE_ID)
    assert route["platform"] == "claude"
    assert route["mode"] == "review"
    assert route["sanctioned_wrapper"] == CLOUD_WRAPPER
    assert route["authority_ceiling"] == "read_only"
    assert route["mutability"] == {
        "vault_docs": False,
        "source": False,
        "runtime": False,
        "public": False,
        "provider_spend": False,
    }
    assert "frontier_review_required" in route["quality_envelope"]["eligible_quality_floors"]
    # The billing surface is the promotional cloud credit: a distinct capacity
    # pool from the subscription quota the claude -p route draws on.
    assert route["capacity_pool"] == "promotional_credit_quota"
    assert route["capacity_pool"] != "subscription_quota"
    assert route["auth_surface"] == "oauth"
    # Fail-closed by default: only governed receipts can admit the route.
    assert route["route_state"] == "blocked"
    assert "claude_cloud_review_seat_receipt_admission_required" in route["blocked_reasons"]
    assert "claude_cloud_review_route_specific_quota_receipt_absent" in (route["blocked_reasons"])


def test_blocked_cloud_route_degrades_claude_family(rt: ModuleType) -> None:
    platform_registry = rt.PlatformCapabilityRegistry.model_validate(_platform_registry_payload())
    blocked = rt.review_route_blocked_families(_registry(), platform_registry=platform_registry)
    assert "claude" in blocked
    assert any(
        "claude_cloud_review_seat_receipt_admission_required" in reason
        for reason in blocked["claude"]
    )
    assert any(
        "claude_cloud_review_route_specific_quota_receipt_absent" in reason
        for reason in blocked["claude"]
    )


def test_admitted_cloud_route_keeps_claude_family_available(rt: ModuleType) -> None:
    payload = _platform_registry_payload()
    route = next(row for row in payload["routes"] if row["route_id"] == CLOUD_ROUTE_ID)
    _mark_route_fresh(route)
    platform_registry = rt.PlatformCapabilityRegistry.model_validate(payload)
    blocked = rt.review_route_blocked_families(_registry(), platform_registry=platform_registry)
    assert "claude" not in blocked


def test_dispatch_recognizes_cloud_wrapper_quota_wall_diagnostic(
    dispatch: ModuleType,
) -> None:
    """A credit-exhausted cloud seat must fold to the same quota-wall verdict
    class as any walled seat: the family outage latch engages through the
    wrapper-authored diagnostic, and the wrapper's own lines never leak into
    downstream classification."""

    wrapper = (REPO_ROOT / CLOUD_WRAPPER).read_text(encoding="utf-8")
    match = re.search(r'QUOTA_WALL_DIAGNOSTIC = \(\s*"([^"]+)"', wrapper)
    assert match is not None
    diagnostic = match.group(1)
    assert diagnostic.startswith("hapax-claude-cloud-reviewer: ")
    assert "quota-wall" in diagnostic

    stderr = f"some provider noise\n{diagnostic}\n"
    assert dispatch.reviewer_stdout_quota_wall_diagnostic(stderr) is True
    stripped = dispatch.stderr_without_reviewer_stdout_diagnostics(stderr)
    assert diagnostic not in stripped
    assert "some provider noise" in stripped


def test_claude_outage_recovery_is_witnessed_by_cloud_route_only(
    rt: ModuleType, dispatch: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The family's outage latch clears only on a post-outage admission witness
    for claude.review.cloud; the claude -p route's receipts never clear it."""

    observed = "2026-09-25T20:55:00+00:00"
    state = tmp_path / "family-outage.json"
    state.write_text(
        json.dumps(
            {
                "claude": {
                    "observed_at": observed,
                    "outage_started_at": observed,
                }
            }
        ),
        encoding="utf-8",
    )

    class Resolved:
        source = "live"
        live_error = None
        ledger = object()

    queried_route_ids: list[str] = []

    def fake_subscription_quota_state(_ledger, route_id, *, now):
        queried_route_ids.append(route_id)
        return (
            SubscriptionQuotaState.FRESH,
            ("relay-receipt:test-admission.yaml:observed_at:2026-09-25T21:00:00Z",),
        )

    monkeypatch.setattr(
        dispatch.review_team, "load_quota_spend_ledger_resolved", lambda: Resolved()
    )
    monkeypatch.setattr(
        dispatch.review_team, "subscription_quota_state_for_route", fake_subscription_quota_state
    )

    witness = dispatch.clear_route_recovered_family_outage(
        {"claude": observed},
        registry=dispatch.review_team.load_lens_registry(),
        route_blocked_families={},
        now_iso="2026-09-25T21:05:00+00:00",
        state_path=state,
    )

    assert witness == {}
    assert queried_route_ids == [CLOUD_ROUTE_ID]
    assert LEGACY_POOL_ROUTE_ID not in queried_route_ids
    assert json.loads(state.read_text(encoding="utf-8")) == {}
