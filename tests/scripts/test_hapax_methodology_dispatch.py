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

from shared.platform_capability_registry import PlatformCapabilityRegistry
from shared.quota_spend_ledger import QUOTA_SPEND_LEDGER_FIXTURES
from shared.relay_mq import send_message
from shared.relay_mq_envelope import Envelope

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


def _native_lifecycle_writer(variant: str = "matching") -> str:
    """Independent native-stream/receipt fixture, executed only by the fake launcher."""
    return (
        f"{sys.executable} - <<'PY'\n"
        f"variant = {variant!r}\n"
        + textwrap.dedent(
            r"""
            import hashlib
            import json
            import os
            from pathlib import Path

            if variant == "missing":
                raise SystemExit(0)
            receipt = Path(os.environ["HAPAX_NATIVE_LIFECYCLE_RECEIPT"])
            receipt.parent.mkdir(parents=True, exist_ok=True)
            stream = receipt.with_suffix(".jsonl")
            events = [
                {"type": "thread.started", "thread_id": "native-fixture-session"},
                {"type": "turn.started"},
                {"type": "turn.completed"},
            ]
            stream.write_bytes(
                ("\n".join(json.dumps(event) for event in events) + "\n").encode()
            )
            observed = {
                "receipt_path": str(receipt),
                "stream_path": str(stream),
                "platform": "codex",
                "phase": "complete",
                "session_id": "native-fixture-session",
                "session_identity": "single_native_session",
                "readiness": "unobserved",
                "complete": True,
                "cancel_requested": False,
                "cancel_confirmed": False,
                "resume": "unobserved",
                "process_returncode": 0,
                "owned_native_process": True,
                "evidence": [
                    {"offset": 0, "line": 1, "type": "thread.started"},
                    {"offset": 0, "line": 2, "type": "turn.started"},
                    {"offset": 0, "line": 3, "type": "turn.completed"},
                ],
                "malformed_lines": 0,
                "may_authorize": False,
            }
            if variant == "wrong_path":
                observed["receipt_path"] = "/another/launch.json"
            elif variant == "wrong_platform":
                observed["platform"] = "claude"
            elif variant == "escalation":
                observed["may_authorize"] = True
            elif variant == "invalid_owned":
                observed["owned_native_process"] = "true"
            elif variant == "bool_returncode":
                observed["process_returncode"] = False
            elif variant == "transport_status":
                observed["owned_native_process"] = False
            elif variant == "transport":
                observed.update(
                    owned_native_process=False,
                    process_returncode=None,
                    phase="turn_complete",
                    complete=False,
                )
            elif variant == "missing_field":
                observed.pop("complete")
            elif variant == "false_complete":
                events[-1] = {"type": "turn.failed"}
                stream.write_bytes(
                    ("\n".join(json.dumps(event) for event in events) + "\n").encode()
                )
            elif variant == "malformed_stream":
                stream.write_bytes(b"[]\n")
            elif variant == "stale_stream":
                stream.write_bytes(b"")
            observed["stream_sha256"] = hashlib.sha256(stream.read_bytes()).hexdigest()
            if variant == "bad_hash":
                digest = observed["stream_sha256"]
                observed["stream_sha256"] = ("1" if digest[0] == "0" else "0") + digest[1:]
            if variant == "malformed":
                observed = []
            receipt.write_text(json.dumps(observed))
            """
        )
        + "PY\n"
    )


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
    close_guard = (
        "frontmatter_task_id closed_duplicate closed task duplicate has task_id"
        if close_guarded
        else "legacy cc-close"
    )
    _write(path / "scripts" / "cc-claim", f"#!/usr/bin/env bash\n# {guard}\n")
    _write(path / "scripts" / "cc-close", f"#!/usr/bin/env bash\n# {close_guard}\n")
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
    db_path.parent.mkdir(parents=True, exist_ok=True)
    message_id = send_message(
        db_path,
        Envelope(
            sender="test-dispatcher",
            message_type="dispatch",
            priority=0,
            subject=task_id,
            authority_case=authority_case,
            authority_item=task_id,
            recipients_spec=lane,
            payload="durable dispatch binding",
        ),
    )
    return db_path, message_id


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


def _claim_sweep_composition(module, claims, active, monkeypatch):
    from shared.gate0b_claim_publication_install import ClaimPublicationCompositionRoots

    for state in ("active", "closed", "refused"):
        (active.parent / state).mkdir(parents=True, exist_ok=True)
    roots = ClaimPublicationCompositionRoots(
        invocation_store_root=str(claims.parent / "invocations"),
        claim_cache_dir=str(claims),
        claim_vault_root=str(active.parent),
        claim_transaction_root=str(claims.parent / "transactions"),
        claim_receipt_root=str(claims.parent / "receipts"),
        claim_lock_root=str(claims.parent / "non-default-role-locks"),
    )
    monkeypatch.setattr(module, "_claim_sweep_roots", lambda: roots, raising=False)
    monkeypatch.setenv("HAPAX_COORD_DIR", str(claims.parent / "coord"))
    return roots


@pytest.mark.parametrize("session_id", ["session-abcdef01", "9b6ba5ca-513c-41aa-9900-d3026b42aad1"])
def test_claim_sweep_ambiguous_role_cannot_unlink_concurrent_writer(
    tmp_path, monkeypatch, session_id
):
    import shared.sdlc_claim as claim_module
    from shared.session_identity import is_claim_keyable_session_id

    assert is_claim_keyable_session_id(session_id)
    module = _dispatcher_module()
    claims, active = tmp_path / "claims", tmp_path / "tasks" / "active"
    claims.mkdir()
    roots = _claim_sweep_composition(module, claims, active, monkeypatch)
    claim = claims / f"cc-active-task-gamma-{session_id}"
    claim.write_text("old-task\n")
    os.utime(claim, (1000, 1000))
    _task(active.parent, "old-task", "", status="done", assigned_to="gamma")
    monkeypatch.setattr(claim_module, "_CLAIM_PUBLICATION_LOCK_TIMEOUT_SECONDS", 0.02)
    script = (
        "from pathlib import Path\n"
        "from shared.sdlc_claim import claim_role_exclusion\n"
        f"with claim_role_exclusion('gamma', lock_root=Path({roots.claim_lock_root!r})):\n"
        " print('locked', flush=True)\n"
        " input()\n"
        f" Path({str(claim)!r}).write_text('new-task\\n')\n"
        " print('published', flush=True)\n"
    )
    writer = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    unlink = Path.unlink
    raced = []

    def publish_at_last_unlink(path, *args, **kwargs):
        if path == claim:
            writer.stdin.write("\n")
            writer.stdin.flush()
            assert writer.stdout.readline() == "published\n"
            raced.append(True)
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", publish_at_last_unlink)
    try:
        assert writer.stdout.readline() == "locked\n"
        module.sweep_stale_claims(claims, active, now=30000)
        assert claim.exists(), "sweep deleted the participating writer's new claim"
        assert claim.read_text() == "old-task\n"
        assert not raced
    finally:
        stdout, stderr = writer.communicate("" if raced else "\n", timeout=10)
    assert writer.returncode == 0, (stdout, stderr)
    assert claim.read_text() == "new-task\n"


