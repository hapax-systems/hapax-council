import base64
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from shared.coord_dispatch import DispatchPreparationBinding, lane_ownership_projection_hashes
from shared.platform_capability_registry import PlatformCapabilityRegistry
from shared.quota_spend_ledger import QUOTA_SPEND_LEDGER_FIXTURES
from shared.relay_mq import (
    COORDINATOR_PREPARED_DISPATCH_REASON,
    prepare_coordinator_dispatch,
    send_message,
)
from shared.relay_mq_envelope import Envelope
from shared.sdlc_task_store import ClaimDispatchBinding
from tests.scripts.launcher_activation_fixture import install_launcher_activation

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-methodology-dispatch"
RECEIPT_SCRIPT = REPO_ROOT / "scripts" / "hapax-platform-capability-receipts"
REGISTRY = REPO_ROOT / "config" / "platform-capability-registry.json"
CLAUDE_DISPATCH_ADMISSION_WITNESS = "claude-subscription-headroom-observed-20260709t0710z"


def _dispatcher_module() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("hapax_methodology_dispatch", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[loader.name] = module
    spec.loader.exec_module(module)
    return module


def _fresh_registry(tmp_path: Path, *, codex_exec_auth_host: str = "appendix") -> Path:
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    checked_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    codex_host = (
        "hapax-appendix"
        if codex_exec_auth_host in {"appendix", "hapax-appendix"}
        else codex_exec_auth_host
    )
    for route in payload["routes"]:
        quota_refs = [f"test:{route['route_id']}:quota"]
        if route.get("capacity_pool") == "subscription_quota":
            quota_refs.append(f"test:{route['route_id']}:account-live-quota:observed")
        route["route_state"] = "active"
        route["blocked_reasons"] = []
        route["freshness"]["capability_checked_at"] = checked_at
        route["freshness"]["quota_checked_at"] = checked_at
        route["freshness"]["resource_checked_at"] = checked_at
        route["freshness"]["provider_docs_checked_at"] = checked_at
        route["freshness"]["evidence"] = {
            "capability": {
                "evidence_refs": [f"test:{route['route_id']}:capability"],
                "blocked_reasons": [],
            },
            "quota": {
                "evidence_refs": quota_refs,
                "blocked_reasons": [],
            },
            "resource": {
                "evidence_refs": [f"test:{route['route_id']}:resource"],
                "blocked_reasons": [],
            },
            "provider_docs": {
                "evidence_refs": [f"test:{route['route_id']}:provider_docs"],
                "blocked_reasons": [],
            },
        }
        if route.get("platform") == "codex" and route.get("auth_surface") == "oauth":
            route["freshness"]["evidence"]["capability"]["evidence_refs"].append(
                f"host:{codex_host}:codex:exec:auth:saved-login:observed"
            )
        for score in route["capability_scores"].values():
            score["observed_at"] = checked_at
        for tool in route["tool_state"]:
            tool["observed_at"] = checked_at
    path = tmp_path / "fixtures" / "fresh-platform-capability-registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_codex_access_token(tmp_path: Path) -> Path:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    payload = (
        base64.urlsafe_b64encode(
            json.dumps({"exp": int(datetime.now(UTC).timestamp()) + 3600}).encode()
        )
        .decode()
        .rstrip("=")
    )
    target = tmp_path / "codex-oauth" / "access_token"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{header}.{payload}.sig", encoding="utf-8")
    target.chmod(0o600)
    return target


