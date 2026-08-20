"""A decision that does not name its adjudicator is not replayable.

Measured 2026-08-20: `route-decisions.jsonl` carries `routing_model_version` on 559 of 559
records and its value is the constant `"capacity-dimensional-v1"` — a basis name. None of the
48 keys on a record holds a 40-hex sha. Meanwhile the activation symlink repointed roughly
7x/day across Aug 17-20 and moved twice during the session that wrote these tests
(`150462adc0af` -> `45086a03e7a4`), while `~/.claude/settings.json` pins its hooks to an
absolute release path frozen 11 days earlier.

So every mechanical check over that history is void across a redeploy boundary: a check that
reddens today and greens tomorrow may be evidence of a repair, or may be evidence that
different code ran.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from shared.adjudicator_identity import (
    AdjudicatorIdentity,
    adjudicator_identity,
    record_has_usable_adjudicator,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SHA_RE = re.compile(r"\A[0-9a-f]{40}\Z")


@pytest.fixture(autouse=True)
def _clear_cache():
    """`adjudicator_identity` is lru_cached; tests must not observe each other's answers."""
    adjudicator_identity.cache_clear()
    yield
    adjudicator_identity.cache_clear()


def test_a_release_path_alone_is_a_claim_not_a_verified_identity() -> None:
    """Raised by codex-1 and confirmed by measurement: release trees here are WRITABLE.

    At the time of writing, the live release tree `45086a03…` carried a modified
    `scripts/hapax-determine` while its directory name asserted that commit. An earlier version
    of this module read the sha out of the path and reported `dirty=False`, which would have
    attributed a decision to a commit the running code did not match — defeating the exact
    guarantee the module exists to provide.

    A release path with nothing verifiable behind it therefore keeps its claim in
    `declared_sha` and leaves `sha` None, rather than promoting an unverified name into the
    verified slot.
    """
    sha = "0" * 39 + "a"
    ident = adjudicator_identity(
        f"/home/hapax/.cache/hapax/source-activation/releases/{sha}/shared/adjudicator_identity.py"
    )
    assert ident.declared_sha == sha, "the claim must be preserved, not discarded"
    assert ident.sha is None, "an unverifiable claim must not occupy the verified slot"
    assert ident.source == "indeterminate"
    assert not record_has_usable_adjudicator(ident.as_receipt())


def test_the_release_layout_only_means_release_inside_the_trusted_root(
    tmp_path: Path, monkeypatch
) -> None:
    """Raised by coderabbitai: a substring is not a location.

    The first implementation regex-searched for ``/source-activation/releases/<40-hex>``
    anywhere in the resolved path, so ANY directory that happened to contain those components
    was read as a deployed release — a scratch copy, an unpacked archive, a fixture tree. That
    turns the estate's most load-bearing provenance claim into something any writable directory
    can mint by choosing its own name.

    Containment is checked against the root the activator actually writes
    (``scripts/hapax-source-activate:34``), so the same layout outside that root carries no
    authority and no ``declared_sha``: ``resolved_from`` keeps the full path for forensics,
    while the untrusted sha is not surfaced in a field a reader would take as a claim of
    deployment.
    """
    monkeypatch.setenv("HAPAX_SOURCE_ACTIVATE_STATE_DIR", str(tmp_path / "trusted"))
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


def test_the_trusted_root_follows_the_activators_own_configuration(
    tmp_path: Path, monkeypatch
) -> None:
    """The same layout INSIDE the trusted root does yield the claim — the check is location.

    Paired with the test above so the pair pins a distinction rather than one half of it: if
    containment were implemented as "always False" both the impostor assertion and this one
    could not pass together. The root is read from the activator's own
    ``HAPAX_SOURCE_ACTIVATE_STATE_DIR`` rather than a constant duplicated here, so this test
    fails if the two ever disagree about where releases live.
    """
    state_dir = tmp_path / "trusted"
    monkeypatch.setenv("HAPAX_SOURCE_ACTIVATE_STATE_DIR", str(state_dir))
    sha = "c" * 40
    tree = state_dir / "releases" / sha / "shared"
    tree.mkdir(parents=True)
    module = tree / "adjudicator_identity.py"
    module.write_text("# a deployment, unverifiable — no checkout behind it\n")

    ident = adjudicator_identity(str(module))

    assert ident.declared_sha == sha, "inside the trusted root the path's claim is recorded"
    assert ident.sha is None, "still unverified: there is no checkout behind this tree"
    assert ident.source == "indeterminate"
    assert not record_has_usable_adjudicator(ident.as_receipt())


