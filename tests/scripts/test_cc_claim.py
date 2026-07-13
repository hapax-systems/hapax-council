import hashlib
import json
import os
import re
import subprocess
import textwrap
import time
from pathlib import Path

from shared import sdlc_filesystem_transaction as transaction
from shared.coord_dispatch import lane_ownership_projection_hashes
from shared.sdlc_task_store import load_claim_dispatch_binding

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cc-claim"


def _task_root(home: Path) -> Path:
    root = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (root / "active").mkdir(parents=True, exist_ok=True)
    (root / "closed").mkdir(parents=True, exist_ok=True)
    return root


def _write_task(
    home: Path,
    subdir: str,
    task_id: str,
    *,
    status: str = "offered",
    assigned_to: str = "unassigned",
    blocked_reason: str | None = None,
    blocked_witness: str | None = None,
    depends_on: str | None = "[]",
    kind: str = "build",
    task_type: str | None = None,
    authority_case: str | None = "CASE-TEST-001",
    parent_spec: str | None = "/tmp/isap-test.md",
    quality_floor: str | None = "frontier_required",
    mutation_surface: str | None = "source",
    authority_level: str | None = "authoritative",
    route_metadata_schema: int | None = 1,
    tags: list[str] | None = None,
    body: str = "",
) -> Path:
    root = _task_root(home)
    path = root / subdir / f"{task_id}.md"
    frontmatter = [
        "---",
        "type: cc-task",
        f"task_id: {task_id}",
        f'title: "{task_id}"',
        f"status: {status}",
        f"assigned_to: {assigned_to}",
        f"kind: {kind}",
    ]
    if blocked_reason is not None:
        frontmatter.append(f"blocked_reason: {blocked_reason}")
    if blocked_witness is not None:
        frontmatter.append(f"blocked_witness: {blocked_witness}")
    if task_type is not None:
        frontmatter.append(f"task_type: {task_type}")
    if authority_case is not None:
        frontmatter.append(f"authority_case: {authority_case}")
    if parent_spec is not None:
        frontmatter.append(f"parent_spec: {parent_spec}")
    if quality_floor is not None:
        frontmatter.append(f"quality_floor: {quality_floor}")
    if mutation_surface is not None:
        frontmatter.append(f"mutation_surface: {mutation_surface}")
    if authority_level is not None:
        frontmatter.append(f"authority_level: {authority_level}")
    if route_metadata_schema is not None:
        frontmatter.append(f"route_metadata_schema: {route_metadata_schema}")
    if tags is not None:
        frontmatter.append("tags:")
        frontmatter.extend(f"  - {tag}" for tag in tags)
    if depends_on is not None:
        if depends_on.startswith("\n"):
            frontmatter.append(f"depends_on:{depends_on}")
        else:
            frontmatter.append(f"depends_on: {depends_on}")
    frontmatter.extend(
        [
            "created_at: 2026-05-09T00:00:00Z",
            "updated_at: 2026-05-09T00:00:00Z",
            "claimed_at: null",
            "---",
            "",
            f"# {task_id}",
            "",
            body,
            "",
            "## Session log",
        ]
    )
    path.write_text("\n".join(frontmatter), encoding="utf-8")
    return path


