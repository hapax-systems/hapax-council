"""A decision that cannot name the code that made it is not replayable.

`routing_model_version` is present on 559 of 559 historical route decisions carrying the
constant "capacity-dimensional-v1", so "an adjudicator field exists" was never the same question
as "the adjudicator is known". These pin the difference.

They also pin the LIMIT, which is most of what this module learned. Four mechanisms claiming to
verify that the loaded bytes match the commit were refuted in review; a Python process cannot
observe the bytes it was compiled from. So `record_identifies_its_checkout` is necessary and not
sufficient, and the tests below assert that scope rather than a stronger one.

Every path here is built from a tmp_path-rooted HAPAX_SOURCE_ACTIVATE_STATE_DIR rather than the
operator's home. Raised by codex-1: fixtures hard-coding /home/hapax pass locally and fail on
hosted CI, where HOME is /home/runner — a test that only runs on one machine is not a gate.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from shared.adjudicator_identity import (
    AdjudicatorIdentity,
    adjudicator_identity,
    record_identifies_its_checkout,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SHA_RE = re.compile(r"\A[0-9a-f]{40}\Z")


@pytest.fixture
def releases_root(tmp_path: Path, monkeypatch) -> Path:
    """A trusted releases root under tmp_path, as the activator's own env var defines it."""
    state_dir = tmp_path / "source-activation"
    monkeypatch.setenv("HAPAX_SOURCE_ACTIVATE_STATE_DIR", str(state_dir))
    root = state_dir / "releases"
    root.mkdir(parents=True)
    return root


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _make_checkout(root: Path, marker: str, module_src: Path | None = None) -> Path:
    """A real git checkout with one commit, returning its path."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "test")
    pkg = root / "shared"
    pkg.mkdir(exist_ok=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "adjudicator_identity.py").write_text(
        (module_src or REPO_ROOT / "shared" / "adjudicator_identity.py").read_text()
    )
    (root / "MARKER").write_text(marker)  # differs per tree, so the commits differ
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", marker)
    return root


def _head(tree: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(tree), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


# --------------------------------------------------------------------------------------
# What the deploy path claims, and where that claim is allowed to be heard
# --------------------------------------------------------------------------------------


def test_a_release_path_alone_is_a_claim_not_a_verified_identity(releases_root: Path) -> None:
    """Raised by codex-1 and confirmed by measurement: release trees here are WRITABLE.

    At the time of writing, the live release tree `45086a03` carried a modified
    `scripts/hapax-determine` while its directory name asserted that commit. An earlier version
    read the sha out of the path and reported `dirty=False`, which would have attributed a
    decision to a commit the running code did not match.

    A release path with nothing verifiable behind it keeps its claim in `declared_sha` and
    leaves `sha` None, rather than promoting an unverified name into the verified slot.
    """
    sha = "0" * 39 + "a"
    module = releases_root / sha / "shared" / "adjudicator_identity.py"
    ident = adjudicator_identity(str(module))

    assert ident.declared_sha == sha, "the claim must be preserved, not discarded"
    assert ident.sha is None, "an unverifiable claim must not occupy the verified slot"
    assert ident.source == "indeterminate"
    assert not record_identifies_its_checkout(ident.as_receipt())


def test_the_release_layout_only_means_release_inside_the_trusted_root(
    tmp_path: Path, releases_root: Path
) -> None:
    """Raised by coderabbitai: a substring is not a location.

    The first implementation regex-searched for `/source-activation/releases/<40-hex>` anywhere
    in the resolved path, so ANY directory containing those components was read as a deployed
    release — a scratch copy, an unpacked archive, a fixture tree. That lets any writable
    directory mint the estate's most load-bearing provenance claim by choosing its own name.
    """
    sha = "b" * 40
    impostor = tmp_path / "elsewhere" / "source-activation" / "releases" / sha / "shared"
    impostor.mkdir(parents=True)
    module = impostor / "adjudicator_identity.py"
    module.write_text("# a copy, not a deployment\n")

    ident = adjudicator_identity(str(module))

    assert ident.source != "release_tree", (
        "a path outside the trusted releases root must not be classified as a deployed release"
    )
    assert ident.declared_sha is None, "an untrusted path's sha must not be surfaced as a claim"
    assert str(module) == ident.resolved_from, "the full path is still recorded for forensics"


def test_the_trusted_root_follows_the_activators_own_configuration(releases_root: Path) -> None:
    """The same layout INSIDE the trusted root does yield the claim — the check is location.

    Paired with the test above so the two pin a distinction rather than one half of it: if
    containment were implemented as "always False", both could not pass together. The root comes
    from the activator's own HAPAX_SOURCE_ACTIVATE_STATE_DIR rather than a constant duplicated
    here, so this fails if the two ever disagree about where releases live.
    """
    sha = "c" * 40
    tree = releases_root / sha / "shared"
    tree.mkdir(parents=True)
    module = tree / "adjudicator_identity.py"
    module.write_text("# a deployment, unverifiable — no checkout behind it\n")

    ident = adjudicator_identity(str(module))

    assert ident.declared_sha == sha, "inside the trusted root the path's claim is recorded"
    assert ident.sha is None, "still unverified: there is no checkout behind this tree"
    assert ident.source == "indeterminate"
    assert not record_identifies_its_checkout(ident.as_receipt())


def test_identity_is_resolved_from_the_module_not_the_symlink(releases_root: Path) -> None:
    """The core design decision, pinned.

    Reading `~/.cache/hapax/source-activation/worktree` would name whatever the symlink points
    at NOW. If it repoints mid-run — measured twice in one session — the receipt attributes a
    decision to code that did not make it.
    """
    a, b = "a" * 40, "b" * 40
    id_a = adjudicator_identity(str(releases_root / a / "shared" / "adjudicator_identity.py"))
    id_b = adjudicator_identity(str(releases_root / b / "shared" / "adjudicator_identity.py"))

    assert id_a.declared_sha == a
    assert id_b.declared_sha == b
    assert id_a.resolved_from != id_b.resolved_from


# --------------------------------------------------------------------------------------
# Verified identity against a real checkout
# --------------------------------------------------------------------------------------


def test_two_real_trees_are_distinguishable_by_the_verified_sha(tmp_path: Path) -> None:
    """Raised by codex-1: the path-only test pins `declared_sha`, not `adjudicator_sha`.

    The exit predicate requires two records from different trees to be distinguishable **by
    adjudicator_sha**. Unverifiable trees cannot witness that — both shas are None, and
    `None != None` is false anyway.
    """
    tree_a = _make_checkout(tmp_path / "tree-a", "tree-a")
    tree_b = _make_checkout(tmp_path / "tree-b", "tree-b")

    id_a = adjudicator_identity(str(tree_a / "shared" / "adjudicator_identity.py"))
    id_b = adjudicator_identity(str(tree_b / "shared" / "adjudicator_identity.py"))

    assert SHA_RE.match(id_a.sha or ""), "a real checkout must yield a verified sha"
    assert SHA_RE.match(id_b.sha or "")
    assert id_a.sha != id_b.sha, (
        "two decisions produced from different trees must be distinguishable by adjudicator_sha"
    )
    assert id_a.source == id_b.source == "git_worktree"
    assert id_a.dirty is False and id_b.dirty is False, "freshly committed trees are clean"


def test_a_real_checkout_resolves_to_its_verified_head(tmp_path: Path) -> None:
    """A modified tree is reported dirty, and a dirty tree is not usable.

    A dirty tree's HEAD does not determine the code that ran, so the sha is recorded and the
    record is refused rather than the sha being withheld — the evidence survives, the claim does
    not.
    """
    tree = _make_checkout(tmp_path / "tree", "tree")
    module = tree / "shared" / "adjudicator_identity.py"

    clean = adjudicator_identity(str(module))
    assert clean.sha == _head(tree)
    assert clean.dirty is False
    assert record_identifies_its_checkout(clean.as_receipt())

    (tree / "MARKER").write_text("modified after commit\n")
    dirty = adjudicator_identity(str(module))
    assert dirty.sha == _head(tree), "the sha is still recorded"
    assert dirty.dirty is True
    assert not record_identifies_its_checkout(dirty.as_receipt())


def test_unknown_location_is_indeterminate_not_a_guess(tmp_path: Path) -> None:
    """No release path, no checkout: the answer is that there is no answer.

    A receipt that quietly attributes a decision to the wrong tree is worse than one saying it
    does not know.
    """
    stray = tmp_path / "shared" / "adjudicator_identity.py"
    stray.parent.mkdir(parents=True)
    stray.write_text("# neither a release nor a checkout\n")

    ident = adjudicator_identity(str(stray))

    assert ident.sha is None
    assert ident.source == "indeterminate"
    assert ident.declared_sha is None
    assert ident.resolved_from == str(stray), "where it came from is still recorded"
    assert not record_identifies_its_checkout(ident.as_receipt())


def test_a_failed_git_status_does_not_report_a_clean_tree(tmp_path: Path, monkeypatch) -> None:
    """Raised by codex-1: failure to measure must not be rendered as a measurement.

    An earlier version ignored `git status`'s return code, so a failed status produced empty
    stdout, `bool("")` was False, and the identity reported a VERIFIED CLEAN tree — the exact
    defect this module exists to prevent, committed inside it.
    """
    from shared import adjudicator_identity as mod

    tree = _make_checkout(tmp_path / "tree", "tree")
    real_run = mod.subprocess.run

    def fake_run(args, **kwargs):
        if "status" in args:
            return subprocess.CompletedProcess(args, returncode=128, stdout="", stderr="boom")
        return real_run(args, **kwargs)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    ident = adjudicator_identity(str(tree / "shared" / "adjudicator_identity.py"))

    assert ident.sha == _head(tree), "HEAD was measured successfully and must be reported"
    assert ident.dirty is None, "cleanliness was NOT measured; None, never False"
    assert not record_identifies_its_checkout(ident.as_receipt())


# --------------------------------------------------------------------------------------
# The receipt shape, and the check over it
# --------------------------------------------------------------------------------------


def test_receipt_shape_is_serializable_and_complete(releases_root: Path) -> None:
    """What gets written onto a decision must survive JSON and carry every field.

    `adjudicator_declared_sha` is part of the shape precisely because it can disagree with
    `adjudicator_sha`; a receipt that dropped it would hide the disagreement.
    """
    sha = "c" * 40
    ident = adjudicator_identity(str(releases_root / sha / "shared" / "x.py"))
    receipt = ident.as_receipt()

    assert set(receipt) == {
        "adjudicator_sha",
        "adjudicator_source",
        "adjudicator_resolved_from",
        "adjudicator_dirty",
        "adjudicator_loaded_modules",
        "adjudicator_declared_sha",
    }
    assert json.loads(json.dumps(receipt)) == receipt
    assert receipt["adjudicator_declared_sha"] == sha
    assert receipt["adjudicator_sha"] is None


def test_a_basis_name_constant_does_not_satisfy_the_check() -> None:
    """The distinction the estate did not have.

    559 of 559 route decisions carry `routing_model_version: "capacity-dimensional-v1"`. The
    field exists on every record and distinguishes none of them.
    """
    assert not record_identifies_its_checkout(
        {"routing_model_version": "capacity-dimensional-v1", "task_id": "t-1"}
    )


@pytest.mark.parametrize(
    ("record", "usable", "why"),
    [
        (
            {
                "adjudicator_sha": "a" * 40,
                "adjudicator_source": "release_tree",
                "adjudicator_dirty": False,
            },
            True,
            "a verified sha over a tree measured clean — the whole of what this certifies",
        ),
        (
            {
                "adjudicator_sha": "a" * 40,
                "adjudicator_source": "git_worktree",
                "adjudicator_dirty": False,
            },
            True,
            "a checkout is a weaker provenance than a release, but it is still verified",
        ),
        (
            {
                "adjudicator_sha": "a" * 40,
                "adjudicator_source": "release_tree",
                "adjudicator_dirty": None,
            },
            False,
            "cleanliness UNKNOWN is not cleanliness verified — raised by codex-1 as "
            "'a failed git status is promoted to a verified clean identity'",
        ),
        (
            {"adjudicator_sha": "a" * 40, "adjudicator_source": "release_tree"},
            False,
            "a record with no dirty field has not been verified clean; absence is not False",
        ),
        (
            {
                "adjudicator_sha": "a" * 40,
                "adjudicator_source": "release_tree",
                "adjudicator_dirty": True,
            },
            False,
            "a dirty tree's HEAD does not determine the code that ran",
        ),
        (
            {
                "adjudicator_sha": None,
                "adjudicator_source": "indeterminate",
                "adjudicator_declared_sha": "b" * 40,
            },
            False,
            "an unverified release path must not be promoted into the verified slot",
        ),
        ({"adjudicator_sha": "short", "adjudicator_source": "release_tree"}, False, "not a sha"),
        ({}, False, "no fields at all"),
    ],
)
def test_usable_adjudicator_check(record: dict, usable: bool, why: str) -> None:
    assert record_identifies_its_checkout(record) is usable, why


#: The shape of a route decision as written for the 559 records preceding this change: an
#: adjudicator field that exists in name and carries zero bits. Held in the repo because the
#: live stream below is operator-local — raised by codex-1: a test that skips when the ledger is
#: absent cannot durably witness the claim it exists to witness.
LEGACY_ROUTE_DECISION_SHAPES = [
    {"routing_model_version": "capacity-dimensional-v1", "task_id": "t-1", "decision": "route"},
    {"routing_model_version": "capacity-dimensional-v1", "task_id": "t-2", "blocked": True},
    {"routing_model_version": "capacity-dimensional-v1", "adjudicator_sha": None},
    {"routing_model_version": "capacity-dimensional-v1", "adjudicator_sha": ""},
]


def test_no_legacy_route_decision_shape_can_pass_the_check() -> None:
    """The negative case, witnessed in CI rather than only on the operator's host."""
    assert LEGACY_ROUTE_DECISION_SHAPES, "an empty fixture would make this test vacuous"
    for record in LEGACY_ROUTE_DECISION_SHAPES:
        assert not record_identifies_its_checkout(record), record


