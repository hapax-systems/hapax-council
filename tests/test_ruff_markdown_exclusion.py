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
# Globs that actually reach every markdown file in a config root's subtree. Anything narrower
# (docs/*.md) leaves markdown exposed while still ending in "*.md".
WHOLE_SUBTREE_MARKDOWN_GLOBS = frozenset({"*.md", "**/*.md", "*.markdown", "**/*.markdown"})
# The exact args each ruff-action step must carry. The format step must pass NO paths: ruff applies
# excludes during path discovery, so a named path is formatted regardless (absent --force-exclude).
EXPECTED_RUFF_ACTION_ARGS = frozenset({"check", "format --check"})


def _iter_config_roots() -> list[tuple[Path, tuple[str, ...]]]:
    """Every file in the tree that makes its directory a ruff config root.

    DISCOVERED, not listed. An earlier version of this test hard-coded four known paths; review
    pointed out that a fifth package carrying [tool.ruff] would silently reintroduce the outage.
    """
    found: list[tuple[Path, tuple[str, ...]]] = []
    unreadable: list[str] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in {"ruff.toml", ".ruff.toml"}:
            found.append((path, ("format", "exclude")))
        elif path.name == "pyproject.toml":
            try:
                data = tomllib.loads(path.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError) as exc:
                # DO NOT `continue` silently. A file we cannot read may declare [tool.ruff] and
                # become a config root, so skipping it means the exclusion is UNPROVEN there —
                # the exact fail-quiet class this discovery walk exists to eliminate.
                unreadable.append(f"{path.relative_to(REPO_ROOT)} ({type(exc).__name__})")
                continue
            if isinstance(data.get("tool"), dict) and "ruff" in data["tool"]:
                found.append((path, ("tool", "ruff", "extend-exclude")))
    assert not unreadable, (
        "ruff config discovery could not parse: "
        + ", ".join(unreadable)
        + ". Each may carry [tool.ruff] and become a config root, so markdown exclusion cannot be "
        "proven there. Next action: fix the TOML, or add its directory to SKIP_DIRS with a reason "
        "if it is deliberately outside the build."
    )
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
        if not isinstance(value, list):
            continue
        # EXACT match against whole-subtree globs, never `endswith("*.md")`. A narrow declaration
        # like "docs/*.md" ends with "*.md" while leaving every markdown file outside docs/
        # exposed — the assertion would stay green as the 2026-07-11 outage came back.
        if any(str(entry).strip() in WHOLE_SUBTREE_MARKDOWN_GLOBS for entry in value):
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


def _ruff_action_steps() -> list[tuple[str, dict]]:
    """Every astral-sh/ruff-action step in EVERY workflow, as (workflow_path, step).

    Not just ci.yml. The predicate is "every ruff-action step carries an exact version"; scanning a
    single file makes that claim true only inside that file, so a second workflow adding a ruff step
    would be unpinned and unnoticed — the same blind spot in a new place.
    """
    steps: list[tuple[str, dict]] = []
    workflow_dir = REPO_ROOT / ".github" / "workflows"

    for workflow_path in sorted(workflow_dir.glob("*.y*ml")):
        rel = str(workflow_path.relative_to(REPO_ROOT))
        try:
            document = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise AssertionError(
                f"{rel} could not be parsed ({type(exc).__name__}), so a ruff-action step inside it "
                "cannot be checked for a version pin. Next action: fix the workflow YAML."
            ) from exc

        def walk(node: object, rel: str = rel) -> None:
            if isinstance(node, dict):
                uses = node.get("uses")
                if isinstance(uses, str) and uses.startswith("astral-sh/ruff-action@"):
                    steps.append((rel, node))
                for value in node.values():
                    walk(value, rel)
            elif isinstance(node, list):
                for value in node:
                    walk(value, rel)

        walk(document)
    return steps


def test_every_ruff_action_step_pins_a_tool_version() -> None:
    """A SHA-pinned action that installs an unpinned tool is only half pinned.

    PARSED, not grepped. An earlier version counted occurrences of the string 'version: "0.16' in
    the file, which this very docstring would have satisfied.
    """
    steps = _ruff_action_steps()
    assert steps, "no astral-sh/ruff-action steps found in any workflow — update this pin"
    unpinned = [
        f"{rel}: {step.get('uses')}"
        for rel, step in steps
        if not re.fullmatch(r"\d+\.\d+\.\d+", str((step.get("with") or {}).get("version", "")))
    ]
    assert not unpinned, (
        f"{len(unpinned)} of {len(steps)} ruff-action step(s) have no exact `version:` input: "
        + ", ".join(unpinned)
        + ". An unpinned ruff can change this gate's behaviour with no commit here — that is the "
        '2026-07-11 outage. Next action: add `version: "<x.y.z>"` under the step\'s `with:`.'
    )


def test_every_ruff_action_step_uses_the_expected_invocation() -> None:
    """Pinning the version is not enough if the ARGUMENTS drift.

    In particular the format step must pass no paths. Ruff applies excludes during path discovery,
    so a step that names files formats them regardless of any exclusion — the config fix would be
    silently bypassed while every version assertion still passed.
    """
    steps = _ruff_action_steps()
    unexpected = [
        f"{rel}: args={(step.get('with') or {}).get('args', '<unset>')!r}"
        for rel, step in steps
        if str((step.get("with") or {}).get("args", "")).strip() not in EXPECTED_RUFF_ACTION_ARGS
    ]
    assert not unexpected, (
        "ruff-action step(s) do not use an expected invocation: "
        + ", ".join(unexpected)
        + f". Expected one of {sorted(EXPECTED_RUFF_ACTION_ARGS)}. Next action: restore the args, "
        "and note that adding paths to the format step defeats the markdown exclusion entirely."
    )


def _pinned_ruff_version() -> str:
    versions = {str((s.get("with") or {}).get("version", "")) for _, s in _ruff_action_steps()}
    versions.discard("")
    assert len(versions) == 1, (
        f"ruff-action steps disagree on version: {sorted(versions)}. Next action: make every step "
        "use the same exact version, or this test cannot say which one CI actually runs."
    )
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
        # This fallback runs whatever ruff is on PATH, which is NOT necessarily the pinned one.
        # Verify it EXACTLY. A prefix/startswith comparison would accept "ruff 0.16.10" for a
        # 0.16.1 pin, and the test would then attest to a version CI never runs.
        reported = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [ruff, "--version"], capture_output=True, text=True, timeout=60
        ).stdout.strip()
        assert reported == f"ruff {version}", (
            f"PATH ruff reports {reported!r}, but CI pins {version!r}. This test would otherwise "
            "attest to a version CI never runs. Next action: install uv/uvx on this runner so the "
            f"pinned version is fetched, or put ruff {version} on PATH."
        )
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
        "a markdown file appeared in ruff format output, so some config root is not excluding it. "
        "Next action: run `ruff check --show-settings <that file>` to see which config root ruff "
        f"resolved for it, then add a whole-subtree markdown glob there.\n{result.stdout[-800:]}"
    )