@pytest.mark.parametrize(
    "name",
    [
        "gamma-session-abcdef01",
        "gamma-abcdefgh",
        "cx-claim-rebind",
        "gamma-9b6ba5ca-513c-41aa-9900-d3026b42aad1",
    ],
)
def test_claim_sweep_ambiguous_names_hold_without_binding(tmp_path, monkeypatch, name):
    module = _dispatcher_module()
    claims, active = tmp_path / "claims", tmp_path / "tasks" / "active"
    claims.mkdir()
    _claim_sweep_composition(module, claims, active, monkeypatch)
    claim = claims / f"cc-active-task-{name}"
    claim.write_text("task-a\n")
    os.utime(claim, (1000, 1000))
    _task(active.parent, "task-a", "", status="done", assigned_to=name)
    before = claim.read_bytes(), claim.stat()
    result = module.sweep_stale_claims(claims, active, now=30000)
    assert claim.exists(), "note assignment cannot disambiguate a marker's owning lock"
    assert (claim.read_bytes(), claim.stat()) == before
    assert result.holds[0].reason_code == "claim_sweep_role_ambiguous"


def _sweep_binding(claims: Path, key: str, *, lane: str, session_id: str, task_id: str) -> None:
    from shared.sdlc_task_store import ClaimDispatchBinding, write_claim_dispatch_binding

    write_claim_dispatch_binding(
        claims,
        key,
        ClaimDispatchBinding.create(
            task_id=task_id,
            lane=lane,
            session_id=session_id,
            claim_epoch=1,
            dispatch_message_id=f"dispatch-{task_id}",
            platform="codex",
            mode="headless",
            profile="ultra",
            authority_case="CASE-TEST-001",
            binding_hash="a" * 64,
        ),
    )


_SWEEP_UUID = "9b6ba5ca-513c-41aa-9900-d3026b42aad1"


@pytest.mark.parametrize(
    "name,lane",
    [
        (f"gamma-{_SWEEP_UUID}", "gamma"),
        ("cx-claim-rebind", "cx-claim-rebind"),
        (f"cx-claim-rebind-{_SWEEP_UUID}", "cx-claim-rebind"),
    ],
)
def test_claim_sweep_resolves_marker_role_through_its_exact_dispatch_binding(
    tmp_path, monkeypatch, name, lane
):
    # PR4726 review (Muse, finding 7): every hyphenated or session-keyed marker was held as
    # role_ambiguous forever, so terminal markers accumulated and the sweep always exited 8.
    module = _dispatcher_module()
    claims, active = tmp_path / "claims", tmp_path / "tasks" / "active"
    claims.mkdir()
    _claim_sweep_composition(module, claims, active, monkeypatch)
    claim = claims / f"cc-active-task-{name}"
    claim.write_text("task-a\n")
    os.utime(claim, (1000, 1000))
    _sweep_binding(claims, name, lane=lane, session_id=_SWEEP_UUID, task_id="task-a")
    _task(active.parent, "task-a", "", status="done", assigned_to=lane)
    result = module.sweep_stale_claims(claims, active, now=30000)
    assert result.reaped == [(claim.name, "task-a", "terminal")]
    assert not result.holds
    assert not claim.exists()


@pytest.mark.parametrize(
    "lane,session_id,task_id",
    [
        ("gamma", "0a0a0a0a-0000-4000-8000-000000000000", "task-a"),  # does not reproduce the key
        ("gamma", _SWEEP_UUID, "other-task"),  # binds a different task
    ],
    ids=["key_mismatch", "task_mismatch"],
)
def test_claim_sweep_holds_marker_whose_binding_does_not_prove_it(
    tmp_path, monkeypatch, lane, session_id, task_id
):
    module = _dispatcher_module()
    claims, active = tmp_path / "claims", tmp_path / "tasks" / "active"
    claims.mkdir()
    _claim_sweep_composition(module, claims, active, monkeypatch)
    name = f"gamma-{_SWEEP_UUID}"
    claim = claims / f"cc-active-task-{name}"
    claim.write_text("task-a\n")
    os.utime(claim, (1000, 1000))
    _sweep_binding(claims, name, lane=lane, session_id=session_id, task_id=task_id)
    _task(active.parent, "task-a", "", status="done", assigned_to="gamma")
    before = claim.read_bytes(), claim.stat()
    result = module.sweep_stale_claims(claims, active, now=30000)
    assert (claim.read_bytes(), claim.stat()) == before
    assert not result.reaped
    assert result.holds[0].reason_code in {
        "claim_sweep_role_ambiguous",
        "claim_sweep_role_binding_changed",
    }


def test_claim_sweep_rechecks_the_binding_immediately_before_deleting(tmp_path, monkeypatch):
    # PR4726 round 2 (Muse minor): the binding recheck ran right after the marker read, well
    # before the unlink; a binding swapped in between left the wrong owner's marker deleted.
    import shared.sdlc_task_store as task_store

    module = _dispatcher_module()
    claims, active = tmp_path / "claims", tmp_path / "tasks" / "active"
    claims.mkdir()
    _claim_sweep_composition(module, claims, active, monkeypatch)
    name = f"gamma-{_SWEEP_UUID}"
    claim = claims / f"cc-active-task-{name}"
    claim.write_text("task-a\n")
    os.utime(claim, (1000, 1000))
    _sweep_binding(claims, name, lane="gamma", session_id=_SWEEP_UUID, task_id="task-a")
    _task(active.parent, "task-a", "", status="done", assigned_to="gamma")
    original_build = task_store.build_task_identity_index

    def build_then_swap_binding(*args, **kwargs):
        index = original_build(*args, **kwargs)
        (claims / f"cc-claim-dispatch-{name}.json").unlink()
        _sweep_binding(claims, name, lane="gamma", session_id=_SWEEP_UUID, task_id="other-task")
        return index

    monkeypatch.setattr(task_store, "build_task_identity_index", build_then_swap_binding)
    result = module.sweep_stale_claims(claims, active, now=30000)
    assert claim.exists(), "a marker whose binding changed was deleted"
    assert not result.reaped
    assert result.holds[0].reason_code == "claim_sweep_role_binding_changed"