def _without_account_live_quota_evidence(
    tmp_path: Path,
    registry_path: Path,
    route_id: str,
) -> Path:
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    for route in payload["routes"]:
        if route["route_id"] != route_id:
            continue
        quota = route["freshness"]["evidence"]["quota"]
        quota["evidence_refs"] = [
            ref for ref in quota["evidence_refs"] if "account-live-quota" not in ref
        ]
    path = tmp_path / "fixtures" / "no-account-live-platform-capability-registry.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _availability_degraded_registry(tmp_path: Path, route_id: str) -> Path:
    path = _fresh_registry(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    for route in payload["routes"]:
        if route["route_id"] != route_id:
            continue
        route["freshness"]["quota_checked_at"] = "2026-01-01T00:00:00Z"
        route["freshness"]["evidence"]["quota"]["evidence_refs"] = [
            f"test:{route_id}:quota:degraded"
        ]
    degraded_path = tmp_path / "fixtures" / "degraded-platform-capability-registry.json"
    degraded_path.write_text(json.dumps(payload), encoding="utf-8")
    return degraded_path


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _claude_subscription_quota_ledger(
    tmp_path: Path,
    *,
    state: str,
    evidence_refs: list[str] | None = None,
    fresh_until: datetime | None = None,
) -> Path:
    now = datetime.now(UTC).replace(microsecond=0)
    payload = json.loads(QUOTA_SPEND_LEDGER_FIXTURES.read_text(encoding="utf-8"))
    payload["captured_at"] = _iso(now)
    payload["paid_api_budget_freshness_ttl_s"] = 3600
    generated_from = list(payload.get("generated_from", []))
    if "scripts/hapax-quota-telemetry-writer" not in generated_from:
        generated_from.append("scripts/hapax-quota-telemetry-writer")
    payload["generated_from"] = generated_from
    payload["quota_snapshots"] = [
        snapshot
        for snapshot in payload.get("quota_snapshots", [])
        if snapshot.get("route_id") != "claude.headless.full"
    ]
    snapshot: dict[str, object] = {
        "quota_snapshot_schema": 1,
        "snapshot_id": f"quota-claude-headless-full-{state}-dispatch-test",
        "captured_at": _iso(now),
        "route_id": "claude.headless.full",
        "provider": "anthropic-claude-subscription",
        "capacity_pool": "subscription_quota",
        "subscription_quota_state": state,
        "evidence_refs": evidence_refs
        if evidence_refs is not None
        else ["relay-receipt:claude:quota-admission:absent"],
        "operator_visible_reason": f"dispatch test claude account-live quota {state}",
    }
    if fresh_until is not None:
        snapshot["fresh_until"] = _iso(fresh_until)
    payload["quota_snapshots"].append(snapshot)
    path = tmp_path / "fixtures" / f"quota-spend-ledger-claude-{state}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _fresh_claude_subscription_quota_ledger(tmp_path: Path) -> Path:
    now = datetime.now(UTC).replace(microsecond=0)
    fresh_until = now + timedelta(minutes=15)
    evidence_ref = (
        "relay-receipt:claude-subscription-quota-admission-dispatch-test.yaml:"
        f"witness:{CLAUDE_DISPATCH_ADMISSION_WITNESS}:"
        "observation:subscription_quota_headroom_observed:"
        f"observed_at:{_iso(now)}:"
        f"fresh_until:{_iso(fresh_until)}:"
        "account-live-quota:observed"
    )
    return _claude_subscription_quota_ledger(
        tmp_path,
        state="fresh",
        evidence_refs=[evidence_ref],
        fresh_until=fresh_until,
    )


def _registry_from_path(path: Path) -> PlatformCapabilityRegistry:
    return PlatformCapabilityRegistry.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _availability_dispatch_request(
    module: ModuleType,
    registry: PlatformCapabilityRegistry,
    route_id: str = "codex.headless.full",
):
    platform, mode, profile = route_id.split(".", 2)
    route = module.route_for(platform, mode, profile)
    return module.build_dispatch_request(
        task_id="governed-build",
        lane="cx-green",
        platform=platform,
        mode=mode,
        profile=profile,
        task_fields={"kind": "build", "authority_case": "CASE-TEST-001"},
        registry=registry,
        legacy_route_supported=route is not None,
        legacy_route_mutable=route.mutable if route else False,
        now=datetime.now(UTC),
    )


def _fake_binary(bin_dir: Path, name: str, output: str) -> None:
    target = bin_dir / name
    target.write_text(f"#!/bin/sh\nprintf '%s\\n' '{output}'\n", encoding="utf-8")
    target.chmod(0o755)


def _codex_only_build_frontmatter(spec: Path) -> str:
    return f"""
    kind: build
    authority_case: CASE-TEST-001
    parent_spec: {spec}
    route_metadata_schema: 1
    quality_floor: frontier_required
    authority_level: authoritative
    mutation_surface: source
    mutation_scope_refs: []
    risk_flags:
      governance_sensitive: false
      privacy_or_secret_sensitive: false
      public_claim_sensitive: false
      aesthetic_theory_sensitive: false
      audio_or_live_egress_sensitive: false
      provider_billing_sensitive: false
    context_shape:
      codebase_locality: module
      vault_context_required: true
      external_docs_required: false
      currentness_required: false
    verification_surface:
      deterministic_tests: []
      static_checks: []
      runtime_observation: []
      operator_only: false
    route_constraints:
      preferred_platforms: [codex]
      allowed_platforms: [codex]
      prohibited_platforms: []
      required_mode: headless
      required_profile: full
    review_requirement:
      support_artifact_allowed: false
      independent_review_required: false
      authoritative_acceptor_profile: null
    """


def _default_route_metadata(frontmatter: str) -> str:
    if "route_metadata_schema:" in frontmatter:
        return frontmatter
    if "kind: build" in frontmatter and "authority_case:" in frontmatter:
        return frontmatter + textwrap.dedent(
            """
                route_metadata_schema: 1
                quality_floor: frontier_required
                authority_level: authoritative
                mutation_surface: source
                mutation_scope_refs: []
                risk_flags:
                  governance_sensitive: false
                  privacy_or_secret_sensitive: false
                  public_claim_sensitive: false
                  aesthetic_theory_sensitive: false
                  audio_or_live_egress_sensitive: false
                  provider_billing_sensitive: false
                context_shape:
                  codebase_locality: module
                  vault_context_required: true
                  external_docs_required: false
                  currentness_required: false
                verification_surface:
                  deterministic_tests: []
                  static_checks: []
                  runtime_observation: []
                  operator_only: false
                route_constraints:
                  preferred_platforms: []
                  allowed_platforms: []
                  prohibited_platforms: []
                  required_mode: null
                  required_profile: null
                review_requirement:
                  support_artifact_allowed: false
                  independent_review_required: false
                  authoritative_acceptor_profile: null
                """
        )
    if "read-only" in frontmatter:
        return frontmatter + textwrap.dedent(
            """
                route_metadata_schema: 1
                quality_floor: deterministic_ok
                authority_level: relay_only
                mutation_surface: none
                mutation_scope_refs: []
                risk_flags:
                  governance_sensitive: false
                  privacy_or_secret_sensitive: false
                  public_claim_sensitive: false
                  aesthetic_theory_sensitive: false
                  audio_or_live_egress_sensitive: false
                  provider_billing_sensitive: false
                context_shape:
                  codebase_locality: none
                  vault_context_required: false
                  external_docs_required: false
                  currentness_required: false
                verification_surface:
                  deterministic_tests: []
                  static_checks: []
                  runtime_observation: []
                  operator_only: false
                route_constraints:
                  preferred_platforms: []
                  allowed_platforms: []
                  prohibited_platforms: []
                  required_mode: null
                  required_profile: null
                review_requirement:
                  support_artifact_allowed: false
                  independent_review_required: false
                  authoritative_acceptor_profile: null
                """
        )
    return frontmatter


def _governed_source_frontmatter(
    spec: Path,
    *,
    extra: str = "",
    mutation_scope_refs: str = "[]",
    preferred_platforms: str = "[]",
    allowed_platforms: str = "[]",
    prohibited_platforms: str = "[]",
    required_mode: str = "null",
    required_profile: str = "null",
) -> str:
    return f"""
    kind: build
    authority_case: CASE-TEST-001
    parent_spec: {spec}
    {extra}
    route_metadata_schema: 1
    quality_floor: frontier_required
    authority_level: authoritative
    mutation_surface: source
    mutation_scope_refs: {mutation_scope_refs}
    risk_flags:
      governance_sensitive: false
      privacy_or_secret_sensitive: false
      public_claim_sensitive: false
      aesthetic_theory_sensitive: false
      audio_or_live_egress_sensitive: false
      provider_billing_sensitive: false
    context_shape:
      codebase_locality: module
      vault_context_required: true
      external_docs_required: false
      currentness_required: false
    verification_surface:
      deterministic_tests: []
      static_checks: []
      runtime_observation: []
      operator_only: false
    route_constraints:
      preferred_platforms: {preferred_platforms}
      allowed_platforms: {allowed_platforms}
      prohibited_platforms: {prohibited_platforms}
      required_mode: {required_mode}
      required_profile: {required_profile}
    review_requirement:
      support_artifact_allowed: false
      independent_review_required: false
      authoritative_acceptor_profile: null
    """


def _operator_coupled_manifest(tmp_path: Path, *, body: str | None = None) -> Path:
    manifest = tmp_path / "invariant-manifest.yaml"
    manifest.write_text(
        body
        if body is not None
        else textwrap.dedent(
            """\
            schema_version: 1
            unknown_path_policy: flag
            classes:
              operator_coupled:
                policy:
                  dispatch_mode: interactive_only
            invariants:
              - id: operator-coupled-broadcast-visual
                class: operator_coupled
                globs:
                  - agents/studio_compositor/**
            """
        ),
        encoding="utf-8",
    )
    return manifest


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _task(
    root: Path,
    task_id: str,
    frontmatter: str,
    *,
    status: str = "offered",
    assigned_to: str = "unassigned",
    route_metadata_defaults: bool = True,
) -> Path:
    frontmatter_text = textwrap.dedent(frontmatter).strip()
    if route_metadata_defaults:
        frontmatter_text = _default_route_metadata(frontmatter_text)
    return _write(
        root / "active" / f"{task_id}.md",
        "\n".join(
            [
                "---",
                "type: cc-task",
                f"task_id: {task_id}",
                f'title: "{task_id}"',
                f"status: {status}",
                f"assigned_to: {assigned_to}",
                frontmatter_text,
                "---",
                "",
                f"# {task_id}",
                "",
            ]
        ),
    )


def _spec(path: Path, case_id: str = "CASE-TEST-001") -> Path:
    return _write(
        path,
        textwrap.dedent(
            f"""\
            ---
            status: implementation_slice_authorization_packet
            case_id: {case_id}
            slice_id: SLICE-TEST
            ---

            # Test ISAP
            """
        ),
    )


def _worktree(path: Path, *, guarded: bool = True, close_guarded: bool = True) -> Path:
    guard = (
        "missing required AuthorityCase/ISAP fields authority_case parent_spec"
        if guarded
        else "legacy cc-claim"
    )
    claim_lines = ["#!/usr/bin/env bash", f"# {guard}"]
    if guarded:
        claim_lines.extend(
            [
                'if [[ "${1:-}" == "--dispatch-protocol-version" ]]; then',
                "  echo hapax-claim-dispatch-v1",
                "  exit 0",
                "fi",
            ]
        )
    claim_lines.extend(["exit 0", ""])
    claim = _write(path / "scripts" / "cc-claim", "\n".join(claim_lines))
    claim.chmod(0o755)
    close_lines = ["#!/usr/bin/env bash"]
    if close_guarded:
        close_lines.extend(
            [
                'if [[ "${1:-}" == "--dispatch-protocol-version" ]]; then',
                "  echo hapax-close-dispatch-v1",
                "  exit 0",
                "fi",
            ]
        )
    close_lines.extend(["exit 0", ""])
    close = _write(path / "scripts" / "cc-close", "\n".join(close_lines))
    close.chmod(0o755)
    return path


def _arg_value(args: tuple[str, ...], name: str) -> str | None:
    if name not in args:
        return None
    index = args.index(name)
    if index + 1 >= len(args):
        return None
    return args[index + 1]


def _frontmatter_scalar(path: Path, key: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip().strip('"')
    return ""


def _write_resume_projection(
    cache: Path,
    *,
    lane: str,
    task_id: str,
    platform: str = "codex",
    session_id: str = "11111111-2222-4333-8444-555555555555",
) -> str:
    cache.mkdir(parents=True, exist_ok=True)
    binding = ClaimDispatchBinding.create(
        task_id=task_id,
        lane=lane,
        session_id=session_id,
        claim_epoch=1234,
        dispatch_message_id="message-1",
        platform=platform,
        mode="headless",
        profile="full",
        authority_case="CASE-TEST-001",
        binding_hash="a" * 64,
    )
    for key in (lane, f"{lane}-{session_id}"):
        (cache / f"cc-active-task-{key}").write_text(f"{task_id}\n", encoding="utf-8")
        (cache / f"cc-claim-epoch-{key}").write_text(
            f"1234 {task_id}\n",
            encoding="utf-8",
        )
        (cache / f"cc-claim-dispatch-{key}.json").write_text(
            json.dumps(binding.to_record()),
            encoding="ascii",
        )
    return session_id


def _maybe_write_durable_mq_binding(
    tmp_path: Path, args: tuple[str, ...]
) -> tuple[Path, str | None]:
    db_path = tmp_path / "relay" / "messages.db"
    task_id = _arg_value(args, "--task")
    lane = _arg_value(args, "--lane")
    if not task_id or not lane:
        return db_path, None
    task_path = tmp_path / "tasks" / "active" / f"{task_id}.md"
    if not task_path.exists():
        return db_path, None
    authority_case = _frontmatter_scalar(task_path, "authority_case")
    if not authority_case or authority_case in {"null", "None", "~"}:
        return db_path, None
    parent_spec = _frontmatter_scalar(task_path, "parent_spec")
    parent_spec_path = Path(parent_spec).expanduser()
    if not parent_spec_path.is_absolute():
        parent_spec_path = tmp_path / "home" / "Documents" / "Personal" / parent_spec_path
    if not parent_spec_path.is_file():
        return db_path, None
    cache_dir = tmp_path / "home" / ".cache" / "hapax"
    claim_hash, relay_hash = lane_ownership_projection_hashes(
        cache_dir=cache_dir,
        relay_dir=cache_dir / "relay",
        role=lane,
        session="",
    )
    pid = os.getpid()
    stat_text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    generation = f"pid:{pid}:{stat_text.rsplit(')', 1)[1].split()[19]}"
    binding = DispatchPreparationBinding(
        task_id=task_id,
        task_path=str(task_path.resolve()),
        task_sha256=hashlib.sha256(task_path.read_bytes()).hexdigest(),
        lane=lane,
        lane_session="",
        lane_generation=generation,
        lane_pid=pid,
        lane_pid_generation=generation,
        claim_projection_sha256=claim_hash,
        relay_projection_sha256=relay_hash,
        platform=_arg_value(args, "--platform") or "claude",
        mode=_arg_value(args, "--mode") or "headless",
        authority_case=authority_case,
        authority_item=_frontmatter_scalar(task_path, "authority_item") or task_id,
        parent_spec=parent_spec,
        parent_spec_sha256=hashlib.sha256(parent_spec_path.read_bytes()).hexdigest(),
    )
    payload = json.dumps(
        {
            "dispatch_binding": binding.to_record(),
            "kind": "coordinator_dispatch",
            "task_id": task_id,
            "lane": lane,
            "platform": binding.platform,
            "mode": binding.mode,
            "parent_spec": parent_spec,
        },
        sort_keys=True,
    )
    db_path.parent.mkdir(parents=True, exist_ok=True)
    preparation = prepare_coordinator_dispatch(
        db_path,
        Envelope(
            sender="hapax-coordinator",
            message_type="dispatch",
            priority=0,
            subject=task_id,
            authority_case=authority_case,
            authority_item=binding.authority_item,
            recipients_spec=lane,
            payload=payload,
        ),
    )
    return db_path, preparation.message_id


def _recipient_row(db_path: Path, message_id: str, recipient: str) -> sqlite3.Row:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT r.state, r.reason, m.message_id
            FROM recipients r
            JOIN messages m ON m.message_id = r.message_id
            WHERE m.message_id = :message_id
              AND r.recipient = :recipient
            """,
            {"message_id": message_id, "recipient": recipient},
        ).fetchone()
    assert row is not None
    return row


def test_claim_sweep_projects_blocked_unassigned_without_detaching(tmp_path: Path) -> None:
    module = _dispatcher_module()
    claims = tmp_path / "claims"
    active = tmp_path / "tasks" / "active"
    claims.mkdir(parents=True)
    active.mkdir(parents=True)
    task_id = "p0-incident-blocked-task"
    claim = claims / "cc-active-task-gamma-9b6ba5ca-513c-41aa-9900-d3026b42aad1"
    claim_key = claim.name.removeprefix("cc-active-task-")
    epoch = claims / f"cc-claim-epoch-{claim_key}"
    binding = claims / f"cc-claim-dispatch-{claim_key}.json"
    claim.write_text(f"{task_id}\n", encoding="utf-8")
    epoch.write_text(f"1000 {task_id}\n", encoding="utf-8")
    binding.write_text("{}\n", encoding="utf-8")
    (active / f"{task_id}.md").write_text(
        f"---\ntask_id: {task_id}\nstatus: blocked\nassigned_to: unassigned\n---\n",
        encoding="utf-8",
    )
    old = 1000.0
    os.utime(claim, (old, old))

    candidates = module.sweep_stale_claims(claims, active, now=old + 301, grace_secs=300)

    assert candidates == [(claim.name, task_id, "blocked-unassigned")]
    assert claim.read_text(encoding="utf-8") == f"{task_id}\n"
    assert epoch.read_text(encoding="utf-8") == f"1000 {task_id}\n"
    assert binding.read_text(encoding="utf-8") == "{}\n"


def test_claim_sweep_holds_when_canonical_task_store_is_unavailable(tmp_path: Path) -> None:
    module = _dispatcher_module()
    claims = tmp_path / "claims"
    claims.mkdir()
    task_id = "task-on-unavailable-store"
    claim = claims / "cc-active-task-cx-red"
    claim.write_text(f"{task_id}\n", encoding="utf-8")
    old = 1000.0
    os.utime(claim, (old, old))

    candidates = module.sweep_stale_claims(
        claims,
        tmp_path / "missing" / "active",
        now=old + 301,
        grace_secs=300,
    )

    assert candidates == []
    assert claim.read_text(encoding="utf-8") == f"{task_id}\n"


def test_dispatch_lane_blocker_rejects_unreadable_pid_generation(tmp_path: Path) -> None:
    module = _dispatcher_module()
    parent_spec = _spec(tmp_path / "spec.md")
    binding = DispatchPreparationBinding(
        task_id="task-1",
        task_path=str(tmp_path / "task-1.md"),
        task_sha256="1" * 64,
        lane="cx-red",
        lane_session="",
        lane_generation="pid:99999999:1",
        lane_pid=99_999_999,
        lane_pid_generation="pid:99999999:1",
        claim_projection_sha256="2" * 64,
        relay_projection_sha256="3" * 64,
        platform="codex",
        mode="headless",
        authority_case="CASE-TEST-001",
        authority_item="task-1",
        parent_spec=str(parent_spec),
        parent_spec_sha256=hashlib.sha256(parent_spec.read_bytes()).hexdigest(),
    )

    assert module.dispatch_preparation_lane_blocker(binding) == ("dispatch_lane_generation_changed")


def test_dispatch_lane_blocker_rejects_changed_parent_spec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _dispatcher_module()
    home = tmp_path / "home"
    cache_dir = home / ".cache" / "hapax"
    relay_dir = cache_dir / "relay"
    cache_dir.mkdir(parents=True)
    relay_dir.mkdir()
    parent_spec = _spec(tmp_path / "spec.md")
    claim_hash, relay_hash = lane_ownership_projection_hashes(
        cache_dir=cache_dir,
        relay_dir=relay_dir,
        role="cx-red",
        session="",
    )
    pid = os.getpid()
    stat_text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    generation = f"pid:{pid}:{stat_text.rsplit(')', 1)[1].split()[19]}"
    binding = DispatchPreparationBinding(
        task_id="task-1",
        task_path=str(tmp_path / "task-1.md"),
        task_sha256="1" * 64,
        lane="cx-red",
        lane_session="",
        lane_generation=generation,
        lane_pid=pid,
        lane_pid_generation=generation,
        claim_projection_sha256=claim_hash,
        relay_projection_sha256=relay_hash,
        platform="codex",
        mode="headless",
        authority_case="CASE-TEST-001",
        authority_item="task-1",
        parent_spec=str(parent_spec),
        parent_spec_sha256=hashlib.sha256(parent_spec.read_bytes()).hexdigest(),
    )
    monkeypatch.setenv("HOME", str(home))
    parent_spec.write_text(parent_spec.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")

    assert module.dispatch_preparation_lane_blocker(binding) == (
        "dispatch_parent_spec_preimage_changed"
    )


def test_claim_sweep_ignores_body_status_lines(tmp_path: Path) -> None:
    module = _dispatcher_module()
    claims = tmp_path / "claims"
    active = tmp_path / "tasks" / "active"
    claims.mkdir(parents=True)
    active.mkdir(parents=True)
    task_id = "p0-incident-body-status"
    claim = claims / "cc-active-task-gamma-9b6ba5ca-513c-41aa-9900-d3026b42aad1"
    claim.write_text(f"{task_id}\n", encoding="utf-8")
    (active / f"{task_id}.md").write_text(
        f"---\ntask_id: {task_id}\nstatus: claimed\nassigned_to: gamma\n---\n"
        "\n# Notes\n\nstatus: blocked\nassigned_to: unassigned\n",
        encoding="utf-8",
    )
    old = 1000.0
    os.utime(claim, (old, old))

    reaped = module.sweep_stale_claims(claims, active, now=old + 301, grace_secs=300)

    assert reaped == []
    assert claim.exists()


def test_lane_active_task_lease_reads_session_keyed_claim(tmp_path: Path) -> None:
    module = _dispatcher_module()
    claims = tmp_path / "claims"
    claims.mkdir(parents=True)
    task_id = "p0-incident-session-keyed-pickup"
    claim = claims / "cc-active-task-gamma-9b6ba5ca-513c-41aa-9900-d3026b42aad1"
    claim.write_text(f"{task_id}\n", encoding="utf-8")

    previous = os.environ.get("HAPAX_CC_CLAIMS_DIR")
    os.environ["HAPAX_CC_CLAIMS_DIR"] = str(claims)
    try:
        assert module.lane_active_task_lease("gamma") == task_id
    finally:
        if previous is None:
            os.environ.pop("HAPAX_CC_CLAIMS_DIR", None)
        else:
            os.environ["HAPAX_CC_CLAIMS_DIR"] = previous


def test_operator_coupled_path_match_accepts_absolute_repo_paths(tmp_path: Path) -> None:
    module = _dispatcher_module()
    absolute_ref = str(REPO_ROOT / "agents" / "studio_compositor" / "programme.py")
    previous = os.environ.get("HAPAX_INVARIANT_MANIFEST")
    os.environ["HAPAX_INVARIANT_MANIFEST"] = str(_operator_coupled_manifest(tmp_path))
    try:
        matches = module.operator_coupled_path_matches({"mutation_scope_refs": [absolute_ref]})
    finally:
        if previous is None:
            os.environ.pop("HAPAX_INVARIANT_MANIFEST", None)
        else:
            os.environ["HAPAX_INVARIANT_MANIFEST"] = previous

    assert matches == ("agents/studio_compositor/programme.py#operator-coupled-broadcast-visual",)


def test_operator_coupled_path_match_reads_nested_route_metadata(tmp_path: Path) -> None:
    module = _dispatcher_module()
    previous = os.environ.get("HAPAX_INVARIANT_MANIFEST")
    os.environ["HAPAX_INVARIANT_MANIFEST"] = str(_operator_coupled_manifest(tmp_path))
    try:
        matches = module.operator_coupled_path_matches(
            {
                "route_metadata": {
                    "route_metadata_schema": 1,
                    "quality_floor": "frontier_required",
                    "authority_level": "authoritative",
                    "mutation_surface": "source",
                    "mutation_scope_refs": ["agents/studio_compositor/programme.py"],
                }
            }
        )
    finally:
        if previous is None:
            os.environ.pop("HAPAX_INVARIANT_MANIFEST", None)
        else:
            os.environ["HAPAX_INVARIANT_MANIFEST"] = previous

    assert matches == ("agents/studio_compositor/programme.py#operator-coupled-broadcast-visual",)


def test_operator_coupled_path_match_reports_manifest_failure_detail(tmp_path: Path) -> None:
    module = _dispatcher_module()
    previous = os.environ.get("HAPAX_INVARIANT_MANIFEST")
    os.environ["HAPAX_INVARIANT_MANIFEST"] = str(_operator_coupled_manifest(tmp_path, body="[]\n"))
    try:
        matches = module.operator_coupled_path_matches(
            {"mutation_scope_refs": ["agents/studio_compositor/programme.py"]}
        )
    finally:
        if previous is None:
            os.environ.pop("HAPAX_INVARIANT_MANIFEST", None)
        else:
            os.environ["HAPAX_INVARIANT_MANIFEST"] = previous

    assert matches == ("manifest_unavailable:RuntimeError:invariant-manifest-is-not-a-mapping",)


def test_operator_coupled_path_match_rejects_non_string_globs(tmp_path: Path) -> None:
    module = _dispatcher_module()
    manifest = _operator_coupled_manifest(
        tmp_path,
        body=textwrap.dedent(
            """\
            schema_version: 1
            unknown_path_policy: flag
            classes:
              operator_coupled:
                policy:
                  dispatch_mode: interactive_only
            invariants:
              - id: operator-coupled-broadcast-visual
                class: operator_coupled
                globs:
                  - agents/studio_compositor/**
                  - 123
            """
        ),
    )
    previous = os.environ.get("HAPAX_INVARIANT_MANIFEST")
    os.environ["HAPAX_INVARIANT_MANIFEST"] = str(manifest)
    try:
        matches = module.operator_coupled_path_matches(
            {"mutation_scope_refs": ["agents/studio_compositor/programme.py"]}
        )
    finally:
        if previous is None:
            os.environ.pop("HAPAX_INVARIANT_MANIFEST", None)
        else:
            os.environ["HAPAX_INVARIANT_MANIFEST"] = previous

    assert matches == (
        "manifest_unavailable:RuntimeError:"
        "operator_coupled-invariant-operator-coupled-broadcast-visual-has-non-string-glob",
    )


def test_operator_coupled_path_match_rejects_non_list_globs(tmp_path: Path) -> None:
    module = _dispatcher_module()
    manifest = _operator_coupled_manifest(
        tmp_path,
        body=textwrap.dedent(
            """\
            schema_version: 1
            unknown_path_policy: flag
            classes:
              operator_coupled:
                policy:
                  dispatch_mode: interactive_only
            invariants:
              - id: operator-coupled-broadcast-visual
                class: operator_coupled
                globs: agents/studio_compositor/**
            """
        ),
    )
    previous = os.environ.get("HAPAX_INVARIANT_MANIFEST")
    os.environ["HAPAX_INVARIANT_MANIFEST"] = str(manifest)
    try:
        matches = module.operator_coupled_path_matches(
            {"mutation_scope_refs": ["agents/studio_compositor/programme.py"]}
        )
    finally:
        if previous is None:
            os.environ.pop("HAPAX_INVARIANT_MANIFEST", None)
        else:
            os.environ["HAPAX_INVARIANT_MANIFEST"] = previous

    assert matches == (
        "manifest_unavailable:RuntimeError:"
        "operator_coupled-invariant-operator-coupled-broadcast-visual-globs-is-not-a-list",
    )


def test_operator_coupled_path_match_reports_missing_manifest(tmp_path: Path) -> None:
    module = _dispatcher_module()
    previous = os.environ.get("HAPAX_INVARIANT_MANIFEST")
    os.environ["HAPAX_INVARIANT_MANIFEST"] = str(tmp_path / "missing-invariant-manifest.yaml")
    try:
        matches = module.operator_coupled_path_matches(
            {"mutation_scope_refs": ["agents/studio_compositor/programme.py"]}
        )
    finally:
        if previous is None:
            os.environ.pop("HAPAX_INVARIANT_MANIFEST", None)
        else:
            os.environ["HAPAX_INVARIANT_MANIFEST"] = previous

    assert len(matches) == 1
    assert matches[0].startswith("manifest_unavailable:FileNotFoundError:")


def test_operator_coupled_glob_matching_segment_semantics() -> None:
    module = _dispatcher_module()

    assert module._path_matches_glob(
        "agents/studio_compositor/programme.py",
        "agents/studio_compositor/**",
    )
    assert module._path_matches_glob(
        "agents/studio_compositor/programme.py",
        "agents/**/programme.py",
    )
    assert module._path_matches_glob("config/screwm-a.json", "config/screwm-?.json")
    assert not module._path_matches_glob(
        "agents/studio_compositor/nested/programme.py",
        "agents/studio_compositor/*.py",
    )


def _run(
    tmp_path: Path,
    *args: str,
    extra_env: dict[str, str] | None = None,
    durable_mq: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["HAPAX_CC_TASK_ROOT"] = str(tmp_path / "tasks")
    env["HAPAX_DISPATCH_WORKTREE"] = str(tmp_path / "worktree")
    env["HAPAX_ORCHESTRATION_LEDGER_DIR"] = str(tmp_path / "ledger")
    env["HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR"] = str(tmp_path / "platform-receipts")
    env["HAPAX_QUOTA_SPEND_LEDGER"] = str(_fresh_claude_subscription_quota_ledger(tmp_path))
    env["HAPAX_COORD_LEDGER_DB"] = str(tmp_path / "coord" / "ledger.db")
    env["HAPAX_COORD_JSONL_MIRROR"] = str(tmp_path / "coord" / "ledger.jsonl")
    env["HAPAX_COORD_SPOOL_DIR"] = str(tmp_path / "coord" / "spool")
    if durable_mq:
        mq_db, message_id = _maybe_write_durable_mq_binding(tmp_path, args)
        env["HAPAX_RELAY_MQ_DB"] = str(mq_db)
        if message_id:
            env["HAPAX_METHODOLOGY_DISPATCH_MESSAGE_ID"] = message_id
    else:
        env["HAPAX_RELAY_MQ_DB"] = str(tmp_path / "relay" / "missing.db")
        env["HAPAX_METHODOLOGY_DISPATCH_MESSAGE_ID"] = "missing-message-id"
    if extra_env:
        env.update(extra_env)
    codex_exec_auth_host = (
        env.get("HAPAX_CODEX_EXEC_AUTH_HOST")
        or env.get("HAPAX_DISPATCH_HOST")
        or env.get("HAPAX_DEFAULT_DISPATCH_HOST")
        or "appendix"
    )
    env.setdefault(
        "HAPAX_PLATFORM_CAPABILITY_REGISTRY",
        str(_fresh_registry(tmp_path, codex_exec_auth_host=codex_exec_auth_host)),
    )
    return subprocess.run(
        [str(SCRIPT), *args],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_read_task_rejects_filename_frontmatter_identity_mismatch(tmp_path: Path) -> None:
    module = _dispatcher_module()
    _write(
        tmp_path / "tasks" / "active" / "requested-id.md",
        "---\ntask_id: different-id\nstatus: offered\nassigned_to: unassigned\n---\n",
    )

    assert module.read_task(tmp_path / "tasks", "requested-id") is None


def test_read_task_malformed_exact_path_cannot_fall_through_to_prefix_sibling(
    tmp_path: Path,
) -> None:
    module = _dispatcher_module()
    _write(
        tmp_path / "tasks" / "active" / "requested-id.md",
        "---\ntask_id: different-id\nstatus: offered\nassigned_to: unassigned\n---\n",
    )
    _write(
        tmp_path / "tasks" / "active" / "requested-id-followup.md",
        "---\ntask_id: requested-id\nstatus: offered\nassigned_to: unassigned\n---\n",
    )

    assert module.read_task(tmp_path / "tasks", "requested-id") is None


def test_read_task_exact_path_precedes_valid_prefix_sibling(tmp_path: Path) -> None:
    module = _dispatcher_module()
    _write(
        tmp_path / "tasks" / "active" / "requested-id.md",
        "---\ntask_id: requested-id\nstatus: offered\nassigned_to: unassigned\n---\n",
    )
    _write(
        tmp_path / "tasks" / "active" / "requested-id-copy.md",
        "---\ntask_id: requested-id-copy\nstatus: offered\nassigned_to: unassigned\n---\n",
    )

    task = module.read_task(tmp_path / "tasks", "requested-id")
    assert task is not None
    assert task.path.name == "requested-id.md"


def test_read_task_rejects_multiple_prefix_notes_for_same_identity(tmp_path: Path) -> None:
    module = _dispatcher_module()
    for suffix in ("one", "two"):
        _write(
            tmp_path / "tasks" / "active" / f"requested-id-{suffix}.md",
            "---\ntask_id: requested-id\nstatus: offered\nassigned_to: unassigned\n---\n",
        )

    assert module.read_task(tmp_path / "tasks", "requested-id") is None


@pytest.mark.parametrize(
    "owner_line",
    ["", "assigned_to: []\n"],
)
def test_read_task_rejects_missing_or_malformed_ownership(
    tmp_path: Path,
    owner_line: str,
) -> None:
    module = _dispatcher_module()
    _write(
        tmp_path / "tasks" / "active" / "requested-id.md",
        f"---\ntask_id: requested-id\nstatus: offered\n{owner_line}---\n",
    )

    assert module.read_task(tmp_path / "tasks", "requested-id") is None


def test_read_task_accepts_explicit_null_ownership(tmp_path: Path) -> None:
    module = _dispatcher_module()
    _write(
        tmp_path / "tasks" / "active" / "requested-id.md",
        "---\ntask_id: requested-id\nstatus: offered\nassigned_to: null\n---\n",
    )

    task = module.read_task(tmp_path / "tasks", "requested-id")
    assert task is not None
    assert task.fields["assigned_to"] is None


@pytest.mark.parametrize("owner_line", [None, "assigned_to: []"])
def test_dispatch_blocks_missing_or_malformed_task_ownership(
    tmp_path: Path,
    owner_line: str | None,
) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    task_path = _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )
    replacement = "" if owner_line is None else f"{owner_line}\n"
    task_path.write_text(
        task_path.read_text(encoding="utf-8").replace(
            "assigned_to: unassigned\n",
            replacement,
        ),
        encoding="utf-8",
    )

    result = _run(tmp_path, "--task", "governed-build", "--lane", "cx-green")

    assert result.returncode == 10
    assert "task not found" in result.stderr


def test_blocks_mutation_task_with_null_parent_spec(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    _task(
        tmp_path / "tasks",
        "bad-build",
        """
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: null
        """,
    )

    result = _run(tmp_path, "--task", "bad-build", "--lane", "beta")

    assert result.returncode == 10
    assert "missing required AuthorityCase/ISAP fields" in result.stderr
    assert "parent_spec" in result.stderr
    ledger = (tmp_path / "ledger" / "methodology-dispatch.jsonl").read_text(encoding="utf-8")
    assert '"ok": false' in ledger


def test_blocks_mutation_task_with_malformed_parent_spec(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _write(tmp_path / "malformed-spec.md", "not frontmatter\n")
    _task(
        tmp_path / "tasks",
        "malformed-parent-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )

    result = _run(
        tmp_path,
        "--task",
        "malformed-parent-build",
        "--lane",
        "cx-green",
    )

    assert result.returncode == 10
    assert "parent_spec frontmatter is malformed or unreadable" in result.stderr


def test_allows_explicit_read_only_intake_without_authority(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    _task(
        tmp_path / "tasks",
        "intake-only",
        """
        kind: intake
        task_type: read-only
        parent_spec: null
        tags:
          - intake
          - read-only
        """,
    )

    result = _run(tmp_path, "--task", "intake-only", "--lane", "beta", "--print-prompt")

    assert result.returncode == 0, result.stderr
    assert "eligible: intake-only -> claude/headless/full/beta" in result.stdout
    assert "AuthorityCase: read-only-exempt" in result.stdout


def test_governed_prompt_is_specific_and_not_work_pool_prompt(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        route_metadata_schema: 1
        quality_floor: deterministic_ok
        authority_level: authoritative
        mutation_surface: source
        mutation_scope_refs: []
        risk_flags:
          governance_sensitive: false
          privacy_or_secret_sensitive: false
          public_claim_sensitive: false
          aesthetic_theory_sensitive: false
          audio_or_live_egress_sensitive: false
          provider_billing_sensitive: false
        context_shape:
          codebase_locality: module
          vault_context_required: true
          external_docs_required: false
          currentness_required: false
        verification_surface:
          deterministic_tests: []
          static_checks: []
          runtime_observation: []
          operator_only: false
        route_constraints:
          preferred_platforms: []
          allowed_platforms: []
          prohibited_platforms: []
          required_mode: null
          required_profile: null
        review_requirement:
          support_artifact_allowed: false
          independent_review_required: false
          authoritative_acceptor_profile: null
        """,
        route_metadata_defaults=False,
    )

    result = _run(tmp_path, "--task", "governed-build", "--lane", "beta", "--print-prompt")

    assert result.returncode == 0, result.stderr
    assert "Task: governed-build" in result.stdout
    assert "AuthorityCase: CASE-TEST-001" in result.stdout
    assert str(spec) in result.stdout
    assert "claim the next" not in result.stdout
    assert "highest-WSJF" not in result.stdout
    assert "Never stop" not in result.stdout


def test_blocks_offered_task_preassigned_to_target_lane(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "preassigned-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
        assigned_to="beta",
    )

    result = _run(tmp_path, "--task", "preassigned-build", "--lane", "beta")

    assert result.returncode == 10
    assert "offered task assigned_to 'beta' is not claimable" in result.stderr
    assert "target-lane routing belongs in dispatch" in result.stderr
    assert "must remain unassigned until cc-claim" in result.stderr


def test_allows_claimed_task_assigned_to_target_lane(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "claimed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
        status="claimed",
        assigned_to="beta",
    )

    result = _run(tmp_path, "--task", "claimed-build", "--lane", "beta")

    assert result.returncode == 0, result.stderr
    assert "eligible: claimed-build -> claude/headless/full/beta" in result.stdout


@pytest.mark.parametrize(
    ("assigned_to", "platform", "lane"),
    [
        ("claude/beta", "claude", "beta"),
        ("codex/cx-green", "codex", "cx-green"),
    ],
)
def test_allows_claimed_task_assigned_to_exact_platform_qualified_lane(
    tmp_path: Path,
    assigned_to: str,
    platform: str,
    lane: str,
) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "claimed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
        status="claimed",
        assigned_to=assigned_to,
    )

    result = _run(
        tmp_path,
        "--task",
        "claimed-build",
        "--lane",
        lane,
        "--platform",
        platform,
    )

    assert result.returncode == 0, result.stderr
    assert f"eligible: claimed-build -> {platform}/headless/full/{lane}" in result.stdout


@pytest.mark.parametrize(
    ("assigned_to", "platform", "lane"),
    [
        ("codex/beta", "claude", "beta"),
        ("claude/cx-green", "codex", "cx-green"),
        ("claude/delta", "claude", "beta"),
    ],
)
def test_blocks_claimed_task_assigned_to_other_platform_or_role(
    tmp_path: Path,
    assigned_to: str,
    platform: str,
    lane: str,
) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "claimed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
        status="claimed",
        assigned_to=assigned_to,
    )

    result = _run(
        tmp_path,
        "--task",
        "claimed-build",
        "--lane",
        lane,
        "--platform",
        platform,
    )

    assert result.returncode == 10
    assert f"task already assigned to '{assigned_to}'" in result.stderr
    assert "claimed/in_progress tasks may only be dispatched" in result.stderr


def test_blocks_claimed_task_assigned_to_unassigned(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "bad-claimed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
        status="claimed",
        assigned_to="unassigned",
    )

    result = _run(tmp_path, "--task", "bad-claimed-build", "--lane", "beta")

    assert result.returncode == 10
    assert "claimed/in_progress tasks may only be dispatched" in result.stderr


def test_blocks_ready_task_even_for_receipt_only_dispatch(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "ready-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
        status="ready",
        assigned_to="unassigned",
    )

    result = _run(
        tmp_path,
        "--task",
        "ready-build",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "receipt-only",
        "--print-prompt",
    )

    assert result.returncode == 10
    assert "task status 'ready' is not dispatchable" in result.stderr
    assert "SDLC GOVERNED DISPATCH" not in result.stdout


def test_codex_receipt_only_prints_governed_prompt_without_launch_route(
    tmp_path: Path,
) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(tmp_path / "tasks", "governed-build", _codex_only_build_frontmatter(spec))

    result = _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "receipt-only",
        "--print-prompt",
    )

    assert result.returncode == 0, result.stderr
    assert "SDLC GOVERNED DISPATCH." in result.stdout
    assert "Mode: receipt-only" in result.stdout
    assert "Task: governed-build" in result.stdout
    assert "eligible: governed-build -> codex/receipt-only/full/cx-green" in result.stdout
    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["ok"] is True
    assert receipt["mode"] == "receipt-only"
    assert "route_policy_action" not in receipt


def test_receipt_only_blocks_malformed_route_metadata(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "malformed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        route_metadata_schema: 1
        quality_floor: deterministic_ok
        authority_level: delegated
        mutation_surface: planning
        """,
        route_metadata_defaults=False,
    )

    result = _run(
        tmp_path,
        "--task",
        "malformed-build",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "receipt-only",
        "--print-prompt",
    )

    assert result.returncode == 10
    assert "route metadata not dispatchable" in result.stderr
    assert "SDLC GOVERNED DISPATCH" not in result.stdout


def test_blocks_stale_worktree_cc_claim_before_launch(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree", guarded=False)
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )

    result = _run(tmp_path, "--task", "governed-build", "--lane", "beta")

    assert result.returncode == 10
    assert "stale cc-claim" in result.stderr


def test_blocks_stale_worktree_cc_close_before_launch(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree", guarded=True, close_guarded=False)
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )

    result = _run(tmp_path, "--task", "governed-build", "--lane", "beta")

    assert result.returncode == 10
    assert "stale cc-close" in result.stderr


def test_blocks_claude_dev_operator_pool_before_worktree_probe(tmp_path: Path) -> None:
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )

    for lane in ("dev", "dev2", "DEV12"):
        result = _run(tmp_path, "--task", "governed-build", "--lane", lane)

        assert result.returncode == 10
        assert "interactive Claude operator pool" in result.stderr
        assert "not a governed dispatch lane" in result.stderr
        assert "scripts/hapax-codex-health" in result.stderr
        assert "--json <cx-lane>" in result.stderr
        assert "scripts/hapax-claude-health" in result.stderr
        assert "--json <lane>" in result.stderr
        assert "not dev/devN" in result.stderr
        assert "missing cc-claim" not in result.stderr


def test_prompt_contains_worktree_local_cc_claim_path(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )

    result = _run(tmp_path, "--task", "governed-build", "--lane", "beta", "--print-prompt")

    assert result.returncode == 0, result.stderr
    prompt = result.stdout
    assert "scripts/cc-claim governed-build" in prompt
    assert "/scripts/cc-claim governed-build" in prompt
    assert "If the launcher already claimed it" in prompt
    assert "cc-active-task-beta" in prompt
    assert "scripts/cc-close" in prompt
    assert "/scripts/cc-close" in prompt
    lines = [l for l in prompt.splitlines() if "cc-claim" in l.lower()]
    for line in lines:
        assert "Run cc-claim governed-build" not in line or "/scripts/cc-claim" in line, (
            f"bare cc-claim without absolute path found: {line!r}"
        )
    close_lines = [l for l in prompt.splitlines() if "cc-close" in l.lower()]
    for line in close_lines:
        assert "bare cc-close" in line or "/scripts/cc-close" in line, (
            f"bare cc-close without absolute path found: {line!r}"
        )


def test_prompt_does_not_use_canonical_checkout_cc_claim(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )

    result = _run(tmp_path, "--task", "governed-build", "--lane", "beta", "--print-prompt")

    assert result.returncode == 0, result.stderr
    prompt = result.stdout
    assert "hapax-council/scripts/cc-claim" not in prompt or "hapax-council--beta" in prompt, (
        "prompt must not reference the canonical checkout cc-claim for a non-alpha lane"
    )


def test_receipt_contains_task_and_authority(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )

    result = _run(tmp_path, "--task", "governed-build", "--lane", "beta")

    assert result.returncode == 0, result.stderr
    line = (
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    receipt = json.loads(line)
    assert receipt["ok"] is True
    assert receipt["task_id"] == "governed-build"
    assert receipt["parent_spec_path"] == str(spec)
    assert receipt["route_decision_id"].startswith("rd-")
    assert receipt["route_policy_action"] == "launch"
    assert receipt["dimensional_route_receipt_schema"] == 1
    assert receipt["dimensional_selected_route_id"] == "claude.headless.full"


def test_dispatch_admission_reuses_worker_adapter_map(monkeypatch) -> None:
    module = _dispatcher_module()
    request = object()
    sentinel = object()
    calls: list[object] = []

    class SpyAdapter:
        def admit(self, policy_request: object) -> object:
            calls.append(policy_request)
            return sentinel

    monkeypatch.setitem(module._WORKER_FAILURE_ADAPTERS, "codex", SpyAdapter)

    adapter = module._capability_adapter_for_admission("codex")

    assert adapter.admit(request) is sentinel
    assert calls == [request]


def test_dispatch_main_uses_adapter_admit_for_route_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _dispatcher_module()
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(tmp_path / "tasks", "governed-build", _codex_only_build_frontmatter(spec))
    (tmp_path / "home" / ".cache" / "hapax" / "stage0-durable-sink").mkdir(parents=True)
    seen_platforms: list[str] = []
    seen_requests: list[object] = []
    seen_candidate_requests: list[object] = []

    class HoldingAdapter:
        def admit(self, policy_request, *, candidate_requests=None):
            seen_requests.append(policy_request)
            seen_candidate_requests.append(candidate_requests)
            return module.RouteDecision(
                decision_id="rd-adapter-fixture",
                created_at=datetime(2026, 7, 5, tzinfo=UTC),
                task_id=policy_request.task_id,
                lane=policy_request.lane,
                route_id=policy_request.route_id,
                platform=policy_request.platform,
                mode=policy_request.mode,
                profile=policy_request.profile,
                action=module.DispatchAction.HOLD,
                policy_outcome="adapter_fixture_hold",
                launch_allowed=False,
                prompt_allowed=False,
                quality_floor_satisfied=True,
                authority_allowed=True,
                reason_codes=("adapter_fixture_hold",),
                message="fixture adapter admission hold",
            )

    def adapter_for_admission(platform: str) -> HoldingAdapter:
        seen_platforms.append(platform)
        return HoldingAdapter()

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HAPAX_CC_TASK_ROOT", str(tmp_path / "tasks"))
    monkeypatch.setenv("HAPAX_DISPATCH_WORKTREE", str(tmp_path / "worktree"))
    monkeypatch.setenv("HAPAX_ORCHESTRATION_LEDGER_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_REGISTRY", str(_fresh_registry(tmp_path)))
    monkeypatch.setenv(
        "HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR",
        str(tmp_path / "platform-receipts"),
    )
    monkeypatch.setenv(
        "HAPAX_QUOTA_SPEND_LEDGER",
        str(_fresh_claude_subscription_quota_ledger(tmp_path)),
    )
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR", str(tmp_path / "platform-receipts"))
    monkeypatch.setenv(
        "HAPAX_QUOTA_SPEND_LEDGER", str(_fresh_claude_subscription_quota_ledger(tmp_path))
    )
    monkeypatch.setenv("HAPAX_DISPATCH_CLAIM_SWEEP", "0")
    monkeypatch.setattr(module, "_capability_adapter_for_admission", adapter_for_admission)

    rc = module.main(
        [
            "--task",
            "governed-build",
            "--lane",
            "cx-green",
            "--platform",
            "codex",
            "--mode",
            "headless",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 10
    assert seen_platforms == ["codex"]
    assert len(seen_requests) == 1
    assert seen_candidate_requests == [None]
    assert "fixture adapter admission hold" in captured.err
    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["route_decision_id"] == "rd-adapter-fixture"
    assert receipt["route_policy_action"] == "hold"
    assert receipt["route_policy_reason_codes"] == ["adapter_fixture_hold"]


def test_dispatch_admission_falls_back_to_base_adapter_for_non_worker_route() -> None:
    module = _dispatcher_module()

    adapter = module._capability_adapter_for_admission("api")

    assert type(adapter) is module.CapabilityAdapter
    assert not isinstance(adapter, module.WorkerAdapter)


def test_unsupported_selected_route_reason_fails_closed_for_launch_decision() -> None:
    module = _dispatcher_module()
    unsupported = module.RouteDecision(
        decision_id="rd-unsupported-selected-route-test",
        created_at=datetime(2026, 7, 5, tzinfo=UTC),
        task_id="governed-build",
        lane="cx-green",
        route_id="external.headless.full",
        platform="external",
        mode="headless",
        profile="full",
        action=module.DispatchAction.LAUNCH,
        policy_outcome="launch",
        launch_allowed=True,
        prompt_allowed=True,
        quality_floor_satisfied=True,
        authority_allowed=True,
        reason_codes=("policy_launch",),
        message="policy_launch",
    )
    supported = unsupported.model_copy(
        update={
            "route_id": "codex.headless.full",
            "platform": "codex",
            "mode": "headless",
            "profile": "full",
        }
    )

    reason = module._unsupported_selected_route_reason(unsupported)

    assert reason is not None
    assert "route policy selected unsupported route: external.headless.full" in reason
    assert "next action: inspect dimensional_selected_route_id" in reason
    assert module._unsupported_selected_route_reason(supported) is None


def test_availability_recomposition_candidates_return_none_without_recomposition(
    tmp_path: Path,
) -> None:
    module = _dispatcher_module()
    registry = _registry_from_path(_fresh_registry(tmp_path))
    primary = _availability_dispatch_request(module, registry)

    candidates = module._availability_recomposition_candidate_requests(
        primary,
        task_fields={},
        policy_sources=module.DispatchPolicySources(registry=registry),
        validation=module.Validation(True, "eligible"),
        rollback_mode=False,
    )

    assert primary.capability.availability_recomposition_required is False
    assert candidates is None


def test_availability_recomposition_candidates_fail_closed_when_registry_missing(
    tmp_path: Path,
) -> None:
    module = _dispatcher_module()
    registry = _registry_from_path(_availability_degraded_registry(tmp_path, "codex.headless.full"))
    primary = _availability_dispatch_request(module, registry)

    candidates = module._availability_recomposition_candidate_requests(
        primary,
        task_fields={},
        policy_sources=module.DispatchPolicySources(registry=None),
        validation=module.Validation(True, "eligible"),
        rollback_mode=False,
    )

    assert primary.capability.availability_recomposition_required is True
    assert candidates == ()


def test_availability_recomposition_candidates_skip_unsupported_routes(
    tmp_path: Path,
) -> None:
    module = _dispatcher_module()
    registry = _registry_from_path(_availability_degraded_registry(tmp_path, "codex.headless.full"))
    primary = _availability_dispatch_request(module, registry)

    def descriptor(route_id: str) -> SimpleNamespace:
        platform, mode, profile = route_id.split(".", 2)
        return SimpleNamespace(
            route_id=route_id,
            platform=SimpleNamespace(value=platform),
            mode=SimpleNamespace(value=mode),
            profile=SimpleNamespace(value=profile),
        )

    candidate_registry = SimpleNamespace(
        routes=(
            descriptor("codex.headless.full"),
            descriptor("ghost.headless.full"),
        )
    )

    candidates = module._availability_recomposition_candidate_requests(
        primary,
        task_fields={},
        policy_sources=module.DispatchPolicySources.model_construct(registry=candidate_registry),
        validation=module.Validation(True, "eligible"),
        rollback_mode=False,
    )

    assert primary.capability.availability_recomposition_required is True
    assert candidates == ()


def test_availability_recomposition_candidates_skip_supported_immutable_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _dispatcher_module()
    registry = _registry_from_path(_availability_degraded_registry(tmp_path, "codex.headless.full"))
    primary = _availability_dispatch_request(module, registry)

    def descriptor(route_id: str) -> SimpleNamespace:
        platform, mode, profile = route_id.split(".", 2)
        return SimpleNamespace(
            route_id=route_id,
            platform=SimpleNamespace(value=platform),
            mode=SimpleNamespace(value=mode),
            profile=SimpleNamespace(value=profile),
        )

    read_only_route = module.route_for("local_tool", "local", "worker")
    assert read_only_route is not None
    assert read_only_route.mutable is False
    candidate_registry = SimpleNamespace(routes=(descriptor("local_tool.local.worker"),))
    monkeypatch.setattr(module, "supports_route", lambda _platform, _mode: True)

    def forbidden_build_dispatch_request(**_kwargs):
        raise AssertionError("immutable recomposition candidates must be skipped before build")

    monkeypatch.setattr(module, "build_dispatch_request", forbidden_build_dispatch_request)

    candidates = module._availability_recomposition_candidate_requests(
        primary,
        task_fields={},
        policy_sources=module.DispatchPolicySources.model_construct(registry=candidate_registry),
        validation=module.Validation(True, "eligible"),
        rollback_mode=False,
    )

    assert primary.capability.availability_recomposition_required is True
    assert candidates == ()


def test_dispatch_worker_adapter_map_includes_live_worker_families() -> None:
    module = _dispatcher_module()

    assert module._WORKER_FAILURE_ADAPTERS["agy"] is module.AgyAdapter
    assert isinstance(module._worker_adapter_for_launch("agy"), module.AgyAdapter)
    assert module._WORKER_FAILURE_ADAPTERS["vibe"] is module.VibeAdapter
    assert isinstance(module._worker_adapter_for_launch("vibe"), module.VibeAdapter)


def test_dispatch_launch_requires_worker_adapter() -> None:
    module = _dispatcher_module()

    with pytest.raises(module.AuthorityViolation, match="no WorkerAdapter registered"):
        module._worker_adapter_for_launch("api")


def test_dispatch_launch_adapter_rejects_non_launch_decision_before_side_effect() -> None:
    module = _dispatcher_module()
    decision = module.RouteDecision(
        decision_id="rd-test",
        created_at=datetime(2026, 7, 5, tzinfo=UTC),
        task_id="governed-build",
        lane="cx-green",
        route_id="codex.headless.full",
        platform="codex",
        mode="headless",
        profile="full",
        action=module.DispatchAction.HOLD,
        policy_outcome="held",
        launch_allowed=False,
        prompt_allowed=False,
        quality_floor_satisfied=True,
        authority_allowed=True,
        reason_codes=("held_for_test",),
        message="held for test",
    )
    launch_called = False

    def launch_callable() -> int:
        nonlocal launch_called
        launch_called = True
        return 0

    with pytest.raises(module.AuthorityViolation, match="not authorized"):
        module._worker_adapter_for_launch("codex").launch(
            decision=decision,
            request=object(),
            launch_callable=launch_callable,
        )

    assert launch_called is False


def test_launch_authority_violation_writes_blocked_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _dispatcher_module()
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        _governed_source_frontmatter(
            spec,
            allowed_platforms="[codex]",
            required_mode="headless",
            required_profile="full",
        ),
        route_metadata_defaults=False,
    )
    (tmp_path / "home" / ".cache" / "hapax" / "stage0-durable-sink").mkdir(parents=True)
    args = (
        "--task",
        "governed-build",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--launch",
    )
    mq_db, message_id = _maybe_write_durable_mq_binding(tmp_path, args)
    assert message_id is not None

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HAPAX_CC_TASK_ROOT", str(tmp_path / "tasks"))
    monkeypatch.setenv("HAPAX_DISPATCH_WORKTREE", str(tmp_path / "worktree"))
    monkeypatch.setenv("HAPAX_ORCHESTRATION_LEDGER_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_REGISTRY", str(_fresh_registry(tmp_path)))
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR", str(tmp_path / "platform-receipts"))
    monkeypatch.setenv(
        "HAPAX_QUOTA_SPEND_LEDGER", str(_fresh_claude_subscription_quota_ledger(tmp_path))
    )
    monkeypatch.setenv("HAPAX_COORD_LEDGER_DB", str(tmp_path / "coord" / "ledger.db"))
    monkeypatch.setenv("HAPAX_COORD_JSONL_MIRROR", str(tmp_path / "coord" / "ledger.jsonl"))
    monkeypatch.setenv("HAPAX_COORD_SPOOL_DIR", str(tmp_path / "coord" / "spool"))
    monkeypatch.setenv("HAPAX_RELAY_MQ_DB", str(mq_db))
    monkeypatch.setenv("HAPAX_METHODOLOGY_DISPATCH_MESSAGE_ID", message_id)
    monkeypatch.setenv("HAPAX_DISPATCH_CLAIM_SWEEP", "0")
    monkeypatch.setattr(module, "_await_sdlc_admission", lambda args: None)

    class RefusingAdapter:
        def launch(self, *, decision, request, launch_callable):
            raise module.AuthorityViolation("fixture refusal")

    monkeypatch.setattr(module, "_worker_adapter_for_launch", lambda platform: RefusingAdapter())

    rc = module.main(list(args))

    captured = capsys.readouterr()
    assert rc == 10
    assert "BLOCKED: capability adapter launch refused: fixture refusal" in captured.err
    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["ok"] is False
    assert receipt["launched"] is False
    assert receipt["route_policy_action"] == "launch"
    assert receipt["durable_mq_dispatch_bound"] is True
    assert receipt["reason"] == "capability adapter launch refused: fixture refusal"


def test_dispatch_main_launches_through_worker_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _dispatcher_module()
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(tmp_path / "tasks", "governed-build", _codex_only_build_frontmatter(spec))
    (tmp_path / "home" / ".cache" / "hapax" / "stage0-durable-sink").mkdir(parents=True)
    args = (
        "--task",
        "governed-build",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--launch",
    )
    mq_db, message_id = _maybe_write_durable_mq_binding(tmp_path, args)
    assert message_id is not None
    launcher_args = tmp_path / "codex-args.txt"
    fake_launcher = tmp_path / "bin" / "hapax-codex"
    fake_launcher.parent.mkdir(parents=True, exist_ok=True)
    fake_launcher.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {launcher_args}
""",
        encoding="utf-8",
    )
    fake_launcher.chmod(0o755)
    launch_calls: list[tuple[str, str]] = []
    admission_order: list[str] = []
    original_policy_load = module.load_dispatch_policy_sources

    class SpyCodexAdapter(module.CodexAdapter):
        def launch(self, *, decision, request, launch_callable):
            launch_calls.append((decision.action.value, request.platform))
            return super().launch(
                decision=decision,
                request=request,
                launch_callable=launch_callable,
            )

    monkeypatch.setitem(module._WORKER_FAILURE_ADAPTERS, "codex", SpyCodexAdapter)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HAPAX_CC_TASK_ROOT", str(tmp_path / "tasks"))
    monkeypatch.setenv("HAPAX_DISPATCH_WORKTREE", str(tmp_path / "worktree"))
    monkeypatch.setenv("HAPAX_ORCHESTRATION_LEDGER_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_REGISTRY", str(_fresh_registry(tmp_path)))
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR", str(tmp_path / "platform-receipts"))
    monkeypatch.setenv(
        "HAPAX_QUOTA_SPEND_LEDGER", str(_fresh_claude_subscription_quota_ledger(tmp_path))
    )
    monkeypatch.setenv("HAPAX_COORD_LEDGER_DB", str(tmp_path / "coord" / "ledger.db"))
    monkeypatch.setenv("HAPAX_COORD_JSONL_MIRROR", str(tmp_path / "coord" / "ledger.jsonl"))
    monkeypatch.setenv("HAPAX_COORD_SPOOL_DIR", str(tmp_path / "coord" / "spool"))
    monkeypatch.setenv("HAPAX_RELAY_MQ_DB", str(mq_db))
    monkeypatch.setenv("HAPAX_METHODOLOGY_DISPATCH_MESSAGE_ID", message_id)
    monkeypatch.setenv("HAPAX_DISPATCH_CLAIM_SWEEP", "0")
    monkeypatch.setenv("HAPAX_METHODOLOGY_CODEX_HEADLESS", str(fake_launcher))
    monkeypatch.setattr(
        module,
        "_await_sdlc_admission",
        lambda args: admission_order.append("pressure_wait_complete"),
    )

    def record_policy_load(**kwargs):
        admission_order.append("route_authority_loaded")
        return original_policy_load(**kwargs)

    monkeypatch.setattr(module, "load_dispatch_policy_sources", record_policy_load)

    rc = module.main(list(args))

    assert rc == 0
    assert admission_order[:2] == ["pressure_wait_complete", "route_authority_loaded"]
    assert launch_calls == [("launch", "codex")]
    assert launcher_args.exists()
    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["route_policy_action"] == "launch"
    assert receipt["launched"] is True


def test_dispatch_rejects_task_byte_drift_during_admission_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _dispatcher_module()
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    task_path = _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )
    args = (
        "--task",
        "governed-build",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--launch",
    )
    mq_db, message_id = _maybe_write_durable_mq_binding(tmp_path, args)
    assert message_id is not None
    launch_calls: list[str] = []

    class SpyAdapter(module.CodexAdapter):
        def launch(self, *, decision, request, launch_callable):
            launch_calls.append(request.task_id)
            return super().launch(
                decision=decision,
                request=request,
                launch_callable=launch_callable,
            )

    def drift_task(_args) -> None:
        task_path.write_text(
            task_path.read_text(encoding="utf-8") + "\nconcurrent body change\n",
            encoding="utf-8",
        )

    monkeypatch.setitem(module._WORKER_FAILURE_ADAPTERS, "codex", SpyAdapter)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HAPAX_CC_TASK_ROOT", str(tmp_path / "tasks"))
    monkeypatch.setenv("HAPAX_DISPATCH_WORKTREE", str(tmp_path / "worktree"))
    monkeypatch.setenv("HAPAX_ORCHESTRATION_LEDGER_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_REGISTRY", str(_fresh_registry(tmp_path)))
    monkeypatch.setenv(
        "HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR",
        str(tmp_path / "platform-receipts"),
    )
    monkeypatch.setenv(
        "HAPAX_QUOTA_SPEND_LEDGER",
        str(_fresh_claude_subscription_quota_ledger(tmp_path)),
    )
    monkeypatch.setenv("HAPAX_COORD_LEDGER_DB", str(tmp_path / "coord" / "ledger.db"))
    monkeypatch.setenv("HAPAX_COORD_JSONL_MIRROR", str(tmp_path / "coord" / "ledger.jsonl"))
    monkeypatch.setenv("HAPAX_COORD_SPOOL_DIR", str(tmp_path / "coord" / "spool"))
    monkeypatch.setenv("HAPAX_RELAY_MQ_DB", str(mq_db))
    monkeypatch.setenv("HAPAX_METHODOLOGY_DISPATCH_MESSAGE_ID", message_id)
    monkeypatch.setenv("HAPAX_DISPATCH_CLAIM_SWEEP", "0")
    monkeypatch.setattr(module, "_await_sdlc_admission", drift_task)

    rc = module.main(list(args))

    assert rc == 10
    assert launch_calls == []
    assert "dispatch task preimage changed before actuation" in capsys.readouterr().err


def test_policy_hold_writes_route_decision_before_prompt_or_launch(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "missing-metadata-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
        route_metadata_defaults=False,
    )
    launcher_args = tmp_path / "launcher-args.txt"
    fake_launcher = tmp_path / "bin" / "hapax-codex"
    fake_launcher.parent.mkdir(parents=True, exist_ok=True)
    fake_launcher.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {launcher_args}
""",
        encoding="utf-8",
    )
    fake_launcher.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "missing-metadata-build",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--print-prompt",
        "--launch",
        extra_env={"HAPAX_METHODOLOGY_CODEX_HEADLESS": str(fake_launcher)},
    )

    assert result.returncode == 10
    assert result.stdout == ""
    assert not launcher_args.exists()
    route_receipt = json.loads(
        (tmp_path / "ledger" / "route-decisions.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )
    assert route_receipt["action"] == "hold"
    assert "route_metadata_missing_or_incomplete" in route_receipt["reason_codes"]
    dispatch_receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert dispatch_receipt["prompt"] is None
    assert dispatch_receipt["route_policy_action"] == "hold"


def test_operator_coupled_frontmatter_refuses_headless_before_prompt_or_launch(
    tmp_path: Path,
) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "operator-coupled-build",
        _governed_source_frontmatter(spec, extra="operator_coupled: true"),
        route_metadata_defaults=False,
    )
    launcher_args = tmp_path / "launcher-args.txt"
    fake_launcher = tmp_path / "bin" / "hapax-codex"
    fake_launcher.parent.mkdir(parents=True, exist_ok=True)
    fake_launcher.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {launcher_args}
""",
        encoding="utf-8",
    )
    fake_launcher.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "operator-coupled-build",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--print-prompt",
        "--launch",
        extra_env={"HAPAX_METHODOLOGY_CODEX_HEADLESS": str(fake_launcher)},
    )

    assert result.returncode == 10
    assert result.stdout == ""
    assert not launcher_args.exists()
    assert "operator_coupled_interactive_only" in result.stderr
    assert "hapax-claude --terminal tmux" in result.stderr
    route_receipt = json.loads(
        (tmp_path / "ledger" / "route-decisions.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )
    assert route_receipt["action"] == "refuse"
    assert "operator_coupled_interactive_only" in route_receipt["reason_codes"]
    assert "operator_coupled:frontmatter" in route_receipt["reason_codes"]
    dispatch_receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert dispatch_receipt["prompt"] is None
    assert dispatch_receipt["route_policy_action"] == "refuse"
    assert "operator_coupled_interactive_only" in dispatch_receipt["route_policy_reason_codes"]


def test_operator_coupled_manifest_path_refuses_headless(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    manifest = _operator_coupled_manifest(tmp_path)
    _task(
        tmp_path / "tasks",
        "operator-path-build",
        _governed_source_frontmatter(
            spec,
            mutation_scope_refs="[agents/studio_compositor/programme.py]",
        ),
        route_metadata_defaults=False,
    )

    result = _run(
        tmp_path,
        "--task",
        "operator-path-build",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--print-prompt",
        extra_env={"HAPAX_INVARIANT_MANIFEST": str(manifest)},
    )

    assert result.returncode == 10
    assert result.stdout == ""
    route_receipt = json.loads(
        (tmp_path / "ledger" / "route-decisions.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )
    assert route_receipt["action"] == "refuse"
    assert "operator_coupled_interactive_only" in route_receipt["reason_codes"]
    assert (
        "operator_coupled:path:agents/studio_compositor/programme.py"
        "#operator-coupled-broadcast-visual" in route_receipt["reason_codes"]
    )


def test_operator_coupled_nested_route_metadata_path_refuses_headless(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    manifest = _operator_coupled_manifest(tmp_path)
    _task(
        tmp_path / "tasks",
        "operator-nested-path-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        route_metadata:
          route_metadata_schema: 1
          quality_floor: frontier_required
          authority_level: authoritative
          mutation_surface: source
          mutation_scope_refs:
            - agents/studio_compositor/programme.py
        """,
        route_metadata_defaults=False,
    )

    result = _run(
        tmp_path,
        "--task",
        "operator-nested-path-build",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--print-prompt",
        extra_env={"HAPAX_INVARIANT_MANIFEST": str(manifest)},
    )

    assert result.returncode == 10
    assert result.stdout == ""
    route_receipt = json.loads(
        (tmp_path / "ledger" / "route-decisions.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )
    assert route_receipt["action"] == "refuse"
    assert "operator_coupled_interactive_only" in route_receipt["reason_codes"]
    assert (
        "operator_coupled:path:agents/studio_compositor/programme.py"
        "#operator-coupled-broadcast-visual" in route_receipt["reason_codes"]
    )


def test_operator_coupled_malformed_manifest_refuses_headless(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    manifest = _operator_coupled_manifest(tmp_path, body="schema_version: [\n")
    _task(
        tmp_path / "tasks",
        "operator-malformed-manifest-build",
        _governed_source_frontmatter(
            spec,
            mutation_scope_refs="[agents/studio_compositor/programme.py]",
        ),
        route_metadata_defaults=False,
    )

    result = _run(
        tmp_path,
        "--task",
        "operator-malformed-manifest-build",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--print-prompt",
        extra_env={"HAPAX_INVARIANT_MANIFEST": str(manifest)},
    )

    assert result.returncode == 10
    assert result.stdout == ""
    assert "operator_coupled_interactive_only" in result.stderr
    assert "manifest_unavailable:RuntimeError:invariant-manifest-parse-error" in result.stderr
    route_receipt = json.loads(
        (tmp_path / "ledger" / "route-decisions.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )
    assert route_receipt["action"] == "refuse"
    assert "operator_coupled_interactive_only" in route_receipt["reason_codes"]
    assert (
        "operator_coupled:path:manifest_unavailable:RuntimeError:invariant-manifest-parse-error"
        in route_receipt["reason_codes"]
    )


def test_operator_coupled_interactive_and_receipt_only_still_dispatch(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "operator-interactive-build",
        _governed_source_frontmatter(spec, extra="operator_coupled: true"),
        route_metadata_defaults=False,
    )
    _task(
        tmp_path / "tasks",
        "operator-receipt-build",
        _governed_source_frontmatter(spec, extra="dispatch_mode: interactive_only"),
        route_metadata_defaults=False,
    )

    interactive = _run(
        tmp_path,
        "--task",
        "operator-interactive-build",
        "--lane",
        "beta",
        "--platform",
        "claude",
        "--mode",
        "interactive",
        "--print-prompt",
    )
    receipt_only = _run(
        tmp_path,
        "--task",
        "operator-receipt-build",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "receipt-only",
        "--print-prompt",
    )

    assert interactive.returncode == 0, interactive.stderr
    assert (
        "eligible: operator-interactive-build -> claude/interactive/full/beta" in interactive.stdout
    )
    assert receipt_only.returncode == 0, receipt_only.stderr
    assert (
        "eligible: operator-receipt-build -> codex/receipt-only/full/cx-green"
        in receipt_only.stdout
    )


def test_launch_blocks_without_durable_mq_authority_binding(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )
    launcher_args = tmp_path / "launcher-args.txt"
    fake_launcher = tmp_path / "bin" / "hapax-codex"
    fake_launcher.parent.mkdir(parents=True, exist_ok=True)
    fake_launcher.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {launcher_args}
""",
        encoding="utf-8",
    )
    fake_launcher.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--launch",
        extra_env={"HAPAX_METHODOLOGY_CODEX_HEADLESS": str(fake_launcher)},
        durable_mq=False,
    )

    assert result.returncode == 10
    assert not launcher_args.exists()
    assert "durable MQ authority binding required" in result.stderr
    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["durable_mq_dispatch_bound"] is False
    assert receipt["advisory_only"] is True


def test_launch_rejects_non_coordinator_dispatch_message(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )
    mq_db = tmp_path / "relay" / "messages.db"
    mq_db.parent.mkdir(parents=True, exist_ok=True)
    message_id = send_message(
        mq_db,
        Envelope(
            sender="test-dispatcher",
            message_type="dispatch",
            priority=0,
            subject="governed-build",
            authority_case="CASE-TEST-001",
            authority_item="governed-build",
            recipients_spec="cx-green",
            payload="non-coordinator dispatch",
        ),
    )

    result = _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--launch",
        durable_mq=False,
        extra_env={
            "HAPAX_RELAY_MQ_DB": str(mq_db),
            "HAPAX_METHODOLOGY_DISPATCH_MESSAGE_ID": message_id,
        },
    )

    assert result.returncode == 10
    assert "coordinator_dispatch_preparation_required" in result.stderr


def test_launch_rejects_shared_authority_item_bound_to_different_task(
    tmp_path: Path,
) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "task-b",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        authority_item: shared-item
        parent_spec: {spec}
        """,
    )
    mq_db = tmp_path / "relay" / "messages.db"
    mq_db.parent.mkdir(parents=True, exist_ok=True)
    message_id = send_message(
        mq_db,
        Envelope(
            sender="test-dispatcher",
            message_type="dispatch",
            priority=0,
            subject="task-a",
            authority_case="CASE-TEST-001",
            authority_item="shared-item",
            recipients_spec="cx-green",
            payload="wrong task binding",
        ),
    )
    launcher_args = tmp_path / "launcher-args.txt"
    fake_launcher = tmp_path / "bin" / "hapax-codex"
    fake_launcher.parent.mkdir(parents=True, exist_ok=True)
    fake_launcher.write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > {launcher_args}\n",
        encoding="utf-8",
    )
    fake_launcher.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "task-b",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--launch",
        durable_mq=False,
        extra_env={
            "HAPAX_RELAY_MQ_DB": str(mq_db),
            "HAPAX_METHODOLOGY_DISPATCH_MESSAGE_ID": message_id,
            "HAPAX_METHODOLOGY_CODEX_HEADLESS": str(fake_launcher),
        },
    )

    assert result.returncode == 10
    assert not launcher_args.exists()
    assert "durable MQ authority binding required" in result.stderr
    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["durable_mq_reason"] == "durable_mq_authority_binding_missing"


def test_launch_requires_strict_mq_message_id(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )
    launcher_args = tmp_path / "launcher-args.txt"
    fake_launcher = tmp_path / "bin" / "hapax-codex"
    fake_launcher.parent.mkdir(parents=True, exist_ok=True)
    fake_launcher.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {launcher_args}
""",
        encoding="utf-8",
    )
    fake_launcher.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--launch",
        extra_env={
            "HAPAX_METHODOLOGY_CODEX_HEADLESS": str(fake_launcher),
            "HAPAX_METHODOLOGY_DISPATCH_MESSAGE_ID": "",
        },
    )

    assert result.returncode == 10
    assert not launcher_args.exists()
    assert "strict_mq_message_id_required" in result.stderr


def test_launch_blocks_mq_message_id_mismatch_without_consuming(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )
    launcher_args = tmp_path / "launcher-args.txt"
    fake_launcher = tmp_path / "bin" / "hapax-codex"
    fake_launcher.parent.mkdir(parents=True, exist_ok=True)
    fake_launcher.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {launcher_args}
""",
        encoding="utf-8",
    )
    fake_launcher.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--launch",
        extra_env={
            "HAPAX_METHODOLOGY_CODEX_HEADLESS": str(fake_launcher),
            "HAPAX_METHODOLOGY_DISPATCH_MESSAGE_ID": "wrong-message-id",
        },
    )

    assert result.returncode == 10
    assert not launcher_args.exists()
    assert "durable MQ authority binding required" in result.stderr
    with sqlite3.connect(tmp_path / "relay" / "messages.db") as conn:
        states = conn.execute("SELECT state FROM recipients").fetchall()
    assert states == [("deferred",)]


def test_launches_codex_headless_through_codex_launcher(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )
    launcher_args = tmp_path / "launcher-args.txt"
    launcher_env = tmp_path / "launcher-env.txt"
    fake_launcher = tmp_path / "bin" / "hapax-codex"
    fake_launcher.parent.mkdir(parents=True, exist_ok=True)
    fake_launcher.write_text(
        f"""#!/usr/bin/env bash
printf 'host=%s\\nfallback=%s\\n' "$HAPAX_DISPATCH_HOST" "${{HAPAX_DISPATCH_HOST_FALLBACK:-}}" > {launcher_env}
printf '%s\\n' "$@" > {launcher_args}
""",
        encoding="utf-8",
    )
    fake_launcher.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--launch",
        extra_env={
            "HAPAX_METHODOLOGY_CODEX_HEADLESS": str(fake_launcher),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        },
    )

    assert result.returncode == 0, result.stderr
    # Strictly MQ-bound governed Codex launches may reactivate a clean retired
    # relay. Local fallback remains independently restricted to P0 drain lanes.
    recorded = launcher_args.read_text(encoding="utf-8")
    assert recorded.startswith("--task\ngoverned-build\n--force\ncx-green\n")
    assert "SDLC GOVERNED DISPATCH." in recorded
    assert "Task: governed-build" in recorded
    assert "AuthorityCase: CASE-TEST-001" in recorded
    assert "If the launcher already claimed it" in recorded
    assert "claim the next" not in recorded
    assert "highest-WSJF" not in recorded

    line = (
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    receipt = json.loads(line)
    assert receipt["platform"] == "codex"
    assert receipt["lane"] == "cx-green"
    assert receipt["launched"] is True
    assert receipt["launch_returncode"] == 0
    assert receipt["route_policy_action"] == "launch"
    assert receipt["route_policy_launch_allowed"] is True
    assert receipt["coord_dispatch_replayed"] is False
    assert receipt["coord_dispatch_cleanup_state"] == "processed"
    assert receipt["dispatch_host"] == "appendix"
    assert launcher_env.read_text(encoding="utf-8").splitlines() == [
        "host=appendix",
        "fallback=",
    ]


def test_degraded_codex_recomposes_to_claude_coverage_substitute(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    registry = _availability_degraded_registry(tmp_path, "codex.headless.full")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        route_metadata_schema: 1
        quality_floor: frontier_required
        authority_level: authoritative
        mutation_surface: source
        mutation_scope_refs: []
        risk_flags:
          governance_sensitive: false
          privacy_or_secret_sensitive: false
          public_claim_sensitive: false
          aesthetic_theory_sensitive: false
          audio_or_live_egress_sensitive: false
          provider_billing_sensitive: false
        context_shape:
          codebase_locality: module
          vault_context_required: true
          external_docs_required: false
          currentness_required: false
        verification_surface:
          deterministic_tests: []
          static_checks: []
          runtime_observation: []
          operator_only: false
        route_constraints:
          preferred_platforms: []
          allowed_platforms: [claude, codex]
          prohibited_platforms: []
          required_mode: headless
          required_profile: full
        review_requirement:
          support_artifact_allowed: false
          independent_review_required: false
          authoritative_acceptor_profile: null
        """,
    )
    launcher_args = tmp_path / "launcher-args.txt"
    launcher_env = tmp_path / "launcher-env.txt"
    fake_claude = tmp_path / "bin" / "hapax-claude-headless"
    fake_claude.parent.mkdir(parents=True, exist_ok=True)
    fake_claude.write_text(
        f"""#!/usr/bin/env bash
printf 'host=%s\\nmodel=%s\\n' "$HAPAX_DISPATCH_HOST" "$HAPAX_CLAUDE_MODEL" > {launcher_env}
printf '%s\\n' "$@" > {launcher_args}
""",
        encoding="utf-8",
    )
    fake_claude.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "eta",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--profile",
        "full",
        "--launch",
        extra_env={
            "HAPAX_PLATFORM_CAPABILITY_REGISTRY": str(registry),
            "HAPAX_METHODOLOGY_CLAUDE_HEADLESS": str(fake_claude),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        },
    )

    assert result.returncode == 0, result.stderr
    recorded = launcher_args.read_text(encoding="utf-8")
    assert recorded.startswith("--task\ngoverned-build\neta\n")
    assert "Platform: claude" in recorded
    assert "Profile: full" in recorded
    assert launcher_env.read_text(encoding="utf-8").splitlines() == [
        "host=appendix",
        "model=opus",
    ]

    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["platform"] == "claude"
    assert receipt["mode"] == "headless"
    assert receipt["profile"] == "full"
    assert receipt["platform_path_summary"] == "Claude Code headless stream-json lane"
    assert receipt["route_policy_action"] == "launch"
    assert receipt["route_policy_launch_allowed"] is True
    assert receipt["dimensional_selected_route_id"] == "claude.headless.full"
    reasons = set(receipt["route_policy_reason_codes"])
    assert "availability_recomposition_required" in reasons
    assert "availability_recomposed_from:codex.headless.full" in reasons
    assert "availability_recomposed_to:claude.headless.full" in reasons
    assert any(
        reason.startswith("capability-availability-receipt:codex.headless.full:")
        for reason in reasons
    )


def test_claude_lane_recomposed_to_codex_fails_before_mq_consumption(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    registry = _availability_degraded_registry(tmp_path, "claude.headless.full")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        route_metadata_schema: 1
        quality_floor: frontier_required
        authority_level: authoritative
        mutation_surface: source
        mutation_scope_refs: []
        risk_flags:
          governance_sensitive: false
          privacy_or_secret_sensitive: false
          public_claim_sensitive: false
          aesthetic_theory_sensitive: false
          audio_or_live_egress_sensitive: false
          provider_billing_sensitive: false
        context_shape:
          codebase_locality: module
          vault_context_required: true
          external_docs_required: false
          currentness_required: false
        verification_surface:
          deterministic_tests: []
          static_checks: []
          runtime_observation: []
          operator_only: false
        route_constraints:
          preferred_platforms: []
          allowed_platforms: [claude, codex]
          prohibited_platforms: []
          required_mode: headless
          required_profile: full
        review_requirement:
          support_artifact_allowed: false
          independent_review_required: false
          authoritative_acceptor_profile: null
        """,
    )
    launcher_args = tmp_path / "codex-launcher-args.txt"
    fake_codex = tmp_path / "bin" / "hapax-codex-headless"
    fake_codex.parent.mkdir(parents=True, exist_ok=True)
    fake_codex.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {launcher_args}
""",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "eta",
        "--platform",
        "claude",
        "--mode",
        "headless",
        "--profile",
        "full",
        "--launch",
        extra_env={
            "HAPAX_METHODOLOGY_CODEX_HEADLESS": str(fake_codex),
            "HAPAX_PLATFORM_CAPABILITY_REGISTRY": str(registry),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        },
    )

    assert result.returncode == 10
    assert "selected route codex.headless.full requires a Codex cx-* lane" in result.stderr
    assert not launcher_args.exists()
    with sqlite3.connect(tmp_path / "relay" / "messages.db") as conn:
        message_id = conn.execute("SELECT message_id FROM messages").fetchone()[0]
    row = _recipient_row(tmp_path / "relay" / "messages.db", message_id, "eta")
    assert row["state"] == "deferred"
    assert row["reason"] == COORDINATOR_PREPARED_DISPATCH_REASON

    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["ok"] is False
    assert receipt["launched"] is False
    assert receipt["platform"] == "codex"
    assert receipt["mode"] == "headless"
    assert receipt["profile"] == "full"
    assert receipt["dimensional_selected_route_id"] == "codex.headless.full"
    assert "availability_recomposed_from:claude.headless.full" in set(
        receipt["route_policy_reason_codes"]
    )
    assert "durable_mq_dispatch_bound" not in receipt


def test_cx_lane_recomposed_to_codex_remains_launch_admissible(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    registry = _availability_degraded_registry(tmp_path, "claude.headless.full")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        route_metadata_schema: 1
        quality_floor: frontier_required
        authority_level: authoritative
        mutation_surface: source
        mutation_scope_refs: []
        risk_flags:
          governance_sensitive: false
          privacy_or_secret_sensitive: false
          public_claim_sensitive: false
          aesthetic_theory_sensitive: false
          audio_or_live_egress_sensitive: false
          provider_billing_sensitive: false
        context_shape:
          codebase_locality: module
          vault_context_required: true
          external_docs_required: false
          currentness_required: false
        verification_surface:
          deterministic_tests: []
          static_checks: []
          runtime_observation: []
          operator_only: false
        route_constraints:
          preferred_platforms: []
          allowed_platforms: [claude, codex]
          prohibited_platforms: []
          required_mode: headless
          required_profile: full
        review_requirement:
          support_artifact_allowed: false
          independent_review_required: false
          authoritative_acceptor_profile: null
        """,
    )
    launcher_args = tmp_path / "codex-launcher-args.txt"
    fake_codex = tmp_path / "bin" / "hapax-codex-headless"
    fake_codex.parent.mkdir(parents=True, exist_ok=True)
    fake_codex.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {launcher_args}
""",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "cx-green",
        "--platform",
        "claude",
        "--mode",
        "headless",
        "--profile",
        "full",
        "--launch",
        extra_env={
            "HAPAX_METHODOLOGY_CODEX_HEADLESS": str(fake_codex),
            "HAPAX_PLATFORM_CAPABILITY_REGISTRY": str(registry),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "cx-green" in launcher_args.read_text(encoding="utf-8").splitlines()
    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["ok"] is True
    assert receipt["launched"] is True
    assert receipt["platform"] == "codex"
    assert receipt["lane"] == "cx-green"
    assert receipt["dimensional_selected_route_id"] == "codex.headless.full"
    assert receipt["durable_mq_dispatch_bound"] is True
    assert "availability_recomposed_from:claude.headless.full" in set(
        receipt["route_policy_reason_codes"]
    )


def test_claude_route_with_codex_lane_fails_before_mq_consumption(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )
    launcher_args = tmp_path / "claude-launcher-args.txt"
    fake_claude = tmp_path / "bin" / "hapax-claude-headless"
    fake_claude.parent.mkdir(parents=True, exist_ok=True)
    fake_claude.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {launcher_args}
""",
        encoding="utf-8",
    )
    fake_claude.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "cx-green",
        "--platform",
        "claude",
        "--mode",
        "headless",
        "--profile",
        "full",
        "--launch",
        extra_env={"HAPAX_METHODOLOGY_CLAUDE_HEADLESS": str(fake_claude)},
    )

    assert result.returncode == 10
    assert "selected route claude.headless.full requires a Claude headless role" in result.stderr
    assert not launcher_args.exists()
    with sqlite3.connect(tmp_path / "relay" / "messages.db") as conn:
        message_id = conn.execute("SELECT message_id FROM messages").fetchone()[0]
    row = _recipient_row(tmp_path / "relay" / "messages.db", message_id, "cx-green")
    assert row["state"] == "deferred"
    assert row["reason"] == COORDINATOR_PREPARED_DISPATCH_REASON
    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["ok"] is False
    assert receipt["launched"] is False
    assert receipt["platform"] == "claude"
    assert "durable_mq_dispatch_bound" not in receipt


def test_vibe_route_with_codex_lane_fails_before_mq_consumption(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        route_metadata_schema: 1
        quality_floor: deterministic_ok
        authority_level: support_non_authoritative
        mutation_surface: source
        mutation_scope_refs: []
        risk_flags:
          governance_sensitive: false
          privacy_or_secret_sensitive: false
          public_claim_sensitive: false
          aesthetic_theory_sensitive: false
          audio_or_live_egress_sensitive: false
          provider_billing_sensitive: false
        context_shape:
          codebase_locality: module
          vault_context_required: true
          external_docs_required: false
          currentness_required: false
        verification_surface:
          deterministic_tests: []
          static_checks: []
          runtime_observation: []
          operator_only: false
        route_constraints:
          preferred_platforms: []
          allowed_platforms: []
          prohibited_platforms: []
          required_mode: null
          required_profile: null
        review_requirement:
          support_artifact_allowed: false
          independent_review_required: false
          authoritative_acceptor_profile: null
        """,
        route_metadata_defaults=False,
    )
    launcher_args = tmp_path / "vibe-launcher-args.txt"
    fake_vibe = tmp_path / "bin" / "hapax-vibe"
    fake_vibe.parent.mkdir(parents=True, exist_ok=True)
    fake_vibe.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {launcher_args}
""",
        encoding="utf-8",
    )
    fake_vibe.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "cx-green",
        "--platform",
        "vibe",
        "--mode",
        "headless",
        "--profile",
        "full",
        "--launch",
        extra_env={"HAPAX_METHODOLOGY_VIBE_LAUNCHER": str(fake_vibe)},
    )

    assert result.returncode == 10
    assert "selected route vibe.headless.full requires a Vibe" in result.stderr
    assert not launcher_args.exists()
    with sqlite3.connect(tmp_path / "relay" / "messages.db") as conn:
        message_id = conn.execute("SELECT message_id FROM messages").fetchone()[0]
    row = _recipient_row(tmp_path / "relay" / "messages.db", message_id, "cx-green")
    assert row["state"] == "deferred"
    assert row["reason"] == COORDINATOR_PREPARED_DISPATCH_REASON
    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["ok"] is False
    assert receipt["launched"] is False
    assert receipt["platform"] == "vibe"
    assert "durable_mq_dispatch_bound" not in receipt


def test_codex_route_with_cx_lane_remains_launch_admissible(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )
    launcher_args = tmp_path / "codex-launcher-args.txt"
    fake_codex = tmp_path / "bin" / "hapax-codex-headless"
    fake_codex.parent.mkdir(parents=True, exist_ok=True)
    fake_codex.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {launcher_args}
""",
        encoding="utf-8",
    )
    fake_codex.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--profile",
        "full",
        "--launch",
        extra_env={"HAPAX_METHODOLOGY_CODEX_HEADLESS": str(fake_codex)},
    )

    assert result.returncode == 0, result.stderr
    codex_args = launcher_args.read_text(encoding="utf-8").splitlines()
    assert codex_args[0:2] == ["--task", "governed-build"]
    assert "cx-green" in codex_args
    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["ok"] is True
    assert receipt["launched"] is True
    assert receipt["platform"] == "codex"
    assert receipt["lane"] == "cx-green"
    assert receipt["durable_mq_dispatch_bound"] is True


def test_unsupported_selected_route_writes_blocked_receipt_with_next_action(
    tmp_path: Path,
    monkeypatch,
    capfd,
) -> None:
    module = _dispatcher_module()
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HAPAX_CC_TASK_ROOT", str(tmp_path / "tasks"))
    monkeypatch.setenv("HAPAX_DISPATCH_WORKTREE", str(tmp_path / "worktree"))
    monkeypatch.setenv("HAPAX_ORCHESTRATION_LEDGER_DIR", str(tmp_path / "ledger"))
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_REGISTRY", str(_fresh_registry(tmp_path)))
    monkeypatch.setenv("HAPAX_DISPATCH_CLAIM_SWEEP", "0")

    class UnsupportedSelectionAdapter:
        def admit(self, policy_request, *, candidate_requests=None):
            return module.RouteDecision(
                decision_id="rd-unsupported-selected-route-test",
                created_at=datetime(2026, 5, 9, 22, 30, tzinfo=UTC),
                task_id=policy_request.task_id,
                lane=policy_request.lane,
                route_id="external.headless.full",
                platform="external",
                mode="headless",
                profile="full",
                action=module.DispatchAction.LAUNCH,
                policy_outcome="launch",
                launch_allowed=True,
                prompt_allowed=True,
                quality_floor_satisfied=True,
                authority_allowed=True,
                reason_codes=("policy_launch",),
                message="policy_launch",
            )

    monkeypatch.setattr(
        module,
        "_capability_adapter_for_admission",
        lambda _platform: UnsupportedSelectionAdapter(),
    )

    rc = module.main(
        [
            "--task",
            "governed-build",
            "--lane",
            "cx-green",
            "--platform",
            "codex",
            "--mode",
            "headless",
        ]
    )
    captured = capfd.readouterr()

    assert rc == 10
    assert "route policy selected unsupported route: external.headless.full" in captured.err
    assert "next action: inspect dimensional_selected_route_id" in captured.err
    assert "Supported governed routes:" in captured.err

    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["ok"] is False
    assert receipt["launched"] is False
    assert receipt["route_policy_action"] == "launch"
    assert "next action" in receipt["reason"]


def test_codex_p0_incident_drain_lane_allows_local_fallback(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    task_id = "p0-incident-sdlc-task-stalled-test"
    _task(
        tmp_path / "tasks",
        task_id,
        f"""
        kind: build
        priority: p0
        tags: [cc-task, p0, incident-intake, technical-alert]
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )
    launcher_env = tmp_path / "launcher-env.txt"
    launcher_args = tmp_path / "launcher-args.txt"
    fake_launcher = tmp_path / "bin" / "hapax-codex"
    fake_launcher.parent.mkdir(parents=True, exist_ok=True)
    fake_launcher.write_text(
        f"""#!/usr/bin/env bash
printf 'host=%s\\nfallback=%s\\n' "$HAPAX_DISPATCH_HOST" "${{HAPAX_DISPATCH_HOST_FALLBACK:-}}" > {launcher_env}
printf '%s\\n' "$@" > {launcher_args}
""",
        encoding="utf-8",
    )
    fake_launcher.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        task_id,
        "--lane",
        "cx-p0",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--launch",
        extra_env={
            "HAPAX_METHODOLOGY_CODEX_HEADLESS": str(fake_launcher),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        },
    )

    assert result.returncode == 0, result.stderr
    assert launcher_env.read_text(encoding="utf-8").splitlines() == [
        "host=appendix",
        "fallback=local",
    ]
    recorded = launcher_args.read_text(encoding="utf-8")
    assert recorded.startswith(f"--task\n{task_id}\n--force\ncx-p0\n")