def _claim(home: Path, task_id: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for key in (
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_ROLE",
        "CODEX_ROLE",
        "CODEX_SESSION",
        "CODEX_SESSION_NAME",
        "CODEX_THREAD_NAME",
        "HAPAX_AGENT_NAME",
        "HAPAX_SESSION_ID",
    ):
        env.pop(key, None)
    env["HOME"] = str(home)
    env["HAPAX_AGENT_ROLE"] = "cx-test"
    return subprocess.run(
        ["bash", str(SCRIPT), task_id],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _dispatch_bound_env(home: Path, note: Path) -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_ROLE",
        "CODEX_ROLE",
        "CODEX_SESSION",
        "CODEX_SESSION_NAME",
        "CODEX_THREAD_NAME",
        "HAPAX_AGENT_NAME",
        "HAPAX_SESSION_ID",
    ):
        env.pop(key, None)
    env["HOME"] = str(home)
    env["HAPAX_AGENT_ROLE"] = "cx-test"
    parent_spec = home / "Documents" / "Personal" / "isap-test.md"
    parent_spec.parent.mkdir(parents=True, exist_ok=True)
    parent_spec.write_text(
        "---\ncase_id: CASE-TEST-001\n---\n\n# Test authority\n",
        encoding="utf-8",
    )
    note.write_text(
        note.read_text(encoding="utf-8").replace(
            "parent_spec: /tmp/isap-test.md",
            f"parent_spec: {parent_spec}",
        ),
        encoding="utf-8",
    )
    cache_dir = home / ".cache" / "hapax"
    relay_dir = cache_dir / "relay"
    claim_hash, relay_hash = lane_ownership_projection_hashes(
        cache_dir=cache_dir,
        relay_dir=relay_dir,
        role="cx-test",
        session="",
    )
    pid = os.getpid()
    stat_text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    pid_generation = f"pid:{pid}:{stat_text.rsplit(')', 1)[1].split()[19]}"
    env.update(
        {
            "HAPAX_CLAIM_DISPATCH_AUTHORITY_CASE": "CASE-TEST-001",
            "HAPAX_CLAIM_DISPATCH_BINDING_HASH": "a" * 64,
            "HAPAX_CLAIM_DISPATCH_CLAIM_PROJECTION_SHA256": claim_hash,
            "HAPAX_CLAIM_DISPATCH_IDEMPOTENCY_KEY": "dispatch-key",
            "HAPAX_CLAIM_DISPATCH_LANE_GENERATION": pid_generation,
            "HAPAX_CLAIM_DISPATCH_LANE_PID": str(pid),
            "HAPAX_CLAIM_DISPATCH_LANE_PID_GENERATION": pid_generation,
            "HAPAX_CLAIM_DISPATCH_LANE_SESSION": "",
            "HAPAX_CLAIM_DISPATCH_MESSAGE_ID": "dispatch-message",
            "HAPAX_CLAIM_DISPATCH_MODE": "headless",
            "HAPAX_CLAIM_DISPATCH_PARENT_SPEC": str(parent_spec),
            "HAPAX_CLAIM_DISPATCH_PARENT_SPEC_SHA256": hashlib.sha256(
                parent_spec.read_bytes()
            ).hexdigest(),
            "HAPAX_CLAIM_DISPATCH_PLATFORM": "codex",
            "HAPAX_CLAIM_DISPATCH_PROFILE": "full",
            "HAPAX_CLAIM_DISPATCH_RELAY_PROJECTION_SHA256": relay_hash,
            "HAPAX_CLAIM_DISPATCH_TASK_PATH": str(note.resolve()),
            "HAPAX_CLAIM_DISPATCH_TASK_SHA256": hashlib.sha256(note.read_bytes()).hexdigest(),
        }
    )
    return env


def test_exact_task_note_precedes_prefix_sibling(tmp_path: Path) -> None:
    home = tmp_path / "home"
    exact = _write_task(home, "active", "requested-id")
    sibling = _write_task(home, "active", "requested-id-copy")

    result = _claim(home, "requested-id")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in exact.read_text(encoding="utf-8")
    assert "status: offered" in sibling.read_text(encoding="utf-8")


def test_initial_claim_persists_platform_qualified_owner(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "qualified-initial")

    result = _claim(home, "qualified-initial")

    assert result.returncode == 0, result.stderr
    assert "assigned_to: codex/cx-test" in note.read_text(encoding="utf-8")


def test_claim_refuses_invalid_session_instead_of_legacy_downgrade(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "invalid-session")
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["HAPAX_AGENT_ROLE"] = "cx-test"
    env["HAPAX_SESSION_ID"] = "1234"

    result = subprocess.run(
        ["bash", str(SCRIPT), "invalid-session"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 8
    assert "refusing legacy-role downgrade" in result.stderr
    assert "status: offered" in note.read_text(encoding="utf-8")
    assert not (home / ".cache" / "hapax" / "cc-active-task-cx-test").exists()


def test_claim_recovers_interrupted_legacy_journal_before_other_task(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    first = _write_task(home, "active", "first-task")
    second = _write_task(home, "active", "second-task")
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    role_key = hashlib.sha256(b"cx-test").hexdigest()
    task_key = hashlib.sha256(b"first-task").hexdigest()
    legacy_journal = cache / f"cc-ownership-txn-{role_key}-{task_key}.json"
    preimage = first.read_bytes()
    postimage = preimage.replace(b"status: offered", b"status: claimed", 1)
    record = transaction._prepare_journal(
        legacy_journal,
        [
            {
                "path": str(first),
                "pre_content": transaction._encoded(preimage),
                "pre_mode": first.stat().st_mode & 0o777,
                "post_content": transaction._encoded(postimage),
                "post_mode": first.stat().st_mode & 0o777,
            }
        ],
        allowed_roots=(cache, _task_root(home)),
    )
    transaction._apply(
        record.entries,
        image="post",
        accepted_current_images=("pre",),
        allowed_roots=(cache, _task_root(home)),
    )
    assert "status: claimed" in first.read_text(encoding="utf-8")

    result = _claim(home, "second-task")

    assert result.returncode == 0, result.stderr
    assert "status: offered" in first.read_text(encoding="utf-8")
    assert "status: claimed" in second.read_text(encoding="utf-8")
    assert (cache / "cc-active-task-cx-test").read_text(encoding="utf-8").strip() == "second-task"
    assert not legacy_journal.exists()
    assert list(cache.glob(f".{legacy_journal.name}.history-*-recovered-pre"))


def test_claim_retires_stranded_legacy_journal_after_later_claim_committed(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    _write_task(
        home,
        "active",
        "second-task",
        status="claimed",
        assigned_to="codex/cx-test",
    )
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim_path = cache / "cc-active-task-cx-test"
    role_key = hashlib.sha256(b"cx-test").hexdigest()
    task_key = hashlib.sha256(b"first-task").hexdigest()
    legacy_journal = cache / f"cc-ownership-txn-{role_key}-{task_key}.json"
    record = transaction._prepare_journal(
        legacy_journal,
        [
            {
                "path": str(claim_path),
                "pre_content": transaction._encoded(None),
                "pre_mode": None,
                "post_content": transaction._encoded(b"first-task\n"),
                "post_mode": 0o600,
            }
        ],
        allowed_roots=(cache, _task_root(home)),
    )
    transaction._apply(
        record.entries,
        image="post",
        accepted_current_images=("pre",),
        allowed_roots=(cache, _task_root(home)),
    )
    claim_path.write_text("second-task\n", encoding="utf-8")
    (cache / "cc-claim-epoch-cx-test").write_text(
        "1780000000 second-task\n",
        encoding="utf-8",
    )

    result = _claim(home, "second-task")

    # The stale A journal no longer wedges every future command at recovery.
    # This synthetic role-only B projection is still (correctly) rejected by
    # the independent same-session ownership check.
    assert result.returncode == 7
    assert "claim_same_task_session_unproven" in result.stderr
    assert "ownership transaction recovery failed" not in result.stderr
    assert claim_path.read_text(encoding="utf-8") == "second-task\n"
    assert not legacy_journal.exists()
    assert list(cache.glob(f".{legacy_journal.name}.history-*-legacy-superseded-third-image"))


def test_dispatch_bound_claim_rejects_changed_task_preimage(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "claim-target")
    env = _dispatch_bound_env(home, note)
    note.write_text(note.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(SCRIPT), "claim-target"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "claim_dispatch_task_preimage_mismatch" in result.stderr
    assert not (home / ".cache" / "hapax" / "cc-active-task-cx-test").exists()


def test_dispatch_bound_claim_rejects_changed_parent_spec_preimage(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "claim-target")
    env = _dispatch_bound_env(home, note)
    Path(env["HAPAX_CLAIM_DISPATCH_PARENT_SPEC"]).write_text(
        "---\ncase_id: CASE-TEST-001\n---\nchanged\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(SCRIPT), "claim-target"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "claim_dispatch_parent_spec_preimage_mismatch" in result.stderr
    assert "status: offered" in note.read_text(encoding="utf-8")
    assert not (home / ".cache" / "hapax" / "cc-active-task-cx-test").exists()


def test_dispatch_bound_claim_writes_exact_sidecar_before_cache(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "claim-target")
    env = _dispatch_bound_env(home, note)

    result = subprocess.run(
        ["bash", str(SCRIPT), "claim-target"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    cache_dir = home / ".cache" / "hapax"
    binding = load_claim_dispatch_binding(cache_dir / "cc-claim-dispatch-cx-test.json")
    assert binding.task_id == "claim-target"
    assert binding.dispatch_message_id == "dispatch-message"
    assert binding.coord_dispatch_idempotency_key == "dispatch-key"
    assert (cache_dir / "cc-active-task-cx-test").read_text(encoding="utf-8").strip() == (
        "claim-target"
    )

    verified = subprocess.run(
        ["bash", str(SCRIPT), "--verify-dispatch-binding", "claim-target"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr


def test_dispatch_bound_ready_state_resume_verifies_exact_binding(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(
        home,
        "active",
        "claim-target",
        status="merge_queue",
        assigned_to="codex/cx-test",
    )
    env = _dispatch_bound_env(home, note)

    resumed = subprocess.run(
        ["bash", str(SCRIPT), "claim-target"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert resumed.returncode == 0, resumed.stderr

    verified = subprocess.run(
        ["bash", str(SCRIPT), "--verify-dispatch-binding", "claim-target"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert verified.returncode == 0, verified.stderr
    assert "assigned_to: codex/cx-test" in note.read_text(encoding="utf-8")


def test_dispatch_protocol_probe_is_executable_contract() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--dispatch-protocol-version"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "hapax-claim-dispatch-v1"


def test_dispatch_binding_verification_rejects_changed_parent_spec(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "claim-target")
    env = _dispatch_bound_env(home, note)
    claimed = subprocess.run(
        ["bash", str(SCRIPT), "claim-target"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert claimed.returncode == 0, claimed.stderr
    Path(env["HAPAX_CLAIM_DISPATCH_PARENT_SPEC"]).write_text(
        "---\ncase_id: CASE-TEST-001\n---\nchanged\n",
        encoding="utf-8",
    )

    verified = subprocess.run(
        ["bash", str(SCRIPT), "--verify-dispatch-binding", "claim-target"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert verified.returncode != 0
    assert "claim_dispatch_authoritative_state_mismatch" in verified.stderr


def test_body_bullets_are_not_claim_dependencies(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(
        home,
        "active",
        "claim-target",
        depends_on="[]",
        body=textwrap.dedent(
            """\
            Ordinary markdown body bullets must not be parsed as dependencies:

            - imaginary-dependency
            - another-body-bullet
            """
        ),
    )

    result = _claim(home, "claim-target")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")
    assert (home / ".cache" / "hapax" / "cc-active-task-cx-test").read_text(
        encoding="utf-8"
    ).strip() == "claim-target"


def test_missing_depends_on_field_means_no_dependencies(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "no-deps-field", depends_on=None)

    result = _claim(home, "no-deps-field")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_terminal_frontmatter_dependency_allows_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(home, "closed", "done-dep", status="done", assigned_to="cx-peer")
    note = _write_task(
        home,
        "active",
        "claim-target",
        depends_on="\n  - done-dep",
    )

    result = _claim(home, "claim-target")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_nonterminal_frontmatter_dependency_blocks_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(
        home,
        "active",
        "unfinished-dep",
        status="in_progress",
        assigned_to="cx-peer",
    )
    _write_task(
        home,
        "active",
        "claim-target",
        depends_on="\n  - unfinished-dep",
    )

    result = _claim(home, "claim-target")

    assert result.returncode == 5
    assert "unmet dependencies" in result.stderr
    assert "unfinished-dep (status_not_fulfilling:in_progress)" in result.stderr


def test_blocked_task_refusal_includes_reason_and_witness(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(
        home,
        "active",
        "blocked-target",
        status="blocked",
        blocked_reason="minio_mirror_still_d_state",
        blocked_witness="~/.cache/hapax/witness/minio-d-state.json",
    )

    result = _claim(home, "blocked-target")

    assert result.returncode == 4
    assert "current status is 'blocked'" in result.stderr
    assert "blocked_reason: minio_mirror_still_d_state" in result.stderr
    assert "blocked_witness: ~/.cache/hapax/witness/minio-d-state.json" in result.stderr
    assert "status: blocked" in note.read_text(encoding="utf-8")
    assert not (home / ".cache" / "hapax" / "cc-active-task-cx-test").exists()


def test_blocked_dependency_reports_precise_reason_and_witness(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(
        home,
        "active",
        "blocked-dep",
        status="blocked",
        blocked_reason="provider_budget_receipt_absent",
        blocked_witness="~/.cache/hapax/witness/provider-budget.json",
    )
    _write_task(
        home,
        "active",
        "claim-target",
        depends_on="\n  - blocked-dep",
    )

    result = _claim(home, "claim-target")

    assert result.returncode == 5
    assert "blocked-dep (blocked_reason:provider_budget_receipt_absent" in result.stderr
    assert "blocked_witness:~/.cache/hapax/witness/provider-budget.json" in result.stderr


def test_missing_frontmatter_dependency_blocks_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(
        home,
        "active",
        "claim-target",
        depends_on="\n  - missing-dep",
    )

    result = _claim(home, "claim-target")

    assert result.returncode == 5
    assert "missing-dep (not found in vault)" in result.stderr


def test_unchecked_acceptance_dependency_blocks_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(
        home,
        "closed",
        "false-done-dep",
        status="done",
        assigned_to="cx-peer",
        body="## Acceptance criteria\n\n- [ ] Evidence exists\n",
    )
    _write_task(
        home,
        "active",
        "claim-target",
        depends_on="\n  - false-done-dep",
    )

    result = _claim(home, "claim-target")

    assert result.returncode == 5
    assert "unchecked_acceptance_criteria:Evidence exists" in result.stderr


def test_malformed_route_metadata_dependency_blocks_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(
        home,
        "closed",
        "bad-route-dep",
        status="done",
        assigned_to="cx-peer",
        quality_floor="frontier_review_required",
        authority_level="authoritative",
        mutation_surface="source",
    )
    _write_task(
        home,
        "active",
        "claim-target",
        depends_on="\n  - bad-route-dep",
    )

    result = _claim(home, "claim-target")

    assert result.returncode == 5
    assert "route_metadata:" in result.stderr
    assert "frontier_review_required artifacts cannot be authoritative directly" in result.stderr


def test_build_task_with_null_parent_spec_blocks_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(
        home,
        "active",
        "ungoverned-build",
        parent_spec="null",
        authority_case="CASE-TEST-001",
    )

    result = _claim(home, "ungoverned-build")

    assert result.returncode == 6
    assert "missing required AuthorityCase/ISAP fields" in result.stderr
    assert "parent_spec" in result.stderr


def test_build_task_missing_authority_case_blocks_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(
        home,
        "active",
        "missing-authority",
        authority_case=None,
        parent_spec="/tmp/isap-test.md",
    )

    result = _claim(home, "missing-authority")

    assert result.returncode == 6
    assert "missing required AuthorityCase/ISAP fields" in result.stderr
    assert "authority_case" in result.stderr


def test_explicit_read_only_intake_without_parent_spec_allows_claim(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    note = _write_task(
        home,
        "active",
        "intake-only",
        kind="intake",
        task_type="read-only",
        authority_case=None,
        parent_spec=None,
        tags=["intake", "read-only"],
    )

    result = _claim(home, "intake-only")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_assigned_to_unassigned_allows_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "unassigned-owner", assigned_to="unassigned")

    result = _claim(home, "unassigned-owner")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_assigned_to_null_scalar_allows_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "null-owner", assigned_to="null")

    result = _claim(home, "null-owner")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_assigned_to_tilde_allows_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "tilde-owner", assigned_to="~")

    result = _claim(home, "tilde-owner")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_assigned_to_none_allows_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "none-owner", assigned_to="none")

    result = _claim(home, "none-owner")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_empty_assigned_to_scalar_allows_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "empty-owner", assigned_to="")

    result = _claim(home, "empty-owner")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_assigned_to_other_role_blocks_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "owned-task", assigned_to="cx-other")

    result = _claim(home, "owned-task")

    assert result.returncode == 4
    assert "already assigned to 'cx-other'" in result.stderr
    assert "status: offered" in note.read_text(encoding="utf-8")


def test_pr_open_assigned_to_same_role_resumes_without_status_change(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    note = _write_task(
        home,
        "active",
        "review-fix",
        status="pr_open",
        assigned_to="cx-test",
    )

    result = _claim(home, "review-fix")

    assert result.returncode == 0, result.stderr
    text = note.read_text(encoding="utf-8")
    assert "status: pr_open" in text
    assert "assigned_to: cx-test" in text
    assert "claimed_at: null" in text
    assert "resumed ready-state task (cc-claim" in text  # tolerate session=<sid> suffix
    assert (home / ".cache" / "hapax" / "cc-active-task-cx-test").read_text(
        encoding="utf-8"
    ).strip() == "review-fix"


def test_ready_state_resume_uses_existing_session_log_heading_case(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    note = _write_task(
        home,
        "active",
        "capital-log",
        status="pr_open",
        assigned_to="cx-test",
    )
    note.write_text(
        note.read_text(encoding="utf-8").replace("## Session log", "## Session Log"),
        encoding="utf-8",
    )

    result = _claim(home, "capital-log")

    assert result.returncode == 0, result.stderr
    text = note.read_text(encoding="utf-8")
    assert "## Session Log\n- " in text
    assert "resumed ready-state task (cc-claim" in text  # tolerate session=<sid> suffix
    assert "## Session log" not in text


def test_merge_queue_assigned_to_same_role_resumes_without_status_change(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    note = _write_task(
        home,
        "active",
        "queue-followup",
        status="merge_queue",
        assigned_to="cx-test",
    )

    result = _claim(home, "queue-followup")

    assert result.returncode == 0, result.stderr
    text = note.read_text(encoding="utf-8")
    assert "status: merge_queue" in text
    assert "assigned_to: cx-test" in text
    assert "claimed_at: null" in text
    assert "resumed ready-state task (cc-claim" in text  # tolerate session=<sid> suffix
    assert (home / ".cache" / "hapax" / "cc-active-task-cx-test").read_text(
        encoding="utf-8"
    ).strip() == "queue-followup"


def test_pr_open_unassigned_blocks_resume(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(
        home,
        "active",
        "unowned-review",
        status="pr_open",
        assigned_to="unassigned",
    )

    result = _claim(home, "unowned-review")

    assert result.returncode == 4
    assert "ready-state task is not assigned to 'cx-test'" in result.stderr
    assert "status: pr_open" in note.read_text(encoding="utf-8")
    assert not (home / ".cache" / "hapax" / "cc-active-task-cx-test").exists()


def test_merge_queue_different_assignee_blocks_resume(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(
        home,
        "active",
        "other-queue",
        status="merge_queue",
        assigned_to="cx-other",
    )

    result = _claim(home, "other-queue")

    assert result.returncode == 4
    assert "assigned to 'cx-other', not 'codex/cx-test'" in result.stderr
    assert "status: merge_queue" in note.read_text(encoding="utf-8")
    assert not (home / ".cache" / "hapax" / "cc-active-task-cx-test").exists()


def test_depends_on_null_scalar_means_no_dependencies(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "null-dep", depends_on="null")

    result = _claim(home, "null-dep")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_depends_on_tilde_means_no_dependencies(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "tilde-dep", depends_on="~")

    result = _claim(home, "tilde-dep")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_depends_on_none_means_no_dependencies(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "none-dep", depends_on="none")

    result = _claim(home, "none-dep")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_depends_on_quoted_null_means_no_dependencies(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "quoted-null", depends_on='"null"')

    result = _claim(home, "quoted-null")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_block_style_depends_on_does_not_bleed_into_tags(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(home, "closed", "real-dep", status="done", assigned_to="cx-peer")
    note = _write_task(
        home,
        "active",
        "bleed-test",
        depends_on="\n  - real-dep",
        tags=["cc-task", "sdlc", "implementation"],
    )

    result = _claim(home, "bleed-test")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_depends_on_as_terminal_frontmatter_key(tmp_path: Path) -> None:
    """depends_on as the last key before closing --- must not collect body items."""
    home = tmp_path / "home"
    _write_task(home, "closed", "term-dep", status="done", assigned_to="cx-peer")
    root = _task_root(home)
    path = root / "active" / "terminal-key.md"
    path.write_text(
        textwrap.dedent("""\
            ---
            type: cc-task
            task_id: terminal-key
            title: "terminal-key"
            status: offered
            assigned_to: unassigned
            kind: build
            authority_case: CASE-TEST-001
            parent_spec: /tmp/isap-test.md
            created_at: 2026-05-09T00:00:00Z
            updated_at: 2026-05-09T00:00:00Z
            claimed_at: null
            depends_on:
              - term-dep
            ---

            # terminal-key

            Body bullets that must not be parsed as deps:

            - fake-dep-one
            - fake-dep-two

            ## Session log
        """),
        encoding="utf-8",
    )

    result = _claim(home, "terminal-key")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in path.read_text(encoding="utf-8")


def test_governed_build_task_allows_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "governed-build")

    result = _claim(home, "governed-build")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")


def test_claim_inserts_missing_claim_keys(tmp_path: Path) -> None:
    """A note authored without claimed_at must still get a COMPLETE stamp.

    The re.sub stamps were silent no-ops for absent keys: the claim landed as
    `status: claimed` with claimed_at missing — exactly the cc-hygiene H1
    ghost predicate — and H1 reverted the fresh claim out from under the live
    lane (2026-07-01 eta/ndcvb-phase1 incident)."""
    home = tmp_path / "home"
    root = _task_root(home)
    task_id = "cc-missing-keys"
    path = root / "active" / f"{task_id}.md"
    path.write_text(
        textwrap.dedent(
            f"""\
            ---
            type: cc-task
            task_id: {task_id}
            title: "{task_id}"
            status: offered
            assigned_to: unassigned
            kind: build
            authority_case: CASE-TEST-001
            parent_spec: /tmp/isap-test.md
            quality_floor: frontier_required
            mutation_surface: source
            authority_level: authoritative
            route_metadata_schema: 1
            depends_on: []
            created_at: 2026-05-09T00:00:00Z
            updated_at: 2026-05-09T00:00:00Z
            ---

            # {task_id}

            ## Session log
            """
        ),
        encoding="utf-8",
    )

    result = _claim(home, task_id)

    assert result.returncode == 0, result.stderr
    text = path.read_text(encoding="utf-8")
    frontmatter = text[: text.find("\n---", 4)]
    assert "status: claimed" in frontmatter
    assert "assigned_to: codex/cx-test" in frontmatter
    assert re.search(r"^claimed_at: \d{4}-\d{2}-\d{2}T", frontmatter, flags=re.MULTILINE), (
        "claimed_at must be inserted when the authored note lacks the key:\n" + frontmatter
    )


def test_claim_stamp_ignores_body_decoy_lines(tmp_path: Path) -> None:
    """A column-0 `claimed_at:` line in the note BODY must neither absorb the
    stamp nor satisfy the verification — stamping is frontmatter-scoped."""
    home = tmp_path / "home"
    root = _task_root(home)
    task_id = "cc-body-decoy"
    path = root / "active" / f"{task_id}.md"
    path.write_text(
        textwrap.dedent(
            f"""\
            ---
            type: cc-task
            task_id: {task_id}
            title: "{task_id}"
            status: offered
            assigned_to: unassigned
            kind: build
            authority_case: CASE-TEST-001
            parent_spec: /tmp/isap-test.md
            quality_floor: frontier_required
            mutation_surface: source
            authority_level: authoritative
            route_metadata_schema: 1
            depends_on: []
            created_at: 2026-05-09T00:00:00Z
            updated_at: 2026-05-09T00:00:00Z
            ---

            # {task_id}

            Quoted frontmatter from an earlier incident report:
            claimed_at: 1999-01-01T00:00:00Z
            status: offered

            ## Session log
            """
        ),
        encoding="utf-8",
    )

    result = _claim(home, task_id)

    assert result.returncode == 0, result.stderr
    text = path.read_text(encoding="utf-8")
    frontmatter = text[: text.find("\n---", 4)]
    assert re.search(r"^claimed_at: \d{4}-\d{2}-\d{2}T", frontmatter, flags=re.MULTILINE), (
        "claimed_at must be stamped INTO the frontmatter despite the body decoy:\n" + frontmatter
    )
    # The body decoy line is untouched.
    assert "claimed_at: 1999-01-01T00:00:00Z" in text


def test_claim_writes_task_bound_epoch_sidecar(tmp_path: Path) -> None:
    """cc-claim records `<epoch> <task_id>` in the cc-claim-epoch sidecar so
    task_is_terminal has a heartbeat-immune, task-bound claim-age witness."""
    home = tmp_path / "home"
    _write_task(home, "active", "cc-sidecar")

    result = _claim(home, "cc-sidecar")

    assert result.returncode == 0, result.stderr
    sidecar = home / ".cache" / "hapax" / "cc-claim-epoch-cx-test"
    assert sidecar.exists()
    epoch, _, task = sidecar.read_text(encoding="utf-8").strip().partition(" ")
    assert epoch.isdigit()
    assert task == "cc-sidecar"


def test_claim_writes_session_keyed_epoch_sidecar(tmp_path: Path) -> None:
    """The session-keyed sidecar is written alongside the session-keyed cache
    with an explicitly constructed path (never substring substitution on the
    full path, which corrupts when a parent dir contains cc-active-task)."""
    home = tmp_path / "home"
    _write_task(home, "active", "cc-sidecar-session")
    sid = "0f9f9f9f-1111-2222-3333-444455556666"
    env = os.environ.copy()
    for key in (
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_ROLE",
        "CODEX_ROLE",
        "CODEX_SESSION",
        "CODEX_SESSION_NAME",
        "CODEX_THREAD_NAME",
        "HAPAX_AGENT_NAME",
    ):
        env.pop(key, None)
    env["HOME"] = str(home)
    env["HAPAX_AGENT_ROLE"] = "cx-test"
    env["HAPAX_SESSION_ID"] = sid

    result = subprocess.run(
        ["bash", str(SCRIPT), "cc-sidecar-session"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    cache_dir = home / ".cache" / "hapax"
    session_cache = cache_dir / f"cc-active-task-cx-test-{sid}"
    assert session_cache.read_text(encoding="utf-8").strip() == "cc-sidecar-session"
    session_sidecar = cache_dir / f"cc-claim-epoch-cx-test-{sid}"
    assert session_sidecar.exists(), sorted(p.name for p in cache_dir.iterdir())
    epoch, _, task = session_sidecar.read_text(encoding="utf-8").strip().partition(" ")
    assert epoch.isdigit()
    assert task == "cc-sidecar-session"


def test_claim_refuses_duplicate_claim_keys(tmp_path: Path) -> None:
    """Duplicate claim keys are fail-closed: re.sub stamps only the FIRST
    occurrence while YAML consumers treat the LAST as authoritative — the
    combination would leave a ghost-claimable note behind a written cache."""
    home = tmp_path / "home"
    root = _task_root(home)
    task_id = "cc-duplicate-keys"
    path = root / "active" / f"{task_id}.md"
    path.write_text(
        textwrap.dedent(
            f"""\
            ---
            type: cc-task
            task_id: {task_id}
            title: "{task_id}"
            status: offered
            assigned_to: unassigned
            kind: build
            authority_case: CASE-TEST-001
            parent_spec: /tmp/isap-test.md
            quality_floor: frontier_required
            mutation_surface: source
            authority_level: authoritative
            route_metadata_schema: 1
            depends_on: []
            created_at: 2026-05-09T00:00:00Z
            updated_at: 2026-05-09T00:00:00Z
            claimed_at: null
            claimed_at: null
            ---

            # {task_id}

            ## Session log
            """
        ),
        encoding="utf-8",
    )

    result = _claim(home, task_id)

    assert result.returncode != 0
    assert "duplicate frontmatter keys" in result.stderr
    cache_dir = home / ".cache" / "hapax"
    leaked = list(cache_dir.glob("cc-active-task-*")) if cache_dir.exists() else []
    assert leaked == [], f"claim caches must not be written for a duplicate-key note: {leaked}"


def test_claim_refuses_note_without_closing_frontmatter(tmp_path: Path) -> None:
    """An unstampable note must fail loudly WITHOUT writing claim caches —
    the no-cache-on-failure guarantee is the load-bearing fail-closed
    property (a cache over a ghost-claimable note re-opens the H1 race)."""
    home = tmp_path / "home"
    root = _task_root(home)
    task_id = "cc-no-closing-delimiter"
    path = root / "active" / f"{task_id}.md"
    path.write_text(
        "---\n"
        f"task_id: {task_id}\n"
        "status: offered\n"
        "assigned_to: unassigned\n"
        "# frontmatter never closes\n",
        encoding="utf-8",
    )

    result = _claim(home, task_id)

    assert result.returncode != 0
    assert "no closing frontmatter delimiter" in result.stderr
    assert "No claim caches were written" in result.stderr
    cache_dir = home / ".cache" / "hapax"
    leaked = list(cache_dir.glob("cc-active-task-*")) if cache_dir.exists() else []
    assert leaked == [], f"claim caches must not be written on a failed stamp: {leaked}"


def test_expired_claim_is_never_deleted_by_failed_new_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim = cache / "cc-active-task-cx-test-old-session"
    epoch = cache / "cc-claim-epoch-cx-test-old-session"
    binding = cache / "cc-claim-dispatch-cx-test-old-session.json"
    claim.write_text("existing-task\n", encoding="utf-8")
    epoch.write_text("1 existing-task\n", encoding="utf-8")
    binding.write_text("preserve-me\n", encoding="utf-8")
    os.utime(claim, (1, 1))
    before = {path: path.read_bytes() for path in (claim, epoch, binding)}

    result = _claim(home, "missing-target")

    assert result.returncode == 7
    assert "claim_slot_occupied" in result.stderr
    assert {path: path.read_bytes() for path in before} == before


def test_force_cannot_replace_existing_ownership(tmp_path: Path) -> None:
    home = tmp_path / "home"
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    claim = cache / "cc-active-task-cx-test"
    claim.write_text("existing-task\n", encoding="utf-8")
    env = os.environ.copy()
    env.update(HOME=str(home), HAPAX_AGENT_NAME="cx-test", HAPAX_AGENT_ROLE="cx-test")

    result = subprocess.run(
        ["bash", str(SCRIPT), "--force", "new-task"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 8
    assert "ownership replacement is retired" in result.stderr
    assert claim.read_text(encoding="utf-8") == "existing-task\n"


def test_same_task_other_session_cannot_refresh_or_overwrite(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_task(
        home,
        "active",
        "shared-task",
        status="merge_queue",
        assigned_to="cx-test",
    )
    cache = home / ".cache" / "hapax"
    cache.mkdir(parents=True)
    old_session = "11111111-1111-4111-8111-111111111111"
    new_session = "22222222-2222-4222-8222-222222222222"
    legacy = cache / "cc-active-task-cx-test"
    session_claim = cache / f"cc-active-task-cx-test-{old_session}"
    legacy.write_text("shared-task\n", encoding="utf-8")
    session_claim.write_text("shared-task\n", encoding="utf-8")
    (cache / "cc-claim-epoch-cx-test").write_text("1 shared-task\n", encoding="utf-8")
    (cache / f"cc-claim-epoch-cx-test-{old_session}").write_text(
        "1 shared-task\n", encoding="utf-8"
    )
    env = os.environ.copy()
    env.update(
        HOME=str(home),
        HAPAX_AGENT_NAME="cx-test",
        HAPAX_AGENT_ROLE="cx-test",
        HAPAX_SESSION_ID=new_session,
    )

    result = subprocess.run(
        ["bash", str(SCRIPT), "shared-task"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 7
    assert "claim_same_task_owned_by_other_session" in result.stderr
    assert legacy.read_text(encoding="utf-8") == "shared-task\n"
    assert session_claim.read_text(encoding="utf-8") == "shared-task\n"


def test_unbound_refresh_cannot_erase_dispatch_binding(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "bound-task")
    env = _dispatch_bound_env(home, note)
    first = subprocess.run(
        ["bash", str(SCRIPT), "bound-task"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert first.returncode == 0, first.stderr
    binding = home / ".cache" / "hapax" / "cc-claim-dispatch-cx-test.json"
    before = binding.read_bytes()

    second = _claim(home, "bound-task")

    assert second.returncode == 7
    assert "claim_slot_already_dispatch_bound" in second.stderr
    assert binding.read_bytes() == before


def test_platform_qualified_owner_resumes_only_on_exact_platform(tmp_path: Path) -> None:
    home = tmp_path / "home"
    exact = _write_task(
        home,
        "active",
        "qualified-exact",
        status="merge_queue",
        assigned_to="codex/cx-test",
    )

    accepted = _claim(home, "qualified-exact")

    assert accepted.returncode == 0, accepted.stderr
    assert "assigned_to: codex/cx-test" in exact.read_text(encoding="utf-8")

    other_home = tmp_path / "other-home"
    other = _write_task(
        other_home,
        "active",
        "qualified-other",
        status="merge_queue",
        assigned_to="claude/cx-test",
    )
    rejected = _claim(other_home, "qualified-other")

    assert rejected.returncode == 4
    assert "not 'codex/cx-test'" in rejected.stderr
    assert "assigned_to: claude/cx-test" in other.read_text(encoding="utf-8")


def test_bare_known_owner_cannot_resume_from_another_platform(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(
        home,
        "active",
        "bare-cross-platform",
        status="merge_queue",
        assigned_to="cx-test",
    )
    env = os.environ.copy()
    for key in (
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_ROLE",
        "CODEX_ROLE",
        "CODEX_SESSION",
        "CODEX_SESSION_NAME",
        "CODEX_THREAD_NAME",
        "HAPAX_AGENT_NAME",
        "HAPAX_SESSION_ID",
    ):
        env.pop(key, None)
    env.update(
        HOME=str(home),
        HAPAX_AGENT_INTERFACE="claude",
        HAPAX_AGENT_ROLE="cx-test",
    )

    result = subprocess.run(
        ["bash", str(SCRIPT), "bare-cross-platform"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 4
    assert "not 'claude/cx-test'" in result.stderr
    assert "assigned_to: cx-test" in note.read_text(encoding="utf-8")


_REMOTE_SESSION_ID = "remote-projection-session"


def _dispatch_claim_for_remote_projection(
    home: Path,
    note: Path,
) -> tuple[dict[str, str], bytes, bytes, str]:
    pre_claim = note.read_bytes()
    env = _dispatch_bound_env(home, note)
    env["HAPAX_SESSION_ID"] = _REMOTE_SESSION_ID
    claimed = subprocess.run(
        ["bash", str(SCRIPT), note.stem],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert claimed.returncode == 0, claimed.stderr
    post_claim = note.read_bytes()
    printed = subprocess.run(
        ["bash", str(SCRIPT), "--print-post-claim-task-sha256", note.stem],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert printed.returncode == 0, printed.stderr
    post_claim_sha256 = hashlib.sha256(post_claim).hexdigest()
    assert printed.stdout.strip() == post_claim_sha256
    env["HAPAX_CLAIM_REMOTE_POST_CLAIM_TASK_SHA256"] = post_claim_sha256
    env["HAPAX_CLAIM_REMOTE_WAIT_SECONDS"] = "3"
    return env, pre_claim, post_claim, post_claim_sha256


def _clear_remote_projection_slot(home: Path) -> None:
    cache = home / ".cache" / "hapax"
    for pattern in (
        "cc-active-task-cx-test*",
        "cc-claim-epoch-cx-test*",
        "cc-claim-dispatch-cx-test*.json",
        f"session-role-{_REMOTE_SESSION_ID}",
        "cc-claim-remote-projection-cx-test-*.json",
    ):
        for path in cache.glob(pattern):
            path.unlink()


def _remote_projection_paths(home: Path, post_claim_sha256: str) -> list[Path]:
    cache = home / ".cache" / "hapax"
    keys = ("cx-test", f"cx-test-{_REMOTE_SESSION_ID}")
    paths = [cache / f"session-role-{_REMOTE_SESSION_ID}"]
    for key in keys:
        paths.extend(
            (
                cache / f"cc-active-task-{key}",
                cache / f"cc-claim-epoch-{key}",
                cache / f"cc-claim-dispatch-{key}.json",
            )
        )
    paths.append(
        cache
        / (f"cc-claim-remote-projection-cx-test-{_REMOTE_SESSION_ID}-{post_claim_sha256}.json")
    )
    return paths


def _materialize_remote(env: dict[str, str], task_id: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), "--materialize-remote-projection", task_id],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _move_to_closed(note: Path, *, status: str = "done", owner: str | None = None) -> Path:
    text = re.sub(r"^status:.*$", f"status: {status}", note.read_text(), count=1, flags=re.M)
    if owner is not None:
        text = re.sub(r"^assigned_to:.*$", f"assigned_to: {owner}", text, count=1, flags=re.M)
    closed = note.parent.parent / "closed" / note.name
    closed.write_text(text, encoding="utf-8")
    note.unlink()
    return closed


def _retire_terminal_projection(
    env: dict[str, str], task_id: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), "--retire-terminal-projection", task_id],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_terminal_projection_retirement_clears_only_exact_closed_session(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "remote-terminal-retirement")
    env, _pre, _post, _sha = _dispatch_claim_for_remote_projection(home, note)
    closed = _move_to_closed(note)
    closed_before = closed.read_bytes()
    cache = home / ".cache" / "hapax"
    keys = ("cx-test", f"cx-test-{_REMOTE_SESSION_ID}")
    projection_paths = [
        path
        for key in keys
        for path in (
            cache / f"cc-active-task-{key}",
            cache / f"cc-claim-epoch-{key}",
            cache / f"cc-claim-dispatch-{key}.json",
        )
    ]
    assert all(path.is_file() for path in projection_paths)

    result = _retire_terminal_projection(env, "remote-terminal-retirement")

    assert result.returncode == 0, result.stderr
    assert "retired exact terminal projection" in result.stdout
    assert not any(path.exists() for path in projection_paths)
    assert closed.read_bytes() == closed_before

    replay = _retire_terminal_projection(env, "remote-terminal-retirement")
    assert replay.returncode == 0, replay.stderr
    assert "already retired" in replay.stdout


def test_terminal_projection_retirement_refuses_active_task(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "remote-still-active")
    env, _pre, _post, _sha = _dispatch_claim_for_remote_projection(home, note)
    cache = home / ".cache" / "hapax"

    result = _retire_terminal_projection(env, "remote-still-active")

    assert result.returncode == 75
    assert "terminal_projection_task_active" in result.stderr
    assert (cache / "cc-active-task-cx-test").is_file()
    assert (cache / f"cc-active-task-cx-test-{_REMOTE_SESSION_ID}").is_file()


def test_terminal_projection_retirement_refuses_incomplete_or_wrong_owner(
    tmp_path: Path,
) -> None:
    incomplete_home = tmp_path / "incomplete-home"
    incomplete_note = _write_task(incomplete_home, "active", "remote-terminal-incomplete")
    incomplete_env, _pre, _post, _sha = _dispatch_claim_for_remote_projection(
        incomplete_home, incomplete_note
    )
    _move_to_closed(incomplete_note)
    incomplete_cache = incomplete_home / ".cache" / "hapax"
    missing = incomplete_cache / f"cc-claim-epoch-cx-test-{_REMOTE_SESSION_ID}"
    missing.unlink()

    incomplete = _retire_terminal_projection(incomplete_env, "remote-terminal-incomplete")

    assert incomplete.returncode == 8
    assert "terminal_projection_incomplete" in incomplete.stderr
    assert (incomplete_cache / "cc-active-task-cx-test").is_file()

    owner_home = tmp_path / "owner-home"
    owner_note = _write_task(owner_home, "active", "remote-terminal-wrong-owner")
    owner_env, _pre, _post, _sha = _dispatch_claim_for_remote_projection(owner_home, owner_note)
    _move_to_closed(owner_note, owner="codex/cx-other")

    mismatched = _retire_terminal_projection(owner_env, "remote-terminal-wrong-owner")

    assert mismatched.returncode == 8
    assert "terminal_projection_owner_mismatch" in mismatched.stderr
    assert (owner_home / ".cache" / "hapax" / "cc-active-task-cx-test").is_file()


def test_standard_claim_replay_cannot_materialize_remote_projection(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "remote-standard-replay")
    env, _pre_claim, _post_claim, _post_claim_sha256 = _dispatch_claim_for_remote_projection(
        home, note
    )
    _clear_remote_projection_slot(home)

    replay = subprocess.run(
        ["bash", str(SCRIPT), "remote-standard-replay"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert replay.returncode != 0
    assert "claim_dispatch_task_preimage_mismatch" in replay.stderr
    assert not list((home / ".cache" / "hapax").glob("cc-active-task-cx-test*"))


def test_remote_projection_materializes_complete_transaction_and_receipt(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "remote-materialize")
    env, _pre_claim, _post_claim, post_claim_sha256 = _dispatch_claim_for_remote_projection(
        home, note
    )
    _clear_remote_projection_slot(home)

    result = _materialize_remote(env, "remote-materialize")

    assert result.returncode == 0, result.stderr
    paths = _remote_projection_paths(home, post_claim_sha256)
    assert all(path.is_file() for path in paths)
    assert all((path.stat().st_mode & 0o777) == 0o600 for path in paths)
    assert hashlib.sha256(note.read_bytes()).hexdigest() == post_claim_sha256
    receipt_path = paths[-1]
    receipt = json.loads(receipt_path.read_text(encoding="ascii"))
    assert receipt["schema"] == "hapax.remote-claim-projection.v1"
    assert receipt["may_authorize"] is False
    assert receipt["task_id"] == "remote-materialize"
    assert receipt["lane"] == "cx-test"
    assert receipt["session_id"] == _REMOTE_SESSION_ID
    assert receipt["platform"] == "codex"
    assert receipt["post_claim_task_sha256"] == post_claim_sha256
    receipt_hash = receipt.pop("receipt_hash")
    canonical = json.dumps(
        receipt,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    assert receipt_hash == hashlib.sha256(canonical).hexdigest()

    archives = list((home / ".cache" / "hapax").glob(".cc-ownership-txn*.history-*-committed"))
    assert archives
    transaction_path_sets = []
    for archive in archives:
        manifest = json.loads((archive / "manifest.json").read_text(encoding="ascii"))
        transaction_path_sets.append({entry["path"] for entry in manifest["entries"]})
    assert any(
        {str(note.resolve()), str(receipt_path.resolve())} <= transaction_paths
        for transaction_paths in transaction_path_sets
    )

    before_receipt = receipt_path.read_bytes()
    idempotent = _materialize_remote(env, "remote-materialize")
    assert idempotent.returncode == 0, idempotent.stderr
    assert receipt_path.read_bytes() == before_receipt
    assert hashlib.sha256(note.read_bytes()).hexdigest() == post_claim_sha256


def test_remote_projection_waits_for_exact_synced_post_claim_note(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "remote-sync-wait")
    env, pre_claim, post_claim, post_claim_sha256 = _dispatch_claim_for_remote_projection(
        home, note
    )
    _clear_remote_projection_slot(home)
    note.write_bytes(pre_claim)

    process = subprocess.Popen(
        ["bash", str(SCRIPT), "--materialize-remote-projection", "remote-sync-wait"],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(0.35)
    note.write_bytes(post_claim)
    stdout, stderr = process.communicate(timeout=10)

    assert process.returncode == 0, stderr
    assert "materialized exact remote projection" in stdout
    assert all(path.is_file() for path in _remote_projection_paths(home, post_claim_sha256))


def test_remote_projection_timeout_and_owner_mismatch_write_nothing(tmp_path: Path) -> None:
    timeout_home = tmp_path / "timeout-home"
    timeout_note = _write_task(timeout_home, "active", "remote-sync-timeout")
    timeout_env, pre_claim, _post_claim, post_claim_sha256 = _dispatch_claim_for_remote_projection(
        timeout_home, timeout_note
    )
    _clear_remote_projection_slot(timeout_home)
    timeout_note.write_bytes(pre_claim)
    timeout_env["HAPAX_CLAIM_REMOTE_WAIT_SECONDS"] = "1"

    timed_out = _materialize_remote(timeout_env, "remote-sync-timeout")

    assert timed_out.returncode == 8
    assert "claim_remote_post_claim_sync_timeout" in timed_out.stderr
    assert not any(
        path.exists() for path in _remote_projection_paths(timeout_home, post_claim_sha256)
    )

    owner_home = tmp_path / "owner-home"
    owner_note = _write_task(owner_home, "active", "remote-owner-mismatch")
    owner_env, _pre, _post, _sha = _dispatch_claim_for_remote_projection(owner_home, owner_note)
    _clear_remote_projection_slot(owner_home)
    owner_note.write_text(
        owner_note.read_text(encoding="utf-8").replace(
            "assigned_to: codex/cx-test", "assigned_to: claude/cx-test"
        ),
        encoding="utf-8",
    )
    mismatched_sha = hashlib.sha256(owner_note.read_bytes()).hexdigest()
    owner_env["HAPAX_CLAIM_REMOTE_POST_CLAIM_TASK_SHA256"] = mismatched_sha

    mismatched = _materialize_remote(owner_env, "remote-owner-mismatch")

    assert mismatched.returncode == 8
    assert "claim_remote_authoritative_state_mismatch" in mismatched.stderr
    assert not any(path.exists() for path in _remote_projection_paths(owner_home, mismatched_sha))


def test_remote_projection_refuses_partial_existing_projection(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "remote-partial")
    env, _pre, _post, post_claim_sha256 = _dispatch_claim_for_remote_projection(home, note)
    _clear_remote_projection_slot(home)
    legacy = home / ".cache" / "hapax" / "cc-active-task-cx-test"
    legacy.write_text("remote-partial\n", encoding="utf-8")
    legacy.chmod(0o600)

    result = _materialize_remote(env, "remote-partial")

    assert result.returncode == 8
    assert "claim_remote_projection_incomplete" in result.stderr
    assert legacy.read_text(encoding="utf-8") == "remote-partial\n"
    assert sum(path.exists() for path in _remote_projection_paths(home, post_claim_sha256)) == 1
