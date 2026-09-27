"""Post-deploy governed re-provision of the Gate-0B claim-publication install.

Row gate0b-post-deploy-governed-reprovision-20260927. A merge that changes one of the executor-bound
shared/ files correctly invalidates the install receipt; the re-provision replaces it through the governed
install step, with the merge commits as its recorded authority basis, and refuses any mismatch no merge
explains.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

import shared.gate0b_claim_publication_install as install
from shared.execution_admission import ExecutionAdmissionError

SHARED = Path(install.__file__).resolve().parent
_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


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
    """A release repo with the real bound modules at A, one bound-file merge B, and a
    commit C that touches nothing bound; plus install roots for a HOME in tmp_path."""

    repo = tmp_path / "release"
    (repo / "shared").mkdir(parents=True)
    _git(repo, "init", "-q")
    for name in install.BOUND_EXECUTOR_MODULES:
        shutil.copyfile(SHARED / name, repo / "shared" / name)
    a = _commit(repo, "A")
    a_hashes = _hashes(repo)
    with (repo / "shared" / "sdlc_claim.py").open("a", encoding="utf-8") as handle:
        handle.write("\n# a reviewed change merged to main\n")
    b = _commit(repo, "B: change a bound file")
    (repo / "README.md").write_text("unrelated\n", encoding="utf-8")
    c = _commit(repo, "C: nothing bound")
    roots = install.default_claim_publication_roots(home=tmp_path / "home")
    return repo, roots, {"A": a, "B": b, "C": c}, a_hashes


def _install_from(roots, module_sha256: dict[str, str], when: str) -> None:
    install.install_claim_publication_composition(
        roots=roots,
        installed_at=when,
        install_task_ref="test-install",
        module_sha256=module_sha256,
    )


def _store(roots) -> Path:
    return Path(roots.invocation_store_root)


def _now() -> datetime:
    return datetime(2026, 9, 27, 7, 0, tzinfo=UTC)


def test_a_bound_file_merge_reprovisions_with_the_merge_as_its_basis(release) -> None:
    repo, roots, commits, a_hashes = release
    _install_from(roots, a_hashes, "2026-09-27T06:00:00Z")
    old = (_store(roots) / "activation-receipt.json").read_bytes()

    outcome = install.reprovision_claim_publication_install(
        repo=repo, head=commits["C"], roots=roots, now=_now()
    )

    assert outcome.action == "reprovisioned"
    assert outcome.basis_commits == (commits["B"],)
    assert outcome.source_commit in {commits["A"]}
    store = _store(roots)
    quarantined = sorted(store.glob("activation-receipt.json.quarantined-*"))
    assert [path.read_bytes() for path in quarantined] == [old]
    assert sorted(store.glob("composition-manifest.json.quarantined-*"))
    new = install._load_install_receipt(store / "activation-receipt.json")
    # The check cc-claim runs, against the release's own modules: it now passes.
    assert install.claim_publication_executor_descriptor(new, module_sha256=_hashes(repo))
    [basis] = sorted(store.glob("reprovision-basis-*.json"))
    record = json.loads(basis.read_text(encoding="utf-8"))
    assert record["basis_commits"] == [commits["B"]]
    assert record["new_receipt_ref"] == new.receipt_ref
    assert record["authority"].endswith("gate0b-reprovision-authority-ruling.md")


def test_a_rerun_after_reprovision_is_current_and_changes_nothing(release) -> None:
    repo, roots, commits, a_hashes = release
    _install_from(roots, a_hashes, "2026-09-27T06:00:00Z")
    install.reprovision_claim_publication_install(
        repo=repo, head=commits["C"], roots=roots, now=_now()
    )
    before = sorted(path.name for path in _store(roots).iterdir())

    outcome = install.reprovision_claim_publication_install(
        repo=repo, head=commits["C"], roots=roots, now=_now()
    )

    assert outcome.action == "current"
    assert sorted(path.name for path in _store(roots).iterdir()) == before


def test_a_release_with_no_bound_change_leaves_the_receipt_untouched(release) -> None:
    repo, roots, commits, _a_hashes = release
    _install_from(roots, _hashes(repo), "2026-09-27T06:00:00Z")
    before = {path.name: path.read_bytes() for path in _store(roots).iterdir()}

    outcome = install.reprovision_claim_publication_install(
        repo=repo, head=commits["C"], roots=roots, now=_now()
    )

    assert outcome.action == "current"
    assert {path.name: path.read_bytes() for path in _store(roots).iterdir()} == before


def test_a_mismatch_no_merge_explains_refuses_and_changes_nothing(release) -> None:
    repo, roots, commits, a_hashes = release
    forged = {**a_hashes, "sdlc_claim.py": "0" * 64}  # a state main never held
    _install_from(roots, forged, "2026-09-27T06:00:00Z")
    before = {path.name: path.read_bytes() for path in _store(roots).iterdir()}

    with pytest.raises(ExecutionAdmissionError) as raised:
        install.reprovision_claim_publication_install(
            repo=repo, head=commits["C"], roots=roots, now=_now()
        )

    assert raised.value.reason_code == "gate0b_reprovision_unexplained"
    assert {path.name: path.read_bytes() for path in _store(roots).iterdir()} == before


def test_live_files_that_differ_from_the_release_commit_refuse(release) -> None:
    repo, roots, commits, a_hashes = release
    _install_from(roots, a_hashes, "2026-09-27T06:00:00Z")
    with (repo / "shared" / "sdlc_claim.py").open("a", encoding="utf-8") as handle:
        handle.write("# edited in place, never merged\n")
    before = {path.name: path.read_bytes() for path in _store(roots).iterdir()}

    with pytest.raises(ExecutionAdmissionError) as raised:
        install.reprovision_claim_publication_install(
            repo=repo, head=commits["C"], roots=roots, now=_now()
        )

    assert raised.value.reason_code == "gate0b_reprovision_live_drift"
    assert {path.name: path.read_bytes() for path in _store(roots).iterdir()} == before


def test_no_receipt_means_nothing_to_reprovision(release) -> None:
    repo, roots, commits, _a_hashes = release

    outcome = install.reprovision_claim_publication_install(
        repo=repo, head=commits["C"], roots=roots, now=_now()
    )

    assert outcome.action == "absent"
    assert not _store(roots).exists() or not any(_store(roots).iterdir())