def test_codex_p0_incident_local_fallback_force_is_independent_of_reactivation_flag(
    tmp_path: Path, monkeypatch
) -> None:
    module = _dispatcher_module()
    monkeypatch.setenv("HAPAX_P0_CODEX_DRAIN_LANES", "cx-p0")
    launcher_env = tmp_path / "launcher-env.txt"
    launcher_args = tmp_path / "launcher-args.txt"
    fake_launcher = tmp_path / "bin" / "hapax-codex"
    fake_launcher.parent.mkdir(parents=True, exist_ok=True)
    fake_launcher.write_text(
        f"""#!/usr/bin/env bash
printf 'host=%s\\nfallback=%s\\n' "$HAPAX_DISPATCH_HOST" "${{HAPAX_DISPATCH_HOST_FALLBACK:-}}" > {launcher_env}
printf '%s\\n' "$@" > {launcher_args}
""",
        encoding="utf-8",
    )
    fake_launcher.chmod(0o755)
    monkeypatch.setenv("HAPAX_METHODOLOGY_CODEX_HEADLESS", str(fake_launcher))
    validation = module.Validation(
        True,
        "ok",
        module.TaskNote(
            tmp_path / "task.md",
            {
                "status": "claimed",
                "priority": "p0",
                "title": "P0 incident",
                "kind": "recovery_triage",
                "tags": ["incident-intake", "technical-alert"],
            },
        ),
    )

    reactivate_retired_relay = False
    assert module.allow_codex_p0_local_dispatch_fallback(
        "p0-incident-sdlc-task-stalled-test", "cx-p0", validation
    )
    monkeypatch.setattr(
        module,
        "resolve_claim_resume_session",
        lambda **_kwargs: "11111111-2222-4333-8444-555555555555",
    )

    result = module.launch_codex_headless(
        "p0-incident-sdlc-task-stalled-test",
        "cx-p0",
        "prompt",
        validation,
        module.PLATFORM_PATHS[("codex", "headless", "full")],
        reactivate_retired_relay=reactivate_retired_relay,
    )

    assert result == 0
    assert launcher_env.read_text(encoding="utf-8").splitlines() == [
        "host=appendix",
        "fallback=local",
    ]
    recorded = launcher_args.read_text(encoding="utf-8")
    assert recorded.startswith(
        "--task\np0-incident-sdlc-task-stalled-test\n--force\n--no-claim\ncx-p0\n"
    )