def test_identity_is_resolved_from_the_module_not_the_symlink() -> None:
    """The core design decision, pinned.

    Reading `~/.cache/hapax/source-activation/worktree` would name whatever the symlink points
    at NOW. If it repoints mid-run — measured twice in one session — the receipt attributes a
    decision to code that did not make it. `__file__` cannot drift out from under a running
    process.

    This asserts the resolution is a pure function of the path handed in: a caller in release
    tree A gets A, regardless of where any symlink currently points.
    """
    a = "a" * 40
    b = "b" * 40
    base = "/home/hapax/.cache/hapax/source-activation/releases"
    id_a = adjudicator_identity(f"{base}/{a}/shared/adjudicator_identity.py")
    adjudicator_identity.cache_clear()
    id_b = adjudicator_identity(f"{base}/{b}/shared/adjudicator_identity.py")

    assert id_a.declared_sha == a
    assert id_b.declared_sha == b
    assert id_a.declared_sha != id_b.declared_sha, (
        "two decisions made from different release trees must be distinguishable; this is the "
        "whole point of the field"
    )
    assert id_a.resolved_from != id_b.resolved_from


def _make_checkout(root: Path, content: str) -> Path:
    """A real git checkout with one commit, returning the module path inside it."""
    root.mkdir(parents=True)
    run = lambda *a: subprocess.run(  # noqa: E731 - terse local helper, not exported
        ["git", "-C", str(root), *a], check=True, capture_output=True
    )
    run("init", "-q")
    run("config", "user.email", "test@example.invalid")
    run("config", "user.name", "test")
    module = root / "shared" / "adjudicator_identity.py"
    module.parent.mkdir(parents=True)
    module.write_text(content)
    run("add", "-A")
    run("commit", "-q", "-m", content)
    return module


def test_two_real_trees_are_distinguishable_by_the_verified_sha(tmp_path: Path) -> None:
    """Raised by codex-1: the test above pins `declared_sha`, not `adjudicator_sha`.

    The exit predicate requires two records from different trees to be distinguishable **by
    adjudicator_sha**. The path-only test cannot witness that — its trees are unverifiable, so
    both shas are None, and `None != None` is false anyway. It demonstrated a real but different
    property while leaving the required one unevidenced.

    This builds two actual checkouts with different commits, so the field under the predicate is
    the field under assertion.
    """
    module_a = _make_checkout(tmp_path / "tree-a", "# tree a\n")
    module_b = _make_checkout(tmp_path / "tree-b", "# tree b\n")

    id_a = adjudicator_identity(str(module_a))
    adjudicator_identity.cache_clear()
    id_b = adjudicator_identity(str(module_b))

    assert SHA_RE.match(id_a.sha or ""), "a real checkout must yield a verified sha"
    assert SHA_RE.match(id_b.sha or "")
    assert id_a.sha != id_b.sha, (
        "two decisions produced from different trees must be distinguishable by adjudicator_sha "
        "— the predicate's actual requirement"
    )
    assert id_a.source == id_b.source == "git_worktree"
    assert id_a.dirty is False and id_b.dirty is False, "freshly committed trees are clean"
    assert id_a.source_matches_head is None, (
        "an explicitly supplied module_file was never loaded by this process, so the strongest "
        "claim must stay unknown rather than being minted by a fixture"
    )


def test_a_real_checkout_resolves_to_its_verified_head() -> None:
    """Assert unconditionally against the environment's actual state.

    An earlier version wrapped these assertions in `if ident.source == "git_worktree":`, so any
    other source made the test pass having checked nothing. This is the third instance in these
    PRs of a conditional inside an assertion swallowing the failure mode — the branch that gets
    skipped is exactly the one the defect takes. Found here by grepping my own diff for the
    shape rather than waiting for a reviewer to find it a fourth time.

    The test environment is knowable, so it is asserted rather than branched on: these tests
    run from a git checkout, whether or not that checkout also sits under a release path.
    """
    ident = adjudicator_identity(str(REPO_ROOT / "shared" / "adjudicator_identity.py"))
    head = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    assert ident.source in {"git_worktree", "release_tree"}, (
        f"tests run from a checkout; got source={ident.source!r} at {ident.resolved_from}"
    )
    assert ident.sha == head, "the identity must be the tree's verified HEAD, not a path guess"
    assert SHA_RE.match(ident.sha or "")
    assert ident.dirty in (True, False, None)

    dirty_files = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert ident.dirty is bool(dirty_files), (
        "dirtiness must reflect the tree that was actually inspected; reporting clean for a "
        "modified tree is how a sha claims more than it knows"
    )