def test_claim_sweep_never_acts_on_a_stale_cached_index_and_recovers(tmp_path, monkeypatch):
    # PR4726 review (Gemini, finding 8): the index is cached across markers. Revalidation
    # inside the task lock refuses drift; the stale index is then dropped so the next marker
    # rebuilds rather than every later marker holding on it.
    import shared.sdlc_task_store as task_store

    module = _dispatcher_module()
    claims, active = tmp_path / "claims", tmp_path / "tasks" / "active"
    claims.mkdir()
    _claim_sweep_composition(module, claims, active, monkeypatch)
    for role, task in (("alpha", "task-a"), ("beta", "task-b"), ("gamma", "task-c")):
        marker = claims / f"cc-active-task-{role}"
        marker.write_text(f"{task}\n")
        os.utime(marker, (1000, 1000))
        _task(active.parent, task, "", status="done", assigned_to=role)
    reopened = active / "task-b.md"
    original_build = task_store.build_task_identity_index
    builds = 0

    def build_then_reopen(*args, **kwargs):
        nonlocal builds
        builds += 1
        index = original_build(*args, **kwargs)
        if builds == 1:
            # The vault moves after the index is cached: task-b is reopened.
            reopened.write_text(
                reopened.read_text()
                .replace("status: done", "status: claimed")
                .replace("assigned_to: beta", "assigned_to: beta")
            )
        return index

    monkeypatch.setattr(task_store, "build_task_identity_index", build_then_reopen)
    result = module.sweep_stale_claims(claims, active, now=30000)
    assert (claims / "cc-active-task-beta").exists(), "a reopened task's marker was deleted"
    assert [hold.marker for hold in result.holds] == ["cc-active-task-alpha"]
    assert result.holds[0].reason_code == "task_store_frontier_changed_since_index"
    assert builds == 2
    assert result.reaped == [("cc-active-task-gamma", "task-c", "terminal")]


def test_claim_sweep_audit_unavailable_prevents_deletion(tmp_path, monkeypatch):
    module = _dispatcher_module()
    claims, active = tmp_path / "claims", tmp_path / "tasks" / "active"
    claims.mkdir()
    _claim_sweep_composition(module, claims, active, monkeypatch)
    claim = claims / "cc-active-task-gamma"
    claim.write_text("task-a\n")
    os.utime(claim, (1000, 1000))
    _task(active.parent, "task-a", "", status="done", assigned_to="gamma")
    (tmp_path / "coord" / "ledger.db").mkdir(parents=True)
    result = module.sweep_stale_claims(claims, active, now=30000)
    assert claim.exists(), "an unavailable decision witness cannot authorize unlink"
    assert not result.reaped
    assert result.holds[0].reason_code == "claim_sweep_audit_unavailable"


def test_claim_sweep_records_decision_before_unlink_and_outcome(tmp_path, monkeypatch):
    module = _dispatcher_module()
    claims, active = tmp_path / "claims", tmp_path / "tasks" / "active"
    claims.mkdir()
    roots = _claim_sweep_composition(module, claims, active, monkeypatch)
    claim = claims / "cc-active-task-gamma"
    claim.write_text("task-a\n")
    os.utime(claim, (1000, 1000))
    before = claim.stat()
    _task(active.parent, "task-a", "", status="done", assigned_to="gamma")
    unlink = Path.unlink

    def inspect_before_unlink(path, *args, **kwargs):
        if path == claim:
            events = module.coord_event_log_from_env().replay(fail_open=True).events
            assert len(events) == 1, "unlink must have a recorded decision"
            event = events[0]
            assert event.event_type == "claim_sweep.delete_decided"
            assert event.subject == "task-a"
            assert event.payload["marker"]["inode"] == before.st_ino
            assert event.payload["marker"]["sha256"] == hashlib.sha256(b"task-a\n").hexdigest()
            assert event.payload["installed_roots"]["claim_lock_root"] == roots.claim_lock_root
            assert event.payload["outcome"] == "pending"
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", inspect_before_unlink)
    result = module.sweep_stale_claims(claims, active, now=30000)
    assert result.reaped == [(claim.name, "task-a", "terminal")]
    events = module.coord_event_log_from_env().replay().events
    assert [e.event_type for e in events] == ["claim_sweep.delete_decided", "claim_sweep.deleted"]
    assert events[1].payload["decision_event_id"] == events[0].event_id
    assert events[1].payload["outcome"] == "deleted"


@pytest.mark.parametrize("status", ["claimed", "in_progress", "pr_open", "offered", "blocked"])
def test_claim_sweep_age_never_proves_attempt_death(tmp_path, monkeypatch, status):
    module = _dispatcher_module()
    claims = tmp_path / "claims"
    active = tmp_path / "tasks" / "active"
    claims.mkdir()
    _claim_sweep_composition(module, claims, active, monkeypatch)
    _task(
        active.parent,
        "long-running-task",
        status=status,
        assigned_to="gamma",
        frontmatter="pr: 4726\npr_repo: hapax-systems/hapax-council",
    )
    paths = [
        claims / ("cc-active-task-gamma" + suffix)
        for suffix in ("", "-9b6ba5ca-513c-41aa-9900-d3026b42aad1")
    ]
    for path in paths:
        path.write_text("long-running-task\n")
        os.utime(path, (1000, 1000))
    before = [(p.read_bytes(), p.stat()) for p in paths]

    assert module.sweep_stale_claims(claims, active, now=1000 + 21601).reaped == []
    assert [(p.read_bytes(), p.stat()) for p in paths] == before


@pytest.mark.parametrize(
    "variant", ["missing", "empty", "wrong-id", "duplicate", "malformed", "symlink"]
)
def test_claim_sweep_uncertain_terminal_state_holds(tmp_path, monkeypatch, variant):
    module = _dispatcher_module()
    claims = tmp_path / "claims"
    active = tmp_path / "tasks" / "active"
    claims.mkdir()
    _claim_sweep_composition(module, claims, active, monkeypatch)
    claim = claims / "cc-active-task-gamma"
    claim.write_text("" if variant == "empty" else "task-a\n")
    os.utime(claim, (1000, 1000))
    note = _task(active.parent, "task-a", "", status="done", assigned_to="gamma")
    if variant in {"missing", "empty"}:
        note.unlink()
    elif variant == "wrong-id":
        note.write_text(note.read_text().replace("task_id: task-a", "task_id: other"))
    elif variant == "duplicate":
        (active.parent / "closed" / note.name).write_bytes(note.read_bytes())
    elif variant == "malformed":
        note.write_text("---\nstatus: done\nassigned_to: [\n---\n")
    elif variant == "symlink":
        target = tmp_path / "terminal.md"
        note.rename(target)
        note.symlink_to(target)
    before = claim.read_bytes(), claim.stat()

    assert module.sweep_stale_claims(claims, active, now=1000 + 21601).reaped == []
    assert (claim.read_bytes(), claim.stat()) == before


