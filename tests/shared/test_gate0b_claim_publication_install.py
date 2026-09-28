"""Post-deploy governed re-provision of the Gate-0B claim-publication install.

Row gate0b-post-deploy-governed-reprovision-20260927. A merge that changes one of the executor-bound
shared/ modules correctly invalidates the install receipt; the re-provision replaces it through the governed
install step, with the merge commits as its recorded authority basis, and refuses anything no merge explains.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import shared.gate0b_claim_publication_install as install
from shared.execution_admission import ExecutionAdmissionError
from tests.scripts.test_cc_claim import _claim, _write_task

SHARED = Path(install.__file__).resolve().parent
REPO_ROOT = SHARED.parent
_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}
NOW = datetime(2026, 9, 27, 7, 0, tzinfo=UTC)
STAMP = "20260927T070000.000000Z"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], env=_GIT_ENV, capture_output=True, text=True, check=True
    ).stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--no-verify", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _hashes(repo: Path) -> dict[str, str]:
    return {
        name: hashlib.sha256((repo / "shared" / name).read_bytes()).hexdigest()
        for name in install.BOUND_EXECUTOR_MODULES
    }


@pytest.fixture
def release(tmp_path: Path):
    """A release repo whose old state A differs in one bound module, a merge B that restores
    the modules this checkout really loads (so a real cc-claim can use the result), and a
    commit C that touches nothing bound. The install roots belong to HOME = tmp_path/home."""

    repo = tmp_path / "release"
    (repo / "shared").mkdir(parents=True)
    _git(repo, "init", "-q")
    for name in install.BOUND_EXECUTOR_MODULES:
        shutil.copyfile(SHARED / name, repo / "shared" / name)
    with (repo / "shared" / "sdlc_claim.py").open("a", encoding="utf-8") as handle:
        handle.write("\n# the state before the merge\n")
    a = _commit(repo, "A")
    a_hashes = _hashes(repo)
    shutil.copyfile(SHARED / "sdlc_claim.py", repo / "shared" / "sdlc_claim.py")
    b = _commit(repo, "B: a reviewed change to a bound module")
    (repo / "README.md").write_text("unrelated\n", encoding="utf-8")
    c = _commit(repo, "C: nothing bound")
    roots = install.default_claim_publication_roots(home=tmp_path / "home")
    return repo, roots, {"A": a, "B": b, "C": c}, a_hashes


def _install_from(roots, module_sha256: dict[str, str]) -> None:
    install.install_claim_publication_composition(
        roots=roots,
        installed_at="2026-09-27T06:00:00Z",
        install_task_ref="test-install",
        module_sha256=module_sha256,
    )


def _store(roots) -> Path:
    return Path(roots.invocation_store_root)


def _snapshot(roots) -> dict[str, bytes]:
    store = _store(roots)
    return {p.name: p.read_bytes() for p in store.iterdir()} if store.exists() else {}


def _reprovision(repo: Path, roots, head: str):
    return install.reprovision_claim_publication_install(repo=repo, head=head, roots=roots, now=NOW)


def test_a_bound_file_merge_reprovisions_with_the_merge_as_its_basis(release) -> None:
    repo, roots, commits, a_hashes = release
    _install_from(roots, a_hashes)
    old = (_store(roots) / "activation-receipt.json").read_bytes()

    outcome = _reprovision(repo, roots, commits["C"])

    assert (outcome.action, outcome.basis_commits) == ("reprovisioned", (commits["B"],))
    store = _store(roots)
    assert (store / f"activation-receipt.json.quarantined-{STAMP}").read_bytes() == old
    assert (store / f"composition-manifest.json.quarantined-{STAMP}").exists()
    new = install._load_install_receipt(store / "activation-receipt.json")
    assert install.claim_publication_executor_descriptor(new, module_sha256=_hashes(repo))
    pending = json.loads((store / f"reprovision-basis-{STAMP}.pending.json").read_text())
    final = json.loads((store / f"reprovision-basis-{STAMP}.json").read_text())
    assert pending["basis_commits"] == final["basis_commits"] == [commits["B"]]
    assert pending["status"] == "pending" and pending["new_receipt_ref"] is None
    assert (final["status"], final["new_receipt_ref"]) == ("complete", new.receipt_ref)
    assert final["authority"] == install.REPROVISION_AUTHORITY
    assert not (store / _MARKER).exists()  # retired, by rename, once the install is consistent
    assert json.loads((store / f"{_MARKER}.resolved-{STAMP}").read_text())["stamp"] == STAMP


def test_the_fresh_install_binds_the_release_modules_not_the_checkout_running_it(release) -> None:
    # cc-claim loads the release's modules, so the receipt must bind those bytes.
    repo, roots, commits, a_hashes = release
    _install_from(roots, a_hashes)
    with (repo / "shared" / "sdlc_claim.py").open("a", encoding="utf-8") as handle:
        handle.write("\n# the release's own bytes, not this checkout's\n")
    d = _commit(repo, "D: a second bound change")

    outcome = _reprovision(repo, roots, d)

    assert outcome.basis_commits == (commits["B"], d)
    new = install._load_install_receipt(_store(roots) / "activation-receipt.json")
    assert install.claim_publication_executor_descriptor(new, module_sha256=_hashes(repo))
    with pytest.raises(ExecutionAdmissionError):
        install.claim_publication_executor_descriptor(new)


def test_the_basis_is_recorded_before_anything_is_quarantined_or_installed(
    release, monkeypatch: pytest.MonkeyPatch
) -> None:
    # #4809 round 1 (codex): an install must never exist without its recorded authority basis.
    repo, roots, commits, a_hashes = release
    _install_from(roots, a_hashes)
    real_install = install.install_claim_publication_composition
    seen: dict[str, bool] = {}

    def observing_install(**kwargs):
        store = _store(roots)
        seen["pending"] = (store / f"reprovision-basis-{STAMP}.pending.json").exists()
        seen["quarantined"] = (store / f"activation-receipt.json.quarantined-{STAMP}").exists()
        seen["marker"] = (store / _MARKER).exists()
        return real_install(**kwargs)

    monkeypatch.setattr(install, "install_claim_publication_composition", observing_install)
    _reprovision(repo, roots, commits["C"])

    assert seen == {"pending": True, "quarantined": True, "marker": True}


_PAIR = ("activation-receipt.json", "composition-manifest.json")
_MARKER = "reprovision-in-flight.json"


def _fail_the_install(monkeypatch: pytest.MonkeyPatch, store: Path, *, partial: bool) -> None:
    def failing_install(**_kwargs):
        if partial:  # the install writes the receipt first, then the manifest
            (store / "activation-receipt.json").write_bytes(b"a partial fresh receipt\n")
        raise ExecutionAdmissionError("gate0b_install_directory_unavailable", "simulated")

    monkeypatch.setattr(install, "install_claim_publication_composition", failing_install)


@pytest.mark.parametrize("partial", [False, True])
def test_a_failed_fresh_install_restores_the_old_pair_and_holds(
    release, monkeypatch: pytest.MonkeyPatch, partial: bool
) -> None:
    # codex (1) on #4809: a failed install left no receipt, so the next cc-claim's first-use
    # install ran with no basis. Now the quarantined pair comes back, and it holds.
    repo, roots, commits, a_hashes = release
    _install_from(roots, a_hashes)
    store = _store(roots)
    old = {name: (store / name).read_bytes() for name in _PAIR}
    _fail_the_install(monkeypatch, store, partial=partial)

    with pytest.raises(ExecutionAdmissionError) as raised:
        _reprovision(repo, roots, commits["C"])

    assert raised.value.reason_code == "gate0b_reprovision_install_failed"
    assert {name: (store / name).read_bytes() for name in _PAIR} == old
    assert not list(store.glob("*.quarantined-*"))
    assert not (store / _MARKER).exists()  # the pair is verified back, so the marker is retired
    assert (store / f"{_MARKER}.resolved-{STAMP}").exists()
    final = json.loads((store / f"reprovision-basis-{STAMP}.json").read_text())
    assert (final["status"], final["new_receipt_ref"]) == ("rolled_back", None)
    set_aside = store / f"activation-receipt.json.unrecorded-{STAMP}"
    assert set_aside.exists() == partial

    monkeypatch.undo()  # the cause is repaired: the next activation tick retries
    retry = install.reprovision_claim_publication_install(
        repo=repo, head=commits["C"], roots=roots, now=NOW + timedelta(minutes=2)
    )
    assert retry.action == "reprovisioned"


def test_after_a_failed_install_a_following_cc_claim_holds_rather_than_installing(
    release, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, roots, commits, a_hashes = release
    home = tmp_path / "home"
    _install_from(roots, a_hashes)
    _fail_the_install(monkeypatch, _store(roots), partial=False)
    with pytest.raises(ExecutionAdmissionError):
        _reprovision(repo, roots, commits["C"])
    _write_task(home, "active", "after-failed-install")

    held = _claim(home, "after-failed-install", install_gate0b=False)

    assert held.returncode == 8
    assert "gate0b_install_executor_descriptor_mismatch" in held.stderr


def test_two_reprovisions_in_the_same_second_do_not_collide(release) -> None:
    # glm on #4809: second-resolution names made a same-second rerun hold on quarantine_exists.
    repo, roots, commits, a_hashes = release
    store = _store(roots)
    _install_from(roots, a_hashes)
    _reprovision(repo, roots, commits["C"])
    for name in _PAIR:  # the receipt goes stale again within the same second
        (store / name).rename(store / f"{name}.set-aside-by-test")
    _install_from(roots, a_hashes)

    later = install.reprovision_claim_publication_install(
        repo=repo, head=commits["C"], roots=roots, now=NOW + timedelta(milliseconds=500)
    )

    assert later.action == "reprovisioned"
    assert len(list(store.glob("activation-receipt.json.quarantined-*"))) == 2


# gate0b-reprovision-inflight-hold-marker-20260927


def _fail_renames(monkeypatch: pytest.MonkeyPatch, *, when) -> None:
    """Fail the renames that ``when(source name, target name)`` selects; the rest proceed."""
    real_rename = os.rename

    def rename(source, target, *args, **kwargs):
        if when(Path(source).name, Path(target).name):
            raise OSError(5, "Input/output error (injected)")
        return real_rename(source, target, *args, **kwargs)

    monkeypatch.setattr(install.os, "rename", rename)


def test_a_rollback_that_fails_leaves_the_marker_so_claims_hold(
    release, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # codex's major on #4814: if putting the quarantined pair back itself fails, no receipt
    # exists, and a following cc-claim's first-use install would run without a basis.
    repo, roots, commits, a_hashes = release
    home = tmp_path / "home"
    _install_from(roots, a_hashes)
    store = _store(roots)
    _fail_the_install(monkeypatch, store, partial=False)
    _fail_renames(monkeypatch, when=lambda source, _target: ".quarantined-" in source)

    with pytest.raises(ExecutionAdmissionError) as raised:
        _reprovision(repo, roots, commits["C"])

    assert raised.value.reason_code == "gate0b_reprovision_rollback_failed"
    assert (store / _MARKER).exists()
    assert not (store / "activation-receipt.json").exists()
    monkeypatch.undo()
    with pytest.raises(ExecutionAdmissionError) as loader:
        install.load_claim_publication_composition(store)
    assert loader.value.reason_code == "gate0b_install_reprovision_in_flight"
    with pytest.raises(ExecutionAdmissionError) as rerun:
        _reprovision(repo, roots, commits["C"])
    assert rerun.value.reason_code == "gate0b_reprovision_in_flight"
    _write_task(home, "active", "during-an-unfinished-reprovision")

    held = _claim(home, "during-an-unfinished-reprovision", install_gate0b=False)

    assert held.returncode == 8
    assert "gate0b_install_reprovision_in_flight" in held.stderr
    assert not (store / "activation-receipt.json").exists()  # no first-use install


def test_a_partial_quarantine_is_rolled_back_and_holds(
    release, monkeypatch: pytest.MonkeyPatch
) -> None:
    # gemini on #4814: the receipt was moved, then moving the manifest failed.
    repo, roots, commits, a_hashes = release
    _install_from(roots, a_hashes)
    store = _store(roots)
    old = {name: (store / name).read_bytes() for name in _PAIR}
    _fail_renames(
        monkeypatch,
        when=lambda source, target: (
            source == "composition-manifest.json" and "quarantined" in target
        ),
    )

    with pytest.raises(ExecutionAdmissionError) as raised:
        _reprovision(repo, roots, commits["C"])

    assert raised.value.reason_code == "gate0b_reprovision_quarantine_failed"
    assert {name: (store / name).read_bytes() for name in _PAIR} == old
    assert not list(store.glob("*.quarantined-*"))
    assert not (store / _MARKER).exists()


def test_a_second_reprovision_refuses_on_the_marker_and_changes_nothing(release) -> None:
    repo, roots, commits, a_hashes = release
    _install_from(roots, a_hashes)
    (_store(roots) / _MARKER).write_text('{"stamp": "another run"}\n', encoding="utf-8")
    before = _snapshot(roots)

    with pytest.raises(ExecutionAdmissionError) as raised:
        _reprovision(repo, roots, commits["C"])

    assert raised.value.reason_code == "gate0b_reprovision_in_flight"
    assert _snapshot(roots) == before


@pytest.mark.parametrize("moved", ["activation-receipt.json", "composition-manifest.json"])
def test_a_reprovision_that_starts_inside_the_loader_still_holds_it(
    release, monkeypatch: pytest.MonkeyPatch, moved: str
) -> None:
    # codex on #4822: the loader checked the marker, then read the pair. A re-provision that
    # created the marker and moved a file in between made the read say "missing", which is the
    # one result cc-claim answers with a first-use install. The loader re-checks after a miss.
    _repo, roots, _commits, a_hashes = release
    _install_from(roots, a_hashes)
    store = _store(roots)
    reader = (
        "_load_install_receipt"
        if moved == "activation-receipt.json"
        else "_read_private_install_file"
    )
    real_read = getattr(install, reader)

    def reprovision_starts_first(path, *args, **kwargs):
        if Path(path).name == moved and not (store / _MARKER).exists():
            (store / _MARKER).write_text('{"stamp": "racing run"}\n', encoding="utf-8")
            (store / moved).rename(store / f"{moved}.quarantined-racing")
        return real_read(path, *args, **kwargs)

    monkeypatch.setattr(install, reader, reprovision_starts_first)

    with pytest.raises(ExecutionAdmissionError) as raised:
        install.load_claim_publication_composition(store)

    assert raised.value.reason_code == "gate0b_install_reprovision_in_flight"


def test_a_run_that_starts_between_the_check_and_the_marker_loses_the_race(
    release, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The early check is advice; the exclusive create is what makes the fence hold.
    repo, roots, commits, a_hashes = release
    _install_from(roots, a_hashes)
    store = _store(roots)
    real_bound_state = install._bound_state

    def other_run_starts(*args, **kwargs):
        if not (store / _MARKER).exists():
            (store / _MARKER).write_text('{"stamp": "the other run"}\n', encoding="utf-8")
        return real_bound_state(*args, **kwargs)

    monkeypatch.setattr(install, "_bound_state", other_run_starts)
    before_pair = {name: (store / name).read_bytes() for name in _PAIR}

    with pytest.raises(ExecutionAdmissionError) as raised:
        _reprovision(repo, roots, commits["C"])

    assert raised.value.reason_code == "gate0b_reprovision_in_flight"
    assert json.loads((store / _MARKER).read_text())["stamp"] == "the other run"
    assert {name: (store / name).read_bytes() for name in _PAIR} == before_pair


@pytest.mark.parametrize("record", ["pending", "complete"])
def test_a_basis_that_cannot_be_recorded_holds_with_no_usable_install(
    release, monkeypatch: pytest.MonkeyPatch, record: str
) -> None:
    # The seat's 07:14Z ruling: no usable install without a recorded basis.
    repo, roots, commits, a_hashes = release
    _install_from(roots, a_hashes)
    store = _store(roots)
    before = _snapshot(roots)
    failing = {"pending": f"reprovision-basis-{STAMP}.pending.json"}.get(
        record, f"reprovision-basis-{STAMP}.json"
    )
    real_write = install._write_private_file

    def write(path: Path, payload: bytes, **kwargs) -> None:
        if Path(path).name == failing:
            raise OSError(28, "No space left on device")
        real_write(path, payload, **kwargs)

    monkeypatch.setattr(install, "_write_private_file", write)
    with pytest.raises(ExecutionAdmissionError) as raised:
        _reprovision(repo, roots, commits["C"])

    assert raised.value.reason_code == "gate0b_reprovision_basis_unrecorded"
    if record == "pending":
        after = _snapshot(roots)
        after.pop(f"{_MARKER}.resolved-{STAMP}")  # nothing moved; the marker was retired
        assert after == before
    else:
        # The fresh install is set aside, and the old pair is back (recovery-paths item 2).
        assert {name: (store / name).read_bytes() for name in _PAIR} == {
            name: before[name] for name in _PAIR
        }
        assert (store / f"activation-receipt.json.unrecorded-{STAMP}").exists()
        assert (store / f"composition-manifest.json.unrecorded-{STAMP}").exists()
        assert (store / f"reprovision-basis-{STAMP}.pending.json").exists()
        assert not list(store.glob("*.quarantined-*"))


def test_a_rerun_after_reprovision_is_current_and_changes_nothing(release) -> None:
    repo, roots, commits, a_hashes = release
    _install_from(roots, a_hashes)
    _reprovision(repo, roots, commits["C"])
    before = _snapshot(roots)

    assert _reprovision(repo, roots, commits["C"]).action == "current"
    assert _snapshot(roots) == before


def test_a_release_with_no_bound_change_leaves_the_receipt_untouched(release) -> None:
    repo, roots, commits, _a_hashes = release
    _install_from(roots, _hashes(repo))
    before = _snapshot(roots)

    assert _reprovision(repo, roots, commits["C"]).action == "current"
    assert _snapshot(roots) == before


@pytest.mark.parametrize(
    "case", ["unexplained", "live_drift", "quarantine_exists", "git_unavailable"]
)
def test_what_no_merge_explains_holds_by_name_and_changes_nothing(
    release, tmp_path: Path, case: str
) -> None:
    repo, roots, commits, a_hashes = release
    if case == "unexplained":
        _install_from(roots, {**a_hashes, "sdlc_claim.py": "0" * 64})  # a state main never held
    else:
        _install_from(roots, a_hashes)
    if case == "live_drift":
        with (repo / "shared" / "sdlc_claim.py").open("a", encoding="utf-8") as handle:
            handle.write("# edited in place, never merged\n")
    if case == "quarantine_exists":
        (_store(roots) / f"activation-receipt.json.quarantined-{STAMP}").write_text("earlier\n")
    if case == "git_unavailable":
        plain = tmp_path / "no-history"
        shutil.copytree(repo / "shared", plain / "shared")
        repo = plain
    before = _snapshot(roots)

    with pytest.raises(ExecutionAdmissionError) as raised:
        _reprovision(repo, roots, commits["C"])

    assert raised.value.reason_code == f"gate0b_reprovision_{case}"
    assert _snapshot(roots) == before


def test_no_receipt_means_nothing_to_reprovision(release) -> None:
    repo, roots, commits, _a_hashes = release

    assert _reprovision(repo, roots, commits["C"]).action == "absent"
    assert _snapshot(roots) == {}


def _cli(tmp_path: Path, repo: Path, head: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "shared.gate0b_claim_publication_install",
            "reprovision",
            "--repo",
            str(repo),
            "--head",
            head,
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "HOME": str(tmp_path / "home")},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("setup", "exit_code", "action"),
    [
        ("none", 0, "absent"),
        ("current", 0, "current"),
        ("old", 0, "reprovisioned"),
        ("live_drift", 3, "held"),
        ("unexplained", 3, "held"),
    ],
)
def test_the_command_line_reports_each_outcome_by_exit_code_and_json(
    release, tmp_path: Path, setup: str, exit_code: int, action: str
) -> None:
    # #4809 round 1 (claude): the hook decides HELD from this exit code.
    repo, roots, commits, a_hashes = release
    installed = {
        "current": _hashes(repo),
        "old": a_hashes,
        "live_drift": a_hashes,
        "unexplained": {**a_hashes, "sdlc_claim.py": "0" * 64},
    }
    if setup in installed:
        _install_from(roots, installed[setup])
    if setup == "live_drift":
        with (repo / "shared" / "sdlc_claim.py").open("a", encoding="utf-8") as handle:
            handle.write("# edited in place, never merged\n")

    result = _cli(tmp_path, repo, commits["C"])

    assert result.returncode == exit_code, result.stderr
    outcome = json.loads(result.stdout)
    assert outcome["action"] == action
    if action == "held":
        assert outcome["reason_code"] == f"gate0b_reprovision_{setup}"


def test_a_following_cc_claim_holds_before_and_publishes_after(release, tmp_path: Path) -> None:
    # The predicate in its own words: after a bound-module merge, cc-claim holds on the stale
    # receipt; after the re-provision, a following cc-claim publishes, with no hand quarantine.
    repo, roots, commits, a_hashes = release
    home = tmp_path / "home"
    _install_from(roots, a_hashes)
    _write_task(home, "active", "after-reprovision")
    held = _claim(home, "after-reprovision", install_gate0b=False)
    assert held.returncode == 8
    assert "gate0b_install_executor_descriptor_mismatch" in held.stderr

    assert _reprovision(repo, roots, commits["C"]).action == "reprovisioned"
    claimed = _claim(home, "after-reprovision", install_gate0b=False)

    assert claimed.returncode == 0, claimed.stderr
    assert "admitted publication applied" in claimed.stdout
