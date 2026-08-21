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
from pathlib import Path, PurePosixPath

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
    """Every tracked path under scripts/, mapped to its mode IN HEAD.

    Three sources could answer "what mode is this file", and only one of them is the question:

    - ``os.access`` asks the filesystem, which describes the working copy. A deploy that chmods
      on the way out makes that answer 755 while the commit stays 644. That is what the
      registered-producer check above uses, and why it could not have caught this defect.
    - ``git ls-files -s`` asks the INDEX. A staged-but-uncommitted chmod reports 755 there while
      HEAD still stores 644 — raised by coderabbitai, and it is the mistake that produced the
      first version of this very commit: ``update-index --chmod=+x`` followed by ``git add -A``
      reset the bit from disk, the commit went out 644, and an index-reading test would have
      passed over it.
    - ``git ls-tree -r HEAD`` asks the COMMITTED TREE, which is what ``git archive``, a fresh
      clone and a container COPY all reproduce. That is the mode that reaches a deploy.

    ``_has_shebang`` already reads content from HEAD, so reading modes from HEAD also keeps both
    halves of this check on the same source rather than comparing across two.

    Uses ``-z``. Raised by gemini-1: without it ``git ls-tree`` C-quotes any path containing a
    space or special character, so the quoted name would be handed to ``git show``, which fails,
    and the file would be silently dropped from the scan. A gate that quietly skips the entries
    hardest to name is the omission-as-fact defect this whole change set is about, and it had
    reproduced itself inside the gate.
    """
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-tree", "-r", "-z", "HEAD", "--", "scripts/"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    modes: dict[str, str] = {}
    for record in out.split("\0"):
        if not record:
            continue
        meta, _, path = record.partition("\t")
        parts = meta.split()
        if parts and path:
            modes[path] = parts[0]
    return modes


#: Tree entries that are not regular files: symlinks and gitlinks (submodules). Neither has a
#: shebang to read, and neither is executed as a script, so they are excluded by MODE rather
#: than by a failed read.
_NON_BLOB_MODES = frozenset({"120000", "160000"})


def _has_shebang(path: str) -> bool:
    """Does HEAD's blob at ``path`` start with ``#!``? Raises if it cannot be read.

    ``check=True``, deliberately. Raised by claude-1: with ``check=False`` any failure —
    unreadable path, an entry type ``git show`` will not print — left stdout empty, the file was
    treated as non-shebanged, and the gate degraded to a PASS. A gate that answers "no defect"
    when it could not look is worse than one that is absent, because it is believed.

    Callers must exclude non-blob entries first (see ``_NON_BLOB_MODES``); anything else that
    fails here is a real surprise and should be loud.
    """
    blob = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"HEAD:{path}"],
        capture_output=True,
        check=True,
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
    assert modes, "the scan found no tracked files under scripts/, so it is asserting nothing"

    offenders = sorted(
        p
        for p, mode in modes.items()
        if mode not in _NON_BLOB_MODES
        and mode == "100644"
        and not Path(p).suffix
        and _has_shebang(p)
    )

    assert offenders == [], (
        "these EXTENSIONLESS scripts declare an interpreter but are committed non-executable, so "
        "a deploy that preserves committed modes cannot run them — and a deploy that chmods them "
        "instead leaves the tree permanently dirty:\n  "
        + "\n  ".join(offenders)
        + "\nFix each with: git update-index --chmod=+x <path>"
    )


def _activation_managed_launchers(modes: dict[str, str]) -> list[str]:
    """The paths ``prepare_active_runtime_surface`` hands to ``link_active_script``.

    ``scripts/hapax-source-activate:1055-1061``::

        for script in "$ACTIVE_WORKTREE"/scripts/hapax-*; do
            link_active_script "$script" || return 1
        done
        for script in cc-claim cc-close; do
            link_active_script "$ACTIVE_WORKTREE/scripts/$script" || return 1
        done

    Mirrored here rather than imported because the activator is bash. If that selection changes,
    this list goes stale — which is a real risk and the reason both the glob and the explicit
    pair are quoted above, so a reader can diff them by eye.
    """
    selected = []
    for path in modes:
        base = PurePosixPath(path).name
        parent = str(PurePosixPath(path).parent)
        if parent != "scripts":
            continue
        if base.startswith("hapax-") or base in {"cc-claim", "cc-close"}:
            selected.append(path)
    return sorted(selected)


def test_the_scanner_raises_rather_than_reporting_no_shebang() -> None:
    """Raised by codex-1: the scanner's own failure paths had no direct test.

    ``_has_shebang`` used ``check=False`` and read stdout only, so any git failure produced an
    empty buffer and the file was reported as non-shebanged — the gate answering "no defect"
    when it could not look. It now uses ``check=True``, and this pins that: a path HEAD does not
    contain must RAISE, not return False.

    The distinction is the whole point of the fix. False means "looked, no shebang"; an exception
    means "could not look". Collapsing the second into the first is how a gate goes quiet.
    """
    with pytest.raises(subprocess.CalledProcessError):
        _has_shebang("scripts/definitely-not-a-tracked-path-9f3a2b")