def test_launch_codex_headless_scrubs_ambient_session_before_explicit_dispatch_env(
    tmp_path: Path, monkeypatch
) -> None:
    module = _dispatcher_module()
    env_log = tmp_path / "launcher-env.txt"
    args_log = tmp_path / "launcher-args.txt"
    launcher = tmp_path / "hapax-codex-headless"
    launcher.write_text(
        f"""#!/usr/bin/env bash
printf '%s|%s\n' "${{HAPAX_SESSION_ID:-<unset>}}" "${{HAPAX_CLAIM_RESUME_SESSION_ID:-<unset>}}" >> {env_log}
printf '%s\n' "$*" >> {args_log}
""",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    monkeypatch.setenv("HAPAX_METHODOLOGY_CODEX_HEADLESS", str(launcher))
    monkeypatch.setenv("HAPAX_SESSION_ID", "ambient-parent-session")
    route = module.PLATFORM_PATHS[("codex", "headless", "full")]

    offered = module.Validation(
        True,
        "ok",
        module.TaskNote(tmp_path / "offered.md", {"status": "offered"}),
    )
    claimed = module.Validation(
        True,
        "ok",
        module.TaskNote(tmp_path / "claimed.md", {"status": "claimed"}),
    )

    assert module.launch_codex_headless("task-new", "cx-amber", "prompt", offered, route) == 0
    with monkeypatch.context() as scoped:
        scoped.setattr(
            module,
            "resolve_claim_resume_session",
            lambda **_kwargs: "explicit-resume-session",
        )
        assert (
            module.launch_codex_headless(
                "task-resume",
                "cx-amber",
                "prompt",
                claimed,
                route,
            )
            == 0
        )

    assert env_log.read_text(encoding="utf-8").splitlines() == [
        "<unset>|<unset>",
        "<unset>|explicit-resume-session",
    ]
    assert "--no-claim" not in args_log.read_text(encoding="utf-8").splitlines()[0]
    assert "--no-claim" in args_log.read_text(encoding="utf-8").splitlines()[1]


def test_resolve_claim_resume_session_requires_one_complete_exact_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _dispatcher_module()
    cache = tmp_path / "cache"
    cache.mkdir()
    lane = "cx-amber"
    task_id = "task-resume"
    session_id = "11111111-2222-4333-8444-555555555555"
    epoch = f"1234 {task_id}\n"
    binding = ClaimDispatchBinding.create(
        task_id=task_id,
        lane=lane,
        session_id=session_id,
        claim_epoch=1234,
        dispatch_message_id="message-1",
        platform="codex",
        mode="headless",
        profile="full",
        authority_case="CASE-TEST-001",
        binding_hash="a" * 64,
    )
    for key in (lane, f"{lane}-{session_id}"):
        (cache / f"cc-active-task-{key}").write_text(f"{task_id}\n", encoding="utf-8")
        (cache / f"cc-claim-epoch-{key}").write_text(epoch, encoding="utf-8")
        (cache / f"cc-claim-dispatch-{key}.json").write_text(
            json.dumps(binding.to_record()),
            encoding="ascii",
        )
    monkeypatch.setenv("HAPAX_CACHE_DIR", str(cache))

    assert (
        module.resolve_claim_resume_session(
            task_id=task_id,
            lane=lane,
            platform="codex",
        )
        == session_id
    )


def test_resolve_claim_resume_session_rejects_wrong_platform(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _dispatcher_module()
    cache = tmp_path / "cache"
    cache.mkdir()
    lane = "cx-amber"
    task_id = "task-resume"
    session_id = "11111111-2222-4333-8444-555555555555"
    binding = ClaimDispatchBinding.create(
        task_id=task_id,
        lane=lane,
        session_id=session_id,
        claim_epoch=1234,
        dispatch_message_id="message-1",
        platform="claude",
        mode="headless",
        profile="full",
        authority_case="CASE-TEST-001",
        binding_hash="a" * 64,
    )
    for key in (lane, f"{lane}-{session_id}"):
        (cache / f"cc-active-task-{key}").write_text(f"{task_id}\n", encoding="utf-8")
        (cache / f"cc-claim-epoch-{key}").write_text(f"1234 {task_id}\n", encoding="utf-8")
        (cache / f"cc-claim-dispatch-{key}.json").write_text(
            json.dumps(binding.to_record()),
            encoding="ascii",
        )
    monkeypatch.setenv("HAPAX_CACHE_DIR", str(cache))

    with pytest.raises(module.TaskStoreError, match="resume_exact_session_missing"):
        module.resolve_claim_resume_session(
            task_id=task_id,
            lane=lane,
            platform="codex",
        )


def test_governed_relay_reactivation_passes_force_to_headless_launcher(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    task_id = "governed-codex-retired-relay"
    _task(
        tmp_path / "tasks",
        task_id,
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
        status="claimed",
        assigned_to="cx-fugu",
    )
    home = tmp_path / "home"
    relay = home / ".cache" / "hapax" / "relay"
    relay.mkdir(parents=True)
    (home / ".cache" / "hapax" / "stage0-durable-sink").mkdir(parents=True)
    (relay / "cx-fugu.yaml").write_text("status: wind_down_idle\n", encoding="utf-8")
    _write_resume_projection(
        home / ".cache" / "hapax",
        lane="cx-fugu",
        task_id=task_id,
    )
    launcher_env = tmp_path / "launcher-env.txt"
    launcher_args = tmp_path / "launcher-args.txt"
    fake_launcher = tmp_path / "bin" / "hapax-codex-headless"
    fake_launcher.parent.mkdir(parents=True, exist_ok=True)
    fake_launcher.write_text(
        f"""#!/usr/bin/env bash
printf 'host=%s\\nfallback=%s\\n' "$HAPAX_DISPATCH_HOST" "${{HAPAX_DISPATCH_HOST_FALLBACK:-}}" > {launcher_env}
printf '%s\\n' "$@" > {launcher_args}
""",
        encoding="utf-8",
    )
    fake_launcher.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        task_id,
        "--lane",
        "cx-fugu",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--launch",
        extra_env={
            "HAPAX_METHODOLOGY_CODEX_HEADLESS": str(fake_launcher),
            "HAPAX_P0_CODEX_DRAIN_LANES": "",
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        },
    )

    assert result.returncode == 0, result.stderr
    recorded = launcher_args.read_text(encoding="utf-8")
    assert recorded.startswith(f"--task\n{task_id}\n--force\n--no-claim\ncx-fugu\n")
    assert launcher_env.read_text(encoding="utf-8").splitlines() == [
        "host=appendix",
        "fallback=",
    ]


def test_codex_p0_incident_drain_lane_force_preserves_live_pid_guard(tmp_path: Path) -> None:
    worktree = _worktree(tmp_path / "worktree")
    (worktree / "scripts" / "cc-claim").chmod(0o755)
    spec = _spec(tmp_path / "isap-test.md")
    task_id = "p0-incident-sdlc-task-stalled-test"
    _task(
        tmp_path / "tasks",
        task_id,
        f"""
        kind: build
        priority: p0
        tags: [cc-task, p0, incident-intake, technical-alert]
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )
    home = tmp_path / "home"
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    pid_dir = tmp_path / "pids"
    pid_dir.mkdir()
    bin_dir = tmp_path / "bin"
    codex_args = tmp_path / "codex-args.txt"
    _write(
        bin_dir / "codex",
        f"""#!/usr/bin/env bash
if [ "${{1:-}}" = "exec" ] && [[ "$*" == *HAPAX_CODEX_EXEC_AUTH_OK* ]]; then
  printf '%s\\n' '{{"type":"item.completed","item":{{"type":"agent_message","text":"HAPAX_CODEX_EXEC_AUTH_OK"}}}}'
  exit 0
fi
if [ "${{1:-}}" = "debug" ] && [ "${{2:-}}" = "models" ]; then
  printf '%s\\n' '{{"models":[{{"slug":"gpt-5.5"}}]}}'
  exit 0
fi
printf '%s\\n' "$*" > {codex_args}
""",
    )
    (bin_dir / "codex").chmod(0o755)

    live = subprocess.Popen(["sleep", "60"])
    try:
        (pid_dir / "cx-p0.pid").write_text(f"{live.pid}\n", encoding="utf-8")
        activation_env = install_launcher_activation(home)
        result = _run(
            tmp_path,
            "--task",
            task_id,
            "--lane",
            "cx-p0",
            "--platform",
            "codex",
            "--mode",
            "headless",
            "--launch",
            extra_env={
                "HAPAX_METHODOLOGY_CODEX_HEADLESS": str(
                    REPO_ROOT / "scripts" / "hapax-codex-headless"
                ),
                "HAPAX_COUNCIL_DIR": str(REPO_ROOT),
                "HAPAX_CODEX_HEADLESS_ALLOW": "1",
                "HAPAX_CODEX_HEADLESS_WORKDIR": str(tmp_path / "worktree"),
                "HAPAX_CODEX_HEADLESS_PID_DIR": str(pid_dir),
                "XDG_CACHE_HOME": str(tmp_path / "cache"),
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                **activation_env,
            },
        )
    finally:
        live.terminate()
        live.wait(timeout=5)

    assert result.returncode == 11
    assert "already live" in result.stderr
    assert not codex_args.exists()
    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["launched"] is False
    assert receipt["launch_returncode"] == 11
    assert receipt["coord_dispatch_cleanup_state"] == "deferred"


def test_governed_codex_dispatch_refuses_role_only_retired_relay_resume(
    tmp_path: Path,
) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    task_id = "governed-codex-retired-relay"
    _task(
        tmp_path / "tasks",
        task_id,
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
        status="claimed",
        assigned_to="cx-fugu",
    )
    home = tmp_path / "home"
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    relay = home / ".cache" / "hapax" / "relay"
    relay.mkdir(parents=True)
    (home / ".cache" / "hapax" / "stage0-durable-sink").mkdir(parents=True)
    (relay / "cx-fugu.yaml").write_text("status: wind_down_idle\n", encoding="utf-8")
    pid_dir = tmp_path / "pids"
    pid_dir.mkdir()
    bin_dir = tmp_path / "bin"
    codex_args = tmp_path / "codex-args.txt"
    _write(
        bin_dir / "codex",
        f"""#!/usr/bin/env bash
if [ "${{1:-}}" = "exec" ] && [[ "$*" == *HAPAX_CODEX_EXEC_AUTH_OK* ]]; then
  printf '%s\\n' '{{"type":"item.completed","item":{{"type":"agent_message","text":"HAPAX_CODEX_EXEC_AUTH_OK"}}}}'
  exit 0
fi
if [ "${{1:-}}" = "debug" ] && [ "${{2:-}}" = "models" ]; then
  printf '%s\\n' '{{"models":[{{"slug":"gpt-5.5"}}]}}'
  exit 0
fi
printf '%s\\n' "$*" > {codex_args}
""",
    )
    (bin_dir / "codex").chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        task_id,
        "--lane",
        "cx-fugu",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--launch",
        extra_env={
            "HAPAX_METHODOLOGY_CODEX_HEADLESS": str(REPO_ROOT / "scripts" / "hapax-codex-headless"),
            "HAPAX_COUNCIL_DIR": str(REPO_ROOT),
            "HAPAX_CODEX_HEADLESS_ALLOW": "1",
            "HAPAX_CODEX_HEADLESS_WORKDIR": str(tmp_path / "worktree"),
            "HAPAX_CODEX_HEADLESS_PID_DIR": str(pid_dir),
            "HAPAX_CODEX_OAUTH_ACCESS_TOKEN_FILE": str(_write_codex_access_token(tmp_path)),
            "HAPAX_DISPATCH_HOST": "local",
            "HAPAX_P0_CODEX_DRAIN_LANES": "",
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
        },
    )

    assert result.returncode == 17
    assert "resume_exact_session_missing" in result.stderr
    assert not codex_args.exists()
    assert (relay / "cx-fugu.yaml").read_text(encoding="utf-8") == "status: wind_down_idle\n"


def test_governed_relay_reactivation_predicate_accepts_bound_mutable_launch(
    tmp_path: Path,
) -> None:
    module = _dispatcher_module()
    route_decision = type(
        "RouteDecisionStub",
        (),
        {"action": module.DispatchAction.LAUNCH},
    )()
    validation = module.Validation(
        True,
        "ok",
        module.TaskNote(
            tmp_path / "task.md",
            {
                "status": "claimed",
                "kind": "build",
                "authority_case": "CASE-TEST-001",
            },
        ),
    )

    assert module.allow_codex_governed_relay_reactivation(
        route=module.PLATFORM_PATHS[("codex", "headless", "full")],
        route_decision=route_decision,
        durable_binding=module.DurableDispatchBinding(
            True,
            False,
            "durable_mq_dispatch_bound",
            message_id="dispatch-message",
        ),
        validation=validation,
    )


def test_governed_relay_reactivation_rejects_advisory_or_unbound_binding(
    tmp_path: Path, monkeypatch, capfd
) -> None:
    module = _dispatcher_module()
    _worktree(tmp_path / "worktree")
    home = tmp_path / "home"
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    relay = home / ".cache" / "hapax" / "relay"
    relay.mkdir(parents=True)
    (relay / "cx-green.yaml").write_text("status: wind_down_idle\n", encoding="utf-8")
    pid_dir = tmp_path / "pids"
    pid_dir.mkdir()
    bin_dir = tmp_path / "bin"
    codex_args = tmp_path / "codex-args.txt"
    _write(
        bin_dir / "codex",
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" > {codex_args}\n",
    )
    (bin_dir / "codex").chmod(0o755)
    monkeypatch.setenv(
        "HAPAX_METHODOLOGY_CODEX_HEADLESS",
        str(REPO_ROOT / "scripts" / "hapax-codex-headless"),
    )
    monkeypatch.setenv("HAPAX_COUNCIL_DIR", str(REPO_ROOT))
    monkeypatch.setenv("HAPAX_CODEX_HEADLESS_ALLOW", "1")
    monkeypatch.setenv("HAPAX_CODEX_HEADLESS_WORKDIR", str(tmp_path / "worktree"))
    monkeypatch.setenv("HAPAX_CODEX_HEADLESS_PID_DIR", str(pid_dir))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    validation = module.Validation(
        True,
        "ok",
        module.TaskNote(
            tmp_path / "task.md",
            {
                "status": "claimed",
                "kind": "build",
                "authority_case": "CASE-TEST-001",
            },
        ),
    )
    route_decision = type(
        "RouteDecisionStub",
        (),
        {"action": module.DispatchAction.LAUNCH},
    )()
    route = module.PLATFORM_PATHS[("codex", "headless", "full")]
    monkeypatch.setattr(
        module,
        "resolve_claim_resume_session",
        lambda **_kwargs: "11111111-2222-4333-8444-555555555555",
    )

    for binding in (
        module.DurableDispatchBinding(
            True,
            True,
            "advisory_binding_must_not_reactivate",
            message_id="dispatch-message",
        ),
        module.DurableDispatchBinding(
            True,
            False,
            "message_id_required_for_reactivation",
            message_id=None,
        ),
    ):
        reactivate = module.allow_codex_governed_relay_reactivation(
            route=route,
            route_decision=route_decision,
            durable_binding=binding,
            validation=validation,
        )

        assert reactivate is False
        result = module.launch_codex_headless(
            "governed-codex-retired-relay",
            "cx-green",
            "prompt",
            validation,
            route,
            reactivate_retired_relay=reactivate,
        )
        assert result == 6
        captured = capfd.readouterr()
        assert "relay 'cx-green' is retired/wound-down" in captured.err
        assert "pass --force to reactivate" in captured.err
        assert not codex_args.exists()


def test_codex_headless_dispatch_propagates_retired_relay_block(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    _task(
        tmp_path / "tasks",
        "read-only-intake",
        """
        kind: intake
        task_type: read-only
        parent_spec: null
        tags:
          - intake
          - read-only
        """,
        status="claimed",
        assigned_to="cx-green",
    )
    home = tmp_path / "home"
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    relay = home / ".cache" / "hapax" / "relay"
    relay.mkdir(parents=True)
    (relay / "cx-green.yaml").write_text("status: wind_down_idle\n", encoding="utf-8")
    _write_resume_projection(
        home / ".cache" / "hapax",
        lane="cx-green",
        task_id="read-only-intake",
    )
    bin_dir = tmp_path / "bin"
    codex_args = tmp_path / "codex-args.txt"
    _write(
        bin_dir / "codex",
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" > {codex_args}\n",
    )
    (bin_dir / "codex").chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "read-only-intake",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--launch",
        extra_env={
            "HAPAX_METHODOLOGY_CODEX_HEADLESS": str(REPO_ROOT / "scripts" / "hapax-codex-headless"),
            "HAPAX_COUNCIL_DIR": str(REPO_ROOT),
            "HAPAX_CODEX_HEADLESS_ALLOW": "1",
            "HAPAX_CODEX_HEADLESS_WORKDIR": str(tmp_path / "worktree"),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
        },
        durable_mq=False,
    )

    assert result.returncode == 6
    assert "retired/wound-down" in result.stderr
    assert not codex_args.exists()


def test_codex_headless_dispatch_blocks_mq_bound_read_only_exempt_retired_relay(
    tmp_path: Path,
) -> None:
    _worktree(tmp_path / "worktree")
    _task(
        tmp_path / "tasks",
        "mq-bound-read-only-intake",
        """
        kind: intake
        task_type: read-only
        authority_case: CASE-TEST-001
        parent_spec: null
        tags:
          - intake
          - read-only
        """,
        status="claimed",
        assigned_to="cx-green",
    )
    home = tmp_path / "home"
    (home / "projects" / "hapax-mcp").mkdir(parents=True)
    relay = home / ".cache" / "hapax" / "relay"
    relay.mkdir(parents=True)
    (relay / "cx-green.yaml").write_text("status: wind_down_idle\n", encoding="utf-8")
    _write_resume_projection(
        home / ".cache" / "hapax",
        lane="cx-green",
        task_id="mq-bound-read-only-intake",
    )
    bin_dir = tmp_path / "bin"
    codex_args = tmp_path / "codex-args.txt"
    _write(
        bin_dir / "codex",
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" > {codex_args}\n",
    )
    (bin_dir / "codex").chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "mq-bound-read-only-intake",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--launch",
        extra_env={
            "HAPAX_METHODOLOGY_CODEX_HEADLESS": str(REPO_ROOT / "scripts" / "hapax-codex-headless"),
            "HAPAX_COUNCIL_DIR": str(REPO_ROOT),
            "HAPAX_CODEX_HEADLESS_ALLOW": "1",
            "HAPAX_CODEX_HEADLESS_WORKDIR": str(tmp_path / "worktree"),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
        },
    )

    assert result.returncode == 6
    assert "retired/wound-down" in result.stderr
    assert not codex_args.exists()
    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["exempt_read_only"] is True
    assert receipt["durable_mq_dispatch_bound"] is True
    assert receipt["durable_mq_reason"] == "read_only_exempt"
    assert receipt["durable_mq_message_id"] is None


def test_split_lane_list_accepts_commas_and_whitespace() -> None:
    module = _dispatcher_module()

    assert module.split_lane_list(" cx-p0,cx-crit  cx-hot\ncx-extra ") == {
        "cx-p0",
        "cx-crit",
        "cx-hot",
        "cx-extra",
    }
    assert module.split_lane_list(" \t\n ") == set()
    assert module.split_lane_list(None) == set()


def test_codex_p0_incident_local_fallback_rejects_non_drain_lane(
    tmp_path: Path, monkeypatch
) -> None:
    module = _dispatcher_module()
    monkeypatch.setenv("HAPAX_P0_CODEX_DRAIN_LANES", "cx-p0")
    validation = module.Validation(
        True,
        "ok",
        module.TaskNote(
            tmp_path / "task.md",
            {
                "priority": "p0",
                "title": "P0 incident",
                "kind": "recovery_triage",
                "tags": ["incident-intake", "technical-alert"],
            },
        ),
    )

    assert not module.allow_codex_p0_local_dispatch_fallback(
        "p0-incident-sdlc-task-stalled-test", "cx-green", validation
    )


def test_codex_p0_incident_local_fallback_rejects_non_incident_drain_task(
    tmp_path: Path, monkeypatch
) -> None:
    module = _dispatcher_module()
    monkeypatch.setenv("HAPAX_P0_CODEX_DRAIN_LANES", "cx-p0")
    validation = module.Validation(
        True,
        "ok",
        module.TaskNote(
            tmp_path / "task.md",
            {
                "priority": "p0",
                "title": "Ordinary source change",
                "kind": "build",
                "tags": ["cc-task", "p0"],
            },
        ),
    )

    assert not module.allow_codex_p0_local_dispatch_fallback(
        "ordinary-p0-build", "cx-p0", validation
    )


def test_codex_p0_incident_local_fallback_rejects_priority_mismatch(
    tmp_path: Path, monkeypatch
) -> None:
    module = _dispatcher_module()
    monkeypatch.setenv("HAPAX_P0_CODEX_DRAIN_LANES", "cx-p0")
    validation = module.Validation(
        True,
        "ok",
        module.TaskNote(
            tmp_path / "task.md",
            {
                "priority": "p1",
                "title": "P0 incident marker in title",
                "kind": "recovery_triage",
                "tags": ["incident-intake", "technical-alert"],
            },
        ),
    )

    assert not module.allow_codex_p0_local_dispatch_fallback(
        "p0-incident-priority-mismatch", "cx-p0", validation
    )


def test_codex_p0_incident_local_fallback_uses_primary_drain_lane_override(
    tmp_path: Path, monkeypatch
) -> None:
    module = _dispatcher_module()
    monkeypatch.setenv("HAPAX_SUPERVISOR_P0_CODEX_LANES", "cx-p0")
    monkeypatch.setenv("HAPAX_P0_CODEX_DRAIN_LANES", "cx-hot")
    validation = module.Validation(
        True,
        "ok",
        module.TaskNote(
            tmp_path / "task.md",
            {
                "priority": "p0",
                "title": "P0 incident",
                "kind": "recovery_triage",
                "tags": ["incident-intake", "technical-alert"],
            },
        ),
    )

    assert module.allow_codex_p0_local_dispatch_fallback(
        "p0-incident-custom-drain", "cx-hot", validation
    )
    assert not module.allow_codex_p0_local_dispatch_fallback(
        "p0-incident-custom-drain", "cx-p0", validation
    )


def test_codex_p0_incident_local_fallback_uses_legacy_singular_drain_lane(
    tmp_path: Path, monkeypatch
) -> None:
    module = _dispatcher_module()
    monkeypatch.delenv("HAPAX_P0_CODEX_DRAIN_LANES", raising=False)
    monkeypatch.delenv("HAPAX_SUPERVISOR_P0_CODEX_LANES", raising=False)
    monkeypatch.setenv("HAPAX_SUPERVISOR_P0_CODEX_LANE", "cx-hot")
    validation = module.Validation(
        True,
        "ok",
        module.TaskNote(
            tmp_path / "task.md",
            {
                "priority": "p0",
                "title": "P0 incident",
                "kind": "recovery_triage",
                "tags": ["incident-intake", "technical-alert"],
            },
        ),
    )

    assert module.allow_codex_p0_local_dispatch_fallback(
        "p0-incident-legacy-drain", "cx-hot", validation
    )
    assert not module.allow_codex_p0_local_dispatch_fallback(
        "p0-incident-legacy-drain", "cx-p0", validation
    )


def test_codex_p0_incident_local_fallback_respects_empty_override(
    tmp_path: Path, monkeypatch
) -> None:
    module = _dispatcher_module()
    monkeypatch.setenv("HAPAX_SUPERVISOR_P0_CODEX_LANES", "cx-p0")
    monkeypatch.setenv("HAPAX_P0_CODEX_DRAIN_LANES", "")
    validation = module.Validation(
        True,
        "ok",
        module.TaskNote(
            tmp_path / "task.md",
            {
                "priority": "p0",
                "title": "P0 incident",
                "kind": "recovery_triage",
                "tags": ["incident-intake", "technical-alert"],
            },
        ),
    )

    assert not module.allow_codex_p0_local_dispatch_fallback(
        "p0-incident-empty-drain-roster", "cx-p0", validation
    )


def test_launch_idempotency_replays_without_second_launcher_call(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )
    launcher_args = tmp_path / "launcher-args.txt"
    launch_count = tmp_path / "launch-count.txt"
    fake_launcher = tmp_path / "bin" / "hapax-codex"
    fake_launcher.parent.mkdir(parents=True, exist_ok=True)
    fake_launcher.write_text(
        f"""#!/usr/bin/env bash
count=0
if [ -f {launch_count} ]; then
  count="$(cat {launch_count})"
fi
printf '%s\\n' "$((count + 1))" > {launch_count}
printf '%s\\n' "$@" > {launcher_args}
""",
        encoding="utf-8",
    )
    fake_launcher.chmod(0o755)

    first = _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--launch",
        "--idempotency-key",
        "dispatch-test-key",
        extra_env={
            "HAPAX_METHODOLOGY_CODEX_HEADLESS": str(fake_launcher),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        },
    )
    assert first.returncode == 0, first.stderr
    with sqlite3.connect(tmp_path / "relay" / "messages.db") as conn:
        message_id = conn.execute("SELECT message_id FROM messages").fetchone()[0]

    second = _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--launch",
        "--idempotency-key",
        "dispatch-test-key",
        durable_mq=False,
        extra_env={
            "HAPAX_RELAY_MQ_DB": str(tmp_path / "relay" / "messages.db"),
            "HAPAX_METHODOLOGY_DISPATCH_MESSAGE_ID": message_id,
            "HAPAX_METHODOLOGY_CODEX_HEADLESS": str(fake_launcher),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        },
    )

    assert second.returncode == 0, second.stderr
    assert launch_count.read_text(encoding="utf-8").strip() == "1"
    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["coord_dispatch_replayed"] is True
    assert receipt["coord_dispatch_reason"] == "replayed_succeeded"


def test_failed_launch_cleans_up_mq_state_and_records_failure(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )
    fake_launcher = tmp_path / "bin" / "hapax-codex"
    fake_launcher.parent.mkdir(parents=True, exist_ok=True)
    fake_launcher.write_text("#!/usr/bin/env bash\nexit 42\n", encoding="utf-8")
    fake_launcher.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--launch",
        extra_env={"HAPAX_METHODOLOGY_CODEX_HEADLESS": str(fake_launcher)},
    )

    assert result.returncode == 42
    with sqlite3.connect(tmp_path / "relay" / "messages.db") as conn:
        message_id = conn.execute("SELECT message_id FROM messages").fetchone()[0]
    row = _recipient_row(tmp_path / "relay" / "messages.db", message_id, "cx-green")
    assert row["state"] == "deferred"
    assert row["reason"].startswith("coord_dispatch_launch_deferred:42:")
    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["launched"] is False
    assert receipt["launch_returncode"] == 42
    assert receipt["coord_dispatch_cleanup_state"] == "deferred"
    mirror = (tmp_path / "coord" / "ledger.jsonl").read_text(encoding="utf-8")
    assert "coord_dispatch.launch_failed" in mirror


def test_launch_recomposes_from_subscription_receipt_without_account_live(
    tmp_path: Path,
) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    registry = _fresh_registry(tmp_path)
    registry = _without_account_live_quota_evidence(tmp_path, registry, "codex.headless.full")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        route_metadata_schema: 1
        quality_floor: frontier_required
        authority_level: authoritative
        mutation_surface: source
        mutation_scope_refs: []
        risk_flags:
          governance_sensitive: false
          privacy_or_secret_sensitive: false
          public_claim_sensitive: false
          aesthetic_theory_sensitive: false
          audio_or_live_egress_sensitive: false
          provider_billing_sensitive: false
        context_shape:
          codebase_locality: module
          vault_context_required: true
          external_docs_required: false
          currentness_required: false
        verification_surface:
          deterministic_tests: []
          static_checks: []
          runtime_observation: []
          operator_only: false
        route_constraints:
          preferred_platforms: []
          allowed_platforms: [claude, codex]
          prohibited_platforms: []
          required_mode: headless
          required_profile: full
        review_requirement:
          support_artifact_allowed: false
          independent_review_required: false
          authoritative_acceptor_profile: null
        """,
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    _fake_binary(bin_dir, "codex", "codex-cli 9.9.9")
    receipt_dir = tmp_path / "receipts"
    receipt_result = subprocess.run(
        [
            sys.executable,
            str(RECEIPT_SCRIPT),
            "--registry",
            str(registry),
            "--receipt-dir",
            str(receipt_dir),
            "--platform",
            "codex",
            "--json",
        ],
        env={**os.environ, "PATH": str(bin_dir)},
        text=True,
        capture_output=True,
        check=False,
    )
    assert receipt_result.returncode == 0, receipt_result.stderr

    launcher_args = tmp_path / "launcher-args.txt"
    fake_launcher = tmp_path / "launcher" / "hapax-claude-headless"
    fake_launcher.parent.mkdir(parents=True, exist_ok=True)
    fake_launcher.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {launcher_args}
""",
        encoding="utf-8",
    )
    fake_launcher.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "eta",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--launch",
        extra_env={
            "HAPAX_METHODOLOGY_CLAUDE_HEADLESS": str(fake_launcher),
            "HAPAX_PLATFORM_CAPABILITY_REGISTRY": str(registry),
            "HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR": str(receipt_dir),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        },
    )

    assert result.returncode == 0, result.stderr
    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["route_policy_action"] == "launch"
    assert receipt["route_policy_launch_allowed"] is True
    assert receipt["platform"] == "claude"
    assert receipt["dimensional_selected_route_id"] == "claude.headless.full"
    reasons = set(receipt["route_policy_reason_codes"])
    assert "availability_recomposition_required" in reasons
    assert "account_live_quota_evidence_absent" in reasons
    assert receipt.get("route_policy_compatibility_mode") in {None, "none"}


def test_glmcp_platform_receipt_uses_sanctioned_review_wrapper_check(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    pass_stub = bin_dir / "pass"
    pass_stub.write_text(
        """#!/usr/bin/env bash
if [ "$1" = "show" ] && [ "$2" = "glmcp/api-key" ]; then
  printf '%s\n' 'test-secret-token'
  exit 0
fi
exit 1
""",
        encoding="utf-8",
    )
    pass_stub.chmod(0o755)
    receipt_dir = tmp_path / "receipts"

    result = subprocess.run(
        [
            sys.executable,
            str(RECEIPT_SCRIPT),
            "--registry",
            str(REGISTRY),
            "--receipt-dir",
            str(receipt_dir),
            "--platform",
            "glmcp",
            "--json",
        ],
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["receipts"][0]["platform"] == "glmcp"
    assert summary["receipts"][0]["cli_available"] is True
    assert summary["receipts"][0]["wrapper_exists"] is True
    receipt = json.loads((receipt_dir / "glmcp.json").read_text(encoding="utf-8"))
    assert receipt["platform"] == "glmcp"
    assert receipt["routes"] == ["glmcp.review.direct"]
    assert receipt["cli"]["binary"] == "scripts/hapax-glmcp-reviewer"
    assert "model=glm-5.2" in receipt["cli"]["version"]
    assert "payg_fallback=enabled" in receipt["cli"]["version"]
    receipt_text = json.dumps(receipt)
    assert "test-secret-token" not in receipt_text
    assert any(
        item["path"].endswith("scripts/hapax-glmcp-reviewer") for item in receipt["config_refs"]
    )


def test_policy_rollback_is_retired_before_launcher(
    tmp_path: Path,
) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )
    launcher_args = tmp_path / "launcher-args.txt"
    route_decisions = tmp_path / "ledger" / "route-decisions.jsonl"
    fake_launcher = tmp_path / "bin" / "hapax-codex"
    fake_launcher.parent.mkdir(parents=True, exist_ok=True)
    fake_launcher.write_text(
        f"""#!/usr/bin/env bash
test -s {route_decisions} || exit 23
printf '%s\\n' "$@" > {launcher_args}
""",
        encoding="utf-8",
    )
    fake_launcher.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--policy-rollback",
        "--launch",
        extra_env={
            "HAPAX_METHODOLOGY_CODEX_HEADLESS": str(fake_launcher),
            "HAPAX_PLATFORM_CAPABILITY_REGISTRY": str(REGISTRY),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        },
    )

    assert result.returncode == 10
    assert not launcher_args.exists()
    assert "policy_rollback_retired" in result.stderr
    route_receipt = json.loads(route_decisions.read_text(encoding="utf-8").splitlines()[-1])
    assert route_receipt["action"] == "hold"
    assert "policy_rollback_retired" in route_receipt["reason_codes"]
    assert "signed_route_authority_receipt_required" in route_receipt["reason_codes"]
    assert route_receipt["route_policy_green"] is False
    assert route_receipt["clog_state"] == "held"
    assert route_receipt["compatibility_mode"] == "none"
    assert route_receipt["degraded_state"] is None
    assert route_receipt["route_selection_authority"] is False
    dispatch_receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert dispatch_receipt["route_policy_green"] is False
    assert dispatch_receipt["route_policy_clog_state"] == "held"
    assert dispatch_receipt["route_policy_compatibility_mode"] == "none"
    assert dispatch_receipt["route_policy_degraded_state"] is None
    assert dispatch_receipt["route_policy_route_selection_authority"] is False


def test_policy_rollback_holds_non_full_profile_before_launcher(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )
    launcher_args = tmp_path / "launcher-args.txt"
    fake_launcher = tmp_path / "bin" / "hapax-codex"
    fake_launcher.parent.mkdir(parents=True, exist_ok=True)
    fake_launcher.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {launcher_args}
""",
        encoding="utf-8",
    )
    fake_launcher.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "headless",
        "--profile",
        "spark",
        "--policy-rollback",
        "--launch",
        extra_env={
            "HAPAX_METHODOLOGY_CODEX_HEADLESS": str(fake_launcher),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        },
    )

    assert result.returncode == 10
    assert not launcher_args.exists()
    assert "policy_rollback_retired" in result.stderr
    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["platform"] == "codex"
    assert receipt["profile"] == "spark"
    assert receipt["route_policy_action"] == "hold"
    assert receipt["route_policy_green"] is False
    assert receipt["route_policy_clog_state"] == "held"
    assert "policy_rollback_retired" in receipt["route_policy_reason_codes"]


def test_claude_sonnet_fallback_refuses_authoritative_dispatch(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )
    launcher_env = tmp_path / "claude-env.txt"
    fake_launcher = tmp_path / "bin" / "hapax-claude-headless"
    fake_launcher.parent.mkdir(parents=True, exist_ok=True)
    fake_launcher.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$HAPAX_CLAUDE_MODEL" "$@" > {launcher_env}
""",
        encoding="utf-8",
    )
    fake_launcher.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "beta",
        "--platform",
        "claude",
        "--mode",
        "headless",
        "--profile",
        "quota-fallback",
        "--launch",
        extra_env={"HAPAX_METHODOLOGY_CLAUDE_HEADLESS": str(fake_launcher)},
    )

    assert result.returncode == 10
    assert not launcher_env.exists()
    assert "quality_floor_not_satisfied" in result.stderr
    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["platform"] == "claude"
    assert receipt["profile"] == "sonnet"
    assert receipt["route_policy_action"] == "refuse"


def test_claude_headless_launch_holds_without_account_live_quota_receipt(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    quota_ledger = _claude_subscription_quota_ledger(tmp_path, state="unknown")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )
    launcher_args = tmp_path / "claude-args.txt"
    fake_launcher = tmp_path / "bin" / "hapax-claude-headless"
    fake_launcher.parent.mkdir(parents=True, exist_ok=True)
    fake_launcher.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {launcher_args}
""",
        encoding="utf-8",
    )
    fake_launcher.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "beta",
        "--platform",
        "claude",
        "--mode",
        "headless",
        "--launch",
        extra_env={
            "HAPAX_METHODOLOGY_CLAUDE_HEADLESS": str(fake_launcher),
            "HAPAX_QUOTA_SPEND_LEDGER": str(quota_ledger),
        },
    )

    assert result.returncode == 10
    assert not launcher_args.exists()
    assert "subscription_route_quota_not_fresh" in result.stderr
    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["launched"] is False
    assert receipt["route_policy_action"] == "hold"
    reasons = set(receipt["route_policy_reason_codes"])
    assert "subscription_route_quota_not_fresh" in reasons
    assert "route_subscription_quota_state:unknown" in reasons
    assert "relay-receipt:claude:quota-admission:absent" in reasons


