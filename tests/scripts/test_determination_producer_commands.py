"""A producer the spine cannot launch is a property the estate cannot determine.

Measured 2026-08-19: `scripts/hapax-claude-account-live-observe` merged in #4582 committed as
mode 100644 while its sibling `scripts/hapax-agy-quota-admission` was 100755. Nothing caught
it — the PR was fully green — because no test asserts that a registered producer's command is
actually runnable. It happened to work at runtime only because the source-activation copy lands
755 on disk incidentally; a deploy that reproduced the tree faithfully (`git archive`, a clean
checkout, a container COPY) would produce 644, and every run would raise PermissionError. The
spine reports that as `unlaunchable` — which at a glance is indistinguishable from the honest
"this capability is not available on this host".

The registry is a promise that these commands can be run. This pins the promise.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = REPO_ROOT / "config" / "determination-producers.json"


def _producers() -> list[dict]:
    data = json.loads(REGISTRY.read_text())
    producers = data["producers"] if isinstance(data, dict) else data
    assert producers, "registry declares no producers"
    return producers


def _ids(producers: list[dict]) -> list[str]:
    return [p.get("id") or p.get("producer_id") or "<unnamed>" for p in producers]


def _repo_relative_target(producer: dict) -> Path | None:
    """The repo artifact argv[0] names, or None if it is not this tree's business.

    Only ABSOLUTE paths (``/bin/true``) belong to the deploying host. Everything else is a
    repository artifact, because the runner resolves it as one:

        # scripts/hapax-determine:131-132
        if not os.path.isabs(exe):
            argv[0] = str(repo_root / exe)

    There is no PATH lookup anywhere in that path. An earlier version of this helper also
    skipped bare names on the assumption they were PATH-resolved; a registry entry such as
    ``["producer"]`` would then have been excluded from the very check this module exists to
    perform, while the runner launched ``<repo>/producer``. Raised by coderabbitai on #4584
    and verified against the runner.

    Targets that escape the repository are rejected rather than skipped, so ``../`` segments
    and symlink escapes cannot pass as repository artifacts.
    """
    command = producer.get("command")
    assert isinstance(command, list) and command, "command must be a non-empty list"
    argv0 = command[0]
    if os.path.isabs(argv0):
        return None
    target = (REPO_ROOT / argv0).resolve()
    assert target.is_relative_to(REPO_ROOT), (
        f"command target {argv0!r} resolves to {target}, outside the repository. The runner "
        "would still launch it via repo_root; a producer command must not escape the tree."
    )
    return target


@pytest.mark.parametrize("producer", _producers(), ids=_ids(_producers()))
class TestRegisteredCommandsAreRunnable:
    def test_command_target_exists(self, producer: dict) -> None:
        target = _repo_relative_target(producer)
        if target is None:
            pytest.skip("argv[0] is absolute; the deploying host owns it, not this tree")
        assert target.is_file(), (
            f"registry points at {target.relative_to(REPO_ROOT)}, which is not in the tree — "
            "the spine will report this producer unlaunchable forever"
        )

    def test_command_target_is_executable(self, producer: dict) -> None:
        target = _repo_relative_target(producer)
        if target is None:
            pytest.skip("argv[0] is absolute; the deploying host owns it, not this tree")
        assert os.access(target, os.X_OK), (
            f"{target.relative_to(REPO_ROOT)} is not executable. The spine launches producers "
            "with subprocess.run(argv), so this raises PermissionError on any deploy that "
            "preserves the committed mode. Fix with: "
            f"git update-index --chmod=+x {target.relative_to(REPO_ROOT)}"
        )


def _committed_modes() -> dict[str, str]:
    """Every tracked path under scripts/, mapped to its COMMITTED mode.

    Deliberately not ``os.access``. The test above asks the filesystem, which answers about the
    working copy — and a deploy that chmods on the way out makes that answer 755 while the commit
    stays 644. The mode that survives ``git archive``, a fresh clone, or a container COPY is the
    committed one, so that is what gets asserted here.
    """
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-s", "scripts/"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    modes: dict[str, str] = {}
    for line in out.splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if parts and path:
            modes[path] = parts[0]
    return modes


def _has_shebang(path: str) -> bool:
    blob = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"HEAD:{path}"],
        capture_output=True,
        check=False,
    ).stdout
    return blob[:2] == b"#!"


def test_every_shebanged_script_is_committed_executable() -> None:
    """A file that declares an interpreter is meant to be run, so it must be committed runnable.

    Widened from the registered-producer check above, which is where this defect class was first
    caught (#4584: ``hapax-claude-account-live-observe`` merged 644 while its sibling was 755).
    That test covers producers named in ``config/determination-producers.json``. It does not cover
    ``scripts/hapax-determine`` — the RUNNER that launches those producers — so the gate written
    for this exact defect sat one file away from the file that had it.

    Measured 2026-08-21 by the provenance instrument landed in #4588, on its first live reading:
    the deployed release tree reported ``dirty: True`` from a single mode change,
    ``100644 -> 100755 scripts/hapax-determine``, identical blob. The deploy chmods it so it can
    run, which makes every release tree dirty from creation — and
    ``record_identifies_its_checkout`` requires ``dirty is False``, so every production decision
    was unidentifiable for a one-line reason.

    Scoped to EXTENSIONLESS files deliberately. A first draft asserted the property for every
    shebanged file and flagged dozens of ``.py`` scripts — but a ``.py`` file is legitimately
    invoked as ``python foo.py``, where the mode is irrelevant. An extensionless file exists
    precisely to be run as a command, so for those the shebang is a promise the mode has to keep.

    Asserts the class rather than the instance: any extensionless shebanged script under
    ``scripts/`` committed non-executable fails here, whichever one it is next time.
    """
    modes = _committed_modes()
    offenders = sorted(
        p
        for p, mode in modes.items()
        if mode == "100644" and not Path(p).suffix and _has_shebang(p)
    )

    assert offenders == [], (
        "these EXTENSIONLESS scripts declare an interpreter but are committed non-executable, so "
        "a deploy that preserves committed modes cannot run them — and a deploy that chmods them "
        "instead leaves the tree permanently dirty:\n  "
        + "\n  ".join(offenders)
        + "\nFix each with: git update-index --chmod=+x <path>"
    )
