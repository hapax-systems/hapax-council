"""Cross-package proof that agentic-trust evidence remains non-supply and route-inert."""

from __future__ import annotations

import ast
import json
import os
import shutil
import sys
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "packages" / "hapax-agentic-trust"
PACKAGE_SOURCE = PACKAGE_ROOT / "src"
if str(PACKAGE_SOURCE) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SOURCE))

from hapax_agentic_trust import (  # noqa: E402
    AgenticTrustEvidenceReceiptV1,
    verify_terminal_projection,
)

from shared.capability_availability_guarantor import (  # noqa: E402
    RefreshStrategyRegistry,
    evaluate_registry_availability,
)
from shared.capability_surface_delta import CapabilitySurfaceDeltaFile  # noqa: E402
from shared.dispatcher_policy import (  # noqa: E402
    CAPABILITY_SURFACE_DELTA_PATH_ENV,
    RouteAuthorityReceipt,
    build_route_authority_receipt,
    load_dispatch_policy_sources,
)
from shared.platform_capability_receipts import PlatformCapabilityReceipt  # noqa: E402
from shared.platform_capability_registry import (  # noqa: E402
    AGENTIC_TRUST_EVIDENCE_RECEIPT_CLASS,
    AGENTIC_TRUST_EVIDENCE_SURFACE_ID,
    PLATFORM_CAPABILITY_REGISTRY,
    CapabilityShapeFreshnessState,
    PlatformCapabilityRegistry,
    PlatformCapabilityRegistryError,
    ToolState,
    build_supply_vector,
    check_omitted_shape_freshness,
    check_registry_freshness,
    load_platform_capability_registry,
    load_platform_capability_registry_for_dispatch,
)
from shared.quota_spend_ledger import QUOTA_SPEND_LEDGER_FIXTURES  # noqa: E402
from shared.route_metadata_schema import RequiredTool  # noqa: E402

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

_GENERATED_DIRECTORY_NAMES = frozenset(
    {
        ".cache",
        ".eggs",
        ".git",
        ".hypothesis",
        ".mypy_cache",
        ".nox",
        ".playwright-mcp",
        ".pytest_cache",
        ".pytest-tmp",
        ".pyrefly",
        ".ruff_cache",
        ".superpowers",
        ".tox",
        ".venv",
        ".venv-ingest",
        ".worktrees",
        "__pycache__",
        ".benchmarks",
        ".compositor-inspect",
        "build",
        "coverage_html_report",
        "dist",
        "htmlcov",
        "node_modules",
        "out",
        "site-packages",
        "target",
        "wheels",
    }
)
_NON_OPERATIONAL_ROOTS = (("packages", "hapax-agentic-trust"),)
_NON_OPERATIONAL_FILES = {(".git",)}


def _is_non_operational_path(path: Path, *, is_directory: bool) -> bool:
    relative_parts = path.relative_to(ROOT).parts
    if "tests" in relative_parts:
        return True
    if not is_directory and relative_parts in _NON_OPERATIONAL_FILES:
        return True
    directory_parts = relative_parts if is_directory else relative_parts[:-1]
    if any(
        part in _GENERATED_DIRECTORY_NAMES or part.endswith(".egg-info") for part in directory_parts
    ):
        return True
    return any(
        relative_parts[: len(excluded_root)] == excluded_root
        for excluded_root in _NON_OPERATIONAL_ROOTS
    )


@lru_cache(maxsize=1)
def _repo_operational_files() -> tuple[Path, ...]:
    """Return every non-generated repository file outside this package and tests."""
    files: list[Path] = []

    def raise_walk_error(error: OSError) -> None:
        raise error

    for directory_name, child_directories, file_names in os.walk(
        ROOT,
        onerror=raise_walk_error,
    ):
        directory = Path(directory_name)
        for name in child_directories:
            child = directory / name
            if child.is_symlink():
                raise AssertionError(f"operational topology directory is a symlink: {child}")
        child_directories[:] = [
            name
            for name in child_directories
            if not _is_non_operational_path(directory / name, is_directory=True)
        ]
        for name in file_names:
            path = directory / name
            if _is_non_operational_path(path, is_directory=False):
                continue
            if path.is_symlink() or not path.is_file():
                raise AssertionError(f"operational topology path is not a regular file: {path}")
            files.append(path)
    return tuple(sorted(files))


