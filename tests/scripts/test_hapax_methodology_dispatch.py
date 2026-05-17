import json
import os
import subprocess
import textwrap
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-methodology-dispatch"
REGISTRY = REPO_ROOT / "config" / "platform-capability-registry.json"


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
        for score in route["capability_scores"].values():
            score["observed_at"] = checked_at
        for tool in route["tool_state"]:
            tool["observed_at"] = checked_at
    path = tmp_path / "fixtures" / "fresh-platform-capability-registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


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


def _run(
    tmp_path: Path, *args: str, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["HAPAX_CC_TASK_ROOT"] = str(tmp_path / "tasks")
    env["HAPAX_DISPATCH_WORKTREE"] = str(tmp_path / "worktree")
    env["HAPAX_ORCHESTRATION_LEDGER_DIR"] = str(tmp_path / "ledger")
    env["HAPAX_PLATFORM_CAPABILITY_REGISTRY"] = str(_fresh_registry(tmp_path))
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
        """,
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
        extra_env={"HAPAX_METHODOLOGY_CODEX_LAUNCHER": str(fake_launcher)},
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
            "HAPAX_METHODOLOGY_CODEX_LAUNCHER": str(fake_launcher),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        },
    )

    assert result.returncode == 0, result.stderr
    args = launcher_args.read_text(encoding="utf-8").splitlines()
    assert args[:10] == [
        "--session",
        "cx-green",
        "--terminal",
        "tmux",
        "--task",
        "governed-build",
        "--bootstrap",
        args[7],
        "--task-gate",
        "--force",
    ]
    bootstrap = Path(args[7]).read_text(encoding="utf-8")
    assert "SDLC GOVERNED DISPATCH." in bootstrap
    assert "Task: governed-build" in bootstrap
    assert "AuthorityCase: CASE-TEST-001" in bootstrap
    assert "If the launcher already claimed it" in bootstrap
    assert "claim the next" not in bootstrap
    assert "highest-WSJF" not in bootstrap

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


def test_policy_rollback_allows_full_profile_after_route_decision_receipt(
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
            "HAPAX_METHODOLOGY_CODEX_LAUNCHER": str(fake_launcher),
            "HAPAX_PLATFORM_CAPABILITY_REGISTRY": str(REGISTRY),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        },
    )

    assert result.returncode == 0, result.stderr
    route_receipt = json.loads(route_decisions.read_text(encoding="utf-8").splitlines()[-1])
    assert route_receipt["action"] == "launch"
    assert "rollback_full_profile_launch" in route_receipt["reason_codes"]


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
            "HAPAX_METHODOLOGY_CODEX_LAUNCHER": str(fake_launcher),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        },
    )

    assert result.returncode == 10
    assert not launcher_args.exists()
    assert "rollback_non_full_profile_hold" in result.stderr
    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["platform"] == "codex"
    assert receipt["profile"] == "spark"
    assert receipt["route_policy_action"] == "hold"


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


def test_gemini_read_only_quota_fallback_maps_to_flash(tmp_path: Path) -> None:
    _worktree(tmp_path / "worktree")
    _task(
        tmp_path / "tasks",
        "research-only",
        """
        kind: research
        task_type: read-only
        parent_spec: null
        tags:
          - research
          - read-only
        """,
    )
    launcher_args = tmp_path / "gemini-args.txt"
    fake_launcher = tmp_path / "bin" / "hapax-gemini"
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
        "research-only",
        "--lane",
        "iota",
        "--platform",
        "gemini",
        "--mode",
        "headless",
        "--profile",
        "quota-fallback",
        "--launch",
        extra_env={"HAPAX_METHODOLOGY_GEMINI_LAUNCHER": str(fake_launcher)},
    )

    assert result.returncode == 0, result.stderr
    args = launcher_args.read_text(encoding="utf-8").splitlines()
    assert "--model" in args
    assert "gemini-3-flash-preview" in args
    assert "-p" in args
    receipt = json.loads(
        (tmp_path / "ledger" / "methodology-dispatch.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert receipt["platform"] == "gemini"
    assert receipt["profile"] == "flash"
    assert receipt["launched"] is True


def test_gemini_mutation_task_fails_platform_fit(tmp_path: Path) -> None:
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
        "iota",
        "--platform",
        "gemini",
        "--mode",
        "headless",
        "--launch",
    )

    assert result.returncode == 10
    assert "read_only_mutation_route" in result.stderr


def test_lists_platform_profile_paths(tmp_path: Path) -> None:
    result = _run(tmp_path, "--list-platform-paths")

    assert result.returncode == 0, result.stderr
    assert "Default to maximum appropriate quality-preserving utilization" in result.stdout
    assert "codex/headless/full" in result.stdout
    assert "codex/headless/spark" in result.stdout
    assert "claude/headless/sonnet" in result.stdout
    assert "gemini/headless/flash" in result.stdout
    assert "antigrav/interactive/full" in result.stdout


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
        extra_env={"HAPAX_METHODOLOGY_CODEX_LAUNCHER": str(fake_launcher)},
    )

    assert result.returncode == 10
    assert "unsupported_route" in result.stderr