@pytest.mark.parametrize("state", ["active", "closed"])
def test_claim_sweep_retains_terminal_cleanup(tmp_path, monkeypatch, state):
    module = _dispatcher_module()
    claims = tmp_path / "claims"
    active = tmp_path / "tasks" / "active"
    claims.mkdir()
    _claim_sweep_composition(module, claims, active, monkeypatch)
    claim = claims / "cc-active-task-gamma"
    claim.write_text("task-a\n")
    os.utime(claim, (1000, 1000))
    note = _task(active.parent, "task-a", "", status="done", assigned_to="gamma")
    if state == "closed":
        note.rename(active.parent / "closed" / note.name)

    assert module.sweep_stale_claims(claims, active, now=1300).reaped == []
    assert claim.exists()
    assert module.sweep_stale_claims(claims, active, now=1301).reaped == [
        (claim.name, "task-a", "terminal")
    ]
    assert not claim.exists()


@pytest.mark.parametrize("variant", ["missing", "corrupt", "wrong-cache", "wrong-vault"])
def test_claim_sweep_unqualified_composition_holds(tmp_path, monkeypatch, variant):
    from shared.execution_admission import ExecutionAdmissionError

    module = _dispatcher_module()
    claims = tmp_path / "claims"
    active = tmp_path / "tasks" / "active"
    claims.mkdir()
    roots = _claim_sweep_composition(module, claims, active, monkeypatch)
    claim = claims / "cc-active-task-gamma"
    claim.write_text("task-a\n")
    os.utime(claim, (1000, 1000))
    _task(active.parent, "task-a", "", status="done", assigned_to="gamma")

    def invalid_roots():
        if variant == "missing":
            raise ExecutionAdmissionError("gate0b_install_receipt_missing", "restore composition")
        if variant == "corrupt":
            raise ValueError("invalid composition")
        key = "claim_cache_dir" if variant == "wrong-cache" else "claim_vault_root"
        return roots.model_copy(update={key: str(tmp_path / "other")})

    monkeypatch.setattr(module, "_claim_sweep_roots", invalid_roots)
    assert module.sweep_stale_claims(claims, active, now=30000).reaped == []
    assert claim.read_text() == "task-a\n"


