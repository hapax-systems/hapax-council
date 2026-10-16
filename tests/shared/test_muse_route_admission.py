"""End-to-end admission chain for the Meta Muse review route.

A third-family route is admitted only when EVERY per-route link in the admission spine knows it:
the registry entry, the capability-receipt seat blocker, the route-specific quota blocker, the
quota-spend-ledger receipt-bounded allowlist and the dispatcher's route-specific subscription set.
A route missing from any one of those tables is structurally unadmittable, and a unit test of one
table cannot see that. These tests drive the real loader (``load_platform_capability_registry`` ->
``apply_platform_capability_receipts``) with fresh receipts and a live ledger, and then remove one
link at a time.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from shared import platform_capability_registry, quota_spend_ledger
from shared.platform_capability_receipts import (
    CliEvidence,
    EvidenceStatus,
    PlatformCapabilityReceipt,
    ProviderDocsEvidence,
    SurfaceEvidence,
    WrapperEvidence,
)
from shared.platform_capability_registry import (
    ROUTE_SPECIFIC_QUOTA_ADMISSION_BLOCKERS,
    RouteState,
    _capability_receipt_removable_reasons,
    load_platform_capability_registry,
)
from shared.quota_spend_ledger import QUOTA_SPEND_LEDGER_FIXTURES

ROUTE_ID = "muse.review.direct"
NOW = datetime(2026, 10, 15, 8, 1, tzinfo=UTC)
OBSERVED = datetime(2026, 10, 15, 8, 0, tzinfo=UTC)
# A stand-in pin for exercising the chain; the shipped admissible set is empty while the real
# pin is held for the operator's plan answer.
TEST_PIN = "muse-wonder-1.0"


def _admission_ref(*, model: str = TEST_PIN, scrub: str = ":credential_env_scrubbed:meta:") -> str:
    return (
        "relay-receipt:muse-quota-admission-20261015t080000z.yaml:"
        "witness:muse-standard-smoke-20261015t0800z:"
        "supported_tool:hapax-muse-quota-admission:"
        f"model:{model}"
        f"{scrub}"
        "observed_at:2026-10-15T08:00:00Z:"
        "fresh_until:2026-10-15T08:15:00Z"
    )


MUSE_ADMISSION_EVIDENCE_REF = _admission_ref()


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR", str(tmp_path / "no-receipts"))
    monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER_LIVE", str(tmp_path / "missing-live.json"))


@pytest.fixture
def pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quota_spend_ledger, "MUSE_ADMISSION_MODELS", frozenset({TEST_PIN}))


def _muse_receipt(
    *, resource_status: EvidenceStatus = EvidenceStatus.OBSERVED
) -> PlatformCapabilityReceipt:
    return PlatformCapabilityReceipt(
        receipt_id="test-muse-receipt",
        platform="muse",
        routes=[ROUTE_ID],
        observed_at=OBSERVED,
        stale_after="24h",
        cli=CliEvidence(
            binary="scripts/hapax-muse-reviewer",
            available=True,
            version="hapax-muse-reviewer: ok model=muse-wonder-1.0 scrubbed_env=META_API_KEY",
        ),
        wrapper=WrapperEvidence(
            path="scripts/hapax-muse-reviewer", exists=True, executable=True, sha256="abc123"
        ),
        capability=SurfaceEvidence(
            status=EvidenceStatus.OBSERVED,
            source="test",
            observed_at=OBSERVED,
            stale_after="24h",
            evidence_refs=["test:muse:capability:muse-wonder-1.0"],
        ),
        resource=SurfaceEvidence(
            status=resource_status,
            source="test",
            observed_at=OBSERVED,
            stale_after="24h",
            evidence_refs=["test:muse:resource:account-oauth-login"],
            reason_codes=(
                []
                if resource_status is EvidenceStatus.OBSERVED
                else ["fresh_resource_evidence_absent"]
            ),
        ),
        quota=SurfaceEvidence(
            status=EvidenceStatus.UNOBSERVABLE,
            source="test",
            observed_at=OBSERVED,
            stale_after="15m",
            evidence_refs=["test:muse:quota:local-probe-unobservable"],
            reason_codes=["account_live_quota_receipt_absent", "quota_telemetry_unknown"],
        ),
        provider_docs=ProviderDocsEvidence(
            refs=[
                "https://dev.meta.ai/docs/pricing-rate-limits",
                "https://dev.meta.ai/docs/overview",
            ],
            fetched_at=OBSERVED,
            stale_after="30d",
        ),
    )


def _write_receipt(
    receipt_dir: Path, *, resource_status: EvidenceStatus = EvidenceStatus.OBSERVED
) -> None:
    receipt_dir.mkdir(parents=True, exist_ok=True)
    (receipt_dir / "muse.json").write_text(
        _muse_receipt(resource_status=resource_status).model_dump_json(), encoding="utf-8"
    )


def _write_live_ledger(
    path: Path,
    *,
    fresh_until: str = "2026-10-15T08:15:00Z",
    evidence_ref: str = MUSE_ADMISSION_EVIDENCE_REF,
) -> None:
    payload = deepcopy(json.loads(QUOTA_SPEND_LEDGER_FIXTURES.read_text(encoding="utf-8")))
    payload["ledger_id"] = "quota-spend-ledger-test-muse-live"
    payload["captured_at"] = "2026-10-15T08:00:30Z"
    payload["generated_from"] = list(
        dict.fromkeys([*payload["generated_from"], "scripts/hapax-quota-telemetry-writer"])
    )
    payload["quota_snapshots"] = [
        {
            "quota_snapshot_schema": 1,
            "snapshot_id": "quota-muse-review-direct-live",
            "captured_at": "2026-10-15T08:00:00Z",
            "fresh_until": fresh_until,
            "route_id": ROUTE_ID,
            "provider": "meta-muse-code",
            "capacity_pool": "subscription_quota",
            "subscription_quota_state": "fresh",
            "evidence_refs": [evidence_ref],
            "operator_visible_reason": "fixture muse quota admission receipt",
        }
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")


def _route(tmp_path: Path):
    registry = load_platform_capability_registry(receipt_dir=tmp_path / "receipts", now=NOW)
    return registry.require(ROUTE_ID)


def test_muse_route_is_declared_blocked_by_default() -> None:
    registry = load_platform_capability_registry(now=NOW)
    route = registry.require(ROUTE_ID)
    assert route.route_state is RouteState.BLOCKED
    assert "muse_review_seat_receipt_admission_required" in route.blocked_reasons


def test_every_route_specific_quota_route_is_validated_by_the_ledger() -> None:
    """A route whose registry quota blocker the ledger can clear MUST also be in the ledger's
    receipt-bounded allowlist with a provider: outside it, the ledger trusts any fresh-looking
    snapshot without validating its admission evidence, and the blocker clears fail-open."""
    blocker_routes = set(ROUTE_SPECIFIC_QUOTA_ADMISSION_BLOCKERS)

    assert blocker_routes <= quota_spend_ledger.RECEIPT_BOUNDED_SUBSCRIPTION_ROUTES
    assert (
        set(quota_spend_ledger.RECEIPT_BOUNDED_SUBSCRIPTION_PROVIDERS)
        >= quota_spend_ledger.RECEIPT_BOUNDED_SUBSCRIPTION_ROUTES
    )


def test_declared_model_is_not_an_admission(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The route DECLARES a concrete model, but the shipped admission set is empty, so even a
    fully fresh chain whose admission names exactly the declared model stays blocked."""
    declared = load_platform_capability_registry(now=NOW).require(ROUTE_ID)
    declared_model = str(declared.execution_descriptor.model_id)
    assert declared_model == TEST_PIN
    assert frozenset() == quota_spend_ledger.MUSE_ADMISSION_MODELS

    route = _chain(monkeypatch, tmp_path, evidence_ref=_admission_ref(model=declared_model))

    assert route.route_state is RouteState.BLOCKED
    assert route.blocked_reasons == [QUOTA_BLOCKER]


