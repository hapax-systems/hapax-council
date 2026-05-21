import os
import subprocess
import textwrap
from pathlib import Path

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
    env["HOME"] = str(home)
    env["HAPAX_AGENT_ROLE"] = "cx-test"
    return subprocess.run(
        ["bash", str(SCRIPT), task_id],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


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
    assert "resumed ready-state task (cc-claim)" in text
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
    assert "resumed ready-state task (cc-claim)" in text
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
    assert "resumed ready-state task (cc-claim)" in text
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
    assert "assigned to 'cx-other', not 'cx-test'" in result.stderr
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