def test_launches_claude_headless_with_task_binding(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    quota_ledger = _fresh_claude_subscription_quota_ledger(tmp_path)
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )
    launcher_args = tmp_path / "claude-args.txt"
    fake_launcher = tmp_path / "bin" / "hapax-claude-headless"
    fake_launcher.parent.mkdir(parents=True, exist_ok=True)
    fake_launcher.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$HAPAX_METHODOLOGY_DISPATCH_TASK" "$HAPAX_CLAUDE_HEADLESS_WORKDIR" "$@" > {launcher_args}
""",
        encoding="utf-8",
    )
    fake_launcher.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "beta",
        "--platform",
        "claude",
        "--mode",
        "headless",
        "--launch",
        extra_env={
            "HAPAX_METHODOLOGY_CLAUDE_HEADLESS": str(fake_launcher),
            "HAPAX_QUOTA_SPEND_LEDGER": str(quota_ledger),
        },
    )

    assert result.returncode == 0, result.stderr
    args = launcher_args.read_text(encoding="utf-8").splitlines()
    assert args[0] == "governed-build"
    assert args[1] == str(tmp_path / "worktree")
    assert args[2:5] == ["--task", "governed-build", "beta"]
    assert "SDLC GOVERNED DISPATCH." in "\n".join(args[5:])
    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["route_policy_action"] == "launch"
    assert receipt["route_policy_launch_allowed"] is True
    assert receipt["route_policy_quota_freshness_green"] is True
    assert not any(
        reason.startswith("route_subscription_quota_state:")
        for reason in receipt["route_policy_reason_codes"]
    )


def test_sliced_call_preserves_dispatch_env_and_marks_attached(monkeypatch) -> None:
    dispatcher = _dispatcher_module()
    captured: dict[str, object] = {}

    def fake_wrap(args: list[str], *, setenv: dict[str, str]) -> list[str]:
        captured["setenv"] = setenv
        return ["systemd-run", "--", *args]

    def fake_call(args: list[str], env: dict[str, str]) -> int:
        captured["args"] = args
        captured["env"] = env
        return 0

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("HAPAX_CLAUDE_HEADLESS_WORKDIR", raising=False)
    monkeypatch.delenv("HAPAX_DISPATCH_HOST", raising=False)
    monkeypatch.setattr(dispatcher, "sdlc_slice_wrap", fake_wrap)
    monkeypatch.setattr(dispatcher.subprocess, "call", fake_call)

    rc = dispatcher._sliced_call(
        ["hapax-claude-headless", "--task", "t", "alpha"],
        {
            "HAPAX_CLAUDE_HEADLESS_WORKDIR": "/tmp/clean-worktree",
            "HAPAX_DISPATCH_HOST": "local",
        },
    )

    assert rc == 0
    assert captured["args"] == [
        "systemd-run",
        "--",
        "hapax-claude-headless",
        "--task",
        "t",
        "alpha",
    ]
    setenv = captured["setenv"]
    assert isinstance(setenv, dict)
    assert setenv["HAPAX_CLAUDE_HEADLESS_WORKDIR"] == "/tmp/clean-worktree"
    assert setenv["HAPAX_DISPATCH_HOST"] == "local"
    assert setenv["HAPAX_SDLC_SLICE_ATTACHED"] == "1"
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["HAPAX_SDLC_SLICE_ATTACHED"] == "1"


def test_launches_claude_interactive_visible_lane_with_task_binding(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )
    launcher_args = tmp_path / "claude-visible-args.txt"
    fake_launcher = tmp_path / "bin" / "hapax-claude"
    fake_launcher.parent.mkdir(parents=True, exist_ok=True)
    fake_launcher.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {launcher_args}
""",
        encoding="utf-8",
    )
    fake_launcher.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "beta",
        "--platform",
        "claude",
        "--mode",
        "interactive",
        "--launch",
        extra_env={"HAPAX_METHODOLOGY_CLAUDE_LAUNCHER": str(fake_launcher)},
    )

    assert result.returncode == 0, result.stderr
    args = launcher_args.read_text(encoding="utf-8").splitlines()
    assert args == [
        "--role",
        "beta",
        "--terminal",
        "tmux",
        "--task",
        "governed-build",
    ]


