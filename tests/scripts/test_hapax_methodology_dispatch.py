import importlib.machinery
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import textwrap
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

from shared.relay_mq import send_message
from shared.relay_mq_envelope import Envelope

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-methodology-dispatch"
RECEIPT_SCRIPT = REPO_ROOT / "scripts" / "hapax-platform-capability-receipts"
REGISTRY = REPO_ROOT / "config" / "platform-capability-registry.json"


def _dispatcher_module() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("hapax_methodology_dispatch", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[loader.name] = module
    spec.loader.exec_module(module)
    return module


def _fresh_registry(tmp_path: Path) -> Path:
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    checked_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for route in payload["routes"]:
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
                "evidence_refs": [f"test:{route['route_id']}:quota"],
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
        for score in route["capability_scores"].values():
            score["observed_at"] = checked_at
        for tool in route["tool_state"]:
            tool["observed_at"] = checked_at
    path = tmp_path / "fixtures" / "fresh-platform-capability-registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _fake_binary(bin_dir: Path, name: str, output: str) -> None:
    target = bin_dir / name
    target.write_text(f"#!/bin/sh\nprintf '%s\\n' '{output}'\n", encoding="utf-8")
    target.chmod(0o755)


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


def test_claim_sweep_reaps_blocked_unassigned_session_claim(tmp_path: Path) -> None:
    module = _dispatcher_module()
    claims = tmp_path / "claims"
    active = tmp_path / "tasks" / "active"
    claims.mkdir(parents=True)
    active.mkdir(parents=True)
    task_id = "p0-incident-blocked-task"
    claim = claims / "cc-active-task-gamma-9b6ba5ca-513c-41aa-9900-d3026b42aad1"
    claim.write_text(f"{task_id}\n", encoding="utf-8")
    (active / f"{task_id}.md").write_text(
        f"---\ntask_id: {task_id}\nstatus: blocked\nassigned_to: unassigned\n---\n",
        encoding="utf-8",
    )
    old = 1000.0
    os.utime(claim, (old, old))

    reaped = module.sweep_stale_claims(claims, active, now=old + 301, grace_secs=300)

    assert reaped == [(claim.name, task_id, "blocked-unassigned")]
    assert not claim.exists()


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


def _run(
    tmp_path: Path,
    *args: str,
    extra_env: dict[str, str] | None = None,
    durable_mq: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("HAPAX_DISPATCH_HOST", None)
    env.pop("HAPAX_DEFAULT_DISPATCH_HOST", None)
    env["HOME"] = str(tmp_path / "home")
    env["HAPAX_CC_TASK_ROOT"] = str(tmp_path / "tasks")
    env["HAPAX_DISPATCH_WORKTREE"] = str(tmp_path / "worktree")
    env["HAPAX_ORCHESTRATION_LEDGER_DIR"] = str(tmp_path / "ledger")
    env["HAPAX_PLATFORM_CAPABILITY_REGISTRY"] = str(_fresh_registry(tmp_path))
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

    for lane in ("dev", "dev1"):
        result = _run(tmp_path, "--task", "governed-build", "--lane", lane)

        assert result.returncode == 10
        assert "interactive Claude operator pool" in result.stderr
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
    # hapax-codex-headless takes `--task <id> <lane> <prompt>` for ordinary
    # launches. `--force` is reserved for the P0 incident drain-lane path.
    recorded = launcher_args.read_text(encoding="utf-8")
    assert recorded.startswith("--task\ngoverned-build\ncx-green\n")
    assert "\n--force\n" not in recorded
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
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" > {codex_args}\n",
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


def test_codex_headless_dispatch_propagates_retired_relay_block(tmp_path: Path) -> None:
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
        "governed-build",
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


def test_launch_uses_subscription_receipt_without_policy_rollback(tmp_path: Path) -> None:
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
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    _fake_binary(bin_dir, "codex", "codex-cli 9.9.9")
    receipt_dir = tmp_path / "receipts"
    receipt_result = subprocess.run(
        [
            sys.executable,
            str(RECEIPT_SCRIPT),
            "--registry",
            str(REGISTRY),
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
    fake_launcher = tmp_path / "launcher" / "hapax-codex"
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
            "HAPAX_PLATFORM_CAPABILITY_REGISTRY": str(REGISTRY),
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
    assert receipt["route_policy_registry_freshness_green"] is True
    assert receipt["route_policy_quota_freshness_green"] is True
    assert receipt["route_policy_resource_freshness_green"] is True
    assert receipt.get("route_policy_compatibility_mode") in {None, "none"}


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


def test_launches_claude_headless_with_task_binding(tmp_path: Path) -> None:
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
        extra_env={"HAPAX_METHODOLOGY_CLAUDE_HEADLESS": str(fake_launcher)},
    )

    assert result.returncode == 0, result.stderr
    args = launcher_args.read_text(encoding="utf-8").splitlines()
    assert args[0] == "governed-build"
    assert args[1] == str(tmp_path / "worktree")
    assert args[2:5] == ["--task", "governed-build", "beta"]
    assert "SDLC GOVERNED DISPATCH." in "\n".join(args[5:])


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
    assert "antigrav/interactive/full" in result.stdout
    assert "api/headless/api_frontier" in result.stdout
    assert "api/headless/provider_gateway" in result.stdout


def test_antigrav_lane_worktree_tracks_requested_lane(monkeypatch, tmp_path: Path) -> None:
    dispatcher = _dispatcher_module()
    monkeypatch.delenv("HAPAX_DISPATCH_WORKTREE", raising=False)
    monkeypatch.setenv("HAPAX_DISPATCH_PROJECT_ROOT", str(tmp_path))

    assert dispatcher.lane_worktree("antigrav", "antigrav") == (
        tmp_path / "hapax-council--antigrav"
    )
    assert dispatcher.lane_worktree("antigrav-5", "antigrav") == (
        tmp_path / "hapax-council--antigrav-5"
    )
    assert dispatcher.lane_worktree("antigravity", "antigrav") == (
        tmp_path / "hapax-council--antigrav"
    )


def test_antigrav_launch_passes_governed_dispatch_inflection(tmp_path: Path) -> None:
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
    launcher_args = tmp_path / "antigrav-args.txt"
    fake_launcher = tmp_path / "bin" / "hapax-antigrav"
    fake_launcher.parent.mkdir(parents=True, exist_ok=True)
    fake_launcher.write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > {launcher_args}\n",
        encoding="utf-8",
    )
    fake_launcher.chmod(0o755)

    result = _run(
        tmp_path,
        "--task",
        "governed-build",
        "--lane",
        "antigrav-5",
        "--platform",
        "antigrav",
        "--mode",
        "interactive",
        "--launch",
        extra_env={
            "HAPAX_METHODOLOGY_ANTIGRAV_LAUNCHER": str(fake_launcher),
            "HAPAX_ANTIGRAV_SPAWN_DIR": str(tmp_path / "antigrav-spawns"),
        },
    )

    assert result.returncode == 0, result.stderr
    args = launcher_args.read_text(encoding="utf-8").splitlines()
    assert args[:6] == [
        "--session",
        "antigrav-5",
        "--task",
        "governed-build",
        "--terminal",
        "tmux",
    ]
    inflection = Path(args[args.index("--inflection") + 1])
    text = inflection.read_text(encoding="utf-8")
    assert "SDLC GOVERNED DISPATCH." in text
    assert "Task: governed-build" in text
    assert "AuthorityCase: CASE-TEST-001" in text
    assert "Do not choose unrelated queue work" in text


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