def test_unknown_location_is_indeterminate_not_a_guess(tmp_path: Path) -> None:
    """The typed-unknown rule, applied to provenance.

    A location that is neither a release tree nor a git checkout must yield `indeterminate`
    with `sha: None`. Defaulting to a plausible sha would attribute a decision to code that
    may not have produced it — the same defect this module exists to prevent, one level down.
    """
    stray = tmp_path / "shared" / "adjudicator_identity.py"
    stray.parent.mkdir(parents=True)
    stray.write_text("# not a release tree and not a git checkout\n")

    ident = adjudicator_identity(str(stray))
    assert ident.sha is None
    assert ident.source == "indeterminate"
    assert ident.resolved_from == str(stray.resolve()), (
        "even when the sha is unknown the resolved path must be recorded, so the claim is "
        "auditable rather than merely absent"
    )


def test_receipt_shape_is_serializable_and_complete() -> None:
    """What gets written onto a decision must survive JSON and carry every field.

    `adjudicator_declared_sha` is part of the shape precisely because it can disagree with
    `adjudicator_sha`; a receipt that dropped it would hide the disagreement.
    """
    ident = adjudicator_identity(
        "/home/hapax/.cache/hapax/source-activation/releases/" + "c" * 40 + "/shared/x.py"
    )
    receipt = ident.as_receipt()
    assert set(receipt) == {
        "adjudicator_sha",
        "adjudicator_source",
        "adjudicator_resolved_from",
        "adjudicator_dirty",
        "adjudicator_source_matches_head",
        "adjudicator_declared_sha",
    }
    assert json.loads(json.dumps(receipt)) == receipt
    assert receipt["adjudicator_declared_sha"] == "c" * 40
    assert receipt["adjudicator_sha"] is None


def test_a_basis_name_constant_does_not_satisfy_the_check() -> None:
    """The negative test the exit predicate requires.

    `routing_model_version: "capacity-dimensional-v1"` is present on 559/559 existing records
    and identifies nothing. A record carrying only that must NOT be treated as having an
    adjudicator.
    """
    legacy_record = {
        "decision_id": "rd-20260820T000000Z-legacy-aaaaaaaaaaaa",
        "routing_model_version": "capacity-dimensional-v1",
    }
    assert not record_has_usable_adjudicator(legacy_record), (
        "a record carrying only the basis-name constant must not count as identified; that "
        "constant is on 559/559 historical records and distinguishes nothing"
    )


