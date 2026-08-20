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
