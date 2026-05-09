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
    assert "unfinished-dep (status: in_progress)" in result.stderr


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


def test_governed_build_task_allows_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    note = _write_task(home, "active", "governed-build")

    result = _claim(home, "governed-build")

    assert result.returncode == 0, result.stderr
    assert "status: claimed" in note.read_text(encoding="utf-8")
