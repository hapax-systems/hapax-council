"""The shell resolver must agree with the Python one, case for case.

Two implementations of one rule is a hazard, and this is its mitigation. The failure mode without
this pin is not a crash: it is a SPLIT SSOT. A gate consults one vault while a writer updates
another, both succeed, and nothing anywhere reports the disagreement — the same shape as the
twenty independent hardcodes this resolver replaces, only harder to find because it looks
centralised.

So every case is asserted twice: once against the expected value, once against the other
implementation's answer for the identical environment.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FRAGMENT = REPO_ROOT / "hooks/scripts/cc-task-root.sh"


def _shell(env: dict[str, str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    fn = "cc_task_root_resolve"
    script = (
        f'. "{FRAGMENT}"\n'
        f"if {fn}; then\n"
        '  printf "%s\\n%s\\n%s\\n" "$CC_TASK_ROOT" "$CC_TASK_ROOT_SOURCE" "$CC_TASK_ROOT_EXISTS"\n'
        "else\n"
        "  exit $?\n"
        "fi\n"
    )
    return subprocess.run(
        ["bash", "-c", script],
        text=True,
        capture_output=True,
        check=False,
        env=env,
        cwd=cwd,
    )


def _python(env: dict[str, str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    script = (
        "from shared.cc_task_root import resolve_cc_task_root, CcTaskRootUnavailable\n"
        "import sys\n"
        "try:\n"
        "    r = resolve_cc_task_root()\n"
        "except CcTaskRootUnavailable as exc:\n"
        "    print(exc, file=sys.stderr)\n"
        "    sys.exit(2)\n"
        "print(r.path)\nprint(r.source.value)\nprint(1 if r.exists else 0)\n"
    )
    return subprocess.run(
        ["python3", "-c", script],
        text=True,
        capture_output=True,
        check=False,
        env={**env, "PYTHONPATH": str(REPO_ROOT)},
        cwd=cwd or REPO_ROOT,
    )


def _env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    base = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path / "home"),
    }
    base.update(overrides)
    return base


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault" / "20-projects" / "hapax-cc-tasks"
    root.mkdir(parents=True)
    return tmp_path / "vault"


def _assert_agree(
    env: dict[str, str], *, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    sh = _shell(env, cwd=cwd)
    py = _python(env, cwd=cwd)
    assert sh.returncode == py.returncode, (
        f"shell exited {sh.returncode}, python {py.returncode}\n"
        f"shell stderr: {sh.stderr}\npython stderr: {py.stderr}"
    )
    if sh.returncode == 0:
        assert sh.stdout.split() == py.stdout.split(), (
            f"the two resolvers disagree about the SSOT\nshell: {sh.stdout!r}\n"
            f"python: {py.stdout!r}"
        )
    return sh


def test_they_agree_on_the_personal_vault_case(tmp_path: Path, vault: Path) -> None:
    result = _assert_agree(_env(tmp_path, PERSONAL_VAULT_PATH=str(vault)))

    lines = result.stdout.split()
    assert lines[0] == str(vault / "20-projects" / "hapax-cc-tasks")
    assert lines[1] == "personal_vault"
    assert lines[2] == "1"


def test_they_agree_on_the_override_case(tmp_path: Path, vault: Path) -> None:
    root = tmp_path / "elsewhere"
    root.mkdir()

    result = _assert_agree(
        _env(tmp_path, PERSONAL_VAULT_PATH=str(vault), HAPAX_CC_TASKS_ROOT=str(root))
    )

    lines = result.stdout.split()
    assert lines[0] == str(root)
    assert lines[1] == "override"


def test_they_agree_that_a_bad_override_refuses(tmp_path: Path, vault: Path) -> None:
    env = _env(
        tmp_path,
        PERSONAL_VAULT_PATH=str(vault),
        HAPAX_CC_TASKS_ROOT=str(tmp_path / "nope"),
    )

    sh = _shell(env)
    py = _python(env)

    assert sh.returncode == 2
    assert py.returncode == 2
    assert "Refusing rather than falling back" in sh.stderr
    assert "Refusing rather than falling back" in py.stderr
    assert str(vault) not in sh.stdout, "the shell resolver fell back to the vault default"


def test_they_agree_on_the_genesis_case(tmp_path: Path) -> None:
    """Absent-at-default resolves and reports; it does not refuse. Both must do the same thing,
    because this is the state first-init runs in."""
    result = _assert_agree(_env(tmp_path, PERSONAL_VAULT_PATH=str(tmp_path / "not-yet")))

    lines = result.stdout.split()
    assert lines[1] == "personal_vault"
    assert lines[2] == "0"


def test_they_agree_that_whitespace_is_not_an_override(tmp_path: Path, vault: Path) -> None:
    result = _assert_agree(
        _env(tmp_path, PERSONAL_VAULT_PATH=str(vault), HAPAX_CC_TASKS_ROOT="   ")
    )

    assert result.stdout.split()[1] == "personal_vault"


def test_they_agree_that_a_file_is_not_a_root(tmp_path: Path, vault: Path) -> None:
    target = tmp_path / "notes.md"
    target.write_text("not a vault\n", encoding="utf-8")

    env = _env(tmp_path, PERSONAL_VAULT_PATH=str(vault), HAPAX_CC_TASKS_ROOT=str(target))
    sh = _shell(env)
    py = _python(env)

    assert sh.returncode == 2
    assert py.returncode == 2


def test_they_agree_when_the_vault_knob_is_set_but_empty(tmp_path: Path, vault: Path) -> None:
    """The divergence the reviewers found — and my agreement test's input set had no case for it.

    `os.environ.get(k, default)` returns "" for an exported-but-empty variable, while the shell's
    `${k:-default}` substitutes the default. Python therefore built a RELATIVE `Path("")` root and
    the shell built one under $HOME: a silent split SSOT, which is exactly the hazard these two
    implementations were paired to prevent. The pairing was right; its inputs were incomplete.
    """
    result = _assert_agree(_env(tmp_path, PERSONAL_VAULT_PATH=""))

    assert result.stdout.split()[0].startswith("/"), "an empty knob produced a relative root"


def test_they_agree_on_a_tilde_override(tmp_path: Path) -> None:
    """The shell cannot expand a tilde arriving inside a variable; Python's expanduser can.

    Left alone, `-d` fails on a root that exists and the two resolvers answer differently.
    """
    home = tmp_path / "home"
    (home / "tilde-tasks").mkdir(parents=True)

    _assert_agree(_env(tmp_path, HAPAX_CC_TASKS_ROOT="~/tilde-tasks"))


def test_they_agree_on_a_tilde_vault(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "v" / "20-projects" / "hapax-cc-tasks").mkdir(parents=True)

    _assert_agree(_env(tmp_path, PERSONAL_VAULT_PATH="~/v"))


def test_they_agree_that_a_named_user_tilde_override_refuses(tmp_path: Path, vault: Path) -> None:
    """Python expanduser() accepts ~user; the shell case only handles ~ and ~/.

    Expanding on one side and leaving a literal on the other is a silent split SSOT.
    Both sides refuse the form rather than inventing ~user expansion the shell cannot
    perform portably.
    """
    env = _env(
        tmp_path,
        PERSONAL_VAULT_PATH=str(vault),
        HAPAX_CC_TASKS_ROOT="~nobody/tasks",
    )
    sh = _shell(env)
    py = _python(env)

    assert sh.returncode == 2
    assert py.returncode == 2
    assert "named-user tilde" in sh.stderr
    assert "named-user tilde" in py.stderr
    assert str(vault) not in sh.stdout, "the shell resolver fell back to the vault default"


def test_they_agree_that_a_relative_override_refuses(tmp_path: Path, vault: Path) -> None:
    """A relative override is a different directory per cwd. Refuse, do not anchor."""
    env = _env(tmp_path, PERSONAL_VAULT_PATH=str(vault), HAPAX_CC_TASKS_ROOT="vault")
    here = tmp_path / "here"
    there = tmp_path / "there"
    here.mkdir()
    there.mkdir()
    (here / "vault").mkdir()
    (there / "vault").mkdir()

    for cwd in (here, there):
        sh = _shell(env, cwd=cwd)
        py = _python(env, cwd=cwd)
        assert sh.returncode == 2, sh.stderr
        assert py.returncode == 2, py.stderr
        assert "is relative" in sh.stderr
        assert "is relative" in py.stderr
        assert str(vault) not in sh.stdout


def test_they_agree_that_a_relative_vault_knob_refuses(tmp_path: Path) -> None:
    env = _env(tmp_path, PERSONAL_VAULT_PATH="somewhere")
    sh = _shell(env, cwd=tmp_path)
    py = _python(env, cwd=tmp_path)
    assert sh.returncode == 2
    assert py.returncode == 2
    assert "is relative" in sh.stderr
    assert "is relative" in py.stderr


def test_they_agree_that_a_named_user_tilde_vault_refuses(tmp_path: Path) -> None:
    env = _env(tmp_path, PERSONAL_VAULT_PATH="~nobody/vault")
    sh = _shell(env)
    py = _python(env)

    assert sh.returncode == 2
    assert py.returncode == 2
    assert "named-user tilde" in sh.stderr
    assert "named-user tilde" in py.stderr


def test_the_fragment_is_sourced_not_executed() -> None:
    """No shebang, and not executable: it defines variables in its caller's scope and does
    nothing as a child process."""
    assert not FRAGMENT.read_text(encoding="utf-8").startswith("#!")
    assert not os.access(FRAGMENT, os.X_OK)
