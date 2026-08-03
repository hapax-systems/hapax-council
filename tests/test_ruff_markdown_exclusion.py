"""Regression pin: `ruff format` must never own markdown in this repo.

WHY THIS EXISTS. On 2026-07-11 hapax-council stopped merging for 23 days. Not because of a commit:
`.github/workflows/ci.yml` SHA-pins the ruff ACTION but passed no `version:`, so CI installed
whatever ruff was newest. Ruff 0.16 promoted MARKDOWN formatting out of preview, untouched docs went
red, `lint` failed, the REQUIRED `all-green` failed with it, and the merge queue sealed.

The fix declares markdown out of scope in config and pins the tool. These tests are the pin on the
fix. Everything here is DISCOVERED rather than enumerated, because the defect is structural: ruff's
hierarchical discovery makes ANY file carrying its own ruff config the config root for its subtree,
so a config root added tomorrow must be caught by the same assertion that catches today's.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".ruff_cache", "target", "dist"}


def _iter_config_roots() -> list[tuple[Path, tuple[str, ...]]]:
    """Every file in the tree that makes its directory a ruff config root.

    DISCOVERED, not listed. An earlier version of this test hard-coded four known paths; review
    pointed out that a fifth package carrying [tool.ruff] would silently reintroduce the outage.
    """
    found: list[tuple[Path, tuple[str, ...]]] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in {"ruff.toml", ".ruff.toml"}:
            found.append((path, ("format", "exclude")))
        elif path.name == "pyproject.toml":
            try:
                data = tomllib.loads(path.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError):
                continue
            if isinstance(data.get("tool"), dict) and "ruff" in data["tool"]:
                found.append((path, ("tool", "ruff", "extend-exclude")))
    return found


def _dig(data: object, path: tuple[str, ...]) -> object | None:
    for key in path:
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


def _excludes_markdown(config: Path, key_path: tuple[str, ...]) -> bool:
    data = tomllib.loads(config.read_text(encoding="utf-8"))
    # A root ruff.toml may use either [format].exclude or a top-level extend-exclude.
    for candidate in (key_path, ("extend-exclude",), ("tool", "ruff", "extend-exclude")):
        value = _dig(data, candidate)
        if isinstance(value, list) and any(str(p).endswith("*.md") for p in value):
            return True
    return False


def test_every_discovered_ruff_config_root_excludes_markdown() -> None:
    """Each config root must declare the exclusion itself — a parent's cannot reach it."""
    roots = _iter_config_roots()
    assert roots, "no ruff config roots discovered — the walk is broken, not the repo"
    missing = [
        str(path.relative_to(REPO_ROOT))
        for path, key_path in roots
        if not _excludes_markdown(path, key_path)
    ]
    assert not missing, (
        "ruff config root(s) do not exclude '*.md': "
        + ", ".join(missing)
        + ". Ruff's hierarchical discovery makes each of these the config root for its own subtree, "
        "so a root-level exclude cannot reach them. Markdown formatting there sealed the merge "
        "queue for 23 days on 2026-07-11."
    )


def _ruff_action_steps() -> list[dict]:
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps: list[dict] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            uses = node.get("uses")
            if isinstance(uses, str) and uses.startswith("astral-sh/ruff-action@"):
                steps.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(workflow)
    return steps


def test_every_ruff_action_step_pins_a_tool_version() -> None:
    """A SHA-pinned action that installs an unpinned tool is only half pinned.

    PARSED, not grepped. An earlier version counted occurrences of the string 'version: "0.16' in
    the file, which this very docstring would have satisfied.
    """
    steps = _ruff_action_steps()
    assert steps, "no astral-sh/ruff-action steps found in ci.yml — update this pin"
    unpinned = [
        step.get("uses")
        for step in steps
        if not re.fullmatch(r"\d+\.\d+\.\d+", str((step.get("with") or {}).get("version", "")))
    ]
    assert not unpinned, (
        f"{len(unpinned)} of {len(steps)} ruff-action step(s) have no exact `version:` input. "
        "An unpinned ruff can change this gate's behaviour with no commit here — that is the "
        "2026-07-11 outage."
    )


def _pinned_ruff_version() -> str:
    versions = {str((s.get("with") or {}).get("version", "")) for s in _ruff_action_steps()}
    versions.discard("")
    assert len(versions) == 1, f"ruff-action steps disagree on version: {sorted(versions)}"
    return versions.pop()


def test_ruff_format_check_leaves_markdown_alone() -> None:
    """Run the CI invocation, at the CI-pinned version, over the whole tree.

    NEVER SILENTLY SKIPPED. An earlier version skipped when ruff was absent from PATH — a test that
    quietly does not run is the same fail-quiet defect this whole pin exists to catch.

    THE INVOCATION SHAPE IS LOAD-BEARING. Ruff applies excludes during PATH DISCOVERY; a file named
    explicitly on the command line is formatted regardless (absent --force-exclude). An earlier
    version passed an explicit README path and exited 2 against a correct configuration. The
    workflow passes no paths — `args: "format --check"` — so this must not either.
    """
    version = _pinned_ruff_version()
    uvx = shutil.which("uvx") or shutil.which("uv")
    if uvx:
        argv = (
            [uvx, "tool", "run", f"ruff@{version}"]
            if uvx.endswith("uv")
            else [uvx, f"ruff@{version}"]
        )
    else:  # pragma: no cover - CI always has uv
        ruff = shutil.which("ruff")
        assert ruff, "neither uvx nor ruff resolvable; cannot verify the CI path — fix the runner"
        argv = [ruff]

    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [*argv, "format", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert result.returncode == 0, (
        f"`ruff format --check` (ruff {version}) is not clean on the tree — the markdown exclusion "
        "is declared but not reaching the discovery path. This is the 2026-07-11 merge-queue seal.\n"
        f"stdout: {result.stdout[-1200:]}\nstderr: {result.stderr[-400:]}"
    )
    assert ".md" not in result.stdout, (
        f"a markdown file appeared in ruff format output:\n{result.stdout[-800:]}"
    )
