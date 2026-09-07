"""Ambiguity cannot supply admission: a scope must be disjoint under *every* plausible meaning.

The declaration carries reader grammar; a scope reference does not. So a colon-bearing relative
scope can denote either a local path or a qualified location, and admitting it because the
*convenient* reading is disjoint is the defect — in either direction.

These controls are written before the repair, deliberately. They are built to separate three rules
that the existing 36-case local-only reproduction cannot tell apart:

* **current**: classify by string shape — refuses row B, wrongly admits row A.
* **local-only**: treat every colon-bearing scope as local — fixes row A, wrongly admits row B.
* **the contract**: refuse when contained under any plausible meaning — passes both.

Row B is therefore not decoration. It is the control that a naive fix to row A would break, and the
reason a namespace correction must not change unrelated member-reader support.

Rows E-I guard the edges the rule does not settle by itself: the remedy the refusal names must
actually be reachable (E), an alias must not open a hole the literal spelling would have closed (F),
and the qualified side must keep its own conservatism — same-host misses and undeclared hosts refuse
without the remote filesystem (G, H) — while an unparseable qualifier must not fall back into local
permission (I).
"""

import pytest

from tests.scripts import test_hapax_methodology_dispatch as dispatch_tests
from tests.scripts.test_frame_root_entries import _root_dispatch


def _pin_checkout_base(monkeypatch, base):
    """Make the dispatcher's checkout base the same synthetic directory as the producer cwd.

    ``scope_within_decayed`` receives ``council_root=REPO_ROOT_FOR_IMPORTS``, so without this a
    relative scope resolves against the real repository rather than the fixture, and a spelling
    that should be equivalent to its bare form behaves differently for a reason that has nothing to
    do with the grammar under test. A first run here that omitted it produced two extra failures
    that were fixture artifacts, not findings.
    """

    module = dispatch_tests._dispatcher_module()
    monkeypatch.setattr(module, "REPO_ROOT_FOR_IMPORTS", base)
    monkeypatch.setattr(dispatch_tests, "_dispatcher_module", lambda: module)


LOCAL_READERS = ("fs.content_query", "fs.glob")
REFUSED = "lies in legacy-surface (scope_exited)"
REMOTE_DECLARED = "podium.local:/remote/dir"

#: The one open defect these controls isolate: a bare colon-bearing scope enters the qualified
#: namespace on its first segment, and against a *local* decayed member there is then nothing
#: qualified to compare it with — so ``_qualified_disjoint_established`` returns True on an empty
#: comparison and the local containment that does hold is never consulted. Strict, so the repair
#: that closes it turns these into failures until the marks come off with it.
BARE = pytest.param(
    "bare",
    marks=pytest.mark.xfail(
        strict=True,
        reason="ambiguous bare colon scope admitted by empty qualified comparison",
    ),
)


def _location_for(reader, declared):
    location = {"patterns": ["*.txt"]}
    if reader == "fs.content_query":
        location.update(roots=[declared], query="NEEDLE")
    else:
        location.update(path=declared)
    return location


def _remote_location(**extra):
    location = {"path": REMOTE_DECLARED, "patterns": ["*.txt"]}
    location.update(extra)
    return location


@pytest.mark.parametrize("reader", LOCAL_READERS)
@pytest.mark.parametrize("scope_form", [BARE, "dot", "absolute"])
def test_row_a_local_contained_refuses_under_every_scope_spelling(
    tmp_path, monkeypatch, capsys, reader, scope_form
):
    """A: contained under the LOCAL meaning. Must refuse however the scope is spelled.

    The bare spelling is the one that fails today: the scope enters the qualified namespace
    because its first segment carries a colon, and the local containment that does hold is
    never consulted.
    """

    root = tmp_path / "notes:archive"
    root.mkdir()
    candidate = root / "candidate.txt"
    candidate.write_bytes(b"NEEDLE\n")

    relative = f"notes:archive/{candidate.name}"
    scope = {
        "bare": relative,
        "dot": f"./{relative}",
        "absolute": str(candidate),
    }[scope_form]

    _pin_checkout_base(monkeypatch, tmp_path)
    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        _location_for(reader, str(root)),
        reader=reader,
        cwd=tmp_path,
        candidate=scope,
    )
    with capsys.disabled():
        print(f"A {reader} scope={scope!r}: main()={rc}")

    assert rc == 10, "a scope contained under the local meaning must not be admitted"
    assert REFUSED in err