def test_non_blob_entries_are_excluded_by_mode_not_by_a_failed_read() -> None:
    """Symlinks and gitlinks are skipped for what they ARE, not because reading them failed.

    Also raised by codex-1. The scan must not depend on ``git show`` erroring to exclude entry
    types that were never scripts — that would be the same "absence of a result read as a
    result" defect, just relocated. ``_NON_BLOB_MODES`` names them explicitly, so the exclusion
    is a decision rather than a side effect.
    """
    assert frozenset({"120000", "160000"}) == _NON_BLOB_MODES, (
        "symlink (120000) and gitlink (160000) are the non-blob tree entry modes; if this set "
        "changes the scan must be re-reasoned, not silently widened"
    )
    modes = _committed_modes()
    assert all(m in {"100644", "100755"} | _NON_BLOB_MODES for m in modes.values()), (
        f"unexpected tree entry mode under scripts/: {sorted(set(modes.values()))}. "
        "Next: decide explicitly whether the new mode is a script before letting the scan see it."
    )


def test_activation_has_no_mode_to_repair() -> None:
    """The activation mutation itself, witnessed by asserting it is a no-op.

    Raised by codex-1 across several rounds: a test that materialises a worktree proves a raw
    checkout is clean, and "cannot detect mutations made by activation". That was right, and the
    mutation is now located precisely — ``scripts/hapax-source-activate:977``::

        if [[ ! -x "$script" ]] && ! chmod +x "$script"; then

    ``link_active_script`` chmods ``+x`` any managed launcher that is not already executable, and
    ``prepare_active_runtime_surface`` hands it every ``scripts/hapax-*`` plus ``cc-claim`` and
    ``cc-close``. That chmod is the entire cause of the dirt: a release tree materialises at HEAD's
    modes, activation makes a non-executable launcher runnable, and the tree is dirty from then on.

    The activator's own error text prescribes this fix — "next action: restore its executable Git
    mode and rerun governed source activation". It has been asking for the committed mode all
    along; nothing was reading the message.

    So this asserts the condition under which activation cannot dirty anything: every path that
    glob selects is ALREADY executable in HEAD, so the guard `[[ ! -x ]]` is false and the chmod
    never runs. That is stronger than the previous test in the way that matters — it covers
    ``cc-claim``, ``cc-close`` and every future ``hapax-*`` launcher, not only the one file whose
    breakage happened to be noticed.
    """
    modes = _committed_modes()
    managed = _activation_managed_launchers(modes)
    assert managed, "the activator's launcher selection matched nothing; the mirror has gone stale"

    would_be_chmodded = sorted(p for p in managed if modes[p] == "100644")

    assert would_be_chmodded == [], (
        "source activation would chmod +x these on every deploy (hapax-source-activate:977), "
        "leaving the release tree permanently dirty and every decision written from it "
        "unidentifiable:\n  "
        + "\n  ".join(would_be_chmodded)
        + "\nNext: git update-index --chmod=+x <path> for each, then commit."
    )


