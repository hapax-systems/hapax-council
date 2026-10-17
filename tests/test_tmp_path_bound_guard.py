"""M117: no default-suite test may fill the host tmpfs.

On 2026-09-25 one test (the real-activator witness) left 7.7 GB of uv/CUDA wheels in
``/tmp/pytest-of-hapax``. On appendix ``/tmp`` is an 8 GB tmpfs (RAM): every lane's tests failed
with ENOSPC, and agent sessions lost all tool output. These tests pin the two defenses: the
suite guard that fails a test whose ``tmp_path`` owns more than its budget, and the activator
test's sandbox, which reuses the host uv cache by hardlink and skips on tmpfs.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests import tmp_path_budget as budget

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.write(os.urandom(size))
    return path


# --- owned bytes: what the tree actually costs the filesystem --------------------------------


def test_a_file_over_the_budget_is_a_violation(tmp_path: Path) -> None:
    root = tmp_path / "scratch"
    _write(root / "big.bin", 256 * 1024)
    message = budget.budget_violation(root, budget_bytes=64 * 1024, nodeid="t::big")
    assert message is not None
    assert "t::big" in message
    assert "big.bin" in message


def test_a_tree_under_the_budget_is_not_a_violation(tmp_path: Path) -> None:
    root = tmp_path / "scratch"
    _write(root / "small.bin", 8 * 1024)
    assert budget.budget_violation(root, budget_bytes=64 * 1024, nodeid="t::small") is None


def test_a_hardlink_to_an_inode_outside_the_tree_costs_nothing(tmp_path: Path) -> None:
    # The activator's venv, hardlinked from the host uv cache, allocates no new blocks.
    cache = _write(tmp_path / "cache" / "wheel.so", 256 * 1024)
    root = tmp_path / "scratch"
    root.mkdir()
    os.link(cache, root / "wheel.so")
    assert budget.owned_bytes(root) == 0
    # the same inode, seen from a root that holds every link, is owned once
    assert budget.owned_bytes(tmp_path) >= 256 * 1024
    assert budget.owned_bytes(tmp_path) < 2 * 256 * 1024


def test_hardlinks_inside_the_tree_are_counted_once(tmp_path: Path) -> None:
    root = tmp_path / "scratch"
    first = _write(root / "a.bin", 128 * 1024)
    os.link(first, root / "b.bin")
    owned = budget.owned_bytes(root)
    assert 128 * 1024 <= owned < 2 * 128 * 1024


def test_a_symlink_is_never_followed(tmp_path: Path) -> None:
    outside = _write(tmp_path / "outside" / "big.bin", 256 * 1024)
    root = tmp_path / "scratch"
    root.mkdir()
    (root / "link").symlink_to(outside)
    (root / "dirlink").symlink_to(outside.parent, target_is_directory=True)
    assert budget.owned_bytes(root) < 64 * 1024


def test_a_missing_tree_owns_nothing(tmp_path: Path) -> None:
    assert budget.owned_bytes(tmp_path / "never-created") == 0


# --- filesystem type, from mountinfo --------------------------------------------------------

MOUNTINFO = textwrap.dedent(
    """\
    22 1 8:2 / / rw,relatime shared:1 - ext4 /dev/sda2 rw
    40 22 0:35 / /tmp rw,nosuid,nodev shared:17 - tmpfs tmpfs rw,size=8388608k
    41 22 259:1 / /store-fast rw,relatime shared:20 - xfs /dev/nvme1n1p1 rw
    42 40 0:36 / /tmp/deeper rw shared:21 - xfs /dev/other rw
    """
)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/tmp/pytest-of-someone/pytest-1/test0", "tmpfs"),
        ("/store-fast/tmp/hapax-wt/dev17-pytest/x", "xfs"),
        ("/var/lib/x", "ext4"),
        ("/tmp/deeper/x", "xfs"),  # the longest mount prefix wins
        ("/tmpfoo/x", "ext4"),  # a prefix must end at a path component
    ],
)
def test_filesystem_type_takes_the_longest_mount_prefix(path: str, expected: str) -> None:
    assert budget.filesystem_type(Path(path), mountinfo_text=MOUNTINFO) == expected


def test_mountinfo_escapes_are_decoded() -> None:
    text = (
        "50 22 0:40 / /mnt/with\\040space rw - tmpfs tmpfs rw\n"
        "22 1 8:2 / / rw - ext4 /dev/sda2 rw\n"
    )
    assert budget.filesystem_type(Path("/mnt/with space/x"), mountinfo_text=text) == "tmpfs"


# --- the activator test's sandbox -----------------------------------------------------------


def test_the_activator_sandbox_reuses_the_host_uv_cache_by_hardlink(tmp_path: Path) -> None:
    from tests.scripts import test_determination_producer_commands as producer

    home = tmp_path / "home"
    env = producer._activator_sandbox_env(
        home=home,
        canonical=tmp_path / "canonical",
        state=tmp_path / "state",
        local_bin=tmp_path / "bin",
        host_uv_cache=Path("/store-fast/cache/uv"),
    )
    assert env["HOME"] == str(home)
    assert env["UV_CACHE_DIR"] == "/store-fast/cache/uv"
    assert env["UV_LINK_MODE"] == "hardlink"


def test_the_activator_sandbox_without_a_host_cache_keeps_uv_defaults(tmp_path: Path) -> None:
    from tests.scripts import test_determination_producer_commands as producer

    env = producer._activator_sandbox_env(
        home=tmp_path / "home",
        canonical=tmp_path / "canonical",
        state=tmp_path / "state",
        local_bin=tmp_path / "bin",
        host_uv_cache=None,
    )
    assert env.get("UV_CACHE_DIR") == os.environ.get("UV_CACHE_DIR")


@pytest.mark.parametrize("fstype", ["tmpfs", "ramfs"])
def test_the_activator_refuses_to_materialise_a_release_in_ram(fstype: str) -> None:
    from tests.scripts import test_determination_producer_commands as producer

    reason = producer._activator_ram_skip_reason(fstype)
    assert reason is not None
    assert fstype in reason
    assert "--basetemp" in reason


@pytest.mark.parametrize("fstype", ["xfs", "ext4", "btrfs", "overlay"])
def test_the_activator_runs_on_disk(fstype: str) -> None:
    from tests.scripts import test_determination_producer_commands as producer

    assert producer._activator_ram_skip_reason(fstype) is None


# --- the guard is wired into the suite ------------------------------------------------------


def _run_generated_suite(
    tmp_path: Path, body: str, *, default_budget: int | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a generated test file under the real ``tests/conftest.py`` guard.

    The guard is imported by name: a star import would skip its underscore name, and the
    generated suite would then run unguarded and pass vacuously.
    """

    suite = tmp_path / "suite"
    suite.mkdir()
    conftest = (
        "from tests import tmp_path_budget\n"
        "from tests.conftest import _enforce_tmp_path_budget, pytest_configure  # noqa: F401\n"
    )
    if default_budget is not None:
        # lower the default the fixture reads at teardown, so no test writes 512 MiB to prove it
        conftest += f"tmp_path_budget.DEFAULT_TMP_PATH_BUDGET_BYTES = {default_budget}\n"
    (suite / "conftest.py").write_text(conftest, encoding="utf-8")
    (suite / "test_generated.py").write_text(textwrap.dedent(body), encoding="utf-8")
    pythonpath = os.pathsep.join(p for p in (str(REPO_ROOT), os.environ.get("PYTHONPATH")) if p)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--rootdir",
            str(suite),
            "--basetemp",
            str(tmp_path / "inner-basetemp"),
            str(suite / "test_generated.py"),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": pythonpath},
        cwd=suite,
        timeout=300,
    )