def test_vibe_jr_route_refuses_authoritative_dispatch(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "bounded-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )
    launcher_args = tmp_path / "vibe-args.txt"
    fake_launcher = tmp_path / "bin" / "hapax-vibe"
    fake_launcher.parent.mkdir(parents=True, exist_ok=True)
    fake_launcher.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {launcher_args}
""",
        encoding="utf-8",
    )
    fake_launcher.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "bounded-build",
        "--lane",
        "vbe-1",
        "--platform",
        "vibe",
        "--mode",
        "headless",
        "--launch",
        extra_env={"HAPAX_METHODOLOGY_VIBE_LAUNCHER": str(fake_launcher)},
    )

    assert result.returncode == 10
    assert not launcher_args.exists()
    assert "quality_floor_not_satisfied" in result.stderr


def test_vibe_mutable_launch_reaches_existing_launcher(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "bounded-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        route_metadata_schema: 1
        quality_floor: deterministic_ok
        authority_level: support_non_authoritative
        mutation_surface: source
        mutation_scope_refs: []
        risk_flags:
          governance_sensitive: false
          privacy_or_secret_sensitive: false
          public_claim_sensitive: false
          aesthetic_theory_sensitive: false
          audio_or_live_egress_sensitive: false
          provider_billing_sensitive: false
        context_shape:
          codebase_locality: module
          vault_context_required: true
          external_docs_required: false
          currentness_required: false
        verification_surface:
          deterministic_tests: []
          static_checks: []
          runtime_observation: []
          operator_only: false
        route_constraints:
          preferred_platforms: []
          allowed_platforms: []
          prohibited_platforms: []
          required_mode: null
          required_profile: null
        review_requirement:
          support_artifact_allowed: false
          independent_review_required: false
          authoritative_acceptor_profile: null
        """,
        route_metadata_defaults=False,
    )
    launcher_args = tmp_path / "vibe-args.txt"
    fake_launcher = tmp_path / "bin" / "hapax-vibe"
    fake_launcher.parent.mkdir(parents=True, exist_ok=True)
    fake_launcher.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$@" > {launcher_args}