@pytest.mark.parametrize("lock_kind", ["role", "note"])
def test_claim_sweep_respects_installed_exclusion_across_processes(
    tmp_path, monkeypatch, lock_kind
):
    import shared.sdlc_claim as claim_module

    module = _dispatcher_module()
    claims = tmp_path / "claims"
    active = tmp_path / "tasks" / "active"
    claims.mkdir()
    roots = _claim_sweep_composition(module, claims, active, monkeypatch)
    claim = claims / "cc-active-task-gamma"
    claim.write_text("task-a\n")
    os.utime(claim, (1000, 1000))
    note = _task(active.parent, "task-a", "", status="done", assigned_to="gamma")
    monkeypatch.setattr(claim_module, "_CLAIM_PUBLICATION_LOCK_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setenv("HAPAX_TASK_NOTE_LOCK_TIMEOUT", "0.02")
    script = (
        "from pathlib import Path\n"
        "from shared.sdlc_claim import claim_role_exclusion\n"
        "from shared.task_note_lock import projected_path_lock\n"
        f"lock = claim_role_exclusion('gamma', lock_root=Path({roots.claim_lock_root!r}))\n"
        if lock_kind == "role"
        else "from pathlib import Path\n"
        "from shared.task_note_lock import projected_path_lock\n"
        f"lock = projected_path_lock('task-a', (Path({str(note)!r}),))\n"
    ) + "with lock:\n print('locked', flush=True)\n input()\n"
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline() == "locked\n"
        assert module.sweep_stale_claims(claims, active, now=30000).reaped == []
        assert claim.read_text() == "task-a\n"
    finally:
        stdout, stderr = process.communicate("\n", timeout=10)
    assert process.returncode == 0, (stdout, stderr)
    assert module.sweep_stale_claims(claims, active, now=30000).reaped == [
        (claim.name, "task-a", "terminal")
    ]


@pytest.mark.parametrize("change", ["replacement", "refresh"])
@pytest.mark.parametrize("consumer", ["direct", "cli"])
def test_claim_sweep_preserves_marker_changed_during_resolution(
    tmp_path, monkeypatch, capsys, change, consumer
):
    module = _dispatcher_module()
    claims = tmp_path / "claims"
    active = tmp_path / "tasks" / "active"
    claims.mkdir()
    _claim_sweep_composition(module, claims, active, monkeypatch)
    claim = claims / "cc-active-task-gamma"
    claim.write_text("task-a\n")
    os.utime(claim, (1000, 1000))
    _task(active.parent, "task-a", "", status="done", assigned_to="gamma")
    classify = module._claim_task_dead_reason
    changed_stats = []

    def replace_marker(fields):
        if change == "replacement":
            claim.write_text("new-task\n")
        else:
            os.utime(claim, (1001, 1001))
        changed_stats.append(claim.lstat())
        return classify(fields)

    monkeypatch.setattr(module, "_claim_task_dead_reason", replace_marker)
    if consumer == "direct":
        result = module.sweep_stale_claims(claims, active, now=30000)
        assert result.reaped == []
        report = module.asdict(result)
    else:
        monkeypatch.setenv("HAPAX_CC_CLAIMS_DIR", str(claims))
        monkeypatch.setenv("HAPAX_CC_TASK_ROOT", str(active.parent))
        assert module.main(["--sweep-stale-claims"]) == 8
        captured = capsys.readouterr()
        assert "held 1" in captured.out
        report = json.loads(captured.err)["claim_sweep"]
        assert report["reaped"] == []
    assert changed_stats
    assert claim.lstat() == changed_stats[0]
    assert claim.read_text() == ("new-task\n" if change == "replacement" else "task-a\n")
    assert report["held_count"] == 1
    assert report["holds"][0]["marker"] == claim.name
    assert report["holds"][0]["reason_code"] == "claim_sweep_marker_changed"
    assert "reobserve" in report["holds"][0]["repair_action"]
    assert module.coord_event_log_from_env().replay().events == ()


@pytest.mark.parametrize("kind", ["symlink", "directory", "fifo", "hardlink"])
def test_claim_sweep_reports_unsafe_marker_type(tmp_path, monkeypatch, kind):
    module = _dispatcher_module()
    claims, active = tmp_path / "claims", tmp_path / "tasks" / "active"
    claims.mkdir()
    _claim_sweep_composition(module, claims, active, monkeypatch)
    claim = claims / "cc-active-task-gamma"
    target = tmp_path / "target"
    target.write_text("task-a\n")
    if kind == "symlink":
        claim.symlink_to(target)
    elif kind == "directory":
        claim.mkdir()
    elif kind == "fifo":
        os.mkfifo(claim)
    else:
        claim.hardlink_to(target)
    before = claim.lstat()

    result = module.sweep_stale_claims(claims, active, now=30000)

    assert claim.lstat() == before
    assert target.read_text() == "task-a\n"
    assert result.reaped == []
    assert result.held_count == 1
    assert result.holds[0].marker == claim.name
    assert result.holds[0].reason_code == (
        "claim_sweep_marker_linked" if kind == "hardlink" else "claim_sweep_marker_not_regular"
    )
    assert result.holds[0].repair_action
    assert module.coord_event_log_from_env().replay().events == ()


def test_claim_sweep_loads_installed_roots(tmp_path, monkeypatch):
    import shared.gate0b_claim_publication_install as install

    module = _dispatcher_module()
    locator = str(tmp_path / "invocations")
    installed = SimpleNamespace(claim_lock_root=tmp_path / "installed-locks")
    monkeypatch.setattr(
        install,
        "default_claim_publication_roots",
        lambda **kw: SimpleNamespace(invocation_store_root=locator),
    )
    observed = []

    def load(path):
        observed.append(path)
        return SimpleNamespace(receipt=SimpleNamespace(roots=installed))

    monkeypatch.setattr(install, "load_claim_publication_composition", load)
    assert module._claim_sweep_roots() is installed
    assert observed == [Path(locator)]


def test_claim_sweep_holds_both_locks_at_unlink(tmp_path, monkeypatch):
    import fcntl

    from shared.sdlc_claim import _claim_publication_role_lock_digest
    from shared.task_note_lock import held_by_current_thread

    module = _dispatcher_module()
    claims = tmp_path / "claims"
    active = tmp_path / "tasks" / "active"
    claims.mkdir()
    roots = _claim_sweep_composition(module, claims, active, monkeypatch)
    claim = claims / "cc-active-task-gamma"
    claim.write_text("task-a\n")
    os.utime(claim, (1000, 1000))
    _task(active.parent, "task-a", "", status="done", assigned_to="gamma")
    lock_path = Path(roots.claim_lock_root) / f"{_claim_publication_role_lock_digest('gamma')}.lock"
    unlink = Path.unlink
    observations = []

    def observe_unlink(path, *args, **kwargs):
        if path == claim:
            assert held_by_current_thread()
            with lock_path.open("r+") as handle:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            observations.append(path)
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", observe_unlink)
    assert module.sweep_stale_claims(claims, active, now=30000).reaped == [
        (claim.name, "task-a", "terminal")
    ]
    assert observations == [claim]


def test_claim_sweep_reaps_blocked_unassigned_legacy_claim(tmp_path: Path, monkeypatch) -> None:
    module = _dispatcher_module()
    claims = tmp_path / "claims"
    active = tmp_path / "tasks" / "active"
    claims.mkdir(parents=True)
    active.mkdir(parents=True)
    _claim_sweep_composition(module, claims, active, monkeypatch)
    task_id = "p0-incident-blocked-task"
    claim = claims / "cc-active-task-gamma"
    claim.write_text(f"{task_id}\n", encoding="utf-8")
    (active / f"{task_id}.md").write_text(
        f"---\ntask_id: {task_id}\nstatus: blocked\nassigned_to: unassigned\n---\n",
        encoding="utf-8",
    )
    old = 1000.0
    os.utime(claim, (old, old))

    reaped = module.sweep_stale_claims(claims, active, now=old + 301, grace_secs=300).reaped

    assert reaped == [(claim.name, task_id, "blocked-unassigned")]
    assert not claim.exists()


def test_claim_sweep_ignores_body_status_lines(tmp_path: Path, monkeypatch) -> None:
    module = _dispatcher_module()
    claims = tmp_path / "claims"
    active = tmp_path / "tasks" / "active"
    claims.mkdir(parents=True)
    active.mkdir(parents=True)
    _claim_sweep_composition(module, claims, active, monkeypatch)
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

    reaped = module.sweep_stale_claims(claims, active, now=old + 301, grace_secs=300).reaped

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
        def launch(self, *, decision, request, launch_callable, collect_result_ref=None):
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

    class SpyCodexAdapter(module.CodexAdapter):
        def launch(self, *, decision, request, launch_callable, collect_result_ref=None):
            launch_calls.append((decision.action.value, request.platform))
            return super().launch(
                decision=decision,
                request=request,
                launch_callable=launch_callable,
                collect_result_ref=collect_result_ref,
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
    monkeypatch.setattr(module, "_await_sdlc_admission", lambda args: None)

    rc = module.main(list(args))

    assert rc == 0
    assert launch_calls == [("launch", "codex")]
    assert launcher_args.exists()
    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["route_policy_action"] == "launch"
    assert receipt["launched"] is True


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
    assert states == [("offered",)]


@pytest.mark.parametrize(
    "native_observation",
    [
        "matching",
        "transport",
        "wrong_path",
        "malformed",
        "missing",
        "wrong_platform",
        "escalation",
        "invalid_owned",
        "bool_returncode",
        "transport_status",
        "missing_field",
        "false_complete",
        "malformed_stream",
        "stale_stream",
        "bad_hash",
    ],
)
def test_launches_codex_headless_through_codex_launcher(tmp_path: Path, native_observation) -> None:
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
{_native_lifecycle_writer(native_observation)}
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
    assert recorded.startswith(
        "--execution-route\ncodex.headless.full\n--task\ngoverned-build\n--force\ncx-green\n"
    )
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
    expected_phase = {
        "matching": "complete",
        "transport": "turn_complete",
    }.get(native_observation, "unobserved")
    assert receipt["native_lifecycle"]["phase"] == expected_phase
    assert receipt["native_lifecycle"]["may_authorize"] is False
    assert receipt["native_lifecycle"]["complete"] is (native_observation == "matching")
    if expected_phase == "unobserved":
        assert receipt["result_ref"] is None
        assert receipt["native_lifecycle"]["reason"]
    else:
        result_ref = receipt["result_ref"]
        assert (
            result_ref["sha256"] == hashlib.sha256(Path(result_ref["ref"]).read_bytes()).hexdigest()
        )
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
        "model=claude-opus-4-8",
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
    assert row["state"] == "offered"
    assert row["reason"] is None

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
    assert row["state"] == "offered"
    assert row["reason"] is None
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
    assert row["state"] == "offered"
    assert row["reason"] is None
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
    assert codex_args[0:4] == [
        "--execution-route",
        "codex.headless.full",
        "--task",
        "governed-build",
    ]
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
    assert recorded.startswith(
        f"--execution-route\ncodex.headless.full\n--task\n{task_id}\n--force\ncx-p0\n"
    )


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
        "--execution-route\ncodex.headless.full\n--task\np0-incident-sdlc-task-stalled-test\n--force\n--no-claim\ncx-p0\n"
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
    assert recorded.startswith(
        f"--execution-route\ncodex.headless.full\n--task\n{task_id}\n--force\n--no-claim\ncx-fugu\n"
    )
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


def test_governed_codex_dispatch_reactivates_clean_retired_relay(tmp_path: Path) -> None:
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

    assert result.returncode == 0, result.stderr
    assert "retired/wound-down" not in result.stderr
    assert codex_args.exists()


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


@pytest.mark.parametrize(
    "replay_evidence", ["valid", "receipt_tampered", "stream_tampered", "missing", "legacy"]
)
def test_launch_idempotency_replays_without_second_launcher_call(
    tmp_path: Path, replay_evidence: str
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
{_native_lifecycle_writer("missing" if replay_evidence == "legacy" else "matching")}
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
    ledger = tmp_path / "ledger" / "methodology-dispatch.jsonl"
    first_receipt = json.loads(ledger.read_text().splitlines()[-1])
    original_ref = first_receipt["result_ref"]
    original_native_paths = set((tmp_path / "ledger").glob("native-lifecycle-*.json"))
    if replay_evidence == "legacy":
        assert original_ref is None
        assert first_receipt["native_lifecycle"]["phase"] == "unobserved"
    else:
        assert original_ref is not None
        original_path = Path(original_ref["ref"])
        original_bytes = original_path.read_bytes()
        assert original_ref["sha256"] == hashlib.sha256(original_bytes).hexdigest()
        assert first_receipt["native_lifecycle"]["phase"] == "complete"
        original_observation = json.loads(original_bytes)
        if replay_evidence == "receipt_tampered":
            # Same JSON value, different exact bytes.
            original_path.write_bytes(original_bytes + b"\n")
        elif replay_evidence == "stream_tampered":
            stream = Path(original_observation["stream_path"])
            # Same lifecycle events, different exact bytes.
            stream.write_bytes(stream.read_bytes() + b"\n")
        elif replay_evidence == "missing":
            original_path.unlink()
            original_native_paths.remove(original_path)
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
    assert receipt["coord_dispatch_cleanup_state"] == "processed"
    assert receipt["launch_returncode"] == 0
    assert receipt["launched"] is True
    assert receipt["result_ref"] == original_ref
    assert receipt["native_lifecycle"]["may_authorize"] is False
    assert set((tmp_path / "ledger").glob("native-lifecycle-*.json")) == original_native_paths
    if replay_evidence == "valid":
        assert receipt["native_lifecycle"] == first_receipt["native_lifecycle"]
    else:
        assert receipt["native_lifecycle"]["phase"] == "unobserved"
        assert receipt["native_lifecycle"]["complete"] is False
        assert (
            receipt["native_lifecycle"]["reason"]
            == {
                "receipt_tampered": "native_receipt_hash_mismatch",
                "stream_tampered": "native_stream_hash_mismatch",
                "missing": "native_receipt_unavailable",
                "legacy": "native_receipt_reference_unavailable",
            }[replay_evidence]
        )
    with sqlite3.connect(tmp_path / "relay" / "messages.db") as conn:
        assert conn.execute("SELECT state FROM recipients").fetchall() == [("processed",)]
    events = [
        json.loads(line) for line in (tmp_path / "coord" / "ledger.jsonl").read_text().splitlines()
    ]
    terminal = [
        event for event in events if event["event_type"] == "coord_dispatch.launch_succeeded"
    ]
    assert len(terminal) == 1
    assert terminal[0]["payload"]["result_ref"] == original_ref


@pytest.mark.parametrize("returncode", [0, 42])
@pytest.mark.parametrize("collection_failure", ["raises", "invalid", "invalid_path"])
def test_result_reference_failure_preserves_mq_terminal_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    collection_failure: str,
) -> None:
    from shared.coord_dispatch import run_atomic_dispatch_launch

    module = _dispatcher_module()
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
    mq_db, message_id = _maybe_write_durable_mq_binding(
        tmp_path, ("--task", "governed-build", "--lane", "cx-green")
    )
    assert message_id is not None
    monkeypatch.setenv("HAPAX_RELAY_DIR", str(tmp_path / "relay"))
    event_log = module.CoordEventLog(
        db_path=tmp_path / "coord" / "ledger.db",
        jsonl_path=tmp_path / "coord" / "ledger.jsonl",
        spool_dir=tmp_path / "coord" / "spool",
    )
    request = module.DispatchLaunchRequest(
        task_id="governed-build",
        lane="cx-green",
        platform="codex",
        mode="headless",
        profile="full",
        authority_case="CASE-TEST-001",
        parent_spec=str(spec),
        message_id=message_id,
        mq_db_path=mq_db,
        event_log=event_log,
    )
    calls = []

    def launch():
        calls.append("launch")
        return returncode

    def collect():
        assert calls == ["launch"]
        calls.append("collect")
        if collection_failure == "raises":
            raise OSError("receipt collection failed after native launch")
        if collection_failure == "invalid_path":
            return {"ref": "receipt\0.json", "sha256": "a" * 64}
        return {"ref": "invalid", "sha256": "invalid"}

    first = run_atomic_dispatch_launch(request, launch, collect_result_ref=collect)
    expected_state = "processed" if returncode == 0 else "deferred"
    assert first.launch_returncode == returncode
    assert first.launched is (returncode == 0)
    assert (first.result_ref is not None) is (collection_failure == "invalid_path")
    assert first.cleanup_state == expected_state
    assert _recipient_row(mq_db, message_id, "cx-green")["state"] == expected_state

    def forbidden():
        pytest.fail("terminal replay invoked launch or receipt collection")

    replay = run_atomic_dispatch_launch(request, forbidden, collect_result_ref=forbidden)
    assert calls == ["launch", "collect"]
    assert replay.replayed is True
    assert replay.launch_returncode == returncode
    assert replay.launched == first.launched
    assert replay.result_ref == first.result_ref
    assert replay.cleanup_state == expected_state
    if collection_failure == "invalid_path":
        # Exercise the actual receipt reader at the replay boundary. Invalid
        # filesystem syntax is unobserved evidence, not a new launch outcome.
        observed, reference = module.read_native_lifecycle_receipt(
            Path(replay.result_ref.ref), platform="codex", result_ref=replay.result_ref
        )
        assert reference is None
        assert observed["phase"] == "unobserved" and not observed["complete"]
        assert replay.launch_returncode == returncode
    terminal = [
        event
        for event in event_log.replay().events
        if event.event_type
        in {
            "coord_dispatch.launch_succeeded",
            "coord_dispatch.launch_failed",
        }
    ]
    assert len(terminal) == 1
    assert terminal[0].payload["returncode"] == returncode
    assert terminal[0].payload["result_ref"] == (
        first.result_ref.model_dump() if first.result_ref is not None else None
    )


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
    secret_stub = bin_dir / "hapax-secret"
    secret_stub.write_text(
        """#!/usr/bin/env bash
if [ "$1" = "glmcp/api-key" ]; then
  printf '%s\n' 'test-secret-token'
  exit 0
fi
exit 1
""",
        encoding="utf-8",
    )
    secret_stub.chmod(0o755)
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
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "REINS_SECRET_STORE": str(tmp_path / "empty-secrets"),
        },
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
    assert "model=glm-5.3" in receipt["cli"]["version"]
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
        "--",
        "--model",
        "claude-opus-4-8",
        "--effort",
        "max",
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
    assert "--force" in args


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


@pytest.mark.parametrize("status", ["offered", "claimed", "in_progress"])
def test_codex_dispatch_scrubs_fresh_session_and_preserves_continuation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    module = _dispatcher_module()
    parent_session = "2836fb1e-6ec7-4b6c-997e-9db553e7a092"
    monkeypatch.setenv("HAPAX_SESSION_ID", parent_session)
    output = tmp_path / "launches.jsonl"
    launcher = tmp_path / "launcher"
    launcher.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys, uuid\n"
        f"with open({str(output)!r}, 'a') as stream:\n"
        "    stream.write(json.dumps({'inherited':os.environ.get('HAPAX_SESSION_ID'), "
        "'session':os.environ.get('HAPAX_SESSION_ID') or str(uuid.uuid4()), "
        "'args':sys.argv[1:]})+'\\n')\n"
    )
    launcher.chmod(0o755)
    monkeypatch.setenv("HAPAX_METHODOLOGY_CODEX_HEADLESS", str(launcher))
    validation = SimpleNamespace(task=SimpleNamespace(fields={"status": status}))
    route = module.PLATFORM_PATHS[("codex", "headless", "full")]
    for lane in ("cx-first", "cx-second"):
        result = module.launch_codex_headless("new-task", lane, "prompt", validation, route)
        assert result == 0
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(records) == 2
    if status == "offered":
        assert all(item["inherited"] is None for item in records)
        assert records[0]["session"] != records[1]["session"]
        assert all(item["session"] != parent_session for item in records)
        assert all("--no-claim" not in item["args"] for item in records)
    else:
        assert all(item["inherited"] == parent_session for item in records)
        assert all(item["session"] == parent_session for item in records)
        assert all("--no-claim" in item["args"] for item in records)