@pytest.mark.parametrize(
    ("record", "usable", "why"),
    [
        (
            {
                "adjudicator_sha": "a" * 40,
                "adjudicator_source": "release_tree",
                "adjudicator_dirty": False,
                "adjudicator_source_matches_head": True,
            },
            True,
            "verified sha over a clean tree whose loaded source matches that commit",
        ),
        (
            {
                "adjudicator_sha": "a" * 40,
                "adjudicator_source": "git_worktree",
                "adjudicator_dirty": False,
                "adjudicator_source_matches_head": True,
            },
            True,
            "verified sha over a clean tree whose loaded source matches that commit",
        ),
        (
            {
                "adjudicator_sha": "a" * 40,
                "adjudicator_source": "release_tree",
                "adjudicator_dirty": False,
            },
            False,
            "raised by codex-1 as 'identity is measured from a mutable checkout after code "
            "load': every other field is measured when the receipt is WRITTEN, so a tree can "
            "be modified, run, and restored to a clean HEAD — dirty False, sha pointing at a "
            "commit that never executed. A record that never checked its loaded source against "
            "that commit has not answered the question, and absence is not a pass",
        ),
        (
            {
                "adjudicator_sha": "a" * 40,
                "adjudicator_source": "release_tree",
                "adjudicator_dirty": False,
                "adjudicator_source_matches_head": None,
            },
            False,
            "could-not-check is not checked-and-matched",
        ),
        (
            {
                "adjudicator_sha": "a" * 40,
                "adjudicator_source": "release_tree",
                "adjudicator_dirty": False,
                "adjudicator_source_matches_head": False,
            },
            False,
            "the process is executing code the claimed commit does not contain",
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
    assert record_has_usable_adjudicator(record) is usable, why


def test_a_failed_git_status_does_not_report_a_clean_tree(monkeypatch) -> None:
    """codex-1: "A failed git status is promoted to a verified clean identity."

    `git status --porcelain` returning non-zero produces empty stdout. An earlier version did
    `bool(status.stdout.strip())` without checking the return code, so failure-to-measure was
    rendered as measured-clean — this module's own defect, committed inside it, for the third
    time in two PRs.
    """
    import subprocess as sp

    from shared import adjudicator_identity as mod

    real_run = sp.run

    def fake_run(cmd, *args, **kwargs):
        if "status" in cmd:
            return sp.CompletedProcess(cmd, returncode=128, stdout="", stderr="fatal: bad object")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    head, dirty = mod._git_head(REPO_ROOT)
    assert head is not None, "HEAD is still knowable when only status failed"
    assert dirty is None, (
        "a failed status must yield UNKNOWN cleanliness, not False; False is a claim that the "
        "tree was inspected and found clean"
    )
    assert not record_has_usable_adjudicator(
        {"adjudicator_sha": head, "adjudicator_source": "git_worktree", "adjudicator_dirty": dirty}
    )


#: The shape of a route decision as written for the 559 records preceding this change: an
#: adjudicator field that exists in name and carries zero bits. Held here, in the repo, because
#: the live stream below is operator-local — raised by codex-1: a test that skips when the
#: ledger is absent cannot durably witness the claim it exists to witness, so CI would have
#: had no evidence for the central negative case at all.
LEGACY_ROUTE_DECISION_SHAPES = [
    {"routing_model_version": "capacity-dimensional-v1", "task_id": "t-1", "decision": "route"},
    {"routing_model_version": "capacity-dimensional-v1", "task_id": "t-2", "blocked": True},
    {"routing_model_version": "capacity-dimensional-v1", "adjudicator_sha": None},
    {"routing_model_version": "capacity-dimensional-v1", "adjudicator_sha": ""},
]


def test_no_legacy_route_decision_shape_can_pass_the_check() -> None:
    """The negative case, witnessed in CI rather than only on the operator's host.

    Every one of these is a real historical shape: `routing_model_version` present on 559 of 559
    records carrying the constant `"capacity-dimensional-v1"`, and none of the 48 keys holding a
    40-hex sha. If any of them passes, the check has stopped distinguishing "an adjudicator
    field exists" from "the adjudicator is known", which is the entire distinction it draws.
    """
    assert LEGACY_ROUTE_DECISION_SHAPES, "an empty fixture would make this test vacuous"
    for record in LEGACY_ROUTE_DECISION_SHAPES:
        assert not record_has_usable_adjudicator(record), record


def test_live_route_decisions_are_measured_not_assumed() -> None:
    """Run the check over the real historical stream, if present on this host.

    This is what makes the negative case evidence rather than assertion: the existing records
    were written before this field existed, so they must fail the check.

    Scoped to records that PREDATE the field — those with no `adjudicator_sha` key. Asserting
    that nothing in the stream is identified would be correct today and wrong the moment this
    lands, because the deployed spine will then write records that legitimately pass; a test
    that must be deleted to let the feature work is not a guard, it is a countdown.
    """
    stream = Path.home() / ".cache" / "hapax" / "orchestration" / "route-decisions.jsonl"
    if not stream.is_file():
        pytest.skip("no historical route-decision stream on this host")

    records = [json.loads(line) for line in stream.read_text().splitlines() if line.strip()]
    if not records:
        pytest.skip("route-decision stream is empty")

    legacy = [r for r in records if "adjudicator_sha" not in r]
    identified_legacy = [r for r in legacy if record_has_usable_adjudicator(r)]
    assert identified_legacy == [], (
        f"{len(identified_legacy)} of {len(legacy)} records that predate this field were "
        "reported as carrying a usable adjudicator identity"
    )


def test_route_receipt_carries_the_adjudicator_alongside_the_basis_name() -> None:
    """The wiring, end to end through serialization.

    `routing_model_version` is retained deliberately — it is a true fact about the model, it
    was simply being read as a code identity. Both must be present: one says which basis, the
    other says which build.
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

    serialized = _build_dimensional_route_receipt(decision, request).model_dump(mode="json")

    assert serialized["routing_model_version"] == "capacity-dimensional-v1", (
        "the basis name is retained; it was never wrong, only misread"
    )
    # Assert the receipt carries the RESOLVED identity, not the field default.
    #
    # An earlier version of this test allowed any of the three sources and only checked the
    # sha `if source != "indeterminate"`. That passed vacuously when the wiring was removed
    # entirely: the model defaults `adjudicator_source` to "indeterminate", so an unwired
    # receipt satisfied the assertion and the guard skipped the sha check. Mutation caught it
    # — removing the `**adjudicator_identity().as_receipt()` spread left every test green.
    #
    # Presence-substituted-for-satisfaction, inside the test written to prevent exactly that.
    expected = adjudicator_identity()
    assert serialized["adjudicator_source"] == expected.source, (
        "the receipt is carrying the model's default rather than the resolved identity; "
        "a defaulted adjudicator field is the same zero-bit placeholder "
        "routing_model_version already was"
    )
    assert serialized["adjudicator_sha"] == expected.sha
    assert serialized["adjudicator_resolved_from"] == expected.resolved_from
    assert serialized["adjudicator_dirty"] == expected.dirty
    # Kept conditional deliberately and narrowly: the sha SHAPE is only assertable when a sha
    # exists, and the unconditional equality checks above already pin the value in every case.
    # This is the distinction the other conditionals lacked — they were the only assertion in
    # their branch, so skipping the branch skipped the test.
    if expected.sha is not None:
        assert SHA_RE.match(serialized["adjudicator_sha"] or "")


def test_determination_run_record_carries_the_adjudicator() -> None:
    """A run ledger that cannot be compared across a redeploy is unreadable.

    The spine's ledger already carried `provenance`, but that says how the PROPERTY was
    established (mechanical vs attested), not which build established it.
    """
    import importlib.machinery
    import importlib.util
    from datetime import UTC, datetime

    loader = importlib.machinery.SourceFileLoader(
        "hapax_determine_under_test", str(REPO_ROOT / "scripts" / "hapax-determine")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)

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


def test_main_reports_unidentified_runs_in_its_json_payload(tmp_path: Path, capsys) -> None:
    """Raised by codex-1: the new behaviour had no test through `main` at all.

    `run_producer` was covered, but the payload key, both branches of the usable/unusable
    partition, and the stderr diagnostic were reachable only in production. A field nothing
    exercises end to end is the estate's characteristic failure, and shipping it inside the
    change that exists to name that failure would have been the sharpest possible instance.
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
    assert "unidentified_runs" in payload, "the key must exist even when the list is empty"
    ran = payload["ran"][0]
    assert (ran["producer_id"] in payload["unidentified_runs"]) is (
        not record_has_usable_adjudicator(ran)
    ), "the payload must partition exactly on the usability check, not approximate it"


def test_main_names_an_unidentifiable_run_on_stderr(tmp_path: Path, capsys, monkeypatch) -> None:
    """The text branch must say WHICH run it cannot attribute, and still exit 0.

    An unidentifiable run is a diagnostic, not a veto — refusing to record it would lose the
    evidence entirely. So the guard here is that the run is still reported and the exit code is
    unchanged, while the operator is told the receipt cannot distinguish a repair from a
    redeploy.
    """
    module = _load_determine()
    monkeypatch.setattr(module, "record_has_usable_adjudicator", lambda record: False)

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
    assert "UNIDENTIFIED probe" in captured.err
    assert "repair from a redeploy" in captured.err


def test_main_is_silent_when_every_run_is_identified(tmp_path: Path, capsys, monkeypatch) -> None:
    """The other branch — otherwise the test above passes against a hardcoded warning.

    Paired deliberately: a diagnostic that fires unconditionally is indistinguishable from one
    that fires correctly, and only the pair can tell them apart.
    """
    module = _load_determine()
    monkeypatch.setattr(module, "record_has_usable_adjudicator", lambda record: True)

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


def test_identity_is_stable_within_a_process() -> None:
    """Cached deliberately: the loaded module cannot be relocated mid-run.

    That invariant is what makes `__file__` correct and the symlink incorrect, so the cache is
    part of the design rather than an optimisation.
    """
    first = adjudicator_identity()
    second = adjudicator_identity()
    assert first is second
    assert isinstance(first, AdjudicatorIdentity)