@lru_cache(maxsize=1)
def _python_source_files() -> tuple[Path, ...]:
    sources: list[Path] = []
    for path in _repo_operational_files():
        if path.suffix in {".py", ".pyi", ".pyw"}:
            sources.append(path)
            continue
        with path.open(encoding="utf-8", errors="ignore") as stream:
            first_line = stream.readline().lower()
        if first_line.startswith("#!") and "python" in first_line:
            sources.append(path)
    return tuple(sources)


def _native_receipt(tmp_path: Path) -> AgenticTrustEvidenceReceiptV1:
    fixture = PACKAGE_ROOT / "tests" / "fixtures" / "golden-terminal-v3"
    root = tmp_path / "terminal"
    shutil.copytree(fixture / "store", root)
    for path in root.rglob("*"):
        if path.is_file():
            path.chmod(0o400)
    anchors = json.loads((fixture / "anchors.json").read_text(encoding="utf-8"))
    projection = verify_terminal_projection(
        root,
        "terminal/bundle.json",
        expected_bundle_sha256=anchors["bundle_sha256"],
        expected_evidence_root_sha256=anchors["evidence_root_sha256"],
        expected_manifest_snapshot_artifact_sha256=(anchors["manifest_snapshot_artifact_sha256"]),
    )
    return AgenticTrustEvidenceReceiptV1.from_verified_projection(projection)


def _platform_policy_receipt_payload(evidence_ref: str) -> dict[str, object]:
    surface = {
        "status": "observed",
        "source": "local_test",
        "observed_at": NOW.isoformat(),
        "stale_after": "1h",
        "evidence_refs": [evidence_ref],
        "reason_codes": [],
    }
    return {
        "receipt_schema": 1,
        "receipt_id": "policy-reference-test",
        "platform": "codex",
        "routes": ["codex.headless.full"],
        "observed_at": NOW.isoformat(),
        "stale_after": "1h",
        "cli": {"binary": "codex", "available": True, "version": "test"},
        "wrapper": {"path": "/test/wrapper", "exists": True, "executable": True},
        "capability": surface,
        "resource": {**surface, "evidence_refs": ["local:resource:test"]},
        "quota": {**surface, "evidence_refs": ["local:quota:test"]},
        "provider_docs": {
            "refs": ["official:provider:test"],
            "fetched_at": NOW.isoformat(),
            "stale_after": "1h",
        },
    }


def _all_const_values(value: object) -> set[object]:
    if isinstance(value, dict):
        values = {value["const"]} if "const" in value else set()
        for child in value.values():
            values.update(_all_const_values(child))
        return values
    if isinstance(value, list):
        values: set[object] = set()
        for child in value:
            values.update(_all_const_values(child))
        return values
    return set()