def test_live_route_decisions_are_measured_not_assumed() -> None:
    """Run the check over the real historical stream, if present on this host.

    Scoped to records that PREDATE the field. Asserting that nothing in the stream is identified
    would be correct today and wrong the moment this lands, because the deployed spine will then
    write records that legitimately pass; a test that must be deleted to let the feature work is
    not a guard, it is a countdown.
    """
    stream = Path.home() / ".cache" / "hapax" / "orchestration" / "route-decisions.jsonl"
    if not stream.is_file():
        pytest.skip("no historical route-decision stream on this host")

    records = [json.loads(line) for line in stream.read_text().splitlines() if line.strip()]
    if not records:
        pytest.skip("route-decision stream is empty")

    legacy = [r for r in records if "adjudicator_sha" not in r]
    identified_legacy = [r for r in legacy if record_identifies_its_checkout(r)]
    assert identified_legacy == [], (
        f"{len(identified_legacy)} of {len(legacy)} records that predate this field were "
        "reported as carrying a usable adjudicator identity"
    )


# --------------------------------------------------------------------------------------
# The identity is recomputed, and the enumeration cannot be hidden from
# --------------------------------------------------------------------------------------


def test_the_identity_is_recomputed_rather_than_cached(tmp_path: Path) -> None:
    """Raised by codex-1 twice: a cached identity goes stale the moment coverage can change.

    The cache was justified by "the answer cannot change within a process". Enumerating loaded
    modules makes that false — a lazy import after the first receipt changes the answer — and
    invalidating only on explicit registration still left unregistered late imports invisible.
    A cache whose justification has been withdrawn is a stale answer with a comment attached.
    """
    tree = _make_checkout(tmp_path / "tree", "tree")
    module = tree / "shared" / "adjudicator_identity.py"

    before = adjudicator_identity(str(module))
    assert before.dirty is False

    (tree / "MARKER").write_text("changed\n")
    after = adjudicator_identity(str(module))

    assert after.dirty is True, (
        "a second call must re-measure; serving the first answer would report a tree that no "
        "longer exists"
    )


