"""Ambiguity cannot supply admission: a scope must be disjoint under *every* plausible meaning.

The declaration carries reader grammar; a scope reference does not. So a colon-bearing relative
scope can denote either a local path or a qualified location, and admitting it because the
*convenient* reading is disjoint is the defect — in either direction.

These controls are written before the repair, deliberately. They are built to separate three rules
that the existing 36-case local-only reproduction cannot tell apart:

* **current**: classify by string shape — wrongly admits the bare rows A and D.
* **local-only**: treat every colon-bearing scope as local.
* **the contract**: refuse when contained under any plausible meaning.

Each counterfactual is caught, and by a different set of rows. **The intervention must change the
scope's interpretation only.** Replacing ``_has_qualifier`` outright also changes how a member's
*declaration* is parsed, because the same helper serves both — under that confound a remote
member's location becomes lexical and row B refuses for a reason that has nothing to do with the
scope's reading. Measured with scope-only interventions (``_scope_readings`` alone), on the 58 rows
here:

=========================  =======  ==================================================
rule                       failing  where
=========================  =======  ==================================================
qualified reading only      18      A/D/F bare, J, K (both readers)
local reading only           4      B (both), G, H
refuse anything ambiguous   33      A, C, E, H, I, J, K — admission gone
=========================  =======  ==================================================

Row B is a discriminator against the local-only rule; an earlier revision of this docstring said it
was not, on the strength of the confounded intervention above. Rows E-K guard the edges the rule
does not settle by itself: the remedy the refusal names must stay reachable (E), an alias must not
open a hole the literal spelling would have closed (F), the qualified side keeps its own
conservatism on same-host misses and undeclared hosts (G, H), an unparseable qualifier must not
fall back into local permission (I), one ambiguous ref must not decide a whole multi-ref scope (J),
and every unrelated decision must land exactly where its colon-free twin does (K). Row A's second
assertion is load-bearing for the same reason: a refusal that does not name the containment is not
the contract's refusal.
"""

import os
import pathlib

import pytest
import yaml

from shared import frame_verdicts as fv
from tests.frame_verdict_helpers import git_checkout
from tests.scripts import test_hapax_methodology_dispatch as dispatch_tests
from tests.scripts.test_frame_root_entries import _root_dispatch
from tests.shared.test_frame_verdicts import NOW, _procedure_root, _verdict


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