def test_receipt_identity_is_exact_across_package_registry_config_and_schemas() -> None:
    package_schema = json.loads(
        (PACKAGE_ROOT / "schemas" / "agentic-trust-evidence-receipt-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    registry_schema = json.loads(
        (ROOT / "schemas" / "platform-capability-registry.schema.json").read_text(encoding="utf-8")
    )
    registry_payload = json.loads(PLATFORM_CAPABILITY_REGISTRY.read_text(encoding="utf-8"))
    target = next(
        row
        for row in registry_payload["omitted_capability_shapes"]
        if row["shape_id"] == AGENTIC_TRUST_EVIDENCE_SURFACE_ID
    )

    assert AgenticTrustEvidenceReceiptV1.EVALUATOR_SURFACE_ID == (AGENTIC_TRUST_EVIDENCE_SURFACE_ID)
    assert AgenticTrustEvidenceReceiptV1.RECEIPT_TYPE == AGENTIC_TRUST_EVIDENCE_RECEIPT_CLASS
    assert package_schema["properties"]["evaluator_surface_id"]["const"] == (
        AGENTIC_TRUST_EVIDENCE_SURFACE_ID
    )
    assert package_schema["properties"]["receipt_type"]["const"] == (
        AGENTIC_TRUST_EVIDENCE_RECEIPT_CLASS
    )
    assert target["shape_state"] == "evidence_only"
    assert target["observation_receipt_class"] == AGENTIC_TRUST_EVIDENCE_RECEIPT_CLASS
    assert AGENTIC_TRUST_EVIDENCE_SURFACE_ID in _all_const_values(registry_schema)
    assert AGENTIC_TRUST_EVIDENCE_RECEIPT_CLASS in _all_const_values(registry_schema)


def test_native_receipt_is_rejected_by_every_dispatch_receipt_namespace(tmp_path: Path) -> None:
    document = json.loads(_native_receipt(tmp_path).to_bytes())

    for receipt_model in (
        PlatformCapabilityReceipt,
        RouteAuthorityReceipt,
        CapabilitySurfaceDeltaFile,
    ):
        with pytest.raises(ValidationError):
            receipt_model.model_validate(document)


def test_native_receipt_identities_cannot_be_rewrapped_as_policy_evidence(
    tmp_path: Path,
) -> None:
    native = _native_receipt(tmp_path)
    untyped_or_non_supply_refs = (
        native.receipt_sha256,
        native.run_id,
        f"sha256:{native.receipt_sha256}",
        f"run:{native.run_id}",
        native.non_supply_evidence_ref,
    )

    for evidence_ref in untyped_or_non_supply_refs:
        with pytest.raises(ValidationError):
            PlatformCapabilityReceipt.model_validate(_platform_policy_receipt_payload(evidence_ref))
        with pytest.raises(ValidationError):
            build_route_authority_receipt(
                receipt_type="local_inference_entitlement",
                route_id="local_tool.local.worker",
                evidence_refs=[evidence_ref],
                issued_at=NOW,
            )


@pytest.mark.parametrize(
    "marker",
    (
        AGENTIC_TRUST_EVIDENCE_SURFACE_ID,
        AGENTIC_TRUST_EVIDENCE_RECEIPT_CLASS,
        "agentic-trust-evidence-receipt-v1",
    ),
)
def test_observation_identity_cannot_satisfy_a_required_tool(marker: str) -> None:
    with pytest.raises(ValidationError):
        ToolState(
            tool_id=marker,
            available=True,
            observed_at=NOW,
            stale_after="1h",
            evidence_ref="local:tool:test",
        )
    with pytest.raises(ValidationError):
        RequiredTool(tool_id=marker)


def test_observation_identity_child_remains_an_ordinary_tool_identity() -> None:
    child = f"{AGENTIC_TRUST_EVIDENCE_RECEIPT_CLASS}Child"
    assert RequiredTool(tool_id=child).tool_id == child
    assert (
        ToolState(
            tool_id=child,
            available=True,
            observed_at=NOW,
            stale_after="1h",
            evidence_ref="local:tool:test",
        ).tool_id
        == child
    )


def test_separate_native_receipt_root_cannot_change_dispatch_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HAPAX_AGENTIC_TRUST_RECEIPT_DIR", raising=False)
    monkeypatch.delenv(CAPABILITY_SURFACE_DELTA_PATH_ENV, raising=False)
    platform_root = tmp_path / "platform-capability-receipts"
    baseline = load_dispatch_policy_sources(
        registry_path=PLATFORM_CAPABILITY_REGISTRY,
        quota_ledger_path=QUOTA_SPEND_LEDGER_FIXTURES,
        receipt_dir=platform_root,
        now=NOW,
    )

    native_root = tmp_path / "agentic-trust-receipts"
    native_root.mkdir()
    (native_root / "receipt.json").write_bytes(_native_receipt(tmp_path).to_bytes())
    monkeypatch.setenv("HAPAX_AGENTIC_TRUST_RECEIPT_DIR", str(native_root))
    observed = load_dispatch_policy_sources(
        registry_path=PLATFORM_CAPABILITY_REGISTRY,
        quota_ledger_path=QUOTA_SPEND_LEDGER_FIXTURES,
        receipt_dir=platform_root,
        now=NOW,
    )

    assert baseline.model_dump(mode="json") == observed.model_dump(mode="json")
    assert observed.registry_error is None
    assert observed.surface_delta_refs_by_route == {}
    assert observed.surface_delta_blockers_by_route == {}


def test_non_supply_observation_changes_only_its_dedicated_freshness_report() -> None:
    baseline = load_platform_capability_registry(receipt_dir=Path("/nonexistent"), now=NOW)
    payload = baseline.model_dump(mode="json")
    target = next(
        row
        for row in payload["omitted_capability_shapes"]
        if row["shape_id"] == AGENTIC_TRUST_EVIDENCE_SURFACE_ID
    )
    target.update(
        {
            "observed_at": NOW.isoformat(),
            "freshness_state": CapabilityShapeFreshnessState.FRESH.value,
            "evidence_refs": ["agentic-trust:test-observation"],
            "blocked_reasons": [],
        }
    )
    observed = PlatformCapabilityRegistry.model_validate(payload)

    assert baseline.route_map().keys() == observed.route_map().keys()
    assert [route.model_dump(mode="json") for route in baseline.routes] == [
        route.model_dump(mode="json") for route in observed.routes
    ]
    assert check_registry_freshness(baseline, now=NOW) == check_registry_freshness(
        observed,
        now=NOW,
    )
    no_refresh = RefreshStrategyRegistry()
    assert evaluate_registry_availability(
        baseline,
        now=NOW,
        refresh_strategies=no_refresh,
    ).model_dump(mode="json") == evaluate_registry_availability(
        observed,
        now=NOW,
        refresh_strategies=no_refresh,
    ).model_dump(mode="json")
    assert [
        build_supply_vector(route, now=NOW).model_dump(mode="json") for route in baseline.routes
    ] == [build_supply_vector(route, now=NOW).model_dump(mode="json") for route in observed.routes]
    assert check_omitted_shape_freshness(baseline, now=NOW) != check_omitted_shape_freshness(
        observed,
        now=NOW,
    )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("demand_eligible", True),
        ("route_ids", ["codex.headless.full"]),
        ("authority_ceiling", "authoritative"),
        ("surface_delta_signal", "capability_surface_delta:local_compute"),
        ("observation_receipt_class", "PlatformCapabilityReceipt"),
        ("__remove__", True),
    ],
)
def test_dispatch_loader_fails_closed_on_every_evidence_only_identity_boundary(
    tmp_path: Path,
    field_name: str,
    value: object,
) -> None:
    payload = json.loads(PLATFORM_CAPABILITY_REGISTRY.read_text(encoding="utf-8"))
    if field_name == "__remove__":
        payload["omitted_capability_shapes"] = [
            row
            for row in payload["omitted_capability_shapes"]
            if row["shape_id"] != AGENTIC_TRUST_EVIDENCE_SURFACE_ID
        ]
    else:
        target = next(
            row
            for row in payload["omitted_capability_shapes"]
            if row["shape_id"] == AGENTIC_TRUST_EVIDENCE_SURFACE_ID
        )
        target[field_name] = value
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PlatformCapabilityRegistryError):
        load_platform_capability_registry_for_dispatch(
            registry_path,
            now=NOW,
            apply_receipts=False,
        )


