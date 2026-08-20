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
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SHA_RE = re.compile(r"\A[0-9a-f]{40}\Z")


@pytest.fixture(autouse=True)
def _clear_cache():
    """`adjudicator_identity` is lru_cached; tests must not observe each other's answers."""
    adjudicator_identity.cache_clear()
    yield
    adjudicator_identity.cache_clear()


def test_release_tree_path_is_authoritative() -> None:
    """A deployed release encodes its sha in the path; that is the strongest identity."""
    sha = "0" * 39 + "a"
    ident = adjudicator_identity(
        f"/home/hapax/.cache/hapax/source-activation/releases/{sha}/shared/adjudicator_identity.py"
    )
    assert ident.sha == sha
    assert ident.source == "release_tree"
    assert ident.dirty is False


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

    assert id_a.sha == a
    assert id_b.sha == b
    assert id_a.sha != id_b.sha, (
        "two decisions made from different release trees must be distinguishable; this is the "
        "whole point of the field"
    )


def test_git_worktree_is_weaker_and_says_so() -> None:
    """A development checkout is a real answer, but not an authoritative one."""
    ident = adjudicator_identity(str(REPO_ROOT / "shared" / "adjudicator_identity.py"))
    assert ident.source in {"git_worktree", "release_tree"}
    if ident.source == "git_worktree":
        assert SHA_RE.match(ident.sha or ""), "a git identity must carry a real HEAD sha"
        assert ident.source != "release_tree", (
            "a git worktree may be dirty, so its sha does not fully determine the code; only a "
            "release tree is authoritative"
        )
        head = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert ident.sha == head


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
    """What gets written onto a decision must survive JSON and carry all four fields."""
    ident = adjudicator_identity(
        "/home/hapax/.cache/hapax/source-activation/releases/" + "c" * 40 + "/shared/x.py"
    )
    receipt = ident.as_receipt()
    assert set(receipt) == {
        "adjudicator_sha",
        "adjudicator_source",
        "adjudicator_resolved_from",
        "adjudicator_dirty",
    }
    assert json.loads(json.dumps(receipt)) == receipt


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
    assert "adjudicator_sha" not in legacy_record
    assert not any(SHA_RE.match(str(value)) for value in legacy_record.values()), (
        "no value in a legacy record is a code identity; the field name is not the thing"
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
    if expected.source != "indeterminate":
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


def test_identity_is_stable_within_a_process() -> None:
    """Cached deliberately: the loaded module cannot be relocated mid-run.

    That invariant is what makes `__file__` correct and the symlink incorrect, so the cache is
    part of the design rather than an optimisation.
    """
    first = adjudicator_identity()
    second = adjudicator_identity()
    assert first is second
    assert isinstance(first, AdjudicatorIdentity)