@pytest.mark.parametrize("scope_form", ["bare", "trailing-leaf"])
def test_row_b_qualified_contained_refuses_and_guards_the_naive_fix(
    tmp_path, monkeypatch, capsys, scope_form
):
    """B: contained under the QUALIFIED meaning while disjoint under the local one.

    A member declaring a remote reader keeps `host:path` as its grammar, so this scope is
    contained there. Reading every colon-bearing scope as local would find it disjoint and admit
    it — which is why fixing row A by choosing local everywhere is not the contract.

    Nothing here contacts a host: the decay verdict comes from the epoch's rows, and containment
    is a comparison of declared locations.
    """

    scope = {
        "bare": REMOTE_DECLARED,
        "trailing-leaf": f"{REMOTE_DECLARED}/rollout.txt",
    }[scope_form]

    _pin_checkout_base(monkeypatch, tmp_path)
    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        _remote_location(),
        reader="ssh.glob",
        cwd=tmp_path,
        candidate=scope,
    )
    with capsys.disabled():
        print(f"B ssh.glob scope={scope!r}: main()={rc}")

    assert rc == 10, "a scope contained under the qualified meaning must not be admitted"


@pytest.mark.parametrize("reader", LOCAL_READERS)
def test_row_c_disjoint_under_every_meaning_admits(tmp_path, monkeypatch, capsys, reader):
    """C: outside the declared root under both readings, so admission is correct.

    Without this, a repair that refused every colon-bearing scope would look right on A and B
    while having replaced one wrong answer with another.
    """

    root = tmp_path / "notes:archive"
    root.mkdir()
    (root / "candidate.txt").write_bytes(b"NEEDLE\n")

    elsewhere = tmp_path / "other:archive"
    elsewhere.mkdir()
    outside = elsewhere / "candidate.txt"
    outside.write_bytes(b"NEEDLE\n")

    _pin_checkout_base(monkeypatch, tmp_path)
    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        _location_for(reader, str(root)),
        reader=reader,
        cwd=tmp_path,
        candidate=outside,
    )
    with capsys.disabled():
        print(f"C {reader}: main()={rc}")

    assert rc == 0
    assert REFUSED not in err


@pytest.mark.parametrize("reader", LOCAL_READERS)
@pytest.mark.parametrize("scope_form", [BARE, "dot"])
def test_row_d_a_future_leaf_under_a_contained_root_still_refuses(
    tmp_path, monkeypatch, capsys, reader, scope_form
):
    """D: existence is never the test.

    A scope naming a file that does not exist yet must keep its intended creation surface — so a
    repair may not decide locality by asking the filesystem what is there today. The dot spelling
    carries this today; the bare spelling is expected to fail for row A's reason, and after the
    repair both must refuse for the containment reason rather than because the leaf is absent.
    """

    root = tmp_path / "notes:archive"
    root.mkdir()
    candidate = root / "candidate.txt"
    candidate.write_bytes(b"NEEDLE\n")
    future = root / "not-created-yet.txt"
    assert not future.exists()
    relative = f"notes:archive/{future.name}"
    scope = {"bare": relative, "dot": f"./{relative}"}[scope_form]

    _pin_checkout_base(monkeypatch, tmp_path)
    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        _location_for(reader, str(root)),
        reader=reader,
        cwd=tmp_path,
        candidate=scope,
    )
    with capsys.disabled():
        print(f"D {reader} future leaf scope={scope!r}: main()={rc}")

    assert rc == 10, "a not-yet-created leaf under a decayed root must not be admitted"


@pytest.mark.parametrize("reader", LOCAL_READERS)
def test_row_e_the_remedy_the_refusal_names_is_reachable(tmp_path, monkeypatch, capsys, reader):
    """E: the explicit local spelling the remedy names must actually admit when it is disjoint.

    The refusal tells the operator to re-spell the scope as `./…` or absolute. A repair that
    discharged rows A and B by refusing every colon-bearing scope would leave that instruction
    pointing at a dead end, which is a worse failure than the one it replaced: a false "cannot".
    """

    root = tmp_path / "notes:archive"
    root.mkdir()
    (root / "candidate.txt").write_bytes(b"NEEDLE\n")

    elsewhere = tmp_path / "other:archive"
    elsewhere.mkdir()
    (elsewhere / "candidate.txt").write_bytes(b"NEEDLE\n")

    _pin_checkout_base(monkeypatch, tmp_path)
    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        _location_for(reader, str(root)),
        reader=reader,
        cwd=tmp_path,
        candidate="./other:archive/candidate.txt",
    )
    with capsys.disabled():
        print(f"E {reader} explicit-local disjoint: main()={rc}")

    assert rc == 0, "the explicit local spelling named by the remedy must remain usable"
    assert REFUSED not in err


