from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cc-close"


def _write_task(
    vault_root: Path,
    state: str,
    filename: str,
    task_id: str,
    *,
    status: str = "in_progress",
) -> Path:
    path = vault_root / state / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        textwrap.dedent(
            f"""\
            ---
            type: cc-task
            task_id: {task_id}
            title: "{task_id}"
            status: {status}
            completed_at:
            updated_at:
            pr:
            ---

            # {task_id}

            ## Session log
            """
        ),
        encoding="utf-8",
    )
    return path


def _run_close(home: Path, task_id: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["HAPAX_AGENT_ROLE"] = "test-role"
    return subprocess.run(
        ["bash", str(SCRIPT), task_id, "--status", "withdrawn"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _vault(home: Path) -> Path:
    root = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"
    (root / "active").mkdir(parents=True, exist_ok=True)
    (root / "closed").mkdir(parents=True, exist_ok=True)
    return root


def test_prefix_collision_does_not_block_distinct_closed_task(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "active", "foo.md", "foo")
    _write_task(vault, "closed", "foo-bar.md", "foo-bar", status="done")

    result = _run_close(home, "foo")

    assert result.returncode == 0, result.stderr
    assert not (vault / "active" / "foo.md").exists()
    assert (vault / "closed" / "foo.md").exists()
    assert (vault / "closed" / "foo-bar.md").exists()


def test_true_exact_duplicate_is_blocked(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "active", "foo.md", "foo")
    _write_task(vault, "closed", "foo.md", "foo", status="done")

    result = _run_close(home, "foo")

    assert result.returncode == 8
    assert "closed task duplicate" in result.stderr
    assert (vault / "active" / "foo.md").exists()


def test_descriptor_style_true_duplicate_is_blocked(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "active", "foo-descriptor.md", "foo")
    _write_task(vault, "closed", "foo-other.md", "foo", status="done")

    result = _run_close(home, "foo")

    assert result.returncode == 8
    assert "closed task duplicate" in result.stderr
    assert (vault / "active" / "foo-descriptor.md").exists()


def test_no_closed_tasks_allows_close(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = _vault(home)
    _write_task(vault, "active", "foo.md", "foo")

    result = _run_close(home, "foo")

    assert result.returncode == 0, result.stderr
    assert not (vault / "active" / "foo.md").exists()
    assert (vault / "closed" / "foo.md").exists()


class TestTheDeploymentLayoutsCcCloseIsRunFrom:
    """cc-close must work where it is actually installed, or refuse legibly.

    Two layouts, both documented and both broken until review round 27:

    1. A host whose PATH `python3` lacks PyYAML, with dependencies in the repo
       virtualenv — the estate's own lane clones. cc-close read frontmatter with
       bare `python3` while the parser it imports needs yaml; `|| true` swallowed
       the ImportError, the empty result read as "no such note", and a live valid
       task was reported **"already closed?"** (codex-1).
    2. The install symlink cc-close's own header recommends
       (`ln -sf .../scripts/cc-close ~/.local/bin/cc-close`). SCRIPT_DIR came from
       `$0` without resolving the link, so every sibling resolved against
       `~/.local` — which holds no `hooks/`, no `shared/` and no `.venv`. Measured
       2026-09-15: `~/.local/hooks/scripts/cc-task-root.sh` does not exist, so the
       documented install refused at its first helper.
    """

    def _python3_without_yaml(self, home: Path) -> Path:
        """A real interpreter that cannot import yaml, earlier on PATH."""
        blocker = home / "noyaml"
        blocker.mkdir(parents=True, exist_ok=True)
        (blocker / "yaml.py").write_text(
            "raise ImportError('No module named yaml (test: deps only in .venv)')\n",
            encoding="utf-8",
        )
        stub_dir = home / "stub-bin"
        stub_dir.mkdir(parents=True, exist_ok=True)
        stub = stub_dir / "python3"
        # Strips -I/-S so PYTHONPATH applies; otherwise isolated mode would ignore
        # the shadowing module and the stub would silently be a normal python3 —
        # a test that passes against the defect.
        stub.write_text(
            "#!/bin/sh\n"
            'args=""\n'
            'for a in "$@"; do\n'
            '  case "$a" in -I|-S) ;; *) args="$args \\"$a\\"" ;; esac\n'
            "done\n"
            f'PYTHONPATH="{blocker}" exec /usr/bin/python3 $(eval echo $args)\n',
            encoding="utf-8",
        )
        stub.chmod(0o755)
        return stub_dir

    def test_a_path_python3_without_pyyaml_does_not_misreport_the_note(
        self, tmp_path: Path
    ) -> None:
        home = tmp_path / "home"
        vault = _vault(home)
        note = _write_task(vault, "active", "t-noyaml.md", "t-noyaml")
        stub_dir = self._python3_without_yaml(home)

        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{stub_dir}:{env.get('PATH', '')}"
        env["HAPAX_AGENT_ROLE"] = "test-role"
        result = subprocess.run(
            ["bash", str(SCRIPT), "t-noyaml", "--status", "withdrawn"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        assert "already closed?" not in result.stderr, (
            "a present, valid note was reported as missing because the frontmatter "
            f"parser could not be imported\n{result.stderr}"
        )
        # The repo virtualenv is right there, so the close should simply work.
        assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
        assert not note.exists()
        assert (vault / "closed" / "t-noyaml.md").exists()

    def test_an_unusable_interpreter_refuses_as_a_dependency_problem(self, tmp_path: Path) -> None:
        """No virtualenv to fall back on: the refusal must name the real cause.

        A copy of cc-close in a tree with no `.venv` forces the FALLBACK
        interpreter, and a PATH `python3` that cannot import yaml makes that
        fallback unusable. Both halves are needed: under `uv run` the ambient
        `python3` IS the project virtualenv, so the fake tree alone closed
        successfully and proved nothing.

        What must NOT happen is the note being called missing or malformed — the
        notes were never read.
        """
        import shutil

        home = tmp_path / "home"
        vault = _vault(home)
        note = _write_task(vault, "active", "t-nodeps.md", "t-nodeps")
        stub_dir = self._python3_without_yaml(home)

        fake_root = tmp_path / "installed"
        (fake_root / "scripts").mkdir(parents=True)
        (fake_root / "hooks" / "scripts").mkdir(parents=True)
        shutil.copy2(SCRIPT, fake_root / "scripts" / "cc-close")
        shutil.copy2(
            REPO_ROOT / "hooks" / "scripts" / "cc-task-root.sh",
            fake_root / "hooks" / "scripts" / "cc-task-root.sh",
        )

        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = f"{stub_dir}:{env.get('PATH', '')}"
        env["HAPAX_AGENT_ROLE"] = "test-role"
        result = subprocess.run(
            ["bash", str(fake_root / "scripts" / "cc-close"), "t-nodeps", "--status", "withdrawn"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode != 0
        assert note.exists(), "the note was touched by a run that could not read it"
        assert "already closed?" not in result.stderr, result.stderr
        assert "declares no readable task_id" not in result.stderr, (
            "an unreadable PARSER was reported as an unreadable NOTE — the repair "
            f"the operator is sent to do is the wrong one\n{result.stderr}"
        )
        assert (
            "dependency-unavailable" in result.stderr or "could not be imported" in result.stderr
        ), result.stderr

    def test_the_documented_install_symlink_works(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        vault = _vault(home)
        note = _write_task(vault, "active", "t-symlink.md", "t-symlink")

        bindir = home / ".local" / "bin"
        bindir.mkdir(parents=True)
        link = bindir / "cc-close"
        link.symlink_to(SCRIPT)

        env = os.environ.copy()
        env["HOME"] = str(home)
        env["HAPAX_AGENT_ROLE"] = "test-role"
        result = subprocess.run(
            ["bash", str(link), "t-symlink", "--status", "withdrawn"],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        assert result.returncode == 0, (
            "cc-close's own header documents this install and it refused: "
            f"{result.stdout}\n{result.stderr}"
        )
        assert not note.exists()
        assert (vault / "closed" / "t-symlink.md").exists()