def test_operational_topology_has_no_agentic_trust_execution_wiring() -> None:
    execution_needles = (
        "hapax_agentic_trust",
        "hapax-agentic-trust",
        "HAPAX_AGENTIC_TRUST_RECEIPT_DIR",
    )
    semantic_needles = (
        AGENTIC_TRUST_EVIDENCE_SURFACE_ID,
        AGENTIC_TRUST_EVIDENCE_RECEIPT_CLASS,
        "AGENTIC_TRUST_EVIDENCE_SURFACE_ID",
        "AGENTIC_TRUST_EVIDENCE_RECEIPT_CLASS",
    )
    execution_allowed = {".github/workflows/agentic-trust-package.yml"}
    semantic_allowed = {
        "agents/deliberative_council/capability_admission.py",
        "config/capability-inventory-baseline.json",
        "config/platform-capability-registry.json",
        "schemas/capability-inventory-baseline.schema.json",
        "schemas/platform-capability-registry.schema.json",
        "shared/capability_inventory_contract.py",
        "shared/agentic_trust_boundary.py",
        "shared/cockpit_agent_capabilities.py",
        "shared/platform_capability_registry.py",
    }
    candidates = _repo_operational_files()
    execution_matches: set[str] = set()
    semantic_matches: set[str] = set()
    for path in candidates:
        source = path.read_text(encoding="utf-8", errors="ignore")
        relative_path = path.relative_to(ROOT).as_posix()
        if any(needle in source for needle in execution_needles):
            execution_matches.add(relative_path)
        if any(needle in source for needle in semantic_needles):
            semantic_matches.add(relative_path)

    assert execution_matches == execution_allowed
    assert semantic_matches == semantic_allowed