def test_muse_route_is_in_every_per_route_admission_table() -> None:
    assert ROUTE_ID in ROUTE_SPECIFIC_QUOTA_ADMISSION_BLOCKERS
    assert "muse_review_seat_receipt_admission_required" in _capability_receipt_removable_reasons(
        {"route_id": ROUTE_ID}
    )


def _chain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    receipt: bool = True,
    ledger: bool = True,
    resource_status: EvidenceStatus = EvidenceStatus.OBSERVED,
    **ledger_kwargs: str,
):
    if receipt:
        _write_receipt(tmp_path / "receipts", resource_status=resource_status)
    else:
        (tmp_path / "receipts").mkdir()
    if ledger:
        live = tmp_path / "quota-spend-ledger-live.json"
        _write_live_ledger(live, **ledger_kwargs)
        monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER_LIVE", str(live))
    return _route(tmp_path)


QUOTA_BLOCKER = ROUTE_SPECIFIC_QUOTA_ADMISSION_BLOCKERS.get(ROUTE_ID, "route-not-in-table")


@pytest.mark.usefixtures("pinned")
def test_full_chain_with_fresh_receipts_reaches_active(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    route = _chain(monkeypatch, tmp_path)

    assert route.route_state is RouteState.ACTIVE, route.blocked_reasons
    assert route.blocked_reasons == []
    assert MUSE_ADMISSION_EVIDENCE_REF in route.freshness.evidence.quota.evidence_refs


@pytest.mark.usefixtures("pinned")
def test_chain_without_observed_resource_evidence_stays_blocked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    route = _chain(monkeypatch, tmp_path, resource_status=EvidenceStatus.UNOBSERVABLE)

    assert route.route_state is RouteState.BLOCKED
    assert "fresh_resource_evidence_absent" in route.blocked_reasons


@pytest.mark.usefixtures("pinned")
@pytest.mark.parametrize(
    ("label", "ref"),
    [
        ("no model", _admission_ref().replace(f"model:{TEST_PIN}:", "")),
        (
            "two models",
            _admission_ref().replace(f"model:{TEST_PIN}:", f"model:{TEST_PIN}:model:{TEST_PIN}:"),
        ),
        ("no observed_at", _admission_ref().replace("observed_at:2026-10-15T08:00:00Z:", "")),
        ("no fresh_until", _admission_ref().replace(":fresh_until:2026-10-15T08:15:00Z", "")),
        (
            "foreign receipt label",
            _admission_ref().replace("muse-quota-admission", "kimi-quota-admission"),
        ),
        (
            "foreign supported tool",
            _admission_ref().replace("hapax-muse-quota-admission", "hapax-kimi-quota-admission"),
        ),
        (
            "secretish witness",
            _admission_ref().replace("muse-standard-smoke-20261015t0800z", "bearer-abc"),
        ),
        (
            "two witnesses",
            _admission_ref().replace(
                "supported_tool:", "witness:extra:supported_tool:witness:x:supported_tool:", 1
            ),
        ),
        ("not a relay receipt", _admission_ref().replace("relay-receipt:", "note:", 1)),
    ],
)
def test_admission_ref_validator_refuses_each_missing_conjunct(label: str, ref: str) -> None:
    assert quota_spend_ledger._is_muse_admission_evidence_ref(_admission_ref()) is True
    assert quota_spend_ledger._is_muse_admission_evidence_ref(ref) is False, label


@pytest.mark.usefixtures("pinned")
def test_chain_without_capability_receipt_stays_blocked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    route = _chain(monkeypatch, tmp_path, receipt=False)

    assert route.route_state is RouteState.BLOCKED
    assert "muse_review_seat_receipt_admission_required" in route.blocked_reasons


@pytest.mark.usefixtures("pinned")
def test_chain_without_live_quota_ledger_stays_blocked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    route = _chain(monkeypatch, tmp_path, ledger=False)

    assert route.route_state is RouteState.BLOCKED
    assert route.blocked_reasons == [QUOTA_BLOCKER]


@pytest.mark.usefixtures("pinned")
def test_chain_with_stale_quota_snapshot_stays_blocked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    route = _chain(monkeypatch, tmp_path, fresh_until="2026-10-15T07:59:00Z")

    assert route.route_state is RouteState.BLOCKED
    assert route.blocked_reasons == [QUOTA_BLOCKER]


def test_chain_stays_blocked_while_the_pin_is_held(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The shipped admissible model set is empty: no muse snapshot is trusted before the pin."""
    assert frozenset() == quota_spend_ledger.MUSE_ADMISSION_MODELS

    route = _chain(monkeypatch, tmp_path)

    assert route.route_state is RouteState.BLOCKED
    assert route.blocked_reasons == [QUOTA_BLOCKER]


@pytest.mark.usefixtures("pinned")
def test_chain_refuses_an_unpinned_served_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    route = _chain(monkeypatch, tmp_path, evidence_ref=_admission_ref(model="muse-spark-1.3"))

    assert route.route_state is RouteState.BLOCKED
    assert route.blocked_reasons == [QUOTA_BLOCKER]


def test_chain_refuses_a_contributor_model_even_if_admitted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    contributor = f"{TEST_PIN}-contributor"
    monkeypatch.setattr(quota_spend_ledger, "MUSE_ADMISSION_MODELS", frozenset({contributor}))

    route = _chain(monkeypatch, tmp_path, evidence_ref=_admission_ref(model=contributor))

    assert route.route_state is RouteState.BLOCKED
    assert route.blocked_reasons == [QUOTA_BLOCKER]


@pytest.mark.usefixtures("pinned")
def test_chain_refuses_admission_without_the_credential_scrub_disclosure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    route = _chain(monkeypatch, tmp_path, evidence_ref=_admission_ref(scrub=":"))

    assert route.route_state is RouteState.BLOCKED
    assert route.blocked_reasons == [QUOTA_BLOCKER]


# --------------------------------------------------------------------------------------------
# Mutation witnesses: each disables ONE guard in memory and shows the outcome flips, so every
# guard above is load-bearing and that fact re-runs in CI rather than living in a transcript.
# --------------------------------------------------------------------------------------------


@pytest.mark.usefixtures("pinned")
def test_mutation_witness_seat_blocker_clearing_is_load_bearing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(platform_capability_registry, "MUSE_REVIEW_ROUTE_ID", "mutated.route.id")

    route = _chain(monkeypatch, tmp_path)

    assert route.route_state is RouteState.BLOCKED
    assert "muse_review_seat_receipt_admission_required" in route.blocked_reasons


@pytest.mark.usefixtures("pinned")
def test_mutation_witness_quota_blocker_table_entry_is_load_bearing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mutated = {k: v for k, v in ROUTE_SPECIFIC_QUOTA_ADMISSION_BLOCKERS.items() if k != ROUTE_ID}
    monkeypatch.setattr(
        platform_capability_registry, "ROUTE_SPECIFIC_QUOTA_ADMISSION_BLOCKERS", mutated
    )

    route = _chain(monkeypatch, tmp_path)

    assert route.route_state is RouteState.BLOCKED
    assert QUOTA_BLOCKER in route.blocked_reasons


def test_mutation_witness_ledger_allowlist_entry_prevents_fail_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without the allowlist entry the ledger trusts a contributor-model snapshot unvalidated
    and the route goes ACTIVE: the fail-open the consistency invariant forbids."""
    contributor_ref = _admission_ref(model=f"{TEST_PIN}-contributor")
    monkeypatch.setattr(
        quota_spend_ledger,
        "RECEIPT_BOUNDED_SUBSCRIPTION_ROUTES",
        quota_spend_ledger.RECEIPT_BOUNDED_SUBSCRIPTION_ROUTES - {ROUTE_ID},
    )

    route = _chain(monkeypatch, tmp_path, evidence_ref=contributor_ref)

    assert route.route_state is RouteState.ACTIVE
    assert not set(ROUTE_SPECIFIC_QUOTA_ADMISSION_BLOCKERS) <= (
        quota_spend_ledger.RECEIPT_BOUNDED_SUBSCRIPTION_ROUTES
    )


def test_mutation_witness_contributor_refusal_is_load_bearing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    contributor = f"{TEST_PIN}-contributor"
    monkeypatch.setattr(quota_spend_ledger, "MUSE_ADMISSION_MODELS", frozenset({contributor}))
    monkeypatch.setattr(quota_spend_ledger, "MUSE_CONTRIBUTOR_SUFFIX", "-mutated-suffix")

    route = _chain(monkeypatch, tmp_path, evidence_ref=_admission_ref(model=contributor))

    assert route.route_state is RouteState.ACTIVE


def test_mutation_witness_empty_pin_set_is_load_bearing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(quota_spend_ledger, "MUSE_ADMISSION_MODELS", frozenset({TEST_PIN}))

    route = _chain(monkeypatch, tmp_path)

    assert route.route_state is RouteState.ACTIVE