@pytest.mark.parametrize("boundary", ["composition", "role-lock", "task-store"])
def test_claim_sweep_failures_return_typed_repair(tmp_path, monkeypatch, boundary):
    import shared.sdlc_claim as claim_module
    import shared.sdlc_task_store as task_store
    from shared.execution_admission import ExecutionAdmissionError

    module = _dispatcher_module()
    claims, active = tmp_path / "claims", tmp_path / "tasks" / "active"
    claims.mkdir()
    _claim_sweep_composition(module, claims, active, monkeypatch)
    claim = claims / "cc-active-task-gamma"
    claim.write_text("task-a\n")
    os.utime(claim, (1000, 1000))
    _task(active.parent, "task-a", "", status="done", assigned_to="gamma")
    target, name, error = {
        "composition": (
            module,
            "_claim_sweep_roots",
            ExecutionAdmissionError("install-broken", "restore installed composition"),
        ),
        "role-lock": (
            claim_module,
            "claim_role_exclusion",
            claim_module.ClaimPublicationError(
                "lock-broken", "restore installed role lock", "fixture"
            ),
        ),
        "task-store": (
            task_store,
            "build_task_identity_index",
            task_store.TaskStoreError("index-broken", "reconcile task inventory", "fixture"),
        ),
    }[boundary]

    def refuse(*args, **kwargs):
        raise error

    monkeypatch.setattr(target, name, refuse)
    result = module.sweep_stale_claims(claims, active, now=30000)
    assert claim.exists()
    assert result.held_count == 1
    assert result.holds[0].reason_code == error.reason_code
    assert result.holds[0].repair_action == error.repair_action
    assert not result.reaped