#: Imported THROUGH a symlink, which is repointed before the receipt is built.
_SYMLINK_RACE_PROBE = """
import json, pathlib, sys
link = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(link))
import shared.adjudicator_identity as mod   # capture of __file__ happens at THIS import
link.unlink()
link.symlink_to(sys.argv[2])                # repoint AFTER load, before the receipt is written
print(json.dumps(mod.adjudicator_identity().as_receipt()))
"""


def _run_probe(tmp_path: Path, source: str, *args: str) -> dict:
    probe = tmp_path / "probe.py"
    probe.write_text(source)
    result = subprocess.run(
        [sys.executable, str(probe), *args],
        capture_output=True,
        text=True,
        check=False,
        # Otherwise importing writes __pycache__ into the tree and `git status` reports the dirt
        # the import itself created, hiding the condition under test behind a side effect.
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_a_symlink_repoint_after_load_cannot_relabel_the_identity(tmp_path: Path) -> None:
    """The production race, exercised through the real resolution path.

    Two checkouts hold an IDENTICAL copy of this module at DIFFERENT commits. The module is
    imported through a symlink pointing at tree A, the symlink is repointed to tree B, and only
    then is the receipt built. The identity must still name tree A: resolving `__file__` a second
    time at receipt-build would follow the moved link and name B.
    """
    tree_a = _make_checkout(tmp_path / "a", "tree-a")
    tree_b = _make_checkout(tmp_path / "b", "tree-b")
    sha_a, sha_b = _head(tree_a), _head(tree_b)
    assert sha_a != sha_b, "the two trees must be distinguishable for this test to mean anything"

    link = tmp_path / "worktree"
    link.symlink_to(tree_a)
    receipt = _run_probe(tmp_path, _SYMLINK_RACE_PROBE, str(link), str(tree_b))

    assert receipt["adjudicator_sha"] == sha_a, (
        "the receipt must name the tree the code was LOADED from; naming the repointed tree "
        "would attribute the decision to code that never ran"
    )
    assert receipt["adjudicator_sha"] != sha_b


#: A dependency imported through the symlink, with the link repointed before the receipt is
#: built, so its `__file__` resolves into the new checkout at measurement time.
_REPOINT_ENUMERATION_PROBE = """
import json, pathlib, sys
link = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(link))
import shared.adjudicator_identity as mod
import shared.dep
link.unlink()
link.symlink_to(sys.argv[2])
print(json.dumps(mod.adjudicator_identity().as_receipt()))
"""


def test_a_repoint_cannot_hide_a_loaded_module(tmp_path: Path) -> None:
    """Raised by codex-1: the enumeration had the same silent drop it was added to fix.

    A loaded module keeps a symlink-spelled `__file__` resolved only when the receipt is built,
    so after a repoint it resolves into the NEW checkout. The previous enumeration filtered by
    `relative_to(tree)`, so such a module failed containment against the original tree and
    vanished — leaving coverage that looked complete over code the receipt never saw.

    Enumeration is now by first-party-ness rather than containment, so a module that cannot be
    placed is reported under its full path instead of dropped.
    """
    tree_a = _make_checkout(tmp_path / "a", "tree-a")
    tree_b = _make_checkout(tmp_path / "b", "tree-b")
    for tree in (tree_a, tree_b):
        (tree / "shared" / "dep.py").write_text("VALUE = 1\n")
        _git(tree, "add", "-A")
        _git(tree, "commit", "-q", "-m", "dep")

    link = tmp_path / "worktree"
    link.symlink_to(tree_a)
    receipt = _run_probe(tmp_path, _REPOINT_ENUMERATION_PROBE, str(link), str(tree_b))

    listed = " ".join(receipt["adjudicator_loaded_modules"])
    assert "dep.py" in listed, (
        "a loaded module must remain visible after a repoint; dropping it leaves coverage that "
        "reads as complete over code the receipt never saw"
    )


def test_the_loaded_module_list_names_the_real_route_deciders() -> None:
    """The coverage statement must name the code that actually decides.

    These four execute route-determining logic. There is deliberately no per-module verdict —
    four attempts at one were refuted — but a reader must at minimum be able to see that they
    participated, because a module absent from the receipt is indistinguishable from one that
    was checked.
    """
    from shared import dispatcher_policy  # noqa: F401 - imported for its presence in sys.modules

    ident = adjudicator_identity()
    if ident.sha is None:
        pytest.skip("not running from a checkout")

    # Repo-relative, not basenames. Raised by coderabbitai: reducing entries to `Path(p).name`
    # means a file called `route_metadata_schema.py` in ANY package — including a fixture tree
    # built earlier in the same session — satisfies the assertion. The property under test is
    # that importing shared.dispatcher_policy puts THESE modules in scope, and a basename cannot
    # witness that. Same weak-assertion family as the vacuous guards found earlier in this PR.
    listed = set(ident.loaded_modules)
    for decider in (
        "shared/dispatcher_policy.py",
        "shared/capability_availability_guarantor.py",
        "shared/platform_capability_registry.py",
        "shared/quota_spend_ledger.py",
        "shared/route_metadata_schema.py",
    ):
        assert decider in listed, (
            f"{decider} decides routes and is missing from the receipt entirely; a reader "
            f"cannot see that it participated. Listed: {sorted(listed)}"
        )


def test_vendored_code_is_not_reported_as_participating(tmp_path: Path) -> None:
    """The enumeration is first-party. Reporting site-packages would drown the real signal.

    Paired with the test above so the two pin a boundary rather than one side of it: an
    enumeration that returned everything would satisfy that one and fail this.
    """
    from shared import dispatcher_policy  # noqa: F401 - imported for its presence in sys.modules

    ident = adjudicator_identity()
    if ident.sha is None:
        pytest.skip("not running from a checkout")

    joined = " ".join(ident.loaded_modules)
    for vendored in ("site-packages", "dist-packages", "/.venv/"):
        assert vendored not in joined, f"{vendored} is not this tree's code"


# --------------------------------------------------------------------------------------
# The receipt reaches the real writers
# --------------------------------------------------------------------------------------


def _dimensional_receipt():
    """A receipt built through the REAL production path, not an extracted helper.

    Raised by coderabbitai on an earlier round: a test that exercises an extracted helper proves
    the helper works and says nothing about whether the receipt written to disk carries the
    field.
    """
    from datetime import UTC, datetime

    from shared.dispatcher_policy import (
        DispatchAction,
        DispatchRequest,
        RouteDecision,
        _build_dimensional_route_receipt,
    )

    request = DispatchRequest(
        task_id="t",
        lane="roleless",
        platform="glmcp",
        mode="review",
        profile="direct",
        route_id="glmcp.review.direct",
        route_metadata_status="ok",
    )
    decision = RouteDecision(
        decision_id="rd-20260820T120000Z-t-aaaaaaaaaaaa",
        created_at=datetime(2026, 8, 20, 12, tzinfo=UTC),
        task_id="t",
        lane="roleless",
        route_id=request.route_id,
        platform=request.platform,
        mode=request.mode,
        profile=request.profile,
        action=DispatchAction.HOLD,
        policy_outcome="hold",
        launch_allowed=False,
        prompt_allowed=False,
        quality_floor_satisfied=False,
        authority_allowed=False,
        reason_codes=("x",),
        message="m",
    )

    return _build_dimensional_route_receipt(decision, request)


def test_route_receipt_carries_the_adjudicator_alongside_the_basis_name() -> None:
    """The wiring, end to end through serialization."""
    serialized = _dimensional_receipt().model_dump(mode="json")

    assert serialized["routing_model_version"] == "capacity-dimensional-v1", (
        "the basis name is retained; it was never wrong, only misread"
    )
    # Assert the receipt carries the RESOLVED identity, not the field default.
    #
    # An earlier version allowed any of the three sources and only checked the sha
    # `if source != "indeterminate"`. That passed vacuously when the wiring was removed: the
    # model defaults `adjudicator_source` to "indeterminate", so an unwired receipt satisfied
    # the assertion and the guard skipped the sha check. Mutation caught it — removing the
    # `**adjudicator_identity().as_receipt()` spread left every test green. Presence
    # substituted for satisfaction, inside the test written to prevent exactly that.
    expected = adjudicator_identity()
    assert serialized["adjudicator_source"] == expected.source, (
        "the receipt is carrying the model's default rather than the resolved identity; a "
        "defaulted adjudicator field is the same zero-bit placeholder routing_model_version was"
    )
    assert serialized["adjudicator_sha"] == expected.sha
    assert serialized["adjudicator_resolved_from"] == expected.resolved_from
    assert serialized["adjudicator_dirty"] == expected.dirty
    assert serialized["adjudicator_loaded_modules"] == list(expected.loaded_modules)
    assert serialized["adjudicator_loaded_modules"], (
        "the coverage statement must not be empty on a real receipt; an empty list reads as "
        "'nothing participated', which is never true"
    )
    # Kept conditional deliberately and narrowly: the sha SHAPE is only assertable when a sha
    # exists, and the unconditional equality checks above already pin the value in every case.
    # This is the distinction the other conditionals lacked — they were the only assertion in
    # their branch, so skipping the branch skipped the test.
    if expected.sha is not None:
        assert SHA_RE.match(serialized["adjudicator_sha"] or "")


def test_a_route_receipt_stays_hashable() -> None:
    """Raised by coderabbitai: `_PolicyModel` is frozen, so Pydantic derives `__hash__`.

    A `list` field makes every `DimensionalRouteReceipt` unhashable, so `hash(receipt)` and any
    set or dict-key use raises TypeError — a failure that appears in whatever code first puts a
    receipt in a set, far from the field that caused it. Every other collection on the model is
    already a tuple.
    """
    from shared.dispatcher_policy import DimensionalRouteReceipt

    receipt = _dimensional_receipt()
    assert isinstance(receipt, DimensionalRouteReceipt)
    assert hash(receipt) == hash(receipt), "a frozen receipt must be usable as a key"
    assert len({receipt, receipt}) == 1
    assert isinstance(receipt.adjudicator_loaded_modules, tuple)


def _load_determine():
    """Import the extensionless `scripts/hapax-determine` as a module."""
    import importlib.machinery
    import importlib.util

    loader = importlib.machinery.SourceFileLoader(
        "hapax_determine_under_test", str(REPO_ROOT / "scripts" / "hapax-determine")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _registry_with_one_producer(tmp_path: Path) -> Path:
    registry = tmp_path / "producers.json"
    registry.write_text(
        json.dumps(
            {
                "producers": [
                    {
                        "id": "probe",
                        "property": "p",
                        "subjects": [],
                        "provenance": "mechanical",
                        "command": ["/bin/true"],
                        "cadence_seconds": 300,
                        "evidence_ttl_seconds": 3600,
                    }
                ]
            }
        )
    )
    return registry


def test_determination_run_record_carries_the_adjudicator() -> None:
    """The spine's ledger already carried `provenance`, which answers a different question.

    `provenance` says how the PROPERTY was established (mechanical vs attested), not which build
    established it. Both must survive.
    """
    from datetime import UTC, datetime

    module = _load_determine()
    record = module.run_producer(
        {
            "id": "probe",
            "property": "p",
            "subjects": [],
            "provenance": "mechanical",
            "command": ["/bin/true"],
        },
        now=datetime.now(UTC),
        repo_root=REPO_ROOT,
        timeout=10,
    )

    assert record["outcome"] == "produced"
    assert "adjudicator_source" in record
    assert record["provenance"] == "mechanical", (
        "provenance and adjudicator answer different questions and must both survive"
    )


def test_main_reports_unidentified_runs_in_its_json_payload(tmp_path: Path, capsys) -> None:
    """Raised by codex-1: the new behaviour had no test through `main` at all.

    A field nothing exercises end to end is the estate's characteristic failure, and shipping
    one inside the change that exists to name that failure would be the sharpest instance of it.
    """
    module = _load_determine()
    rc = module.main(
        [
            "--registry",
            str(_registry_with_one_producer(tmp_path)),
            "--run-ledger",
            str(tmp_path / "runs.jsonl"),
            "--force",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert [r["producer_id"] for r in payload["ran"]] == ["probe"]
    assert "runs_without_identified_checkout" in payload, (
        "the key must exist even when the list is empty"
    )
    ran = payload["ran"][0]
    assert (ran["producer_id"] in payload["runs_without_identified_checkout"]) is (
        not record_identifies_its_checkout(ran)
    ), "the payload must partition exactly on the check, not approximate it"


def test_main_names_an_unidentifiable_run_on_stderr(tmp_path: Path, capsys, monkeypatch) -> None:
    """The text branch must say WHICH run it cannot attribute, and still exit 0.

    An unidentifiable run is a diagnostic, not a veto — refusing to record it would lose the
    evidence entirely.
    """
    module = _load_determine()
    monkeypatch.setattr(module, "record_identifies_its_checkout", lambda record: False)

    rc = module.main(
        [
            "--registry",
            str(_registry_with_one_producer(tmp_path)),
            "--run-ledger",
            str(tmp_path / "runs.jsonl"),
            "--force",
        ]
    )
    captured = capsys.readouterr()

    assert rc == 0, "an unattributable run is still a run; this is a diagnostic, not a veto"
    assert "probe: produced" in captured.out, "the run must still be reported"
    assert "UNIDENTIFIED CHECKOUT probe" in captured.err
    assert "repair from a redeploy" in captured.err
    assert "Next:" in captured.err, (
        "the executive_function axiom requires an error to carry its next action; a diagnostic "
        "that names a problem and no remedy makes the operator the lookup table"
    )


def test_main_is_silent_when_every_run_is_identified(tmp_path: Path, capsys, monkeypatch) -> None:
    """The other branch — otherwise the test above passes against a hardcoded warning.

    Paired deliberately: a diagnostic that fires unconditionally is indistinguishable from one
    that fires correctly, and only the pair can tell them apart.
    """
    module = _load_determine()
    monkeypatch.setattr(module, "record_identifies_its_checkout", lambda record: True)

    rc = module.main(
        [
            "--registry",
            str(_registry_with_one_producer(tmp_path)),
            "--run-ledger",
            str(tmp_path / "runs.jsonl"),
            "--force",
        ]
    )
    captured = capsys.readouterr()

    assert rc == 0
    assert "probe: produced" in captured.out
    assert "UNIDENTIFIED" not in captured.err


def test_the_dataclass_defaults_do_not_assert_anything() -> None:
    """An identity constructed with nothing known must claim nothing.

    The defaults are what a partially-populated record falls back to, so they are the quietest
    place for an over-claim to hide.
    """
    ident = AdjudicatorIdentity(sha=None, source="indeterminate", resolved_from="/nowhere")

    assert ident.dirty is None, "unknown, not clean"
    assert ident.loaded_modules == ()
    assert ident.declared_sha is None
    assert not record_identifies_its_checkout(ident.as_receipt())