@pytest.mark.parametrize("reader", LOCAL_READERS)
def test_row_f_a_colon_bearing_alias_into_the_decayed_root_refuses(
    tmp_path, monkeypatch, capsys, reader
):
    """F: an alias must not open a hole the literal spelling closes.

    The scope is spelled through a symlink whose own name carries a colon, so a repair that keys
    on the literal text rather than on where the path leads would find it outside the declared
    root. Aliasing is already refused in the plain namespace; introducing a colon must not be a
    way around that.
    """

    root = tmp_path / "notes:archive"
    root.mkdir()
    (root / "candidate.txt").write_bytes(b"NEEDLE\n")
    alias = tmp_path / "link:alias"
    alias.symlink_to(root, target_is_directory=True)

    _pin_checkout_base(monkeypatch, tmp_path)
    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        _location_for(reader, str(root)),
        reader=reader,
        cwd=tmp_path,
        candidate="./link:alias/candidate.txt",
    )
    with capsys.disabled():
        print(f"F {reader} colon-bearing alias: main()={rc}")

    assert rc == 10, "an alias into the decayed root must not be admitted"


def test_row_g_same_host_lexical_miss_still_refuses(tmp_path, monkeypatch, capsys):
    """G: on the declared host, a lexical path mismatch is not disjointness.

    Deciding this would need the remote filesystem and the remote working directory, and the
    decision path consults neither. The conservatism is the qualified side's own, and the repair
    to the local/qualified cross must not loosen it into an admission.
    """

    _pin_checkout_base(monkeypatch, tmp_path)
    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        _remote_location(),
        reader="ssh.glob",
        cwd=tmp_path,
        candidate="podium.local:/remote/elsewhere/rollout.txt",
    )
    with capsys.disabled():
        print(f"G ssh.glob same-host lexical miss: main()={rc}")

    assert rc == 10, "a same-host miss is unresolved, not disjoint"


def test_row_h_an_undeclared_host_refuses_and_names_the_alias_remedy(tmp_path, monkeypatch, capsys):
    """H: a host the member never declared leaves containment undecidable.

    The remedy is the producer's: declare the host, or map it in `location.host_aliases`. Silence
    about a host is not evidence that it is a different machine.
    """

    _pin_checkout_base(monkeypatch, tmp_path)
    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        _remote_location(host_aliases={"pod": "podium.local"}),
        reader="ssh.glob",
        cwd=tmp_path,
        candidate="unknown-host.local:/remote/dir/rollout.txt",
    )
    with capsys.disabled():
        print(f"H ssh.glob undeclared host: main()={rc}")

    assert rc == 10, "an undeclared remote host must not be treated as a different machine"
    assert "host_aliases" in err


@pytest.mark.parametrize("reader", LOCAL_READERS)
def test_row_i_an_unparseable_qualifier_does_not_fall_back_into_local_permission(
    tmp_path, monkeypatch, capsys, reader
):
    """I: failing to parse as qualified is not permission to read it as local.

    Under the local reading this scope is plainly outside the declared root, so a repair shaped as
    "if it does not parse as a qualified location, treat it as a local path" would admit it. That
    is the same defect as row A with the readings swapped: an interpretation that could not be
    settled, resolved in the direction that grants the work.
    """

    root = tmp_path / "notes:archive"
    root.mkdir()
    (root / "candidate.txt").write_bytes(b"NEEDLE\n")

    _pin_checkout_base(monkeypatch, tmp_path)
    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        _location_for(reader, str(root)),
        reader=reader,
        cwd=tmp_path,
        candidate="not a host!:archive/candidate.txt",
    )
    with capsys.disabled():
        print(f"I {reader} unparseable qualifier: main()={rc}")

    assert rc == 10, "an unparseable qualifier is undecidable, not locally disjoint"
    assert "authority" in err