def test_claim_sweep_outcome_write_failure_keeps_pending_decision(tmp_path, monkeypatch):
    from shared.coord_event_log import CoordEventLog, CoordEventLogError

    module = _dispatcher_module()
    claims, active = tmp_path / "claims", tmp_path / "tasks" / "active"
    claims.mkdir()
    _claim_sweep_composition(module, claims, active, monkeypatch)
    claim = claims / "cc-active-task-gamma"
    claim.write_text("task-a\n")
    os.utime(claim, (1000, 1000))
    _task(active.parent, "task-a", "", status="done", assigned_to="gamma")
    append = CoordEventLog.append

    def fail_outcome(self, event, **kwargs):
        if event.event_type == "claim_sweep.deleted":
            raise CoordEventLogError("fixture outage after unlink")
        return append(self, event, **kwargs)

    monkeypatch.setattr(CoordEventLog, "append", fail_outcome)
    result = module.sweep_stale_claims(claims, active, now=30000)
    assert not claim.exists()
    assert result.reaped == [(claim.name, "task-a", "terminal")]
    assert result.holds[0].reason_code == "claim_sweep_outcome_unrecorded"
    events = module.coord_event_log_from_env().replay().events
    assert len(events) == 1 and events[0].payload["outcome"] == "pending"


@pytest.mark.parametrize("count", [0, 25])
def test_claim_sweep_cli_reports_bounded_holds(tmp_path, monkeypatch, capsys, count):
    module = _dispatcher_module()
    claims, active = tmp_path / "claims", tmp_path / "tasks" / "active"
    claims.mkdir()
    _claim_sweep_composition(module, claims, active, monkeypatch)
    monkeypatch.setenv("HAPAX_CC_CLAIMS_DIR", str(claims))
    monkeypatch.setenv("HAPAX_CC_TASK_ROOT", str(active.parent))
    for index in range(count):
        (claims / f"cc-active-task-gamma-session-abcdef{index:02d}").write_text("task-a\n")
    assert module.main(["--sweep-stale-claims"]) == (8 if count else 0)
    captured = capsys.readouterr()
    assert f"held {count}" in captured.out
    if count:
        report = json.loads(captured.err)["claim_sweep"]
        assert report["held_count"] == count
        assert len(report["holds"]) == 20
        assert all(h["reason_code"] and h["repair_action"] for h in report["holds"])
    else:
        assert not captured.err