def test_strict_registry_loader_is_confined_to_reporting_not_admission() -> None:
    strict_name = "load_platform_capability_registry"
    strict_callers: set[str] = set()
    for path in _python_source_files():
        relative_path = path.relative_to(ROOT).as_posix()
        if relative_path == "shared/platform_capability_registry.py":
            continue
        source = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source, filename=str(path))
        references_strict_loader = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if any(alias.name == strict_name for alias in node.names) or (
                    node.module == "shared.platform_capability_registry"
                    and any(alias.name == "*" for alias in node.names)
                ):
                    references_strict_loader = True
            elif isinstance(node, ast.Import):
                if any(alias.name == "shared.platform_capability_registry" for alias in node.names):
                    references_strict_loader = True
            elif (
                isinstance(node, ast.Name)
                and node.id == strict_name
                or isinstance(node, ast.Attribute)
                and node.attr == strict_name
                or isinstance(node, ast.Constant)
                and node.value == strict_name
            ):
                references_strict_loader = True
        if references_strict_loader:
            strict_callers.add(relative_path)

    assert strict_callers == {"shared/capacity_routing_dashboard.py"}
    dispatch_name = "load_platform_capability_registry_for_dispatch"
    dispatch_callers: set[str] = set()
    for path in _python_source_files():
        relative_path = path.relative_to(ROOT).as_posix()
        if relative_path == "shared/platform_capability_registry.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"), filename=str(path))
        if any(
            isinstance(node, ast.ImportFrom)
            and any(alias.name == dispatch_name for alias in node.names)
            or isinstance(node, ast.Name)
            and node.id == dispatch_name
            or isinstance(node, ast.Attribute)
            and node.attr == dispatch_name
            for node in ast.walk(tree)
        ):
            dispatch_callers.add(relative_path)

    assert dispatch_callers == {
        "agents/deliberative_council/capability_admission.py",
        "scripts/cc-pr-review-dispatch.py",
        "scripts/hapax-capability-surface-delta-intake",
        "scripts/hapax-platform-capability-freshness",
        "scripts/hapax-platform-capability-receipts",
        "scripts/review_team.py",
        "shared/cockpit_agent_capabilities.py",
        "shared/dispatcher_policy.py",
    }
