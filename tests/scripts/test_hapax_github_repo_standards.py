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
    monkeypatch.setattr(audit, "default_branch", lambda repo: "main")
    monkeypatch.setattr(audit, "workflow_paths", lambda repo, ref: [".github/workflows/ci.yml"])
    monkeypatch.setattr(
        audit,
        "read_file_at_ref",
        lambda repo, path, ref: "steps:\n  - uses: astral-sh/setup-uv@v7\n",
    )

    messages = [finding.message for finding in audit.audit_repo("ryanklee/hapax-example")]

    assert "owner must be hapax-systems, got ryanklee" in messages
    assert "personal-account owner ryanklee is forbidden" in messages
    assert ".coderabbit.yaml must keep request_changes_workflow: false" in messages
    assert "Semgrep workflow must use SEMGREP_APP_TOKEN" in messages
    assert ".github/workflows/ci.yml has unpinned action ref astral-sh/setup-uv@v7" in messages