def test_the_real_activator_leaves_its_release_tree_clean(tmp_path: Path) -> None:
    """Runs ``scripts/hapax-source-activate`` itself. Nothing here is a surrogate.

    codex-1 held this clause five times, each time correctly, while I argued the predicate was
    undeliverable. Two assumptions I never checked were doing that work:

    - "the activator follows origin/main, so it cannot witness this branch." It reads
      ``git -C "$CANONICAL_REPO" rev-parse origin/main`` (:620), so pointing CANONICAL at a clone
      whose ``origin/main`` is this commit makes it activate exactly this commit.
    - "running it would repoint the operator's ~/.local/bin." ``LOCAL_BIN`` is
      ``${HAPAX_SOURCE_ACTIVATE_LOCAL_BIN:-$HOME/.local/bin}`` (:775) — overridable, so a
      sandboxed run touches nothing outside tmp_path.

    Every path the activator writes is redirected into tmp_path: canonical clone, state dir,
    releases dir, active worktree symlink, and local bin. The worktrees it creates are registered
    in the CLONE, so they die with tmp_path rather than accumulating in the real repository.
    """
    head = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    sandbox = tmp_path / "sandbox"
    canonical = sandbox / "canonical"
    state = sandbox / "state"
    local_bin = sandbox / "bin"
    local_bin.mkdir(parents=True)

    # The sandbox owns its own origin, a bare repo that ADVERTISES refs/heads/main at this
    # commit. Raised by codex-1: the activator runs `git fetch origin main` explicitly
    # (hapax-source-activate:619, :412), so pointing the clone at REPO_ROOT made the witness
    # depend on REPO_ROOT happening to have a local `main` branch. A detached or shallow CI
    # checkout — the merge queue's normal state, and the environment this test most needs to
    # work in — need not advertise it, and the fetch would fail there while passing here.
    #
    # `--shared` keeps this cheap: the bare repo borrows REPO_ROOT's objects rather than copying
    # them, and only the ref is written.
    bare = sandbox / "origin.git"
    subprocess.run(
        ["git", "clone", "--quiet", "--bare", "--shared", str(REPO_ROOT), str(bare)],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(bare), "update-ref", "refs/heads/main", head],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "clone", "--quiet", "--shared", "--no-checkout", str(bare), str(canonical)],
        capture_output=True,
        check=True,
    )
    resolved = subprocess.run(
        ["git", "-C", str(canonical), "rev-parse", "origin/main"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert resolved == head, (
        f"the sandbox's origin/main is {resolved[:9]}, not this branch's head {head[:9]}; the "
        "activator would deploy a commit that does not contain the change under test"
    )
    subprocess.run(
        ["git", "-C", str(canonical), "checkout", "--quiet", "--detach", head],
        capture_output=True,
        check=True,
    )

    # HOME is redirected, and that is not belt-and-braces.
    #
    # Raised by codex-1 as a live hazard: `active_config_dest` is hardcoded to
    # "$HOME/.config/hapax/usb-topology-policy.json" (hapax-source-activate:795) with NO env
    # override, and sync_active_config publishes it even under --skip-deploy. Redirecting only
    # the activation-specific variables left the operator's real config reachable, so this test
    # could publish an unmerged checkout into the live environment — under a task whose
    # runtime_mutation_authorized is false.
    #
    # It did not, only because this branch does not modify that file and the sync no-ops on
    # identical content (verified: the live file's mtime is months old and unchanged across six
    # runs). A hazard that stayed inert by luck is still a hazard.
    #
    # Redirecting HOME closes every $HOME-derived path at once, including any added later, which
    # an enumerated allowlist of variables cannot do.
    home = sandbox / "home"
    (home / ".config" / "hapax").mkdir(parents=True)
    env = {
        **os.environ,
        "HOME": str(home),
        "HAPAX_SOURCE_ACTIVATE_CANONICAL": str(canonical),
        "HAPAX_SOURCE_ACTIVATE_STATE_DIR": str(state),
        "HAPAX_SOURCE_ACTIVATE_RELEASES_DIR": str(state / "releases"),
        "HAPAX_SOURCE_ACTIVATE_WORKTREE": str(state / "worktree"),
        "HAPAX_SOURCE_ACTIVATE_LOCAL_BIN": str(local_bin),
    }
    proc = subprocess.run(
        [str(REPO_ROOT / "scripts" / "hapax-source-activate"), "--skip-deploy"],
        capture_output=True,
        text=True,
        env=env,
        timeout=600,
        check=False,
    )

    # Activation must have COMPLETED, and must have reached the stage that mutates modes.
    #
    # Raised by codex-1, and it is the same defect this test exists to catch, one level in: with
    # check=False and no return-code assertion, an activation dying after `git worktree add` but
    # before `link_active_script` leaves a raw clean checkout that satisfies every assertion
    # below. The witness would then be a worktree, not an activation — exactly the surrogate the
    # earlier rounds kept producing.
    assert proc.returncode == 0, (
        f"source activation failed (rc={proc.returncode}), so nothing below witnesses a completed "
        f"activation. stderr tail:\n{proc.stderr[-1500:]}"
    )
    published = sorted(p.name for p in local_bin.iterdir())
    assert "hapax-determine" in published, (
        "activation did not reach link_active_script (hapax-source-activate:977), the stage that "
        f"chmods managed launchers — so its mode behaviour is unwitnessed. Published: {published[:8]}"
    )

    release_root = state / "releases"
    trees = sorted(p for p in release_root.iterdir() if p.is_dir()) if release_root.is_dir() else []
    assert trees, (
        f"activation reported success but created no release tree under {release_root}; "
        "there is nothing to measure and a pass here would be vacuous"
    )

    tree = trees[-1]
    status = subprocess.run(
        ["git", "-C", str(tree), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    assert status == "", (
        "a release tree created by the REAL activator is not clean:\n"
        + status
        + "\nNext: a mode row (100644 -> 100755) means link_active_script "
        "(hapax-source-activate:977) chmod'd a launcher committed non-executable; fix with "
        "git update-index --chmod=+x <path>."
    )

    from shared.adjudicator_identity import (  # noqa: PLC0415 - after the tree exists
        adjudicator_identity,
        record_identifies_its_checkout,
    )

    ident = adjudicator_identity(str(tree / "shared" / "adjudicator_identity.py"))
    assert ident.dirty is False, (
        f"the activator's own release tree measures dirty={ident.dirty!r}, so every decision "
        "written from a real deploy is unidentifiable. Next: git -C <tree> status --porcelain."
    )
    assert record_identifies_its_checkout(ident.as_receipt()), (
        f"the activator's own release tree does not identify its checkout: {ident.as_receipt()}"
    )


def test_a_tree_materialised_the_way_activation_does_is_clean(tmp_path: Path, monkeypatch) -> None:
    """The activation integration check codex-1 asked for, using the real mechanism.

    codex-1 blocked on this predicate clause with: "no fresh release produced by the
    source-activation process is shown to remain clean and yield dirty=False... The supplied
    evidence substitutes a clean working checkout and a synthetic release-classification test."
    That was fair — both substitutes were one step away from the thing being claimed.

    This uses the command the activator actually runs. ``scripts/hapax-source-activate:421``:

        git -C "$CANONICAL_REPO" worktree add --detach "$candidate_worktree" "$sha" --quiet

    and that script contains no ``chmod`` at any point, so a release tree materialises every file
    at exactly the mode HEAD records. That is why the mode bit is the whole defect: with 100644 in
    HEAD the tree is born non-executable, something downstream chmods it to run, and the tree is
    permanently dirty thereafter.

    Asserts the predicate's own three clauses on a tree built that way: git reports it clean, the
    adjudicator measures ``dirty=False``, and ``record_identifies_its_checkout()`` returns True.
    Raised by codex-1 — an earlier version checked ``status`` and ``os.access`` but never
    evaluated the identity, which is the clause the predicate actually names, so it asserted
    everything around the claim and not the claim.

    Materialised at ``<trusted releases root>/<sha>/`` so it is classified ``release_tree``
    exactly as a deployed one is, rather than as an incidental checkout.
    """
    sha = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    state_dir = tmp_path / "source-activation"
    monkeypatch.setenv("HAPAX_SOURCE_ACTIVATE_STATE_DIR", str(state_dir))
    target = state_dir / "releases" / sha
    target.parent.mkdir(parents=True)

    subprocess.run(
        ["git", "-C", str(REPO_ROOT), "worktree", "add", "--detach", str(target), "HEAD"],
        capture_output=True,
        check=True,
    )
    try:
        status = subprocess.run(
            ["git", "-C", str(target), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        assert status == "", (
            "a tree materialised the way activation materialises one is not clean:\n"
            + status
            + "\nNext: identify which committed mode or file differs from what the deploy needs; "
            "a mode row (100644 -> 100755) means the file is committed non-executable."
        )
        assert os.access(target / "scripts" / "hapax-determine", os.X_OK), (
            "hapax-determine is not executable in a freshly materialised tree, so the deploy must "
            "chmod it to run — which is precisely what makes every release tree dirty. "
            "Next: git update-index --chmod=+x scripts/hapax-determine, then commit."
        )

        # The predicate's own clause, measured on this tree rather than on a stand-in.
        from shared.adjudicator_identity import (  # noqa: PLC0415 - deliberately after materialisation
            adjudicator_identity,
            record_identifies_its_checkout,
        )

        ident = adjudicator_identity(str(target / "shared" / "adjudicator_identity.py"))
        receipt = ident.as_receipt()

        assert ident.source == "release_tree", (
            f"materialised under the trusted releases root but classified {ident.source!r}. "
            "Next: check HAPAX_SOURCE_ACTIVATE_STATE_DIR and the releases/<sha>/ layout."
        )
        assert ident.sha == sha, "the identity must name the commit the tree was built from"
        assert ident.dirty is False, (
            f"the adjudicator measured dirty={ident.dirty!r} on a freshly materialised release "
            "tree, so every decision written from a real deploy would be unidentifiable. "
            "Next: run `git -C <tree> status --porcelain` to see what the deploy left modified."
        )
        assert record_identifies_its_checkout(receipt), (
            "a freshly materialised release tree does not identify its own checkout, which is "
            f"the whole point of the receipt. Measured: {receipt}. "
            "Next: dirty must be False and the sha must be a verified 40-hex from a git source."
        )
    finally:
        # Registered worktrees outlive the tmp_path teardown and this estate caps them, so the
        # removal is not optional housekeeping.
        subprocess.run(
            ["git", "-C", str(REPO_ROOT), "worktree", "remove", "--force", str(target)],
            capture_output=True,
            check=False,
        )
        subprocess.run(
            ["git", "-C", str(REPO_ROOT), "worktree", "prune"], capture_output=True, check=False
        )