""",
        encoding="utf-8",
    )
    fake_launcher.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "bounded-build",
        "--lane",
        "vbe-1",
        "--platform",
        "vibe",
        "--mode",
        "headless",
        "--launch",
        extra_env={"HAPAX_METHODOLOGY_VIBE_LAUNCHER": str(fake_launcher)},
    )

    assert result.returncode == 0, result.stderr
    args = launcher_args.read_text(encoding="utf-8").splitlines()
    assert args[:6] == ["--session", "vbe-1", "--terminal", "tmux", "--task", "bounded-build"]
    assert "--prompt" in args
    assert "--force" not in args


def test_agy_dispatch_remains_route_gated_without_spawnable_route(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )

    result = _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "cx-green",
        "--platform",
        "agy",
        "--mode",
        "headless",
        "--launch",
    )

    assert result.returncode == 10
    assert "non-launchable read-only agy.review.direct" in result.stderr
    assert "scripts/hapax-agy-reviewer" in result.stderr
    assert "agy/" not in result.stderr
    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["platform"] == "agy"
    assert receipt["launched"] is False
    assert receipt["ok"] is False
    assert "non-launchable read-only agy.review.direct" in receipt["reason"]
    assert receipt["route_policy_reason_codes"] == ["review_route_not_launchable"]


def test_gemini_platform_is_not_dispatchable(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "--task",
        "research-only",
        "--lane",
        "iota",
        "--platform",
        "gemini",
        "--mode",
        "headless",
    )

    assert result.returncode == 2
    assert "invalid choice: 'gemini'" in result.stderr


def test_lists_platform_profile_paths(tmp_path: Path) -> None:
    result = _run(tmp_path, "--list-platform-paths")

    assert result.returncode == 0, result.stderr
    assert "Default to maximum appropriate quality-preserving utilization" in result.stdout
    assert "codex/headless/full" in result.stdout
    assert "codex/headless/spark" in result.stdout
    assert "claude/interactive/full" in result.stdout
    assert "claude/headless/sonnet" in result.stdout
    assert "gemini/" not in result.stdout
    assert "antigrav/" not in result.stdout
    assert "agy/" not in result.stdout
    assert "api/headless/api_frontier" in result.stdout
    assert "api/headless/openrouter" in result.stdout
    assert "api/headless/provider_gateway" in result.stdout


def test_normalizes_openrouter_api_profile_aliases() -> None:
    dispatcher = _dispatcher_module()

    assert dispatcher.normalize_profile("api", "or") == "openrouter"
    assert dispatcher.normalize_profile("api", "open-router") == "openrouter"
    assert dispatcher.normalize_profile("api", "openrouter") == "openrouter"


def test_agy_platform_is_review_route_not_dispatchable_worker(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "--task",
        "research-only",
        "--lane",
        "agy",
        "--platform",
        "agy",
        "--mode",
        "interactive",
    )

    assert result.returncode == 10
    assert "platform 'agy' is the non-launchable read-only agy.review.direct" in result.stderr
    assert "scripts/hapax-agy-reviewer" in result.stderr


def test_antigrav_platform_is_not_dispatchable(tmp_path: Path) -> None:
    for platform in ("antigrav", "Antigrav", "antigravity", "gemini-cli"):
        result = _run(
            tmp_path,
            "--task",
            "research-only",
            "--lane",
            platform,
            "--platform",
            platform,
            "--mode",
            "interactive",
        )

        assert result.returncode == 10
        assert f"platform '{platform.lower()}' is retired/excised" in result.stderr
        assert "Use admitted Claude, Codex, or Vibe routes" in result.stderr
        assert "agy.review.direct" in result.stderr


def test_codex_launch_unsupported_mode_fails_closed(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    spec = _spec(tmp_path / "isap-test.md")
    _task(
        tmp_path / "tasks",
        "governed-build",
        f"""
        kind: build
        authority_case: CASE-TEST-001
        parent_spec: {spec}
        """,
    )
    fake_launcher = tmp_path / "bin" / "hapax-codex"
    fake_launcher.parent.mkdir(parents=True, exist_ok=True)
    fake_launcher.write_text("#!/usr/bin/env bash\nexit 99\n", encoding="utf-8")
    fake_launcher.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "cx-green",
        "--platform",
        "codex",
        "--mode",
        "interactive",
        "--launch",
        extra_env={"HAPAX_METHODOLOGY_CODEX_HEADLESS": str(fake_launcher)},
    )

    assert result.returncode == 10
    assert "unsupported_route" in result.stderr


def test_policy_rollback_help_documents_retirement() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--policy-rollback" in result.stdout
    help_text = result.stdout.lower()
    assert "deprecated" in help_text or "retired" in help_text
    # The old help claimed legacy full-profile routes "may launch" — that is now
    # false (rollback HOLDs). Guard against the stale promise regressing.
    assert "may launch" not in help_text
