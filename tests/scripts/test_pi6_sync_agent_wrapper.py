"""Behavioural tests for the Pi-6 sync wrapper.

The regression this file exists to pin is not subtle and it is not hypothetical: every rsync in
the wrapper ended in ``|| true``, so when the workstation renumbered from ``.80`` to ``.50`` the
timers kept firing, the units kept exiting 0, and no bytes moved for an unknown number of months.
A silent success is indistinguishable from a real one to everything downstream, which is why
nothing ever reported it.

Both reviewer families raised the same gap on the fix: the new fatal-exit behaviour had no test.
That is the more serious version of the original defect — a failure path nothing exercises is a
failure path nobody knows the shape of. Each direction is asserted separately here, because
pulled input and pushed output mean different things and the wrapper reports them differently.

The wrapper reaches the network through ``rsync`` and the disk through ``df``, both resolved from
``PATH``, so a stub directory prepended to ``PATH`` drives every branch with no Pi, no
workstation, and no virtualenv.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parents[2] / "systemd/units-pi6/sync-agent-wrapper.sh"


def _stub(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def harness(tmp_path: Path):
    """Returns a builder: rsync exit codes per call in order, plus where the agent records a run."""

    def build(rsync_rc_by_call: list[int], avail_kb: int = 10_000_000) -> dict[str, object]:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        counter = tmp_path / "rsync-calls"
        rc_list = " ".join(str(rc) for rc in rsync_rc_by_call)
        _stub(
            bin_dir,
            "rsync",
            f'printf "%s\\n" "$*" >> "{counter}"\n'
            f'n=$(wc -l < "{counter}")\n'
            f"codes=({rc_list})\n"
            'rc="${codes[$((n - 1))]:-0}"\n'
            'exit "$rc"',
        )
        _stub(bin_dir, "df", f'echo "Avail"; echo "{avail_kb}"')

        home = tmp_path / "home"
        council = home / "council"
        (council / ".venv-sync/bin").mkdir(parents=True, exist_ok=True)
        ran = tmp_path / "agent-ran"
        _stub(council / ".venv-sync/bin", "python", f'echo "$*" > "{ran}"')

        env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            # The wrapper pins its own PATH for systemd, which would otherwise discard the stubs
            # above and send the post-sync transfers at the real network.
            "HAPAX_SYNC_PATH": f"{bin_dir}:{os.environ['PATH']}",
            "HAPAX_SYNC_HOME": str(home),
            "HAPAX_SYNC_COUNCIL_DIR": str(council),
            "HAPAX_SYNC_WORKSTATION": "203.0.113.9",
        }
        return {"env": env, "ran": ran, "calls": counter}

    return build


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(WRAPPER), *args], text=True, capture_output=True, check=False, env=env
    )


def test_a_failed_pull_is_fatal_and_the_agent_never_runs(harness) -> None:
    """The core of the fix. Running against a stale local copy produces output that looks
    current and is not, which is worse than not running at all."""
    h = harness([1])

    result = _run(h["env"], "obsidian_sync", "documents/vault/notes.md")

    assert result.returncode == 1, "a failed pull exited 0; that is the original regression"
    assert "cannot pull" in result.stderr
    assert not h["ran"].exists(), "the agent ran on input that was never pulled"


def test_a_failed_pull_names_the_next_action(harness) -> None:
    h = harness([1])

    result = _run(h["env"], "obsidian_sync", "documents/vault/notes.md")

    assert "Next:" in result.stderr
    assert "HAPAX_SYNC_WORKSTATION" in result.stderr, (
        "the message must name the knob that fixes the exact failure that already happened once"
    )
    assert "203.0.113.9" in result.stderr, "the message must name the host it could not reach"


def test_a_failed_output_push_is_fatal_even_though_the_agent_succeeded(harness) -> None:
    """A zero exit would claim the run accomplished something. It did not: the output never
    left the Pi."""
    h = harness([0, 1, 0])

    result = _run(h["env"], "obsidian_sync", "documents/vault/notes.md")

    assert h["ran"].exists(), "the agent should have run; only the push failed"
    assert result.returncode == 1
    assert "could not be pushed" in result.stderr
    assert "not lost" in result.stderr, (
        "an operator seeing this must be told the work is held locally, not discarded"
    )


def test_the_second_push_failing_is_also_fatal(harness) -> None:
    """Two pushes, and only the first was ever likely to be eyeballed. The cache push failing
    on its own must not exit 0."""
    h = harness([0, 0, 1])

    result = _run(h["env"], "obsidian_sync", "documents/vault/notes.md")

    assert result.returncode == 1
    assert "could not be pushed" in result.stderr


def test_a_clean_run_still_succeeds(harness) -> None:
    """The guard must not turn a working sync into a failing one."""
    h = harness([0, 0, 0])

    result = _run(h["env"], "obsidian_sync", "documents/vault/notes.md")

    assert result.returncode == 0, result.stderr
    assert h["ran"].read_text(encoding="utf-8").strip() == "-m agents.obsidian_sync --auto"


def test_the_workstation_override_is_honoured(harness) -> None:
    """The pinned address is exactly what broke. An override that silently did nothing would
    reproduce the same failure with a knob attached to it."""
    h = harness([0, 0, 0])
    h["env"]["HAPAX_SYNC_WORKSTATION"] = "198.51.100.7"

    _run(h["env"], "obsidian_sync", "documents/vault/notes.md")

    calls = h["calls"].read_text(encoding="utf-8")
    assert "198.51.100.7" in calls
    assert "192.168.68.50" not in calls


def test_a_full_disk_aborts_before_any_transfer(harness) -> None:
    h = harness([0, 0, 0], avail_kb=1024)

    result = _run(h["env"], "obsidian_sync", "documents/vault/notes.md")

    assert result.returncode == 1
    assert "FATAL" in result.stderr
    assert not h["calls"].exists(), "a disk-full abort still attempted a transfer"


def test_the_wrapper_sets_its_path_once_and_before_the_first_transfer() -> None:
    """Both halves of the script must resolve tools out of the same environment.

    The export sat between the pull and the push, so the pull ran under systemd's minimal
    default and the push under the pinned list. Production never noticed, and a failure in
    either half could not be reproduced by running the other.
    """
    lines = WRAPPER.read_text(encoding="utf-8").splitlines()
    path_exports = [i for i, ln in enumerate(lines) if ln.strip().startswith("export PATH=")]
    rsyncs = [
        i for i, ln in enumerate(lines) if ln.strip().startswith("rsync ") or "rsync -a" in ln
    ]

    assert len(path_exports) == 1, f"PATH is assigned {len(path_exports)} times; it must be once"
    assert rsyncs, "no transfers found; re-derive this ordering assertion"
    assert path_exports[0] < min(rsyncs), (
        f"PATH is set at line {path_exports[0] + 1}, after the first transfer at "
        f"{min(rsyncs) + 1}; the two halves resolve tools differently"
    )


def test_no_rsync_in_the_wrapper_swallows_its_own_failure() -> None:
    """The shape of the original defect, pinned directly.

    Reintroducing `|| true` on any transfer restores a wrapper that reports success while moving
    no bytes, and a newly added third transfer would not necessarily be covered by the
    behavioural tests above.
    """
    for line in WRAPPER.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert not (stripped.startswith("rsync") and "|| true" in stripped), (
            f"an rsync swallows its own failure again: {stripped}"
        )
