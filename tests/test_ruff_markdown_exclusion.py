"""Regression pin: `ruff format` must never own markdown in this repo.

WHY THIS EXISTS. On 2026-07-11 hapax-council merged its last PR for 23 days. The cause was not a
commit: `.github/workflows/ci.yml` SHA-pins the ruff ACTION but passed no `version:`, so CI installed
whatever ruff was newest. Ruff 0.16 promoted MARKDOWN formatting out of preview, ~24 untouched docs
went red, `lint` failed, the REQUIRED `all-green` check failed with it, and the merge queue sealed
with 75 PRs behind it.

Bisected on files byte-identical to origin/main at the time:
    ruff 0.15.3 -> "Markdown formatting is experimental, enable preview mode."
    ruff 0.16.1 -> "2 files would be reformatted"

The fix declares markdown out of scope in CONFIG and pins the tool. These tests exist because the
original review of that fix objected — correctly — that it "adds no test that invokes Ruff through
the CI-equivalent path and proves Markdown is excluded". Without that, deleting one `exclude` line
silently re-arms a 23-day outage, which is precisely how the outage started: a configuration change
nobody was watching.
"""

from __future__ import annotations

import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Every ruff config root in the tree. The three package configs are NOT redundant: each carries its
#: own [tool.ruff], and ruff's hierarchical discovery makes it the config root for its own subtree,
#: so a root-level exclude cannot reach them. Measured during the fix: root-config-only still left 3
#: files flagged (packages/{agentgov,hapax-refusals,hapax-swarm}/README.md).
CONFIG_ROOTS = (
    ("ruff.toml", ("format", "exclude")),
    ("packages/agentgov/pyproject.toml", ("tool", "ruff", "extend-exclude")),
    ("packages/hapax-refusals/pyproject.toml", ("tool", "ruff", "extend-exclude")),
    ("packages/hapax-swarm/pyproject.toml", ("tool", "ruff", "extend-exclude")),
)


def _dig(data: dict, path: tuple[str, ...]):
    for key in path:
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


@pytest.mark.parametrize(("rel_path", "key_path"), CONFIG_ROOTS)
def test_every_ruff_config_root_excludes_markdown(rel_path: str, key_path: tuple[str, ...]) -> None:
    """Each config root must declare the markdown exclusion itself."""
    config = REPO_ROOT / rel_path
    assert config.is_file(), f"{rel_path} missing — ruff config roots changed; update this pin"
    excludes = _dig(tomllib.loads(config.read_text(encoding="utf-8")), key_path)
    assert excludes is not None, (
        f"{rel_path} no longer declares {'.'.join(key_path)}. Ruff would resume formatting markdown "
        f"in this subtree; that sealed the merge queue for 23 days on 2026-07-11."
    )
    assert any(str(pattern).endswith("*.md") for pattern in excludes), (
        f"{rel_path}: {'.'.join(key_path)} = {excludes!r} does not cover '*.md'"
    )


def test_ci_pins_the_ruff_version_not_just_the_action() -> None:
    """A SHA-pinned action that installs an unpinned tool is only half pinned."""
    workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    action_uses = workflow.count("astral-sh/ruff-action@")
    version_pins = workflow.count('version: "0.16')
    assert action_uses > 0, "ruff-action no longer referenced — update this pin"
    assert version_pins >= action_uses, (
        f"{action_uses} ruff-action step(s) but only {version_pins} version pin(s). An unpinned "
        f"ruff can change this gate's behaviour with no commit here — that is the 2026-07-11 outage."
    )


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff not resolvable")
def test_ruff_format_check_leaves_markdown_alone() -> None:
    """The CI-equivalent invocation must be clean across the whole tree.

    This is the half a config assertion cannot give you: it proves the DISCOVERY chain works, not
    merely that the key is spelled correctly somewhere.

    NOTE THE INVOCATION SHAPE, which is load-bearing and got this test wrong on the first attempt.
    Ruff applies exclude patterns during PATH DISCOVERY; a file named EXPLICITLY on the command line
    is formatted regardless (absent --force-exclude). So `ruff format --check some/README.md` exits
    non-zero even with a correct exclusion, and proves nothing about CI. The workflow passes no
    paths at all — `args: "format --check"` — so the test must do the same and let discovery run.
    """
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["ruff", "format", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, (
        "ruff format --check is not clean on the tree — markdown exclusion is declared but not "
        "reaching the discovery path. This is the 2026-07-11 merge-queue seal.\n"
        f"stdout: {result.stdout[-1200:]}\nstderr: {result.stderr[-400:]}"
    )
    assert ".md" not in result.stdout, (
        f"a markdown file appeared in ruff format output:\n{result.stdout[-800:]}"
    )