#: Carried as a strict xfail while the defect was open: a bare colon-bearing scope entered the
#: qualified namespace on its first segment, and against a *local* decayed member there was then
#: nothing qualified to compare it with, so ``_qualified_disjoint_established`` returned True on an
#: empty comparison and the local containment that does hold was never consulted. The repair reads
#: both meanings; strictness is what turned these four into failures the moment it landed.
BARE = "bare"


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
    """B: contained under the QUALIFIED meaning, disjoint under the local one.

    A member declaring a remote reader keeps `host:path` as its grammar, so this scope is
    contained there and must refuse. Reading every colon-bearing scope as local would find it
    disjoint and admit it, which is why fixing row A by choosing local everywhere is not the
    contract — both rows fail under a scope-only local rule.

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
@pytest.mark.parametrize("scope_form", ["bare", "dot", "absolute"])
def test_row_c_disjoint_under_every_meaning_admits(
    tmp_path, monkeypatch, capsys, reader, scope_form
):
    """C: outside the declared root under both readings, so admission is correct.

    The **bare** spelling is the one that carries the claim: it is ambiguous, and admitting it
    requires the scope to be established outside under the local reading *and* the qualified one.
    An absolute-only control would have established explicit-local admission and said nothing
    about the ambiguous case, so a repair that refused every colon-bearing scope would look right
    on A and B while having replaced one wrong answer with another.
    """

    root = tmp_path / "notes:archive"
    root.mkdir()
    (root / "candidate.txt").write_bytes(b"NEEDLE\n")

    elsewhere = tmp_path / "other:archive"
    elsewhere.mkdir()
    outside = elsewhere / "candidate.txt"
    outside.write_bytes(b"NEEDLE\n")

    relative = f"other:archive/{outside.name}"
    scope = {"bare": relative, "dot": f"./{relative}", "absolute": str(outside)}[scope_form]

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
        print(f"C {reader} scope={scope!r}: main()={rc}")

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


@pytest.mark.parametrize(
    ("spelling", "expected"),
    [
        ("notes://archive/future.py", 10),
        ("./notes:/archive/future.py", 10),
        ("absolute", 10),
        ("other://archive/future.py", 0),
    ],
    ids=["uri-shaped", "explicit-local", "absolute", "uri-shaped-disjoint"],
)
def test_row_n_a_uri_shaped_scope_keeps_its_local_reading(
    tmp_path, monkeypatch, capsys, spelling, expected
):
    """N: `//` does not make a scope unambiguous.

    I excluded the authority form from the second reading on the claim that its local meaning would
    need an empty path segment the filesystem grammar refuses. It does not: `_filesystem_scope_parts`
    drops empty segments, so `notes://archive/future.py` reads perfectly well as
    `notes:/archive/future.py` — a directory whose name ends in a colon, which is the very case this
    module exists for. The exception was the defect it was carved out of.

    Reported as critical by the codex reader at `893542fa0` with a reproduction; the disjoint row is
    theirs too, and it is the half that matters — removing the exception must not turn every
    URI-shaped scope into a refusal.
    """

    base = tmp_path / "scope-base"
    inner = base / "notes:/archive"
    inner.mkdir(parents=True)
    (inner / "present.py").write_bytes(b"NEEDLE\n")
    future = inner / "future.py"
    assert not future.exists(), "existence is not the test here either"

    scope = str(future) if spelling == "absolute" else spelling

    _pin_checkout_base(monkeypatch, base)
    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        {"path": str(base), "patterns": ["notes:/**/*.py"]},
        reader="fs.glob",
        cwd=base,
        candidate=scope,
    )
    with capsys.disabled():
        print(f"N scope={scope!r}: main()={rc} (expected {expected})")

    assert rc == expected


@pytest.mark.parametrize(
    ("scope_name", "expected"),
    [("alias.txt", 10), ("selected.txt", 10), ("distinct.txt", 0)],
    ids=["hard-link-alias", "the-selected-name", "a-genuinely-different-file"],
)
def test_row_p_a_hard_link_to_a_selected_file_is_that_file(
    tmp_path, monkeypatch, capsys, scope_name, expected
):
    """P: two names for one inode are one file, and only the filesystem knows.

    `resolve()` collapses symlinks, so the string comparison catches those. It cannot see a hard
    link: `alias.txt` and `selected.txt` are different strings naming the same bytes, and an
    in-place write through the admitted name changes the decayed file the guard was protecting
    (review finding, codex, 2026-09-07, reproduced with `gawk`/`gawk-5.4.0` on the installed tree).

    The third row is the one that keeps this honest: a distinct file in the same directory, under
    the same declaration, must still admit. Identity is the test, not neighbourhood.
    """

    root = tmp_path / "surface"
    root.mkdir()
    selected = root / "selected.txt"
    selected.write_bytes(b"NEEDLE\n")
    alias = root / "alias.txt"
    os.link(selected, alias)
    assert alias.samefile(selected), "the fixture must actually hard-link, not copy"
    distinct = root / "distinct.txt"
    distinct.write_bytes(b"NEEDLE\n")
    assert not distinct.samefile(selected)

    _pin_checkout_base(monkeypatch, tmp_path)
    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        {"path": str(root), "patterns": ["selected.txt"]},
        reader="fs.glob",
        cwd=tmp_path,
        candidate=str(root / scope_name),
    )
    with capsys.disabled():
        print(f"P scope={scope_name!r}: main()={rc} (expected {expected})")

    assert rc == expected


def test_row_q_an_unreadable_identity_is_not_evidence_of_disjointness(
    tmp_path, monkeypatch, capsys
):
    """Q: a filesystem that will not answer has not answered "different".

    Admission here is affirmative — it requires disjointness to be *established* — so a comparison
    that could not be made supplies no admission evidence. The first version of the identity check
    returned False on any OSError and called that "the behaviour that was there before", which is
    the fallback-discipline failure exactly: a precondition asserted away rather than checked.

    A genuinely absent path is the other case and must stay separable: it answers, and its answer
    is that nothing is there. Row D already depends on that.
    """

    root = tmp_path / "surface"
    root.mkdir()
    selected = root / "selected.txt"
    selected.write_bytes(b"NEEDLE\n")
    alias = root / "alias.txt"
    os.link(selected, alias)

    unreadable = {alias.resolve(), alias}
    real_identity = fv._file_identity
    monkeypatch.setattr(
        fv,
        "_file_identity",
        lambda path: fv._UNREADABLE if path in unreadable else real_identity(path),
    )

    _pin_checkout_base(monkeypatch, tmp_path)
    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        {"path": str(root), "patterns": ["selected.txt"]},
        reader="fs.glob",
        cwd=tmp_path,
        candidate=str(alias),
    )
    with capsys.disabled():
        print(f"Q unreadable identity: main()={rc}")

    assert rc == 10, "an unreadable comparison must not admit"
    assert "identity" in err, "and the refusal must say what could not be read"


@pytest.mark.parametrize("spelling", ["plain", "trailing-star"])
@pytest.mark.parametrize("failure", [PermissionError(13, "denied"), RuntimeError("symlink loop")])
def test_row_r_an_unresolvable_exclusion_is_an_actionable_refusal(
    tmp_path, monkeypatch, spelling, failure
):
    """R: resolving an exclusion touches the filesystem, and a refusal to answer is not an empty
    exclusion.

    `load_frame_verdicts` converts only `FrameVerdictsUnavailable` here, so a `PermissionError` or
    a symlink-loop `RuntimeError` escaped the refusal path entirely — no diagnostic, no remedy, no
    receipt (review finding, codex, 2026-09-07). Both resolution branches now convert, and both
    name the exclusion and its path. The trailing-star branch is separate code and was separately
    unguarded.
    """

    base = tmp_path / "base"
    root = base / "surface"
    root.mkdir(parents=True)
    (root / "selected.txt").write_bytes(b"NEEDLE\n")
    excluded = base / "unreadable-exclusion"
    excluded.mkdir()

    real_resolve = pathlib.Path.resolve

    def refuse(self, *args, **kwargs):
        if self.name == excluded.name:
            raise failure
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "resolve", refuse)

    member = _local_member(root=root, patterns=("selected.txt",))
    procedure = _procedure_root(
        tmp_path / "procedure",
        members=[member],
        verdicts=[_verdict("legacy-surface", "scope_exited")],
        exclusions=[
            {
                "id": "unreadable",
                # The trailing-star branch resolves the PARENT and keeps the last segment lexical,
                # so the unreadable directory has to be that parent for this row to exercise it.
                "paths": [
                    str(excluded / "generated") + "*"
                    if spelling == "trailing-star"
                    else str(excluded)
                ],
            }
        ],
    )

    with pytest.raises(fv.FrameVerdictsUnavailable) as caught:
        fv.load_frame_verdicts(procedure, now=NOW)

    assert "exclusion" in str(caught.value), "the refusal must name the exclusion"
    assert caught.value.remedy, "and carry a next action rather than escaping as a traceback"


def test_row_s_a_proven_outside_ref_survives_an_undecidable_sibling(tmp_path):
    """S: one ref's unresolved comparison is not the whole scope's answer.

    `all_inside` is false as soon as any one ref is provably outside, so raising at the first
    undecidable ref discarded a witness that had already settled the question — and two spellings
    of the same path then disagreed, because one of them happened to be undecidable. Only
    valid-but-undecidable containment defers; a malformed ref or an evidence fault still raises.
    """

    base = tmp_path / "base"
    root = base / "surface"
    root.mkdir(parents=True)
    (root / "selected.txt").write_bytes(b"NEEDLE\n")
    outside = base / "elsewhere.txt"
    outside.write_bytes(b"NEEDLE\n")

    verdicts = _decayed(tmp_path, _local_member(root=root, patterns=("selected.txt",)))
    undecidable = "surface/[s-s]elected.txt"

    with pytest.raises(fv.UndecidableScopeContainment):
        fv.scope_within_decayed([undecidable], verdicts, council_root=base, vault_root=base)

    for refs in ([undecidable, str(outside)], [str(outside), undecidable]):
        result = fv.scope_within_decayed(refs, verdicts, council_root=base, vault_root=base)
        assert result.outside == (str(outside),), refs
        assert result.all_inside is False, refs


@pytest.mark.parametrize(
    "skip_dirs",
    [True, 42, "excluded", ["excluded", 7], [""], {"excluded": True}],
    ids=["bool", "int", "string", "mixed-list", "empty-name", "mapping"],
)
def test_row_o_a_malformed_skip_dirs_refuses_by_name_rather_than_crashing(
    tmp_path, monkeypatch, capsys, skip_dirs
):
    """O: a declaration the consumer cannot read is a refusal, not a traceback.

    `tuple(location["skip_dirs"])` accepted anything iterable and raised `TypeError` on anything
    else, so `skip_dirs: true` and `skip_dirs: 42` crashed the consumer with an empty stderr — no
    diagnostic, no remedy, no refusal receipt (review finding, codex, 2026-09-07). The string case
    is the one the crash was hiding: `"excluded"` is iterable, so it became one skipped directory
    per character and decided quietly, which is worse than failing.
    """

    root = tmp_path / "legacy"
    root.mkdir()
    (root / "candidate.txt").write_bytes(b"NEEDLE\n")

    _pin_checkout_base(monkeypatch, tmp_path)
    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        {"path": str(root), "patterns": ["*.txt"], "skip_dirs": skip_dirs},
        reader="fs.glob",
        cwd=tmp_path,
        candidate=str(root / "candidate.txt"),
    )
    with capsys.disabled():
        print(f"O skip_dirs={skip_dirs!r}: main()={rc} err={err.strip()[:90]!r}")

    assert rc == 10, "an unreadable member declaration must refuse"
    assert "skip_dirs" in err, "the refusal must name the field that cannot be read"
    assert "legacy-surface" in err, "and the member it belongs to"
    assert err.strip(), "an empty stderr is the failure this pins"


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
@pytest.mark.parametrize("scope_form", ["bare", "dot"])
def test_row_f_a_colon_bearing_alias_into_the_decayed_root_refuses(
    tmp_path, monkeypatch, capsys, reader, scope_form
):
    """F: an alias must not open a hole the literal spelling closes.

    The scope is spelled through a symlink whose own name carries a colon, so a repair that keys
    on the literal text rather than on where the path leads would find it outside the declared
    root. Aliasing is already refused in the plain namespace; introducing a colon must not be a
    way around that.

    The **bare** spelling is the one that tests the ambiguous hole: the dot spelling never leaves
    the local branch, so on its own it says nothing about whether the local reading of an ambiguous
    ref keeps the canonical alias resolution the explicit one has.
    """

    root = tmp_path / "notes:archive"
    root.mkdir()
    (root / "candidate.txt").write_bytes(b"NEEDLE\n")
    alias = tmp_path / "link:alias"
    alias.symlink_to(root, target_is_directory=True)

    relative = "link:alias/candidate.txt"
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
        print(f"F {reader} colon-bearing alias scope={scope!r}: main()={rc}")

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


# --------------------------------------------------------------------------------------------
# Rows J-M work directly on ``scope_within_decayed``. The properties they pin are about the
# verdict's shape and about which machinery each interpretation reaches — neither survives being
# collapsed into a dispatcher exit code, and one of them needs two refs in a single task scope,
# which the receipt-only dispatch fixture does not carry.
# --------------------------------------------------------------------------------------------


def _local_member(*, root=None, files=None, patterns=("*.txt",), reader="fs.glob"):
    location = {"patterns": list(patterns)}
    if files is not None:
        location["files"] = [str(item) for item in files]
    elif reader == "fs.content_query":
        location["roots"] = [str(root)]
        location["query"] = "NEEDLE"
    else:
        location["path"] = str(root)
    return {
        "id": "legacy-surface",
        "reader": {"id": reader, "version": "^1.0.0"},
        "location": location,
    }


def _decayed(tmp_path, member):
    procedure = _procedure_root(
        tmp_path / "procedure",
        members=[member],
        verdicts=[_verdict("legacy-surface", "scope_exited")],
    )
    if member["reader"]["id"] == "fs.content_query":
        (procedure / "declaration/params.yaml").write_text(
            yaml.safe_dump(
                {
                    "profile_id": "fixture",
                    "parameters": {
                        "max_unit_bytes": {"value": 1 << 20, "why": "test bound"},
                        "encoding_error_policy": {"value": "strict", "why": "test decoding"},
                    },
                }
            )
        )
    return fv.load_frame_verdicts(procedure, now=NOW)


def test_row_j_a_contained_ambiguous_ref_does_not_lose_an_unambiguous_outside_ref(tmp_path):
    """J: one ref's answer must not become the whole task's answer.

    A declared scope can carry several refs. Reading two meanings for one of them adds a way for
    that ref to refuse — it must not add a way for the *scope* to refuse before the other refs are
    decided. The contained ambiguous ref belongs in `matches`, the unambiguous outside ref in
    `outside`, and `all_inside` stays False because they disagree.
    """

    base = tmp_path / "base"
    root = base / "notes:archive"
    root.mkdir(parents=True)
    (root / "candidate.txt").write_bytes(b"NEEDLE\n")
    elsewhere = base / "other:archive"
    elsewhere.mkdir()
    outside = elsewhere / "candidate.txt"
    outside.write_bytes(b"NEEDLE\n")

    verdicts = _decayed(tmp_path, _local_member(root=root))
    result = fv.scope_within_decayed(
        ["notes:archive/candidate.txt", str(outside)],
        verdicts,
        council_root=base,
        vault_root=base,
    )

    assert [match.ref for match in result.matches] == ["notes:archive/candidate.txt"]
    assert result.outside == (str(outside),)
    assert result.all_inside is False


def _twin_outcome(tmp_path, name, tail, *, patterns, extra, reader="fs.glob"):
    """Run one scope shape against a directory named `name`, returning a comparable outcome.

    `name` differs only in whether the directory carries a colon, so two runs of this helper
    differ only in whether the scope reference is ambiguous. Anything else that differs between
    them is the namespace correction reaching work it has no business changing.
    """

    base = tmp_path / ("colon" if ":" in name else "plain")
    root = base / name
    root.mkdir(parents=True)
    for leaf in ("candidate.txt", "notes.md"):
        (root / leaf).write_bytes(b"NEEDLE\n")
    inner = root / "inner"
    inner.mkdir()
    (inner / "deep.md").write_bytes(b"NEEDLE\n")
    for leaf in extra:
        (base / leaf).write_bytes(b"NEEDLE\n")

    verdicts = _decayed(base, _local_member(root=root, patterns=patterns, reader=reader))
    ref = f"{name}{tail}"
    try:
        result = fv.scope_within_decayed([ref], verdicts, council_root=base, vault_root=base)
    except Exception as exc:  # noqa: BLE001 - the exception type is part of the outcome
        return type(exc).__name__
    return result.all_inside, len(result.matches), len(result.outside)


@pytest.mark.parametrize(
    "tail",
    ["/candidate.txt", "/", "/*.txt", "/*.md", "/**/*.md", "/inner/deep.md", "/missing.txt"],
)
@pytest.mark.parametrize("patterns", [("*.txt",), ("**/*",)], ids=["narrow", "broad"])
@pytest.mark.parametrize("reader", LOCAL_READERS)
def test_row_k_the_colon_changes_nothing_but_the_ambiguity(
    tmp_path, capsys, tail, patterns, reader
):
    """K: a scope over a colon-named directory must decide exactly as its colon-free twin.

    This is the control for everything the contract does *not* change. Each interpretation keeps
    its own dirlike and glob parsing, and the local reading keeps whatever admission basis it had:
    plain disjointness for some shapes, the canonical outside witness for a broad `fs.glob` one,
    and — for `fs.content_query` — the earlier undecidable refusal on a broad overlap, which is a
    reader-specific outcome the correction has no business flattening.

    Predicting each of those outcomes separately would only record what I expected; pinning them
    to the twin records the contract. The printed line carries what each shape actually decides,
    so the row cannot be mistaken for two identical refusals compared with each other.
    """

    colon = _twin_outcome(
        tmp_path, "notes:archive", tail, patterns=patterns, extra=("loose.md",), reader=reader
    )
    plain = _twin_outcome(
        tmp_path, "notes-archive", tail, patterns=patterns, extra=("loose.md",), reader=reader
    )
    with capsys.disabled():
        print(f"K {reader} tail={tail!r} patterns={patterns}: colon={colon} plain={plain}")

    assert colon == plain, "reading a second meaning changed a decision the colon does not touch"


def test_row_m_the_local_reading_keeps_its_checkout_projections(tmp_path):
    """M: an ambiguous ref is still tried under each declared member's own checkout.

    The dispatcher runs from one checkout while the mass declares members at another, so a
    repository-relative ref that could never match under the running tree matched under the
    declared one. That projection belongs to the local reading; giving a colon-bearing ref a
    second meaning must not cost it the first meaning's reach, or the guard is inert exactly
    where it runs.
    """

    running = tmp_path / "running"
    declared = tmp_path / "declared"
    git_checkout(running, history="frame scope grammar")
    git_checkout(declared, history="frame scope grammar")
    root = declared / "notes:archive"
    root.mkdir(parents=True)
    (root / "candidate.txt").write_bytes(b"NEEDLE\n")

    verdicts = _decayed(tmp_path, _local_member(root=root))
    ref = "notes:archive/candidate.txt"
    assert not (running / ref).exists(), "the running checkout must not hold the ref itself"

    result = fv.scope_within_decayed([ref], verdicts, council_root=running, vault_root=running)

    assert result.all_inside is True
    assert [match.member_id for match in result.matches] == ["legacy-surface"]