def test_the_suite_guard_fails_a_test_over_its_budget(tmp_path: Path) -> None:
    result = _run_generated_suite(
        tmp_path,
        """
        import os
        import pytest

        @pytest.mark.tmp_path_budget(64 * 1024)
        def test_writes_too_much(tmp_path):
            (tmp_path / "big.bin").write_bytes(os.urandom(512 * 1024))

        @pytest.mark.tmp_path_budget(64 * 1024)
        def test_writes_a_little(tmp_path):
            (tmp_path / "small.bin").write_bytes(os.urandom(4 * 1024))
        """,
    )
    out = result.stdout + result.stderr
    assert result.returncode != 0, out
    # the body passes; the guard errors the over-budget test at teardown, and only that one
    assert "ERROR at teardown of test_writes_too_much" in out, out
    assert "test_writes_a_little" not in out.split("short test summary info")[-1], out
    assert "2 passed, 1 error" in out, out
    assert "tmp_path owns" in out
    # the over-budget tree is removed, so a failed run cannot keep holding the tmpfs
    assert not list((tmp_path / "inner-basetemp").glob("test_writes_too_much*/big.bin"))


def test_the_suite_guard_applies_the_default_budget_without_a_marker(tmp_path: Path) -> None:
    result = _run_generated_suite(
        tmp_path,
        """
        import os

        def test_default_budget_exceeded(tmp_path):
            (tmp_path / "big.bin").write_bytes(os.urandom(512 * 1024))

        def test_default_budget_kept(tmp_path):
            (tmp_path / "small.bin").write_bytes(os.urandom(4 * 1024))
        """,
        default_budget=64 * 1024,
    )
    out = result.stdout + result.stderr
    assert result.returncode != 0, out
    assert "ERROR at teardown of test_default_budget_exceeded" in out, out
    assert "2 passed, 1 error" in out, out
    assert "tmp_path owns" in out


def test_the_default_budget_is_half_a_gibibyte() -> None:
    assert budget.DEFAULT_TMP_PATH_BUDGET_BYTES == 512 * 1024 * 1024
