from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

REPO = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_repo_create_refuses_ryanklee_owner() -> None:
    proc = subprocess.run(
        [str(REPO / "scripts" / "hapax-github-repo-create"), "ryanklee/hapax-example"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 2
    assert "refusing personal-account owner 'ryanklee'" in proc.stderr


def test_repo_create_invokes_gh_under_hapax_systems(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "gh-args.txt"
    gh = fake_bin / "gh"
    gh.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" > "$HAPAX_FAKE_GH_LOG"\n',
        encoding="utf-8",
    )
    gh.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "HAPAX_FAKE_GH_LOG": str(log),
    }

    proc = subprocess.run(
        [
            str(REPO / "scripts" / "hapax-github-repo-create"),
            "hapax-example",
            "--private",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert proc.returncode == 0
    assert log.read_text(encoding="utf-8").splitlines() == [
        "repo",
        "create",
        "hapax-systems/hapax-example",
        "--private",
    ]


def test_unpinned_action_uses_flags_tags_and_missing_refs() -> None:
    audit = _load(
        "hapax_github_repo_standards_audit", REPO / "scripts/hapax-github-repo-standards-audit.py"
    )

    workflow = """
    steps:
      - uses: actions/checkout@f43a0e5ff2bd294095638e18286ca9a3d1956744
      - uses: astral-sh/setup-uv@v7
      - uses: codecov/codecov-action
      - uses: ./local-action
      - uses: docker://rhysd/actionlint:latest
    """

    assert audit.unpinned_action_uses(workflow) == [
        "astral-sh/setup-uv@v7",
        "codecov/codecov-action",
    ]


def test_unpinned_container_images_flags_floating_images() -> None:
    audit = _load(
        "hapax_github_repo_standards_audit_container",
        REPO / "scripts/hapax-github-repo-standards-audit.py",
    )

    workflow = """
    jobs:
      semgrep:
        container:
          image: semgrep/semgrep
      pinned:
        container:
          image: semgrep/semgrep@sha256:06938c1f365d3f67b8cedd8bc117607ae64253f88a0e768e9da9408548927dd6
    """

    assert audit.unpinned_container_images(workflow) == ["semgrep/semgrep"]


def test_unpinned_docker_uses_flags_tag_refs_but_not_digests() -> None:
    audit = _load(
        "hapax_github_repo_standards_audit_docker",
        REPO / "scripts/hapax-github-repo-standards-audit.py",
    )

    digest = "sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667"
    workflow = f"""
    steps:
      - uses: actions/checkout@f43a0e5ff2bd294095638e18286ca9a3d1956744
      - uses: docker://rhysd/actionlint:1.7.12
      - uses: docker://rhysd/actionlint@{digest}
    """

    assert audit.unpinned_docker_uses(workflow) == ["docker://rhysd/actionlint:1.7.12"]


def test_startup_failure_streak_counts_only_the_head_run() -> None:
    audit = _load(
        "hapax_github_repo_standards_audit_streak",
        REPO / "scripts/hapax-github-repo-standards-audit.py",
    )

    assert audit.startup_failure_streak([]) == 0
    assert audit.startup_failure_streak(["startup_failure"] * 3) == 3
    # Recovered: the outage is history, not a current fault.
    assert audit.startup_failure_streak(["success", "startup_failure", "startup_failure"]) == 0
    assert audit.startup_failure_streak(["startup_failure", "success", "startup_failure"]) == 1


def test_audit_workflow_health_flags_dead_workflow(monkeypatch: pytest.MonkeyPatch) -> None:
    audit = _load(
        "hapax_github_repo_standards_audit_health",
        REPO / "scripts/hapax-github-repo-standards-audit.py",
    )

    monkeypatch.setattr(
        audit,
        "active_workflows",
        lambda repo: [
            {"id": 1, "path": ".github/workflows/security-extras.yml"},
            {"id": 2, "path": ".github/workflows/ci.yml"},
            {"id": 3, "path": ".github/workflows/brand-new.yml"},
        ],
    )
    runs = {
        1: ["startup_failure", "startup_failure", "startup_failure"],
        2: ["success", "success", "startup_failure"],
        3: ["startup_failure"],  # too few runs to earn the verdict
    }
    monkeypatch.setattr(audit, "recent_run_conclusions", lambda repo, wid, limit: runs[wid][:limit])

    messages = [f.message for f in audit.audit_workflow_health("hapax-systems/hapax-council")]

    assert len(messages) == 1
    assert messages[0].startswith(
        ".github/workflows/security-extras.yml is active but dead: 3 consecutive startup_failure"
    )


def test_audit_repo_reports_owner_and_workflow_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    audit = _load(
        "hapax_github_repo_standards_audit_repo",
        REPO / "scripts/hapax-github-repo-standards-audit.py",
    )

    files = {
        ".github/workflows/ci.yml": "name: CI\njobs:\n  all-green:\n    runs-on: ubuntu-latest\n",
        ".coderabbit.yaml": "request_changes_workflow: true\n",
        ".github/workflows/semgrep.yml": "name: Semgrep\n",
    }

    monkeypatch.setattr(audit, "gh_ok", lambda *args: args[-1] in audit.REQUIRED_FILES)
    monkeypatch.setattr(audit, "read_file", lambda repo, path: files.get(path))
    # Run health needs the live Actions API; covered by its own test above.
    monkeypatch.setattr(audit, "audit_workflow_health", lambda repo: [])
    monkeypatch.setattr(audit, "default_branch", lambda repo: "main")
    monkeypatch.setattr(audit, "workflow_paths", lambda repo, ref: [".github/workflows/ci.yml"])
    monkeypatch.setattr(
        audit,
        "read_file_at_ref",
        lambda repo, path, ref: (
            "steps:\n  - uses: astral-sh/setup-uv@v7\ncontainer:\n  image: semgrep/semgrep\n"
        ),
    )

    messages = [finding.message for finding in audit.audit_repo("ryanklee/hapax-example")]

    assert "owner must be hapax-systems, got ryanklee" in messages
    assert "personal-account owner ryanklee is forbidden" in messages
    assert ".coderabbit.yaml must keep request_changes_workflow: false" in messages
    assert "Semgrep workflow must use SEMGREP_APP_TOKEN" in messages
    assert ".github/workflows/ci.yml has unpinned action ref astral-sh/setup-uv@v7" in messages
    assert ".github/workflows/ci.yml has unpinned container image semgrep/semgrep" in messages