def test_claim_sweep_unlink_failure_preserves_pending_witness(tmp_path, monkeypatch):
    module = _dispatcher_module()
    claims, active = tmp_path / "claims", tmp_path / "tasks" / "active"
    claims.mkdir()
    _claim_sweep_composition(module, claims, active, monkeypatch)
    claim = claims / "cc-active-task-gamma"
    claim.write_text("task-a\n")
    os.utime(claim, (1000, 1000))
    _task(active.parent, "task-a", "", status="done", assigned_to="gamma")
    unlink = Path.unlink

    def fail_unlink(path, *args, **kwargs):
        if path == claim:
            raise PermissionError("fixture unlink refusal")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    result = module.sweep_stale_claims(claims, active, now=30000)
    assert claim.exists()
    assert not result.reaped
    assert result.held_count == 1
    assert result.holds[0].marker == claim.name
    assert result.holds[0].reason_code == "claim_sweep_unlink_failed"
    events = module.coord_event_log_from_env().replay().events
    assert len(events) == 1 and events[0].payload["outcome"] == "pending"
    assert events[0].event_type == "claim_sweep.delete_decided"
    assert events[0].event_id in result.holds[0].repair_action
    assert "failed unlink" in result.holds[0].repair_action

    # Removing the transient filesystem failure is not reconciliation. A fresh
    # sweep must preserve the same pending decision and all remaining bytes.
    monkeypatch.setattr(Path, "unlink", unlink)
    retry = module.sweep_stale_claims(claims, active, now=30001)
    assert claim.read_text() == "task-a\n"
    assert not retry.reaped
    assert retry.holds[0].reason_code == "claim_sweep_decision_pending"
    assert events[0].event_id in retry.holds[0].repair_action
    assert module.coord_event_log_from_env().replay().events == events


def test_claim_sweep_ignores_only_read_access_time(tmp_path, monkeypatch):
    module = _dispatcher_module()
    claims, active = tmp_path / "claims", tmp_path / "tasks" / "active"
    claims.mkdir()
    _claim_sweep_composition(module, claims, active, monkeypatch)
    claim = claims / "cc-active-task-gamma"
    claim.write_text("task-a\n")
    os.utime(claim, (1000, 1000))
    _task(active.parent, "task-a", "", status="done", assigned_to="gamma")
    lstat = Path.lstat
    calls = 0

    def observed_access(path, *args, **kwargs):
        nonlocal calls
        original = lstat(path, *args, **kwargs)
        if path != claim:
            return original
        calls += 1
        # Model relatime without os.utime(), which also changes ctime.
        from types import SimpleNamespace

        fields = {name: getattr(original, name) for name in dir(original) if name.startswith("st_")}
        fields.update(st_atime=1000 + calls, st_atime_ns=(1000 + calls) * 10**9)
        return SimpleNamespace(**fields)

    monkeypatch.setattr(Path, "lstat", observed_access)
    result = module.sweep_stale_claims(claims, active, now=30000)
    assert not result.holds
    assert result.reaped == [(claim.name, "task-a", "terminal")]
    assert not claim.exists()


def test_claim_sweep_unreadable_decision_history_holds(tmp_path, monkeypatch):
    from shared.coord_event_log import CoordEventLog, CoordEventLogError

    module = _dispatcher_module()
    claims, active = tmp_path / "claims", tmp_path / "tasks" / "active"
    claims.mkdir()
    _claim_sweep_composition(module, claims, active, monkeypatch)
    claim = claims / "cc-active-task-gamma"
    claim.write_text("task-a\n")
    os.utime(claim, (1000, 1000))
    _task(active.parent, "task-a", "", status="done", assigned_to="gamma")

    def unreadable(*args, **kwargs):
        raise CoordEventLogError("fixture history unreadable")

    monkeypatch.setattr(CoordEventLog, "replay", unreadable)
    result = module.sweep_stale_claims(claims, active, now=30000)
    assert claim.read_text() == "task-a\n"
    assert not result.reaped
    assert result.holds[0].reason_code == "claim_sweep_audit_unavailable"


def test_claim_sweep_completed_decision_allows_later_terminal_marker(tmp_path, monkeypatch):
    module = _dispatcher_module()
    claims, active = tmp_path / "claims", tmp_path / "tasks" / "active"
    claims.mkdir()
    _claim_sweep_composition(module, claims, active, monkeypatch)
    claim = claims / "cc-active-task-gamma"
    for task_id in ("task-a", "task-b"):
        claim.write_text(task_id + "\n")
        os.utime(claim, (1000, 1000))
        _task(active.parent, task_id, "", status="done", assigned_to="gamma")
        result = module.sweep_stale_claims(claims, active, now=30000)
        assert result.reaped == [(claim.name, task_id, "terminal")]
        assert not result.holds
    events = module.coord_event_log_from_env().replay().events
    assert [e.event_type for e in events] == [
        "claim_sweep.delete_decided",
        "claim_sweep.deleted",
        "claim_sweep.delete_decided",
        "claim_sweep.deleted",
    ]


def test_claim_sweep_missing_database_with_surviving_history_holds(tmp_path, monkeypatch):
    module = _dispatcher_module()
    claims, active = tmp_path / "claims", tmp_path / "tasks" / "active"
    claims.mkdir()
    _claim_sweep_composition(module, claims, active, monkeypatch)
    claim = claims / "cc-active-task-gamma"
    claim.write_text("task-a\n")
    os.utime(claim, (1000, 1000))
    _task(active.parent, "task-a", "", status="done", assigned_to="gamma")
    unlink = Path.unlink

    def refused(path, *args, **kwargs):
        if path == claim:
            raise PermissionError("fixture pending decision")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", refused)
    assert module.sweep_stale_claims(claims, active, now=30000).holds
    monkeypatch.setattr(Path, "unlink", unlink)
    log = module.coord_event_log_from_env()
    assert log.jsonl_path.is_file()
    log.db_path.rename(log.db_path.with_suffix(".preserved"))
    result = module.sweep_stale_claims(claims, active, now=30001)
    assert claim.exists()
    assert not result.reaped
    assert result.holds[0].reason_code == "claim_sweep_audit_unavailable"
    assert not log.db_path.exists()
