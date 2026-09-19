"""Ambiguity cannot supply admission: a scope needs an admission basis under *every* plausible
meaning.

The declaration carries reader grammar; a scope reference does not. So a colon-bearing relative
scope can denote either a local path or a qualified location, and admitting it because the
*convenient* reading permits it is the defect — in either direction.

**"Disjoint under every meaning" is too narrow, and this file said it for a day.** Disjointness is
one admission basis; the partial-scope outside witness is another, and it establishes
*noncontainment* rather than disjointness — which is the only thing `all_inside` claims. Rows C, E,
K and P2 all rest on that second basis, so the rule as first written described something stricter
than the controls beneath it enforce, and stricter than the estate's disposition allows. The
coordinator found the same over-narrow sentence in its own 08:04 disposition and corrected it in
place on 2026-09-07; this is the matching correction here. Prose that overclaims a rule is the same
failure as prose that names a limit the code does not keep — the direction differs, the gap between
what is written and what runs does not.

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

import errno
import os
import pathlib
import re
import subprocess
import sys

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


@pytest.mark.parametrize("reader", LOCAL_READERS)
@pytest.mark.parametrize("spelling", ["literal", "class"])
def test_row_p3_an_external_alias_is_the_same_file_under_either_spelling(
    tmp_path, monkeypatch, capsys, reader, spelling
):
    """P3: two spellings of one external hard link must not disagree, under either reader.

    The query reader's glob path compares resolved pathnames and parents, so an external hard link
    supplied no overlap witness: `outside/alias.txt` refused while `outside/[a-a]lias.txt` was
    admitted (review finding, codex, 2026-09-07). The class spelling denotes exactly the same file.

    A glob's identity hit is overlap, not whole containment, so it earns the undecidable refusal
    the in-root class alias already gets — not a declaration that the glob is contained.
    """

    root = tmp_path / "surface"
    root.mkdir()
    selected = root / "selected.txt"
    selected.write_bytes(b"NEEDLE\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    alias = outside / "alias.txt"
    os.link(selected, alias)

    location = {"patterns": ["selected.txt"]}
    if reader == "fs.content_query":
        location.update(roots=[str(root)], query="NEEDLE")
    else:
        location.update(path=str(root))
    scope = str(alias) if spelling == "literal" else str(outside / "[a-a]lias.txt")

    _pin_checkout_base(monkeypatch, tmp_path)
    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        location,
        reader=reader,
        cwd=tmp_path,
        candidate=scope,
    )
    with capsys.disabled():
        print(f"P3 {reader} {spelling} external alias: main()={rc}")

    assert rc == 10, "an external hard link is the selected file under either spelling"


@pytest.mark.parametrize(
    ("alias", "pattern"),
    [(True, "tool*"), (False, "tool*"), (True, "toolb*")],
    ids=["mixed-with-alias", "mixed-without-alias", "disjoint-only"],
)
def test_row_p2_one_aliased_file_does_not_make_a_mixed_glob_wholly_decayed(
    tmp_path, monkeypatch, capsys, alias, pattern
):
    """P2: an identity hit on one expansion entry is overlap, not containment of the whole scope.

    My first identity repair returned True as soon as any file the glob expands to aliased a
    selected one, and `ref_within_member`'s caller reads True as whole-scope containment — so a
    glob covering a link to the selected file **and** an independently admitted distinct file was
    refused as wholly decayed (review finding, codex, 2026-09-07, against round 41). A partial
    scope reported as a total one is the same error as admitting one: both replace a measurement
    with a convenient answer.

    **This row briefly asserted an undecidable refusal instead, and that was withdrawn.** Three
    reviewer families converged on calling this admission a critical, and I changed the
    partial-scope witness to withhold on an alias. The coordinator's objection is correct and the
    written record settles it two ways:

    * The witness establishes **noncontainment**, not disjointness. An alias proves overlap, and
      overlap does not contradict "this scope is not wholly inside the decayed union" — which is
      the only claim `all_inside` makes. I made a predicate answer a question it was not asked.
    * `scope_within_decayed` already admits a **multi-ref** scope when one ref is proved outside
      while another is contained or undecidable — a deferral I built myself. Refusing the
      single-ref glob for the same shape contradicts it.

    And `coordination-20260904/FRAME-REVIEW-SCOPE-DISPOSITION-20260907.md` states it outright:
    *"The consumer refuses wholly decayed scopes and does not replace partial-scope semantics with
    an any-match ban."* No later decision supersedes that. **Reviewer convergence is evidence about
    a mechanism, not authority over a policy**, and I treated four families agreeing as though it
    were the second.

    **The pairing this row first claimed did not exist** (coordinator, 2026-09-07 11:38). The
    second arm was spelled `toolb*`, which expands to one file nobody selected — a *disjoint-only*
    scope, admitted by `_local_disjoint_established` without the witness ever running. It could not
    be the control for the alias case, because the withdrawn guard did not act on it either: two
    rows agreeing proved nothing when only one of them was in the guard's reach. A control's twin
    must differ in the one fact under test and in nothing else, so the direct-mixed arm keeps the
    **same `tool*` pattern** over a fixture where the neighbour is an independent file rather than
    a second name for the selected one. The disjoint-only case is retained under its own name for
    the branch it actually exercises. Mutation-verified: re-applying the guard fails
    `mixed-with-alias` alone and leaves the other two green.
    """

    root = tmp_path / "surface"
    root.mkdir()
    selected = root / "tool"
    selected.write_bytes(b"NEEDLE\n")
    neighbour = root / "tool-1.0"
    if alias:
        os.link(selected, neighbour)
    else:
        neighbour.write_bytes(b"INDEPENDENT\n")
    (root / "toolbug").write_bytes(b"DIFFERENT\n")
    # `tool*` reaches the selected file, its neighbour and an unselected one: a mixed scope, whose
    # admission rests on the partial-scope witness. `toolb*` reaches only the unselected file and
    # is established disjoint one layer earlier. The explicit two-ref form of the mixed case is
    # row J2, which speaks the multi-ref API directly.
    scope = str(root / pattern)

    _pin_checkout_base(monkeypatch, tmp_path)
    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        {"path": str(root), "patterns": ["tool"]},
        reader="fs.glob",
        cwd=tmp_path,
        candidate=scope,
    )
    with capsys.disabled():
        print(f"P2 {pattern} with alias={alias}: main()={rc}")

    assert rc == 0, (
        f"{pattern} with alias={alias}: a scope reaching outside the member is a partial scope"
    )


@pytest.mark.parametrize("reader", LOCAL_READERS)
@pytest.mark.parametrize(
    ("scope_name", "expected"),
    [("alias.txt", 10), ("selected.txt", 10), ("distinct.txt", 0)],
    ids=["hard-link-alias", "the-selected-name", "a-genuinely-different-file"],
)
def test_row_p_a_hard_link_to_a_selected_file_is_that_file(
    tmp_path, monkeypatch, capsys, scope_name, expected, reader
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

    location = {"patterns": ["selected.txt"]}
    if reader == "fs.content_query":
        # The query reader has its own containment path, and it returned before the identity
        # comparison — so the same alias that refuses under fs.glob was admitted here.
        location.update(roots=[str(root)], query="NEEDLE")
    else:
        location.update(path=str(root))

    _pin_checkout_base(monkeypatch, tmp_path)
    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        location,
        reader=reader,
        cwd=tmp_path,
        candidate=str(root / scope_name),
    )
    with capsys.disabled():
        print(f"P scope={scope_name!r}: main()={rc} (expected {expected})")

    assert rc == expected


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("alias[12]", True),
        ("alias[123]", False),
        ("alias[312]", False),
        ("alias[321]", False),
        ("alias3", False),
        ("alias1", True),
    ],
    ids=[
        "both-aliases",
        "aliases-then-stranger",
        "stranger-first",
        "stranger-first-reversed",
        "the-stranger-alone",
        "one-alias-alone",
    ],
)
def test_row_p8_a_character_class_is_one_language_however_it_is_written(
    tmp_path, pattern, expected
):
    """P8: `alias[123]` and `alias[312]` name the same six files and must get the same answer.

    `_glob_witnesses` samples the FIRST choice in each character class rather than exhausting it,
    so the generated witness for `[123]` was `alias1` — a decayed file under another name, which
    is no witness — while `[312]` generated `alias3` and admitted. One finite language, two
    verdicts, decided by the order the author happened to type (coordinator, 2026-09-07 12:26;
    reproduced here at `1f8439bb3` as refused/admitted on identical files).

    My previous round said withholding broad disjointness left the partial-scope outcome
    unchanged. That was measured on two shapes and stated about all of them, and this is the case
    that shows it was too strong: before the broad repair these globs never reached the witness at
    all, so its sampling could not be seen.

    The repair gives the witness a second way to look — the entries the scope actually expands to
    — and changes nothing about what counts as one: still a file, still the same relative tail
    under every projection, still established outside every member. `alias[12]`, whose every entry
    is a decayed file, still finds none and is still refused; `alias1` alone is still contained.
    """

    base = tmp_path / "base"
    root = base / "surface"
    root.mkdir(parents=True)
    first = root / "selected1"
    first.write_bytes(b"NEEDLE ONE\n")
    second = root / "selected2"
    second.write_bytes(b"NEEDLE TWO\n")
    elsewhere = base / "elsewhere"
    elsewhere.mkdir()
    os.link(first, elsewhere / "alias1")
    os.link(second, elsewhere / "alias2")
    (elsewhere / "alias3").write_bytes(b"INDEPENDENT\n")

    verdicts = _decayed(tmp_path, _local_member(root=root, patterns=("selected1", "selected2")))
    result = fv.scope_within_decayed(
        [str(elsewhere / pattern)], verdicts, council_root=base, vault_root=base
    )

    assert result.all_inside is expected, (
        f"{pattern}: a character class is one language however its choices are ordered"
    )


@pytest.mark.parametrize("mixed", [False, True], ids=["only-the-alias", "alias-and-a-stranger"])
def test_row_p7_three_spellings_of_one_scope_agree_about_disjointness(tmp_path, mixed):
    """P7: the identity repair covers the broad spellings, not only the literal one.

    `_local_disjoint_established` compares path STRINGS, so the literal repair left the two broad
    spellings of the same directory still certifying disjointness over a hard link the literal
    spelling refused. Four reviewer families called that critical on `d0ecbe35`/`2f7c6b42`, and it
    reproduced at the predicate: `tool*` and `elsewhere/` answered `True` where `elsewhere/tool`
    answered `None`. A predicate that gives one situation two answers depending on how the caller
    spelled it is wrong in the spelling that says more, which is the one claiming disjointness.

    **This is not the withdrawn `aa5939179` under another name.** That guard put the identity check
    in the *witness*, which converted partial-scope admission into refusal — a policy change a
    standing disposition forbade. This one withholds only the disjointness CLAIM: admission falls
    through to the witness, which still says True for both broad spellings, so the mixed scope is
    admitted exactly as before and the wholly-aliased one is still refused by containment. The two
    assertions below are the pair that keeps those apart — the predicate changes, the outcome does
    not.
    """

    base = tmp_path / "base"
    root = base / "surface"
    root.mkdir(parents=True)
    selected = root / "tool"
    selected.write_bytes(b"NEEDLE\n")
    elsewhere = base / "elsewhere"
    elsewhere.mkdir()
    os.link(selected, elsewhere / "tool")
    if mixed:
        (elsewhere / "toolbug").write_bytes(b"DIFFERENT\n")

    verdicts = _decayed(tmp_path, _local_member(root=root, patterns=("tool",)))
    member = verdicts.decayed[0]
    spellings = {
        "literal": (elsewhere / "tool", False, None),
        "glob": (elsewhere, False, "tool*"),
        "dirlike": (elsewhere, True, None),
    }
    answers = {
        name: fv._local_disjoint_established(path, dirlike, pattern, member)
        for name, (path, dirlike, pattern) in spellings.items()
    }
    assert answers == {"literal": None, "glob": None, "dirlike": None}, (
        f"one arrangement, three spellings, one answer: {answers}"
    )

    # REVISED 2026-09-08 under the coordinator's prospective-effect-scope ruling, which is
    # explicit that it is not restricted to trailing-slash directory notation and applies to a
    # declared glob's denoted LANGUAGE.
    #
    # This assertion used to read `result.all_inside is not mixed` — the glob was expected to be
    # wholly inside whenever the directory happened to hold nothing but aliases. That encoded the
    # error codex reported at `81962feab` and claude named at this line: a present expansion
    # cannot establish exhaustive containment of an unbounded prospective language, because
    # `tool*` names files that do not exist yet and those are not in the member. The row was
    # written to prove the disjointness repair did not move admission, and it recorded the
    # admission it found rather than the one the contract requires.
    #
    # `mixed` no longer changes the answer, and that is the point: `tool*` denotes the same
    # unbounded language either way, so a stranger appearing beside the alias cannot be what
    # decides it. The two arrangements are not two languages whose present contents coincide;
    # each separately has a future outside witness.
    result = fv.scope_within_decayed(
        [str(elsewhere / "tool*")], verdicts, council_root=base, vault_root=base
    )
    assert result.all_inside is False, (
        "a glob's present expansion cannot prove exhaustive containment of its prospective "
        "language, whether or not a stranger happens to sit beside the alias today"
    )

    # And the half the ruling explicitly preserves: the LITERAL spelling names one finite thing,
    # which is the decayed file under another name, so it is still wholly inside and still
    # refuses. Without this the row above would be satisfied by admitting everything.
    literal = fv.scope_within_decayed(
        [str(elsewhere / "tool")], verdicts, council_root=base, vault_root=base
    )
    assert literal.all_inside is True, (
        "literal and single-choice-name hard-link refusal is preserved; only the unbounded "
        "language loses its containment proof"
    )


@pytest.mark.parametrize(
    ("target", "expected"),
    [("kept.txt", 10), ("dropped.txt", 0)],
    ids=["alias-of-a-selected-file", "alias-of-a-query-rejected-file"],
)
def test_row_p6_the_query_decides_the_surface_the_identity_check_compares_against(
    tmp_path, monkeypatch, capsys, target, expected
):
    """P6: a content-query member's surface is what its predicate accepts, not what globs match.

    The identity repair built the member's surface from every canonical entry, while the
    concrete-alias loop ten lines below it skips an entry whose content fails the query — *"a
    negative content predicate does establish that a literal file is outside this reader's
    surface"*, in the module's own words. So one function held two answers about one file, and a
    candidate hard-linking a pattern-matched but query-rejected file was refused as undecidable
    (review finding, codex, 2026-09-07, `shared/frame_verdicts.py:2924`; measured here as
    `UndecidableScopeContainment` before the repair, `disjoint_established=True` after).

    Both files sit in the same directory under the same pattern and differ only in whether the
    query accepts them, so the pair isolates the predicate and nothing else. The accepted arm is
    what stops the repair from being a blanket exemption: aliasing a file the member really did
    select still refuses.
    """

    root = tmp_path / "surface"
    root.mkdir()
    accepted = root / "kept.txt"
    accepted.write_bytes(b"NEEDLE\n")
    rejected = root / "dropped.txt"
    rejected.write_bytes(b"NOTHING HERE\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    alias = elsewhere / "alias.txt"
    os.link(root / target, alias)
    assert alias.samefile(root / target), "the fixture must actually hard-link, not copy"

    _pin_checkout_base(monkeypatch, tmp_path)
    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        {"patterns": ["*.txt"], "roots": [str(root)], "query": "NEEDLE"},
        reader="fs.content_query",
        cwd=tmp_path,
        candidate=str(alias),
    )
    with capsys.disabled():
        print(f"P6 alias of {target}: main()={rc} (expected {expected})")

    assert rc == expected, (
        f"an alias of {target} must follow the query's own verdict about that file"
    )


@pytest.mark.parametrize(
    "fault",
    [PermissionError(13, "denied"), OSError(5, "I/O error"), RuntimeError("symlink loop")],
    ids=["permission", "oserror", "runtime"],
)
@pytest.mark.parametrize("linked", [True, False], ids=["same-inode", "distinct-file"])
def test_row_q_an_unreadable_identity_is_not_evidence_of_disjointness(
    tmp_path, monkeypatch, capsys, fault, linked
):
    """Q: a filesystem that will not answer has not answered "different".

    Admission here is affirmative — it requires disjointness to be *established* — so a comparison
    that could not be made supplies no admission evidence. The first version of the identity check
    returned False on any OSError and called that "the behaviour that was there before", which is
    the fallback-discipline failure exactly: a precondition asserted away rather than checked.

    **The injection goes at `Path.stat`, and the row asserts the fault actually fired.** An earlier
    version patched `_file_identity` itself, which tests the caller's handling of the sentinel and
    says nothing about whether the capture still turns an error into "absent" — reverting that
    capture left it green (root's instrumentation finding, 2026-09-07, against its own oracle and
    then against this row). Patching the thing under test out of the way is not a test of it.

    Both a real hard link and a genuinely distinct file are covered, because the answer here is
    about the *comparison* rather than about the outcome it would have had.
    """

    root = tmp_path / "surface"
    root.mkdir()
    selected = root / "selected.txt"
    selected.write_bytes(b"NEEDLE\n")
    other = root / "other.txt"
    if linked:
        os.link(selected, other)
    else:
        other.write_bytes(b"DIFFERENT\n")

    fired = []
    real_stat = pathlib.Path.stat
    real_identity = fv._file_identity

    def refuse(self, *args, **kwargs):
        if self.name == other.name:
            fired.append(self)
            raise fault
        return real_stat(self, *args, **kwargs)

    def identity_under_fault(path):
        # The real `_file_identity` body runs; only the stat it makes is faulted, and only for the
        # duration of that call. Reverting its error handling therefore changes this row's result,
        # which is the whole point — patching the function out would not.
        monkeypatch.setattr(pathlib.Path, "stat", refuse)
        try:
            return real_identity(path)
        finally:
            monkeypatch.setattr(pathlib.Path, "stat", real_stat)

    monkeypatch.setattr(fv, "_file_identity", identity_under_fault)

    _pin_checkout_base(monkeypatch, tmp_path)
    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        {"path": str(root), "patterns": ["selected.txt"]},
        reader="fs.glob",
        cwd=tmp_path,
        candidate=str(other),
    )
    with capsys.disabled():
        print(f"Q {'link' if linked else 'distinct'} {type(fault).__name__}: main()={rc}")

    assert fired, "the fault never reached a stat, so this row measured nothing"
    assert rc == 10, "an unreadable comparison must not admit"
    assert "identity" in err, "and the refusal must say what could not be read"


@pytest.mark.parametrize("scope_name", ["not-created-yet.txt", "nested/deeper.txt"])
def test_row_q2_a_genuinely_absent_path_still_admits(tmp_path, monkeypatch, capsys, scope_name):
    """Q2: the companion. Absence is an ANSWER — nothing is there, nothing can be identical to
    it — so the lexical comparison legitimately stands and a future file keeps its surface. If
    the unreadable repair had been written as "any stat problem refuses", this row would be the
    one that caught it."""

    root = tmp_path / "surface"
    root.mkdir()
    (root / "selected.txt").write_bytes(b"NEEDLE\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    future = elsewhere / scope_name
    assert not future.exists()

    _pin_checkout_base(monkeypatch, tmp_path)
    rc, err = _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        {"path": str(root), "patterns": ["selected.txt"]},
        reader="fs.glob",
        cwd=tmp_path,
        candidate=str(future),
    )
    with capsys.disabled():
        print(f"Q2 absent {scope_name!r}: main()={rc}")

    assert rc == 0, "a not-yet-created path outside the member is not an unreadable comparison"


@pytest.mark.parametrize(
    "unreadable",
    ["_runs/current", "epoch-dir", "publish.json", "coverage.json", "root"],
    ids=["pointer", "epoch-dir", "publish", "coverage", "procedure-root"],
)
@pytest.mark.parametrize(
    "fault", [PermissionError(13, "denied"), OSError(5, "I/O error")], ids=["permission", "io"]
)
def test_row_r4_an_unreadable_load_observation_is_a_refusal_not_a_traceback(
    tmp_path, monkeypatch, unreadable, fault
):
    """R4: the loader's own observations, which my static enumeration said were covered.

    Root's native fault check found five sites reaching `Path.stat` and escaping as
    `PermissionError` rather than `FrameVerdictsUnavailable` — the procedure root, the published
    pointer, the epoch directory, `publish.json` and `coverage.json`. Four of them sit in the two
    loader functions my hand-written `LOAD_PATH` omitted; the fifth sits inside a handler that
    catches only `FrameVerdictsUnavailable`, so a converting raise beside it proved nothing.

    **`exists()` and `is_file()` answer "no" for a path they cannot read as well as for one that
    is not there**, and raise for the failures they cannot answer at all. Missing, unreadable and
    malformed are three facts; this row asserts the middle one has its own refusal, and the
    absent/malformed controls elsewhere in the suite keep the other two distinct.
    """

    root = tmp_path / "surface"
    root.mkdir()
    (root / "selected.txt").write_bytes(b"NEEDLE\n")
    procedure = _procedure_root(
        tmp_path / "procedure",
        members=[_local_member(root=root, patterns=("selected.txt",))],
        verdicts=[_verdict("legacy-surface", "scope_exited")],
    )
    if unreadable == "root":
        target = procedure
    elif unreadable == "epoch-dir":
        # The guarded observation is on the RESOLVED epoch directory, not on `_runs/epochs`; a
        # first version faulted the parent and reached nothing, which is a fixture fault rather
        # than a source gap and would have read as one.
        target = next(iter((procedure / "_runs/epochs").iterdir()))
    else:
        target = procedure / unreadable
    fired = []
    real_stat = pathlib.Path.stat

    def refuse(self, *args, **kwargs):
        if self == target or (unreadable != "root" and self.name == target.name):
            fired.append(self)
            raise fault
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "stat", refuse)

    with pytest.raises(fv.FrameVerdictsUnavailable) as caught:
        fv.load_frame_verdicts(procedure, now=NOW)

    assert fired, "the fault never reached a stat, so this row measured nothing"
    assert caught.value.remedy, "an unreadable observation still owes a next action"


@pytest.mark.parametrize(
    "declared",
    ["~frame-review-user-that-does-not-exist/selected.txt", "no-such/relative/selected.txt"],
    ids=["unknown-user-home", "unresolvable-relative"],
)
def test_row_r2_an_unresolvable_declared_file_is_an_actionable_refusal(
    tmp_path, monkeypatch, declared
):
    """R2: `location.roots` converts its resolution failures and `location.files` did not.

    `~no-such-user/x` raises `RuntimeError` out of `expanduser`, and the loader converts only
    `NonCanonicalScopeRef` at that point, so it escaped as a traceback with no diagnostic, no
    remedy and no receipt. **Third time tonight in this family, each in the branch beside the one
    just repaired** — which is the finding worth keeping, more than the fix.

    **The vault binding is controlled here, not inherited.** A plain relative file is LEGAL when the
    declared vault fallback exists, so as first written this row asserted a refusal that depended on
    the ambient environment: root measured it passing with the binding absent and failing with it
    present. That is the same defect I repaired in another test earlier tonight — reading an
    environmental property and reporting it as a property of the declaration — committed again in a
    row written to catch environmental confusion. The unknown-user case refuses either way; the
    relative case is asserted only under the absent binding, and its positive counterpart is below.
    """

    monkeypatch.delenv(fv.FRAME_VAULT_ROOT_ENV, raising=False)
    monkeypatch.setattr(fv, "DEFAULT_FRAME_VAULT_ROOT", tmp_path / "absent-vault")

    member = {
        "id": "legacy-surface",
        "reader": {"id": "fs.glob", "version": "^1.0.0"},
        "location": {"files": [declared], "patterns": ["*.txt"]},
    }
    procedure = _procedure_root(
        tmp_path / "procedure",
        members=[member],
        verdicts=[_verdict("legacy-surface", "scope_exited")],
    )

    with pytest.raises(fv.FrameVerdictsUnavailable) as caught:
        fv.load_frame_verdicts(procedure, now=NOW)

    assert "legacy-surface" in str(caught.value)
    assert caught.value.remedy


def test_row_r2b_an_unexpandable_scope_ref_is_also_an_actionable_refusal(tmp_path):
    """R2b: the same fault in the SCOPE ref, which R2's repair did not reach.

    R2 above converted `location.files`; `resolve_scope_ref` still called `expanduser` outside
    its own refusal contract, so a `~`-relative SCOPE ref raised `RuntimeError` straight out
    while an absolute one failed inside the contract with a diagnostic and a remedy (review
    finding, codex, at `069e726dc`).

    **Fourth time in this family, and again in the branch beside the one repaired.** R2's own
    docstring says that is the finding worth keeping, more than the fix — and then this row had
    to be written anyway, which is the strongest evidence that noting a pattern is not the same
    as searching for its other instances.
    """
    with pytest.raises(fv.UndecidableScopeContainment) as caught:
        fv.resolve_scope_ref(
            "~frame-review-user-that-does-not-exist/selected.txt",
            council_root=tmp_path,
            vault_root=tmp_path,
        )

    assert "cannot expand scope ref" in str(caught.value)
    assert caught.value.remedy, "a refusal must name its remedy"
    assert "home-directory resolution" in caught.value.remedy, (
        "the remedy must name the actual cause; folding expansion into component resolution "
        "names the wrong repair for half the cases"
    )


@pytest.mark.parametrize(
    "injected",
    [errno.EACCES, errno.ELOOP],
    ids=["propagated-eacces", "suppressed-eloop"],
)
def test_row_r2c_an_unreadable_checkout_anchor_is_also_an_actionable_refusal(
    tmp_path, monkeypatch, injected
):
    """R2c: the statement immediately after R2b's, which R2b's repair did not reach.

    Anchoring a RELATIVE scope ref asks `exists()`/`is_symlink()` of the council and vault
    checkouts, and those fail on their own terms — a permission fault on an ancestor, a symlink
    loop. That selection sat outside the refusal contract while the expansion above it and the
    `is_dir` check below it were both inside (review finding, codex, at `81962feab`).

    **Fifth instance of this family, and the first one I caused.** R2b converted `expanduser`
    four commits earlier and its docstring says, of R2's identical lesson, that noting a pattern
    is not searching for its other members. I wrote that sentence and then did not read the next
    statement in the same function.

    **And this row then failed to hold the repair for two more rounds.** It replaced
    `Path.exists` with a `PermissionError`, which bypasses the suppression twice over: the
    method under test is the one that swallows errnos, and EACCES is not among the ones it
    swallows. So it exercised the handler while the real hazard — an ELOOP that makes `exists()`
    answer False, losing the first anchor and resolving the scope **against the other checkout
    entirely** — went untested (review finding, codex, at `e9a5b4acb`). That redirection is
    worse than the shrunk surfaces elsewhere in this family: the question is asked of a
    different tree.

    Both faults are kept. The EACCES case at `os.stat` is a propagated-error control; the ELOOP
    case is the one that discriminates the unsuppressed anchor read.
    """
    real_stat = os.stat

    def refusing_stat(path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        if pathlib.Path(path).name == "selected.txt":
            raise OSError(injected, "fixture stat denied", str(path))
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", refusing_stat)

    with pytest.raises(fv.UndecidableScopeContainment) as caught:
        fv.resolve_scope_ref(
            "selected.txt/inner.md", council_root=tmp_path, vault_root=tmp_path / "vault"
        )

    assert "cannot choose a checkout anchor" in str(caught.value)
    assert caught.value.remedy, "a refusal must name its remedy"
    assert "absolute path" in caught.value.remedy


def test_row_r2d_an_unresolvable_default_vault_root_is_also_an_actionable_refusal(
    tmp_path, monkeypatch
):
    """R2d: the DEFAULT vault root, which only fails when the caller does not pass one.

    `scope_within_decayed` fills an omitted `vault_root` from `frame_vault_root()`, which ends in
    `expanduser()` — so with no resolvable home directory the default path raised RuntimeError
    straight out, while an explicitly passed root could not fail at all (review finding, claude,
    at `24574cc4f`). Every test in this file passes `vault_root`, which is why nothing saw it.

    **Sixth instance of this family, and on the line directly above a comment I wrote the same
    morning.** R2 named the pattern, R2b repeated it, R2c wrote that noting a pattern is not
    searching for its other members — and I then edited three lines below this call without
    reading it. A fault family is closed by enumerating its call sites once, not by recognising
    it six times.
    """
    monkeypatch.delenv(fv.FRAME_VAULT_ROOT_ENV, raising=False)
    # Build the fixture BEFORE breaking expansion: loading the verdicts resolves the procedure
    # root through the same call, and patching first refuses the setup instead of the subject.
    verdicts = _decayed(tmp_path, _local_member(root=tmp_path / "surface"))

    def refusing_expanduser(self):
        raise RuntimeError("Could not determine home directory")

    monkeypatch.setattr(pathlib.Path, "expanduser", refusing_expanduser)

    with pytest.raises(fv.UndecidableScopeContainment) as caught:
        fv.scope_within_decayed(["scripts/x.py"], verdicts, council_root=tmp_path)

    assert "default frame vault root cannot be resolved" in str(caught.value)
    assert fv.FRAME_VAULT_ROOT_ENV in caught.value.remedy, (
        "the remedy must name the override that repairs it"
    )


def test_row_r3_a_relative_declared_file_resolves_against_a_present_vault(tmp_path, monkeypatch):
    """R3: the positive counterpart, and the reason R2 must control its binding.

    A relative `location.files` entry is legal when the declared vault fallback exists — that is
    the producer's own convention, repaired for `location.roots` before and now shared by its
    sibling. Converting resolution failures must not turn a legal relative declaration into a
    refusal, so the two rows differ only in whether the fallback is there.
    """

    vault = tmp_path / "vault"
    (vault / "30-areas/hapax").mkdir(parents=True)
    (vault / "surface").mkdir()
    (vault / "surface/selected.txt").write_bytes(b"NEEDLE\n")
    monkeypatch.setenv(fv.FRAME_VAULT_ROOT_ENV, str(vault))

    member = {
        "id": "legacy-surface",
        "reader": {"id": "fs.glob", "version": "^1.0.0"},
        "location": {"files": ["surface/selected.txt"], "patterns": ["*.txt"]},
    }
    procedure = _procedure_root(
        tmp_path / "procedure",
        members=[member],
        verdicts=[_verdict("legacy-surface", "scope_exited")],
    )

    verdicts = fv.load_frame_verdicts(procedure, now=NOW)
    assert [member.member_id for member in verdicts.decayed] == ["legacy-surface"]
    assert verdicts.decayed[0].files, "a legal relative declaration keeps its declared file"


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


def test_row_j2_the_contained_ref_may_be_a_hard_link_and_the_scope_is_still_partial(tmp_path):
    """J2: the explicit two-ref form of the shape row P2 tests as a glob.

    An alias is the selected file, so it belongs in `matches` exactly as a directly named file
    does — and a scope carrying it **plus** a provably outside ref is still partial, because
    `all_inside` asks whether every ref is inside, not whether any is.

    This is the pairing the withdrawn overlap guard failed: it refused the glob spelling of this
    situation while this spelling admitted, so the two disagreed about one arrangement of the same
    three files. Keeping them in one module, asserting the same predicate, is what makes that kind
    of divergence visible without a coordinator having to reproduce it.
    """

    base = tmp_path / "base"
    root = base / "surface"
    root.mkdir(parents=True)
    selected = root / "tool"
    selected.write_bytes(b"NEEDLE\n")
    alias = root / "tool-1.0"
    os.link(selected, alias)
    outside = base / "elsewhere.txt"
    outside.write_bytes(b"NEEDLE\n")

    verdicts = _decayed(tmp_path, _local_member(root=root, patterns=("tool",)))
    result = fv.scope_within_decayed(
        [str(alias), str(outside)], verdicts, council_root=base, vault_root=base
    )

    assert [match.ref for match in result.matches] == [str(alias)], "the alias IS the member's file"
    assert result.outside == (str(outside),)
    assert result.all_inside is False, "one contained ref does not make the whole scope contained"


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


@pytest.mark.parametrize(
    ("member_patterns", "scope_pattern", "contained"),
    [
        (("*.txt",), "*.txt", True),
        (("**/*",), "*.txt", True),
        (("a.txt",), "*.txt", False),
        (("a.txt",), "*", False),
        (("a.txt",), "**/*", False),
        (("*.txt",), "*.md", False),
    ],
    ids=[
        "same-language",
        "member-selects-everything",
        "wider-txt",
        "wider-star",
        "wider-recursive",
        "disjoint",
    ],
)
def test_root_loop_containment_rests_on_the_language_not_the_listing(
    tmp_path, member_patterns, scope_pattern, contained
):
    """The broad root loop proves containment from the LANGUAGE, never from what exists today.

    claude read the source at `850ccfdbb` and reported that after the comment *existing files can
    disprove containment, but cannot establish the proof*, the loop still falls through to
    `return True` whenever every current expansion entry resolves into the member surface — a
    present directory listing standing in for an unbounded glob's whole language.

    **It does not, and this row is why claude was right that nothing said so.** The fall-through
    is gated on `canonical_covered or _scope_glob_covered(...)`, so `return True` is reached only
    when the scope's language is a subset of the member's; the expansions check above it can only
    disprove. The rows below hold the directory FIXED — one file, `a.txt`, which the member
    selects in every case — and vary only the two languages. If the listing could establish
    containment, the three `wider-*` rows would be True, because their single existing file is
    selected. They are False.

    The finding was confirmed from a source excerpt rather than by running it, and it cited this
    module's own repair comment — which narrates a fixed defect in the past tense at the site of
    its fix — as evidence of an outstanding contradiction. Both halves of that are now addressed:
    the comment states its current state first, and the behaviour is pinned here instead of being
    inferrable only by reading the gate.
    """
    base = tmp_path / "base"
    root = base / "surface"
    root.mkdir(parents=True)
    (root / "a.txt").write_bytes(b"ONE\n")

    verdicts = _decayed(tmp_path, _local_member(root=root, patterns=member_patterns))
    member = verdicts.decayed[0]

    assert fv.ref_within_member(root, False, member, scope_pattern=scope_pattern) is contained, (
        f"member {member_patterns} / scope {scope_pattern!r}: containment must follow the "
        "language relation, not the one file that happens to exist"
    )


def _equivalent_checkouts(tmp_path):
    """A running checkout and a declared one with the SAME root history, plus a decayed member."""
    running = tmp_path / "running"
    declared = tmp_path / "declared"
    git_checkout(running, history="frame scope grammar")
    git_checkout(declared, history="frame scope grammar")
    surface = declared / "scripts"
    surface.mkdir(parents=True, exist_ok=True)
    (surface / "x.py").write_bytes(b"NEEDLE\n")

    member = {
        "id": "legacy-surface",
        "reader": {"id": "fs.glob", "version": "^1.0.0"},
        "location": {"path": str(surface), "patterns": ["*.py"]},
    }
    procedure = _procedure_root(
        tmp_path / "procedure",
        members=[member],
        verdicts=[_verdict("legacy-surface", "scope_exited")],
    )
    return running, fv.load_frame_verdicts(procedure, now=NOW)


def test_row_r5_an_unreadable_repository_identity_cannot_establish_disjointness(
    tmp_path, monkeypatch
):
    """R5: git failing is not git answering no.

    A repo-relative ref is tried under each decayed member's declared checkout, but only after
    verifying equivalent root histories — and `_repository_identity` returned `None` both when
    git said "not a repository" and when git could not be run at all. The caller drops
    non-matching checkouts, so an unreadable identity silently removed the declared member's
    checkout from the candidate list, containment was never tried there, and a scope the guard
    refuses with git working was ADMITTED with git unavailable (review finding, claude, at
    `850ccfdbb`; reproduced here as all_inside True then False on one arrangement).

    Unknown repository identity cannot establish disjointness. The split is between git RUNNING
    and answering no — a decided negative, and the ordinary case for a `.git` that is not a
    working checkout — and git not running at all, which answers nothing.
    """
    running, verdicts = _equivalent_checkouts(tmp_path)
    ref = "scripts/x.py"
    assert not (running / ref).exists(), "the running checkout must not hold the ref itself"

    readable = fv.scope_within_decayed([ref], verdicts, council_root=running, vault_root=running)
    assert readable.all_inside is True, "the declared checkout's copy is inside the decayed member"

    real_run = subprocess.run

    def timing_out(command, *args, **kwargs):
        if isinstance(command, list) and command[:1] == ["git"]:
            raise subprocess.TimeoutExpired(command, 5)
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", timing_out)

    with pytest.raises(fv.UndecidableScopeContainment) as caught:
        fv.scope_within_decayed([ref], verdicts, council_root=running, vault_root=running)

    assert "repository identity" in str(caught.value)
    assert caught.value.remedy, "a refusal must name its remedy"


@pytest.mark.parametrize(
    ("stderr", "refuses"),
    [
        ("fatal: not a git repository (or any parent up to mount point /)\n", False),
        ("fatal: detected dubious ownership in repository at '/x'\n", True),
        ("fatal: unable to read tree abc123\n", True),
        ("error: object file .git/objects/ab/cdef is empty\n", True),
        ("", True),
    ],
    ids=["not-a-repository", "dubious-ownership", "corrupt-tree", "empty-object", "silent"],
)
def test_row_r5a_a_nonzero_git_exit_is_not_automatically_a_decided_negative(
    tmp_path, monkeypatch, stderr, refuses
):
    """R5a: exit status does not distinguish "not a repository" from "cannot read this one".

    My first split at `862a46ce9` put the line at the EXCEPTION TYPE and read
    `CalledProcessError` as "git ran and said no". All four families reported that as still
    fail-open, and they were right: git exits 128 both for a directory that is not a repository
    and for one it cannot read — dubious ownership, a corrupt object store, a permission fault.
    A checkout that exists and cannot be read had its projections erased, and work wholly inside
    it was admitted.

    So git is ASKED rather than inferred from: only its own "not a git repository" is a decided
    negative. Every other failure is unknown, and unknown cannot establish disjointness.

    The `silent` row matters most — an empty stderr carries no evidence of anything, and the
    permissive reading of "no marker found" would have been to treat it as a repository that is
    simply absent.
    """
    running, verdicts = _equivalent_checkouts(tmp_path)
    real_run = subprocess.run

    def failing(command, *args, **kwargs):
        if isinstance(command, list) and command[:1] == ["git"]:
            raise subprocess.CalledProcessError(128, command, output="", stderr=stderr)
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", failing)

    if refuses:
        with pytest.raises(fv.UndecidableScopeContainment) as caught:
            fv.scope_within_decayed(
                ["scripts/x.py"], verdicts, council_root=running, vault_root=running
            )
        assert "repository identity" in str(caught.value)
    else:
        result = fv.scope_within_decayed(
            ["scripts/x.py"], verdicts, council_root=running, vault_root=running
        )
        assert result.all_inside is False, (
            "git's own 'not a git repository' is a decided negative and supplies no candidates"
        )


def test_row_r5b_a_verified_unrelated_history_still_supplies_no_candidates(tmp_path):
    """R5b: the twin. A checkout git CAN read and that genuinely differs is a decided negative.

    Without this, R5 above would be satisfied by refusing whenever any git question is asked, and
    the repair would have turned a working discrimination into a blanket refusal.
    """
    running = tmp_path / "running"
    declared = tmp_path / "declared"
    git_checkout(running, history="frame scope grammar")
    git_checkout(declared, history="an unrelated history")

    surface = declared / "scripts"
    surface.mkdir(parents=True, exist_ok=True)
    (surface / "x.py").write_bytes(b"NEEDLE\n")
    member = {
        "id": "legacy-surface",
        "reader": {"id": "fs.glob", "version": "^1.0.0"},
        "location": {"path": str(surface), "patterns": ["*.py"]},
    }
    procedure = _procedure_root(
        tmp_path / "procedure",
        members=[member],
        verdicts=[_verdict("legacy-surface", "scope_exited")],
    )
    verdicts = fv.load_frame_verdicts(procedure, now=NOW)

    result = fv.scope_within_decayed(
        ["scripts/x.py"], verdicts, council_root=running, vault_root=running
    )
    assert result.all_inside is False, (
        "a checkout with a verified DIFFERENT root history supplies no candidates, and that is "
        "an answer rather than an absence of one"
    )


def test_row_r5c_checkout_discovery_failures_are_an_actionable_refusal(tmp_path, monkeypatch):
    """R5c: finding the checkout is itself a filesystem question, and it decides the candidates.

    The discovery loop walks each declared location's ancestors looking for `.git`, and an
    unreadable ancestor silently yielded a SHORTER root set — so containment was never tried
    under the checkout that was skipped, and the scope was admitted (review finding, codex, at
    `850ccfdbb`). Same shape as the identity read directly below it: an unreadable answer
    becoming a negative one.

    Seventh instance of this family in this module. R5 above is the sixth.

    **This row took three tries to discriminate anything, and the sequence is the lesson.**

    1. It replaced `Path.exists` — the method that does the suppressing — so it proved the
       handler works while leaving untested the case where the method silently answers False.
    2. Moved to `os.stat`, the supplying boundary, but injecting `PermissionError`. **EACCES is
       not in pathlib's ignored set**, so `Path.exists` propagates it anyway and the unrepaired
       expression still satisfied every assertion here (review finding, codex, at `45b076c53`,
       confirmed by an in-memory rollback). Right layer, wrong errno: a fault the mitigation
       does not apply to measures nothing about the mitigation.
    3. ELOOP, which IS suppressed — so without `_classified_exists` discovery answers False,
       finds no checkout, and never refuses.

    The general form: **a control must inject a fault the repaired code path actually changes
    the handling of.** Layer and errno are two separate choices and both have to be right.
    """
    running, verdicts = _equivalent_checkouts(tmp_path)
    real_stat = os.stat

    def refusing_stat(path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        if str(path).endswith("/.git"):
            raise OSError(errno.ELOOP, "Too many levels of symbolic links")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", refusing_stat)

    with pytest.raises(fv.UndecidableScopeContainment) as caught:
        fv.scope_within_decayed(
            ["scripts/x.py"], verdicts, council_root=running, vault_root=running
        )

    assert "checkout discovery" in str(caught.value)
    assert caught.value.remedy, "a refusal must name its remedy"


@pytest.mark.parametrize(
    ("pattern", "plain", "newline"),
    [
        ("*.txt", True, False),
        ("a.txt", True, False),
        ("*", True, True),
        ("**/*", True, True),
    ],
    ids=["suffix-class", "literal-name", "any-name", "recursive-any-name"],
)
def test_row_s1_a_trailing_newline_filename_is_not_its_plain_twin(pattern, plain, newline):
    """S1: `$` in a Python regex also matches just BEFORE a trailing newline.

    `_glob_to_regex` anchored with `^`/`$`, so `^a\\.txt$` matched the filename `"a.txt\\n"` —
    and a newline is a legal POSIX filename character, so those are two different files (review
    finding, codex, at `850ccfdbb`; reproduced as True/True for `*.txt`, `a.txt` and `*`). A
    member selecting `a.txt` was therefore treated as selecting `a.txt\\n` as well, and a scope
    naming the newline twin compared against the wrong surface.

    Same family as the whitespace findings this row has already closed: a declared subject
    silently equated with a different one.

    The wildcard rows are the discrimination that matters. `\\A`/`\\Z` must not turn this into
    "newline names never match" — `*` and `**/*` genuinely DO name a file whose name contains a
    newline, and a repair that refused them would trade one wrong answer for another.
    """
    assert fv._pattern_matches("a.txt", pattern) is plain
    assert fv._pattern_matches("a.txt\n", pattern) is newline


@pytest.mark.parametrize("patterns", [("**/*.txt",), ("**/*",)], ids=["suffixed", "any"])
def test_row_s1b_a_recursive_glob_reaches_below_a_newline_directory(tmp_path, patterns):
    """S1b: a newline is legal in a path COMPONENT, and `.` does not match one by default.

    `**/` compiles to `(?:.*/)?`, so without `re.DOTALL` a recursive glob never matched a file
    under a directory whose NAME contains a newline — `**/*.txt` did not select `a.txt` below
    `dir\\nwith-newline/` (review finding, cx-blue, at `93f5fceb1`, with twelve reader fixtures
    at 10/2 -> 12/0 on DOTALL alone).

    **This is the opposite question from S1 above, and both answers must hold.** DOTALL governs
    what `.` may match INSIDE a pattern; the `\\A`/`\\Z` anchors govern where a match may END.
    `*` compiles to `[^/]*`, a character class, which is newline-permitting regardless — so
    `*.txt` still refuses `a.txt\\n`, and S1 is the control that keeps this repair from becoming
    "newline names match anything".
    """
    base = tmp_path / "base"
    root = base / "surface"
    inner = root / "dir\nwith-newline"
    inner.mkdir(parents=True)
    target = inner / "a.txt"
    target.write_bytes(b"NEEDLE\n")

    verdicts = _decayed(tmp_path, _local_member(root=root, patterns=patterns))
    result = fv.scope_within_decayed([str(target)], verdicts, council_root=base, vault_root=base)

    assert result.all_inside is True, (
        "a recursive glob selects below a directory whose name contains a newline; that file is "
        "inside the member and the scope naming it must be refused"
    )


def test_row_s1c_a_self_dependent_member_surface_refuses_instead_of_recursing(
    tmp_path, monkeypatch
):
    """S1c: the CYCLE, not the trigger. `re.DOTALL` closed one way in; this closes the way out.

    `_canonical_member_entries` calls `_check_member_symlinks` for each entry, and
    `_check_member_symlinks` rebuilds the whole surface whenever an entry is lexically disjoint.
    Nothing bounded that pair. It terminated only because some entry usually matches the
    member's patterns — a fact about the data, not about the code — so when `**/*` matched
    NOTHING under the root, every entry became disjoint and the two recursed 478 times each into
    a RecursionError. A RecursionError is a crash, not a refusal: it escaped the contract
    entirely, the same shape as the unguarded filesystem faults arrived at differently.

    cx-blue's instruction was that repairing one trigger does not establish the family closed.
    This row holds the CYCLE rather than the newline: the pattern is compiled without DOTALL in
    memory, which is the measured way to make every entry disjoint, and the requirement is a
    named refusal with a remedy rather than a stack overflow. Any future gap between what a
    member's patterns select and what its root contains arrives here.
    """
    real = fv._glob_to_regex

    def without_dotall(pattern: str):
        return re.compile(real(pattern).pattern)

    monkeypatch.setattr(fv, "_glob_to_regex", without_dotall)

    base = tmp_path / "base"
    root = base / "surface"
    inner = root / "dir\nwith-newline"
    inner.mkdir(parents=True)
    target = inner / "a.txt"
    target.write_bytes(b"NEEDLE\n")

    verdicts = _decayed(tmp_path, _local_member(root=root, patterns=("**/*.txt",)))

    with pytest.raises(fv.UndecidableScopeContainment) as caught:
        fv.scope_within_decayed([str(target)], verdicts, council_root=base, vault_root=base)

    assert "re-entered itself" in str(caught.value)
    assert caught.value.remedy, "a refusal must name its remedy"
    # The diagnosis must point at the CONSUMER. This fixture perturbs the consumer's own regex
    # and leaves a valid producer declaration in place, so a remedy sending the operator to
    # repair `location.patterns` would send them to repair something correct (cx-blue,
    # 2026-09-08). Re-entry proves a self-dependent calculation here, not a defective
    # declaration and not that none of the member's entries match.
    assert "consumer" in str(caught.value)
    assert "declaration is not implicated" in caught.value.remedy
    assert "location.patterns" not in caught.value.remedy


@pytest.mark.parametrize(
    "method",
    [
        "exists",
        "is_dir",
        "is_file",
        "is_symlink",
        "resolve",
        "absolute",
        "expanduser",
        "stat",
        "iterdir",
        "glob",
        "read_text",
        "readlink",
        "samefile",
    ],
)
def test_row_s2_no_filesystem_fault_escapes_the_refusal_contract(tmp_path, monkeypatch, method):
    """S2: the fault family, closed by CONSTRUCTION rather than by noticing it again.

    Seven of these were reported one at a time, each in the branch beside the one just repaired —
    `location.files`, the content-query root, the scope expansion, the checkout anchor, the
    default vault root, the checkout discovery, the identity read. After the sixth I wrote that
    a family is closed by enumerating its call sites once, then repaired the seventh from a
    report anyway.

    So this row does the enumeration and keeps doing it. It faults each risky `Path` method in
    turn and requires that the consumer answer with a NAMED refusal or an ordinary verdict —
    never a raw `OSError`/`RuntimeError`. It found the eighth and ninth sites itself
    (`absolute()` in `resolve_scope_ref`, the last unguarded statement in a function I had
    already converted twice, and `is_file()` in `_canonical_member_entries`), which is the only
    reason they are not two more reports.

    **What this row does not establish, corrected 2026-09-08 after it missed two.** A method
    whose fault produces no refusal here was not necessarily guarded; it may simply not lie on
    the path these three refs take. Worse, and measured: this row faults `Path` METHODS, and
    two families then found escapes at layers it cannot reach —

      - `Path.glob` SUPPRESSES the `os.scandir` error beneath it, so faulting `Path.glob` here
        produced a named refusal and the sweep reported the layer covered while an unreadable
        root silently became an empty surface. **A bound stated at the wrong layer looks like
        coverage.** Row S2b faults the syscall instead.
      - every fault injected here is an `OSError`, so a `ValueError` — which `Path.resolve()`
        raises for a NUL in a declared path — could never appear. Row S2c covers that.

    So this row proves the absence of raw escapes for the methods AND the exception type it
    exercises, at the layer it exercises them. That is three bounds, and naming them is the
    point: the sweep was written to close a family and its first report of success was too broad.
    """
    base = tmp_path / "base"
    root = base / "surface"
    root.mkdir(parents=True)
    (root / "a.txt").write_bytes(b"ONE\n")

    member = {
        "id": "legacy-surface",
        "reader": {"id": "fs.glob", "version": "^1.0.0"},
        "location": {"path": str(root), "patterns": ["*.txt"]},
    }
    procedure = _procedure_root(
        tmp_path / "procedure",
        members=[member],
        verdicts=[_verdict("legacy-surface", "scope_exited")],
    )
    verdicts = fv.load_frame_verdicts(procedure, now=NOW)

    real = getattr(pathlib.Path, method)

    def faulting(self, *args, **kwargs):
        if "surface" in str(self) or str(self).endswith("base"):
            raise PermissionError(13, "Permission denied")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, method, faulting)

    for ref in (str(root / "a.txt"), str(root / "*.txt"), f"{root}/"):
        try:
            fv.scope_within_decayed([ref], verdicts, council_root=base, vault_root=base)
        except (fv.NonCanonicalScopeRef, fv.FrameVerdictsUnavailable):
            continue
        except (OSError, RuntimeError) as exc:  # noqa: PERF203
            pytest.fail(
                f"a faulting Path.{method} escaped as a raw {type(exc).__name__} for ref {ref!r}: "
                "every filesystem fault owes a named refusal with a remedy"
            )


@pytest.mark.parametrize("pattern", ["*.txt", "**/*.txt"], ids=["shallow", "recursive"])
def test_row_s2b_an_unreadable_root_is_not_an_empty_surface(tmp_path, monkeypatch, pattern):
    """S2b: the layer BENEATH `Path.glob`, which S2 cannot reach.

    `Path.glob`/`rglob` swallow the `os.scandir` error underneath them: a directory that raises
    `PermissionError` yields no entries and no exception. So an unreadable member root produced
    an EMPTY surface, `all_inside` became False, and the dispatcher returned no refusal — the
    failure this consumer exists to prevent, reached through a fault instead of a spelling.

    Two families reproduced it at `b420f26c9` on `/usr/bin` with patterns `['fsck.ext[234]']`:
    all_inside True normally, False with `os.scandir` faulted, True again on restore.

    **S2 reported this layer as covered**, because faulting `Path.glob` itself raises and is
    converted. The suppression happens one layer down, at the syscall `Path.glob` wraps, which a
    sweep over `Path` methods cannot see. This row faults `os.scandir` instead, and the shallow
    and recursive patterns are separated because they read different amounts of the tree.
    """
    base = tmp_path / "base"
    root = base / "surface"
    (root / "sub").mkdir(parents=True)
    (root / "a.txt").write_bytes(b"ONE\n")
    (root / "sub" / "b.txt").write_bytes(b"TWO\n")

    verdicts = _decayed(tmp_path, _local_member(root=root, patterns=(pattern,)))
    real_scandir = os.scandir

    def refusing_scandir(path=".", *args, **kwargs):
        if str(path).rstrip("/").endswith("surface"):
            raise PermissionError(13, "Permission denied")
        return real_scandir(path, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", refusing_scandir)

    with pytest.raises(fv.NonCanonicalScopeRef) as caught:
        fv.scope_within_decayed([str(root / "a.txt")], verdicts, council_root=base, vault_root=base)

    assert "cannot enumerate" in str(caught.value)
    assert caught.value.remedy, "a refusal must name its remedy"


@pytest.mark.parametrize(
    ("pattern", "refuses"),
    [("sub/*.txt", True), ("*/*.txt", True), ("**/*.txt", True), ("*.txt", False)],
    ids=["literal-nested", "wildcard-nested", "recursive", "shallow-does-not-traverse"],
)
def test_row_s2d_scan_readability_follows_the_declared_grammar(
    tmp_path, monkeypatch, pattern, refuses
):
    """S2d: which directories a pattern TRAVERSES, not whether it contains `**`.

    My first `_require_scannable` treated `recursive = "**" in pattern`, so a nested pattern
    without `**` checked only the root. A persistent fault on `surface/sub` was therefore
    undetected under `sub/*.txt` and `*/*.txt`, the glob came back silently empty, and an
    outside hard-link alias to the selected file was ADMITTED — while the `**/*.txt` twin
    refused correctly, which is exactly what isolates the assumption (review finding, root via
    cx-blue, at `d8794d7c6`).

    **The last row is the other half of the requirement and matters as much.** `*.txt` never
    traverses `sub`, so a fault there must NOT refuse: the repair covers the directories the
    declared grammar actually reaches, and does not demand readability of an unrelated corner of
    the tree that the scope never looks at. Without it, "check everything" would satisfy the
    first three rows and quietly convert unreadable-anywhere into refuse-everything.
    """
    base = tmp_path / "base"
    root = base / "surface"
    sub = root / "sub"
    sub.mkdir(parents=True)
    selected = sub / "a.txt"
    selected.write_bytes(b"NEEDLE\n")
    elsewhere = base / "elsewhere"
    elsewhere.mkdir()
    alias = elsewhere / "alias.txt"
    os.link(selected, alias)

    verdicts = _decayed(tmp_path, _local_member(root=root, patterns=(pattern,)))
    real_scandir = os.scandir

    def refusing(path=".", *args, **kwargs):
        if str(path).rstrip("/") == str(sub):
            raise PermissionError(13, "Permission denied")
        return real_scandir(path, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", refusing)

    if refuses:
        with pytest.raises(fv.NonCanonicalScopeRef) as caught:
            fv.scope_within_decayed([str(alias)], verdicts, council_root=base, vault_root=base)
        assert "cannot enumerate" in str(caught.value)
    else:
        result = fv.scope_within_decayed([str(alias)], verdicts, council_root=base, vault_root=base)
        assert result.all_inside is False, (
            "a shallow pattern never traverses the faulting directory, so the fault is not its "
            "concern and must not refuse a scope that never reads it"
        )


def test_row_s2f_a_directory_alias_matched_after_a_double_star_is_still_checked(
    tmp_path, monkeypatch
):
    """S2f: `**` does not follow symlinks, but an explicit component after it does.

    `**` matches zero or more levels, so `**/sbin/fsck.ext2` reaches `sbin` as an EXPLICIT
    component — and `sbin` may be a directory alias that `os.walk` will not descend. The
    readability walk discarded the remaining segments once it saw `**`, so that alias went
    unchecked; faulting it left the enumeration short and ADMITTED a decayed hard link (review
    finding at `0b2d8e6fb`, reproduced with a content-query member whose `usr/sbin` aliases
    `bin`).

    Content-query members are the case that reaches it, because their pattern is prefixed with
    `**/` on the way in — so the suffix after `**` is exactly where their declared grammar
    lives.
    """
    base = tmp_path / "base"
    root = base / "usr"
    real = root / "bin"
    real.mkdir(parents=True)
    selected = real / "fsck.ext2"
    selected.write_bytes(b"e2fsck NEEDLE\n")
    alias_target = real / "e2fsck"
    os.link(selected, alias_target)
    (root / "sbin").symlink_to("bin", target_is_directory=True)

    member = {
        "id": "legacy-surface",
        "reader": {"id": "fs.content_query", "version": "^1.0.0"},
        "location": {"roots": [str(root)], "patterns": ["sbin/fsck.ext2"], "query": "e2fsck"},
    }
    procedure = _procedure_root(
        tmp_path / "procedure",
        members=[member],
        verdicts=[_verdict("legacy-surface", "scope_exited")],
    )
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
    verdicts = fv.load_frame_verdicts(procedure, now=NOW)

    readable = fv.scope_within_decayed(
        [str(alias_target)], verdicts, council_root=base, vault_root=base
    )
    assert readable.all_inside is True, "with everything readable the alias is inside the member"

    real_scandir = os.scandir

    def refusing(path=".", *args, **kwargs):
        if str(path).rstrip("/") == str(root / "sbin"):
            raise PermissionError(13, "Permission denied")
        return real_scandir(path, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", refusing)

    with pytest.raises(fv.NonCanonicalScopeRef) as caught:
        fv.scope_within_decayed([str(alias_target)], verdicts, council_root=base, vault_root=base)
    assert "cannot enumerate" in str(caught.value)


@pytest.mark.parametrize("pattern", ["*/fs*", "*/*.txt", "**/*.txt"])
def test_row_s2e_a_partial_listing_cannot_decide_containment(tmp_path, monkeypatch, pattern):
    """S2e: some entries survive while a faulted directory suppresses others.

    `_require_scannable` was restricted to run only when enumeration returned NOTHING, and that
    restriction was a fail-open. A partial listing decides containment on what happened to
    survive: with the member rooted above two directories and a pattern reaching both, faulting
    one leaves the other's entries in the expansion, skips the check, and ADMITS a hard link to
    the selected file (review finding at `acd163574`, reproduced on `/usr` with `['*/fs*']`).

    **Row S2d misses this because it has no readable sibling** — its fault empties the whole
    enumeration, so the empty-only check still fired. The sibling is the whole point here.

    The restriction existed to stop this function pre-empting better diagnoses, and its three
    real causes were separately repaired: a missing directory is no longer a failure, an
    unmatched sibling's fault is no longer recorded, and a component fault defers downstream. It
    was a workaround for my own defects that outlived them. A stated bound on a fail-open is
    still a fail-open.
    """
    base = tmp_path / "base"
    root = base / "surface"
    faulting = root / "bin"
    readable = root / "include"
    faulting.mkdir(parents=True)
    readable.mkdir(parents=True)

    # Named so every pattern selects them: `fs*` for the /usr arrangement the finding used, and
    # `*.txt` for the coordinator's own two, which are the same shape stated differently.
    selected = faulting / "fsck.ext2.txt"
    selected.write_bytes(b"NEEDLE\n")
    alias = faulting / "e2fsck.txt"
    os.link(selected, alias)
    # The readable SIBLING: its entry survives the fault and keeps the enumeration non-empty.
    (readable / "fstab.h.txt").write_bytes(b"UNRELATED\n")

    verdicts = _decayed(tmp_path, _local_member(root=root, patterns=(pattern,)))
    normal = fv.scope_within_decayed([str(alias)], verdicts, council_root=base, vault_root=base)
    assert normal.all_inside is True, "with everything readable the alias is inside the member"

    real_scandir = os.scandir

    def refusing(path=".", *args, **kwargs):
        if str(path).rstrip("/") == str(faulting):
            raise PermissionError(13, "Permission denied")
        return real_scandir(path, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", refusing)

    with pytest.raises(fv.NonCanonicalScopeRef) as caught:
        fv.scope_within_decayed([str(alias)], verdicts, council_root=base, vault_root=base)

    assert "cannot enumerate" in str(caught.value)
    assert caught.value.remedy


@pytest.mark.parametrize("field", ["roots", "files"])
def test_row_s2c_a_nul_in_a_declared_path_is_a_named_refusal(tmp_path, field):
    """S2c: `ValueError`, the third exception type in this family, which S2 never injects.

    A NUL cannot appear in a POSIX path and `Path.resolve()` says so with a `ValueError`
    ("embedded null character"). Every handler in the module catches `OSError` and
    `RuntimeError`; none catches this, so a declared root or file containing a NUL exited the
    dispatcher as a traceback instead of the documented refusal, remedy and receipt (review
    finding at `b420f26c9`).

    The family has now been met one exception type at a time — `OSError` for access,
    `RuntimeError` for expansion and loops, `ValueError` for unrepresentable spellings — which
    is why S2's docstring now states the exception type as one of its bounds.
    """
    location = (
        {"path": "/tmp/bad\x00root", "patterns": ["*.txt"]}
        if field == "roots"
        else {"files": ["/tmp/bad\x00file.txt"]}
    )
    member = {
        "id": "legacy-surface",
        "reader": {"id": "fs.glob", "version": "^1.0.0"},
        "location": location,
    }
    procedure = _procedure_root(
        tmp_path / "procedure",
        members=[member],
        verdicts=[_verdict("legacy-surface", "scope_exited")],
    )

    with pytest.raises(fv.FrameVerdictsUnavailable) as caught:
        fv.load_frame_verdicts(procedure, now=NOW)

    assert "NUL" in str(caught.value)
    assert f"location.{field}" in str(caught.value)
    assert caught.value.remedy


def test_row_s2c2_a_nul_in_a_mass_exclusion_path_is_the_same_named_refusal(tmp_path):
    """S2c2: the same `ValueError`, at the declaration site S2c did not reach.

    Review finding (codex, 2026-09-08, `shared/frame_verdicts.py:480`): a mass EXCLUSION path
    containing a NUL reaches `base.resolve()` under a handler that catches only `OSError` and
    `RuntimeError`, so it raised `'lstat: embedded null character in path'` instead of
    `FrameVerdictsUnavailable` — past the dispatcher's named refusal, next action and receipt.

    S2c covers `location.roots` and `location.files` because those are where the first finding
    landed. **The docstring that fix carries already names `ValueError` as the third type in
    this family**, and a second site in the same file still met it uncaught — which is the part
    worth keeping in front of the next reader: naming a family is not sweeping it, and the two
    member fields were the two I had been shown rather than the set that exists.
    """
    member = {
        "id": "legacy-surface",
        "reader": {"id": "fs.glob", "version": "^1.0.0"},
        "location": {"path": str(tmp_path / "surface"), "patterns": ["*.txt"]},
    }
    procedure = _procedure_root(
        tmp_path / "procedure",
        members=[member],
        verdicts=[_verdict("legacy-surface", "scope_exited")],
        exclusions=[{"paths": ["/tmp/bad\x00exclusion.txt"]}],
    )

    with pytest.raises(fv.FrameVerdictsUnavailable) as caught:
        fv.load_frame_verdicts(procedure, now=NOW)

    assert "NUL" in str(caught.value)
    assert "mass exclusion" in str(caught.value)
    assert caught.value.remedy


class _EntryWithFailingIsDir:
    """A `DirEntry` whose `is_dir()` raises, delegating everything else to the real one."""

    def __init__(self, entry, error: OSError) -> None:
        self._entry = entry
        self._error = error

    def __getattr__(self, name):
        return getattr(self._entry, name)

    def is_dir(self, *args, **kwargs):
        raise self._error


class _ScandirFaultingOneName:
    """`os.scandir` replacement that faults `is_dir()` for one entry name only.

    Written as a context manager because both callers use `with os.scandir(...) as entries`,
    and `pathlib` reaches the same entries — which is the whole point of the row below: when
    `Path.glob` suppresses the identical failure, there is no downstream diagnosis left to
    defer to.
    """

    def __init__(self, name: str, error: OSError) -> None:
        self._name = name
        self._error = error
        self._real = os.scandir

    def __call__(self, path="."):
        real_iter = self._real(path)
        entries = []
        with real_iter:
            for entry in real_iter:
                if entry.name == self._name:
                    entries.append(_EntryWithFailingIsDir(entry, self._error))
                else:
                    entries.append(entry)
        return _ScandirResult(entries)


class _ScandirResult:
    """Both an iterator and a context manager, because the two callers use it each way.

    `os.walk` calls `next()` on the object directly, while `_require_scannable` and `pathlib`
    use `with os.scandir(...) as entries`. Returning something that satisfies only one of those
    silently exercises one caller and raises in the other.
    """

    def __init__(self, entries) -> None:
        self._entries = iter(entries)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._entries)

    def close(self) -> None:
        return None


def test_row_s2h_a_fault_on_a_selected_component_is_recorded_not_deferred(tmp_path, monkeypatch):
    """S2h: `is_dir()` failing on a component the pattern NAMES must refuse, not skip.

    Review finding (codex, 2026-09-08, `shared/frame_verdicts.py:1865`), reproduced here: the
    handler skipped the entry and a comment claimed the fault was "already diagnosed
    downstream". **It is not, when `pathlib` suppresses the same failure** — `Path.glob` drops
    the entry just as silently, the member surface comes back short, and the decayed hard link
    is ADMITTED on missing filesystem evidence. A comment asserting a mitigation that does not
    run is the same defect as no mitigation, stated more confidently.

    The reason the skip was there is real but belongs to a different case. Raising on EVERY
    component fault reddened ten committed dispatch controls, twice — but those are faults on
    UNRELATED SIBLINGS, and the name match two lines above now excludes them. What reaches this
    handler has already matched the declared segment, so it is a fault on a component the scope
    actually traverses. Row S2e is the sibling case and must stay green; if this repair ever
    reddens it, the name filter has been lost.

    Codex's own arrangement: an `fs.glob` member rooted where `[s-s]bin/fsck.ext2` selects a
    file through a directory alias, with the scope naming a hard link that shares its inode.
    """
    base = tmp_path / "base"
    root = base / "usr"
    real = root / "bin"
    real.mkdir(parents=True)
    selected = real / "fsck.ext2"
    selected.write_bytes(b"e2fsck NEEDLE\n")
    scope_alias = real / "e2fsck"
    os.link(selected, scope_alias)
    (root / "sbin").symlink_to("bin", target_is_directory=True)

    member = {
        "id": "aliased-surface",
        "reader": {"id": "fs.glob", "version": "^1.0.0"},
        "location": {"path": str(root), "patterns": ["[s-s]bin/fsck.ext2"]},
    }
    procedure = _procedure_root(
        tmp_path / "procedure",
        members=[member],
        verdicts=[_verdict("aliased-surface", "scope_exited")],
    )
    verdicts = fv.load_frame_verdicts(procedure, now=NOW)

    readable = fv.scope_within_decayed(
        [str(scope_alias)], verdicts, council_root=base, vault_root=base
    )
    assert readable.all_inside is True, (
        "with everything readable the scope's hard link is inside the member through the alias"
    )

    monkeypatch.setattr(
        os, "scandir", _ScandirFaultingOneName("sbin", OSError(40, "Too many levels of symlinks"))
    )

    with pytest.raises(fv.NonCanonicalScopeRef) as caught:
        fv.scope_within_decayed([str(scope_alias)], verdicts, council_root=base, vault_root=base)
    assert "cannot enumerate" in str(caught.value)
    _assert_filesystem_remedy_survived(caught.value)


def test_row_s2i_a_classification_fault_during_recursive_traversal_is_recorded(
    tmp_path, monkeypatch
):
    """S2i: the fourth cell — RECURSIVE traversal times an ENTRY-CLASSIFICATION fault.

    Review finding (codex, 2026-09-08, `shared/frame_verdicts.py:1948`), reproduced: the `**`
    branch delegated to `os.walk`, and `os.walk` suppresses an `OSError` from
    `DirEntry.is_dir()` WITHOUT calling `onerror` — it simply treats the entry as a
    non-directory and never descends. So the repaired `_children` handler, which does record
    such a fault, was bypassed on exactly the recursive path where the whole subtree is in
    scope, and a decayed hard link was ADMITTED.

    Codex named the gap in the two rows added with that repair, and named it correctly: S2h
    faults entry classification but not recursively, S2g faults `scandir` recursively but not
    entry classification. Three of four cells. **The pair looked like coverage of a surface
    because each row covered one axis of it** — the same shape as the `Path`-method sweep that
    reported the `os.scandir` layer as covered.

    The repair replaces `os.walk` here with a traversal that records both kinds of failure, so
    the recursive and non-recursive paths now share one mechanism rather than agreeing by
    coincidence.
    """
    base = tmp_path / "base"
    root = base / "usr"
    real = root / "bin"
    real.mkdir(parents=True)
    selected = real / "fsck.ext2"
    selected.write_bytes(b"e2fsck NEEDLE\n")
    scope_alias = real / "e2fsck"
    os.link(selected, scope_alias)

    member = {
        "id": "recursive-surface",
        "reader": {"id": "fs.glob", "version": "^1.0.0"},
        "location": {"path": str(root), "patterns": ["**/fsck.ext2"]},
    }
    procedure = _procedure_root(
        tmp_path / "procedure",
        members=[member],
        verdicts=[_verdict("recursive-surface", "scope_exited")],
    )
    verdicts = fv.load_frame_verdicts(procedure, now=NOW)

    readable = fv.scope_within_decayed(
        [str(scope_alias)], verdicts, council_root=base, vault_root=base
    )
    assert readable.all_inside is True, "readable baseline reaches the selected file"

    monkeypatch.setattr(
        os, "scandir", _ScandirFaultingOneName("bin", OSError(40, "Too many levels of symlinks"))
    )

    with pytest.raises(fv.NonCanonicalScopeRef) as caught:
        fv.scope_within_decayed([str(scope_alias)], verdicts, council_root=base, vault_root=base)
    assert "cannot enumerate" in str(caught.value)
    _assert_filesystem_remedy_survived(caught.value)


@pytest.mark.parametrize(
    ("arrangement", "refuses"),
    [("zero_level", True), ("behind_a_symlink", False)],
    ids=["zero-level-** reaches the base's own children", "** does not follow a symlink"],
)
def test_row_s2j_the_recursive_descent_states_its_own_traversal_rule(
    tmp_path, monkeypatch, arrangement, refuses
):
    """S2j: `_descend` traverses a symlinked directory no more than `**` itself does.

    `_descend` passes `follow_symlinks=False`, matching both `os.walk` and `pathlib`'s own
    `**`. A directory reachable only THROUGH a symlink is therefore outside what the pattern
    traverses, and a fault there must neither refuse nor change the answer. Without this row,
    "record more failures" would read as a strict improvement, and widening the descent to
    follow links would pass every other control in this file.

    The `zero_level` arrangement is the twin that keeps the rule from being read as "faults
    under `**` are ignored": a directory directly under the root IS traversed, and faulting it
    refuses.

    **Two earlier drafts of this row measured nothing, and the mutation runs are what said so.**
    Dropping the base from the descent reddened row S2f, not this one — S2f is the control that
    isolates base-in-frontier, because its alias is a symlink `_descend` will not enter and only
    `_children` reaches. And faulting the symlink's TARGET left the following-symlinks mutant
    green, because the traversal scans the link path, not the resolved one. The fault is
    injected on the link path here for that reason.
    """
    base = tmp_path / "base"
    root = base / "surface"
    direct = root / "direct"
    direct.mkdir(parents=True)
    selected = direct / "leaf.txt"
    selected.write_bytes(b"NEEDLE\n")
    hidden = base / "hidden"
    hidden.mkdir()
    (hidden / "unreachable.txt").write_bytes(b"NEEDLE\n")
    (root / "link").symlink_to(hidden, target_is_directory=True)
    elsewhere = base / "elsewhere"
    elsewhere.mkdir()
    alias = elsewhere / "alias.txt"
    os.link(selected, alias)

    member = {
        "id": "descent-surface",
        "reader": {"id": "fs.glob", "version": "^1.0.0"},
        "location": {"path": str(root), "patterns": ["**/direct/leaf.txt"]},
    }
    procedure = _procedure_root(
        tmp_path / "procedure",
        members=[member],
        verdicts=[_verdict("descent-surface", "scope_exited")],
    )
    verdicts = fv.load_frame_verdicts(procedure, now=NOW)

    readable = fv.scope_within_decayed([str(alias)], verdicts, council_root=base, vault_root=base)
    assert readable.all_inside is True, "readable baseline reaches the selected file"

    # The LINK path, not its target: the traversal scans `root/link`, so faulting `hidden`
    # would leave a following-symlinks mutant green — measured, and it did.
    faulting = direct if arrangement == "zero_level" else root / "link"
    real_scandir = os.scandir

    def refusing(path=".", *args, **kwargs):
        if str(path).rstrip("/") == str(faulting):
            raise PermissionError(13, "Permission denied")
        return real_scandir(path, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", refusing)

    if refuses:
        with pytest.raises(fv.NonCanonicalScopeRef) as caught:
            fv.scope_within_decayed([str(alias)], verdicts, council_root=base, vault_root=base)
        assert "cannot enumerate" in str(caught.value)
        _assert_filesystem_remedy_survived(caught.value)
    else:
        result = fv.scope_within_decayed([str(alias)], verdicts, council_root=base, vault_root=base)
        assert result.all_inside is True, (
            "a directory reachable only through a symlink is not traversed by `**`, so its "
            "fault must neither refuse nor change the answer"
        )


class _ScandirFaultingOnCalls:
    """`os.scandir` replacement that fails only on the listed call numbers for one directory.

    An INTERMITTENT fault is the case a steady one cannot reach: the enumeration and the
    readability check are two separate traversals of the same tree, so a fault present for the
    first and absent for the second leaves a short enumeration and a clean check.
    """

    def __init__(self, target: str, failing_calls: set[int], error: OSError) -> None:
        self._target = target
        self._failing = failing_calls
        self._error = error
        self._real = os.scandir
        self.calls = 0

    def __call__(self, path="."):
        if str(path).rstrip("/") == self._target:
            self.calls += 1
            if self.calls in self._failing:
                raise self._error
        return self._real(path)


def test_row_s2k_an_intermittent_fault_is_not_cleared_by_a_later_clean_traversal(
    tmp_path, monkeypatch
):
    """S2k: the readability check verifies a DIFFERENT traversal than the one it vouches for.

    Review finding (codex, 2026-09-08, `shared/frame_verdicts.py:2591`), reproduced on their
    arrangement: `Path.glob` collects the entries while suppressing its scan errors, and
    `_require_scannable` then walks the tree AGAIN. If the fault is present for the first
    traversal and gone for the second — scandir failing on calls 1 and 3 but not 2 — the
    enumeration comes back short and the check reports the tree readable. `all_inside` flips
    true to false and the dispatcher's refusal becomes None.

    **Every existing scan-fault row keeps the fault active for both traversals**, which is why
    they all pass: a steady fault is seen by whichever traversal is checked. The defect is not
    that the check is too weak — it is that *a check of a re-run is not a check of the run*.

    **This row shipped as `xfail(strict=True)` for one commit, and that was the right shape.**
    I had three candidate repairs and all three were unsound — enumerating ourselves risks
    diverging from the producer's own `Path.glob` selection, checking before and after closes
    one call pattern while being two guards on one hazard, and globbing twice agrees with itself
    on codex's own (1, 3) pattern. Rather than pick one to turn the row green, it was committed
    strict and returned for a decision. The coordinator then found a fourth route in the
    installed pathlib, and the marker did exactly what strict is for: the row XPASSed the moment
    the real repair landed, so the fix announced itself instead of sitting green.

    **The repair is `_observed_glob`**: `Path.glob` reaches its scans through
    `type(parent)._scandir` and preserves the receiver's class down the tree, so a per-call
    subclass sees the failures of the traversal that actually supplies the entries. Native
    matching is untouched, and nothing process-global is rebound.
    """
    base = tmp_path / "base"
    root = base / "bin"
    root.mkdir(parents=True)
    selected = root / "fsck.ext2"
    selected.write_bytes(b"e2fsck NEEDLE\n")
    scope_alias = root / "e2fsck"
    os.link(selected, scope_alias)

    member = {
        "id": "intermittent-surface",
        "reader": {"id": "fs.glob", "version": "^1.0.0"},
        "location": {"path": str(root), "patterns": ["fsck.ext[234]"]},
    }
    procedure = _procedure_root(
        tmp_path / "procedure",
        members=[member],
        verdicts=[_verdict("intermittent-surface", "scope_exited")],
    )
    verdicts = fv.load_frame_verdicts(procedure, now=NOW)

    readable = fv.scope_within_decayed(
        [str(scope_alias)], verdicts, council_root=base, vault_root=base
    )
    assert readable.all_inside is True, "readable baseline reaches the selected file"

    monkeypatch.setattr(
        os,
        "scandir",
        _ScandirFaultingOnCalls(str(root), {1, 3}, PermissionError(13, "Permission denied")),
    )

    with pytest.raises(fv.NonCanonicalScopeRef) as caught:
        fv.scope_within_decayed([str(scope_alias)], verdicts, council_root=base, vault_root=base)
    assert "cannot" in str(caught.value)
    assert caught.value.remedy


class _ClassificationFaultingOnFirstAttempt:
    """`os.scandir` whose ENTRY CLASSIFICATION fails only the FIRST time an entry is classified.

    The scan itself always succeeds; only `DirEntry.is_dir()` raises, only for the named entry,
    and only once. Every later attempt — including the readability walk's — succeeds, which is
    what makes the fault invisible to any check that is a second traversal.

    **Counting `is_dir` attempts rather than traversals was measured, not assumed.** Gating on
    "the first pass over the tree" does not work here: pathlib's recursive selector yields the
    parent before walking it, so the first scan of the root classifies nothing and the first
    classification of a child lands in the SECOND scan. A gate written against the intuition
    silently never fired and the row passed for the wrong reason.
    """

    def __init__(self, name: str, error: OSError) -> None:
        self._name = name
        self._error = error
        self._real = os.scandir
        self.attempts = 0

    def _classify_once(self, entry):  # noqa: ANN001, ANN202
        outer = self

        class _FailsFirstAttempt:
            __slots__ = ("_entry",)

            def __init__(self, wrapped) -> None:  # noqa: ANN001
                self._entry = wrapped

            def __getattr__(self, name):  # noqa: ANN001, ANN204
                return getattr(self._entry, name)

            def is_dir(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN204
                outer.attempts += 1
                if outer.attempts == 1:
                    raise outer._error
                return self._entry.is_dir(*args, **kwargs)

        return _FailsFirstAttempt(entry)

    def __call__(self, path="."):
        entries = []
        with self._real(path) as scan:
            for entry in scan:
                entries.append(self._classify_once(entry) if entry.name == self._name else entry)
        return _ScandirResult(entries)


def test_row_s2m_an_intermittent_classification_fault_is_captured_by_the_supplying_traversal(
    tmp_path, monkeypatch
):
    """S2m: the classification layer has the SAME observation problem as the scan layer.

    Coordinator hold on `7d3a6e8d4`: leaving `DirEntry` classification to the later readability
    walk "cannot certify classification inside the supplying traversal" — the walk is again a
    re-run, so an intermittent classification fault is invisible exactly as an intermittent scan
    fault was. I had reasoned that relevance made capturing them unsafe; the correct order is
    the one they gave: **capture the actual error, then prove it irrelevant or refuse. Unknown
    relevance is not demonstrated disjointness.**

    Here `is_dir()` fails only on the FIRST classification of the directory holding the selected
    file. `Path.glob` suppresses it and returns a short surface; the later walk classifies
    cleanly and reports the tree healthy. The observing enumerator sees the fault at the moment
    the surface is built, so no later success can clear it.
    """
    base = tmp_path / "base"
    root = base / "surface"
    inner = root / "inner"
    inner.mkdir(parents=True)
    selected = inner / "leaf.txt"
    selected.write_bytes(b"NEEDLE\n")
    elsewhere = base / "elsewhere"
    elsewhere.mkdir()
    alias = elsewhere / "alias.txt"
    os.link(selected, alias)

    member = {
        "id": "classification-surface",
        "reader": {"id": "fs.glob", "version": "^1.0.0"},
        "location": {"path": str(root), "patterns": ["**/*.txt"]},
    }
    procedure = _procedure_root(
        tmp_path / "procedure",
        members=[member],
        verdicts=[_verdict("classification-surface", "scope_exited")],
    )
    verdicts = fv.load_frame_verdicts(procedure, now=NOW)

    readable = fv.scope_within_decayed([str(alias)], verdicts, council_root=base, vault_root=base)
    assert readable.all_inside is True, "readable baseline reaches the selected file"

    monkeypatch.setattr(
        os,
        "scandir",
        _ClassificationFaultingOnFirstAttempt("inner", OSError(40, "Too many levels of symlinks")),
    )

    with pytest.raises(fv.NonCanonicalScopeRef) as caught:
        fv.scope_within_decayed([str(alias)], verdicts, council_root=base, vault_root=base)
    assert "cannot enumerate" in str(caught.value)
    assert caught.value.remedy


class _IteratorFaultingOnFirstAttempt:
    """`os.scandir` whose ITERATOR raises once, mid-walk, after opening cleanly."""

    def __init__(self, target: str, error: OSError) -> None:
        self._target = target
        self._error = error
        self._real = os.scandir
        self.attempts = 0

    def __call__(self, path="."):
        entries = []
        with self._real(path) as scan:
            entries.extend(scan)
        if str(path).rstrip("/") == self._target:
            self.attempts += 1
            if self.attempts == 1:
                return _ScandirRaisingMidIteration(entries, self._error)
        return _ScandirResult(entries)


class _ScandirRaisingMidIteration(_ScandirResult):
    """Yields nothing and raises on the first `__next__`, as a failing iterator does."""

    def __init__(self, entries, error: OSError) -> None:
        super().__init__(entries)
        self._error = error
        self._raised = False

    def __next__(self):
        if not self._raised:
            self._raised = True
            raise self._error
        return super().__next__()


def test_row_s2n_a_fault_while_iterating_the_scan_is_captured_too(tmp_path, monkeypatch):
    """S2n: opening a scan, ITERATING it, and classifying an entry fail separately.

    Review finding (codex, 2026-09-08, at `7d3a6e8d4`): the observing enumerator caught only
    errors *opening* the iterator, so a scandir that opened cleanly and then raised mid-walk
    still shortened the surface with nothing recorded. Three layers, and the repair had covered
    one and then two of them — the same one-at-a-time pattern as the `OSError`/`RuntimeError`/
    `ValueError` family this module met three times.

    Relevance is not attempted for this layer, deliberately: the entry an iteration failure
    would have yielded is exactly what was not produced, so there is nothing to test for
    disjointness. Unknown relevance is not demonstrated disjointness, so it refuses.
    """
    base = tmp_path / "base"
    root = base / "bin"
    root.mkdir(parents=True)
    selected = root / "fsck.ext2"
    selected.write_bytes(b"e2fsck NEEDLE\n")
    scope_alias = root / "e2fsck"
    os.link(selected, scope_alias)

    member = {
        "id": "iteration-surface",
        "reader": {"id": "fs.glob", "version": "^1.0.0"},
        "location": {"path": str(root), "patterns": ["fsck.ext[234]"]},
    }
    procedure = _procedure_root(
        tmp_path / "procedure",
        members=[member],
        verdicts=[_verdict("iteration-surface", "scope_exited")],
    )
    verdicts = fv.load_frame_verdicts(procedure, now=NOW)

    readable = fv.scope_within_decayed(
        [str(scope_alias)], verdicts, council_root=base, vault_root=base
    )
    assert readable.all_inside is True, "readable baseline reaches the selected file"

    monkeypatch.setattr(
        os,
        "scandir",
        _IteratorFaultingOnFirstAttempt(str(root), PermissionError(13, "Permission denied")),
    )

    with pytest.raises(fv.NonCanonicalScopeRef) as caught:
        fv.scope_within_decayed([str(scope_alias)], verdicts, council_root=base, vault_root=base)
    assert "cannot enumerate" in str(caught.value)
    assert caught.value.remedy


class _ScanEnterFaultingOnFirstAttempt:
    """`os.scandir` whose returned object fails on CONTEXT ENTRY the first time, not on open."""

    def __init__(self, target: str, error: OSError) -> None:
        self._target = target
        self._error = error
        self._real = os.scandir
        self.attempts = 0

    def __call__(self, path="."):
        entries = []
        with self._real(path) as scan:
            entries.extend(scan)
        if str(path).rstrip("/") == self._target:
            self.attempts += 1
            if self.attempts == 1:
                return _ScandirRaisingOnEnter(entries, self._error)
        return _ScandirResult(entries)


class _ScandirRaisingOnEnter(_ScandirResult):
    """Opens fine; `__enter__` raises. Native pathlib catches it and it vanishes unrecorded."""

    def __init__(self, entries, error: OSError) -> None:
        super().__init__(entries)
        self._error = error

    def __enter__(self):
        raise self._error


def test_row_s2p_a_fault_entering_the_scan_context_is_captured_too(tmp_path, monkeypatch):
    """S2p: the PROTOCOL layer — entering the scan — is a fourth place this defect lives.

    Review finding (root, 2026-09-08, at `8c3302d49`, eight cases): the observing enumerator
    wrapped opening, iterating and classifying, and left `__enter__`/`__exit__` bare. Native
    pathlib catches an error there and it disappears exactly as the other three did.

    **Four layers, closed one at a time, each close reported as complete.** That is the same
    shape as `OSError`/`RuntimeError`/`ValueError` being met one type at a time in this module,
    and worth naming rather than quietly adding a fourth `try`.

    Semantics are unchanged: the error is recorded and re-raised, so the caller sees what it saw.
    """
    base = tmp_path / "base"
    root = base / "bin"
    root.mkdir(parents=True)
    selected = root / "fsck.ext2"
    selected.write_bytes(b"e2fsck NEEDLE\n")
    scope_alias = root / "e2fsck"
    os.link(selected, scope_alias)

    member = {
        "id": "protocol-surface",
        "reader": {"id": "fs.glob", "version": "^1.0.0"},
        "location": {"path": str(root), "patterns": ["fsck.ext[234]"]},
    }
    procedure = _procedure_root(
        tmp_path / "procedure",
        members=[member],
        verdicts=[_verdict("protocol-surface", "scope_exited")],
    )
    verdicts = fv.load_frame_verdicts(procedure, now=NOW)

    readable = fv.scope_within_decayed(
        [str(scope_alias)], verdicts, council_root=base, vault_root=base
    )
    assert readable.all_inside is True, "readable baseline reaches the selected file"

    monkeypatch.setattr(
        os,
        "scandir",
        _ScanEnterFaultingOnFirstAttempt(str(root), PermissionError(13, "Permission denied")),
    )

    with pytest.raises(fv.NonCanonicalScopeRef) as caught:
        fv.scope_within_decayed([str(scope_alias)], verdicts, council_root=base, vault_root=base)
    assert "cannot enumerate" in str(caught.value)


@pytest.mark.parametrize(
    "pattern",
    ["[b]ranch/selected.txt", "./[b]ranch/selected.txt", ".//[b]ranch/selected.txt"],
    ids=["plain", "dot-prefixed", "dot-and-double-slash"],
)
def test_row_s2q_relevance_reads_the_pattern_the_way_the_selector_does(
    tmp_path, monkeypatch, pattern
):
    """S2q: the relevance proof must not carry its own normalization grammar.

    Review finding (root, 2026-09-08, at `8c3302d49`): `_definitely_outside_pattern` split the
    pattern on "/", which keeps `.` and empty segments that pathlib's own selector removes. So
    for `./[b]ranch/selected.txt` the entry `branch` was compared against the segment `.`, the
    match failed, a RELEVANT classification fault was declared irrelevant and discarded, and the
    selection went short with `errors` empty — the fault the observation exists to catch,
    silenced by the filter meant to keep it narrow.

    **Two grammars for one pattern will always drift; the sound reading is the selector's own.**
    `PurePosixPath(pattern).parts` is that reading, and the three spellings here denote the same
    language, which is the property the row pins.
    """
    base = tmp_path / "base"
    root = base / "surface"
    branch = root / "branch"
    branch.mkdir(parents=True)
    selected = branch / "selected.txt"
    selected.write_bytes(b"NEEDLE\n")
    elsewhere = base / "elsewhere"
    elsewhere.mkdir()
    alias = elsewhere / "alias.txt"
    os.link(selected, alias)

    member = {
        "id": "normalization-surface",
        "reader": {"id": "fs.glob", "version": "^1.0.0"},
        "location": {"path": str(root), "patterns": [pattern]},
    }
    procedure = _procedure_root(
        tmp_path / "procedure",
        members=[member],
        verdicts=[_verdict("normalization-surface", "scope_exited")],
    )
    verdicts = fv.load_frame_verdicts(procedure, now=NOW)

    readable = fv.scope_within_decayed([str(alias)], verdicts, council_root=base, vault_root=base)
    assert readable.all_inside is True, f"{pattern}: the healthy selection reaches the file"

    monkeypatch.setattr(
        os,
        "scandir",
        _ClassificationFaultingOnFirstAttempt("branch", OSError(40, "Too many levels of symlinks")),
    )

    with pytest.raises(fv.NonCanonicalScopeRef) as caught:
        fv.scope_within_decayed([str(alias)], verdicts, council_root=base, vault_root=base)
    assert "cannot enumerate" in str(caught.value)


@pytest.mark.parametrize(
    "pattern", ["branch/leaf.txt", "./branch/leaf.txt"], ids=["plain", "dot-prefixed"]
)
def test_row_s2r_the_readability_walk_reads_the_same_normalized_pattern(tmp_path, pattern):
    """S2r: `_require_scannable` had the SAME dot defect, one function away from the repair.

    Codex named both sites in one finding (at `a465c0a99`): "the separate readability walk
    likewise retains the dot segment". Splitting on "/" keeps a `.` that `Path.glob` normalizes
    away, so `_children` matched the literal `"."` against real directory names, the frontier
    emptied, and the walk checked nothing at all for a dot-prefixed pattern.

    I had just repaired the relevance filter for exactly this and left its twin unrepaired in
    the next function — the "fix the instance shown and leave the next one" shape, inside the
    same commit that named it. Exercised directly here rather than through a member, because the
    walk also serves the scope expansions, where nothing else in this file would reach it.
    """
    root = tmp_path / "surface"
    branch = root / "branch"
    branch.mkdir(parents=True)
    (branch / "leaf.txt").write_bytes(b"NEEDLE\n")

    fv._require_scannable(root, pattern, component_faults_recorded=True)

    branch.chmod(0)
    try:
        with pytest.raises(fv.UndecidableScopeContainment) as caught:
            fv._require_scannable(root, pattern, component_faults_recorded=True)
    finally:
        branch.chmod(0o755)
    assert "cannot enumerate" in str(caught.value)
    assert "repair read access" in caught.value.remedy


class _StatFaultingOnFirstAttempts:
    """`os.stat` replacement that fails for one path on its first N attempts, then succeeds."""

    def __init__(self, target: str, failing: set[int], error: OSError) -> None:
        self._target = target
        self._failing = failing
        self._error = error
        self._real = os.stat
        self.attempts = 0

    def __call__(self, path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN204
        if str(path).rstrip("/") == self._target:
            self.attempts += 1
            if self.attempts in self._failing:
                raise self._error
        return self._real(path, *args, **kwargs)


def test_row_s2u_a_selected_file_cannot_leave_the_surface_on_a_suppressed_classification(
    tmp_path, monkeypatch
):
    """S2u: `Path.is_file` hides a fault the same way `is_dir` does, one step further along.

    Review finding (codex, 2026-09-08, at `538e5bcd5`): the selected entries are classified with
    `entry.is_file()` AFTER `enumeration_failures` has been checked, so the observing enumerator
    does not cover it — and `Path.is_file` suppresses an ignorable `OSError` and answers False.
    A selected file whose classification faulted therefore left the member's surface silently,
    and a smaller surface is a weaker comparison that admits.

    **A comment two lines above that call said the sibling had been brought inside the
    conversion.** It had been given a `try` — which is not the same thing, because nothing was
    ever raised into it. That is the fourth comment today whose stated mitigation did not run.

    Classification is now done from an unsuppressed stat, with absence still a decided negative:
    ENOENT and ENOTDIR mean the entry genuinely is not a file and dropping it is right.

    **This row pins the classifier itself rather than a dispatch outcome, and that is a
    correction to my first draft.** I wrote it end-to-end and it passed under the mutation —
    enumerating the outcomes showed the selected file is stat-ed five times and no single-index
    fault flips `all_inside`, so the row proved something other than what it named. A boundary
    this small is pinned exactly by calling it, and stays pinned when the code around it moves.
    """
    present = tmp_path / "present.txt"
    present.write_bytes(b"NEEDLE\n")
    directory = tmp_path / "adir"
    directory.mkdir()
    absent = tmp_path / "absent.txt"

    assert fv._classified_is_file(present) is True
    assert fv._classified_is_file(directory) is False
    assert fv._classified_is_file(absent) is False, "absence is a decided negative"
    assert present.is_file() is True, "the healthy answers agree with pathlib's"
    assert directory.is_file() is False
    assert absent.is_file() is False

    real_stat = os.stat

    def faulting(path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        if str(path).rstrip("/") == str(present):
            raise OSError(40, "Too many levels of symlinks")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", faulting)

    # pathlib answers False and loses the fault; the classifier raises it for conversion.
    assert present.is_file() is False, "pathlib suppresses ELOOP, which is the whole problem"
    with pytest.raises(OSError) as caught:
        fv._classified_is_file(present)
    assert caught.value.errno == 40

    # And a genuinely absent path is still a decided negative under the same fault injector.
    assert fv._classified_is_file(absent) is False


def test_row_s2v_the_selected_file_classifier_is_the_one_production_actually_calls(
    tmp_path, monkeypatch
):
    """S2v: the WIRING, which S2u deliberately does not cover and therefore left unpinned.

    Review finding (codex, 2026-09-08): S2u exercises `_classified_is_file` directly and says so,
    which pins the boundary but not the fact that the member enumeration calls it. **A present
    but unwired helper would pass S2u** — and that is exactly the "merely present unused helper"
    case the coordinator's own campaign added a caller-bypass mutation for.

    The correction is not to move the row back end-to-end. S2u's first draft WAS end-to-end and
    measured nothing, because no single stat index flips the outcome. Both are needed: one row
    that pins the boundary exactly, and one that pins the call. This is the second.
    """
    base = tmp_path / "base"
    root = base / "surface"
    root.mkdir(parents=True)
    (root / "leaf.txt").write_bytes(b"NEEDLE\n")
    elsewhere = base / "elsewhere"
    elsewhere.mkdir()
    alias = elsewhere / "alias.txt"
    os.link(root / "leaf.txt", alias)

    member = {
        "id": "wiring-surface",
        "reader": {"id": "fs.glob", "version": "^1.0.0"},
        "location": {"path": str(root), "patterns": ["*.txt"]},
    }
    procedure = _procedure_root(
        tmp_path / "procedure",
        members=[member],
        verdicts=[_verdict("wiring-surface", "scope_exited")],
    )
    verdicts = fv.load_frame_verdicts(procedure, now=NOW)

    calls: list[str] = []
    real_classifier = fv._classified_is_file

    def recording(entry):  # noqa: ANN001, ANN202
        calls.append(str(entry))
        return real_classifier(entry)

    monkeypatch.setattr(fv, "_classified_is_file", recording)

    result = fv.scope_within_decayed([str(alias)], verdicts, council_root=base, vault_root=base)
    assert result.all_inside is True, "the readable arrangement still decides normally"
    assert str(root / "leaf.txt") in calls, (
        "the member enumeration must classify its selected entries through the unsuppressed "
        f"classifier; it called it for {calls}"
    )


def test_row_s2w_each_converted_classifier_is_the_one_its_caller_actually_calls(
    tmp_path, monkeypatch
):
    """S2w: CALLER OBLIGATION, stated separately from end-to-end reachability.

    Three conversions — `ref_within_member`'s candidate and the two in
    `_refuse_in_root_alias_reaching_surface` — are measured UNPINNED end-to-end: reverting each
    leaves every control green, because `resolve(strict=True)` upstream refuses on the same
    fault first. That is a fact about reachability, and the coordinator's instruction is to hold
    the caller's obligation as a separate claim rather than let one absorb the other.

    So this row asserts what the call sites do, not what a fault reaches: each converted site
    calls the unsuppressed classifier, on the path it is deciding about. A revert to the native
    method makes the recorder see nothing and reddens the row — which is the discrimination the
    stage-triggered and steady faults could not supply, obtained without weakening the earlier
    refusal that intercepts them.

    The absent twins are here because the obligation has two halves: the classifier must be
    called, AND absence must remain a decided negative rather than becoming an error.

    **Calls are attributed to the CALLING FUNCTION, and the first draft was not.** Recording only
    "was this classifier called with this path" passed with the site reverted, because another
    already-converted site classified the same path moments later. A caller obligation that any
    caller can satisfy is not a caller obligation — the fifth row today that measured something
    other than what it named, and again caught only because a mutation failed to redden it.

    **Two of the three conversions are covered here; the third is not, and that is the report.**
    `_refuse_in_root_alias_reaching_surface`'s `canonical_is_file` sits behind a
    `scope_pattern is None` guard, and across four constructed arrangements — root and in-root
    alias, with and without a pattern, matching and non-matching — the function is either not
    entered or returns before that branch. So that site has **no demonstrated obligation at
    all**, end-to-end or caller-level, and reaching it would mean relaxing a guard to arrive at
    a chosen branch. It stays a review candidate with that stated rather than an assumed one.
    """
    root = tmp_path / "member"
    root.mkdir()
    (root / "leaf.txt").write_bytes(b"NEEDLE\n")
    target, alias = tmp_path / "gawk", tmp_path / "awk"
    target.touch()
    alias.symlink_to(target.name)

    seen: dict[str, list[tuple[str, str]]] = {"is_dir": [], "is_file": [], "exists": []}
    originals = {
        "is_dir": fv._classified_is_dir,
        "is_file": fv._classified_is_file,
        "exists": fv._classified_exists,
    }

    synthetic = {"<genexpr>", "<listcomp>", "<setcomp>", "<dictcomp>", "<lambda>"}

    def recorder(name: str):
        def probe(entry):  # noqa: ANN001, ANN202
            # Walk past synthetic frames: the anchor call sits inside a generator expression, so
            # the immediate frame is `<genexpr>` and naming it would attribute the call to the
            # comprehension rather than to the function that owns the decision.
            frame = sys._getframe(1)  # noqa: SLF001
            while frame is not None and frame.f_code.co_name in synthetic:
                frame = frame.f_back
            caller = frame.f_code.co_name if frame is not None else "?"
            seen[name].append((caller, str(entry)))
            return originals[name](entry)

        return probe

    for name in originals:
        monkeypatch.setattr(fv, f"_classified_{name}", recorder(name))

    literal = fv.DecayedMember("m", "scope_exited", (tmp_path,), ("gawk",), ())
    fv.ref_within_member(tmp_path, True, literal, scope_pattern="[a]wk")
    assert ("ref_within_member", str(alias)) in seen["is_dir"], (
        f"the candidate classification must be made by ref_within_member; saw {seen['is_dir']}"
    )

    fv.resolve_scope_ref("member/leaf.txt", council_root=tmp_path, vault_root=tmp_path / "vault")
    assert ("resolve_scope_ref", str(root)) in seen["exists"], (
        f"anchor selection must be made by resolve_scope_ref; saw {seen['exists']}"
    )

    # Absence stays a decided negative in all three, under the real operation.
    missing = tmp_path / "not-here"
    assert originals["is_dir"](missing) is False
    assert originals["is_file"](missing) is False
    assert originals["exists"](missing) is False


def test_row_s2t_the_observed_glob_reads_no_more_than_the_plain_one(tmp_path):
    """S2t: the read that DECIDES must be the read that is OBSERVED, so there is only one.

    Coordinator's static concern on `538e5bcd5`: the first version of the classification hook
    stat-ed to observe and then delegated to `Path.is_dir`, which stats AGAIN — so a transient
    fault hitting only the second read was never seen, and **the observation hook had the very
    same-observation defect it was built to close, one level down.** Repaired structurally
    rather than waiting for the matrix to reproduce it: two reads where one decides is a defect
    by construction, and `Path.is_dir`'s errno behaviour is mirrored from the runtime rather
    than approximated.

    This row pins the property directly instead of through a fault schedule, because a schedule
    depends on call ordering that shifts whenever the code around it moves — which is exactly
    how the previous row's first draft came to measure nothing. Counting is stable.
    """
    root = tmp_path / "surface"
    branch = root / "branch"
    branch.mkdir(parents=True)
    (branch / "leaf.txt").write_bytes(b"NEEDLE\n")
    (root / "other.txt").write_bytes(b"NEEDLE\n")

    real_stat = os.stat

    def counting(counter: list[int]):
        def probe(path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
            counter[0] += 1
            return real_stat(path, *args, **kwargs)

        return probe

    plain: list[int] = [0]
    os.stat = counting(plain)
    try:
        expected = sorted(str(p) for p in root.glob("**/*.txt"))
    finally:
        os.stat = real_stat

    observed_count: list[int] = [0]
    os.stat = counting(observed_count)
    try:
        entries, failures = fv._observed_glob(root, "**/*.txt")
    finally:
        os.stat = real_stat

    assert sorted(str(p) for p in entries) == expected, "observation must not change selection"
    assert failures == [], "a healthy tree records nothing"
    assert observed_count[0] <= plain[0], (
        f"the observing glob performed {observed_count[0]} stats against the plain glob's "
        f"{plain[0]}: an extra read is a read whose faults nothing decides on"
    )


def test_row_s2s_a_root_classification_fault_is_observed_before_pathlib_hides_it(
    tmp_path, monkeypatch
):
    """S2s: the fifth layer, and it runs BEFORE any scan.

    Review finding (codex, 2026-09-08, at `c761b2942`): `Path.glob` asks `parent_path.is_dir()`
    before scanning anything, and `Path.is_dir` swallows an ignorable `OSError` from its `stat`
    and answers False. So a root whose classification faults yielded an empty selection with
    nothing recorded — the enumeration never reached the scan, iterate, enter or entry-classify
    hooks at all, every one of which I had added believing the set was complete.

    **Five layers, closed one at a time, each close reported as complete.** Open, enter, iterate,
    classify an entry, classify the root. Writing that down is the only part that generalises;
    the fix itself is four lines.

    The fault here is transient, on the root's own stat, so no later clean classification can
    clear it — the same property every layer before it needed.
    """
    base = tmp_path / "base"
    root = base / "bin"
    root.mkdir(parents=True)
    selected = root / "fsck.ext2"
    selected.write_bytes(b"e2fsck NEEDLE\n")
    scope_alias = root / "e2fsck"
    os.link(selected, scope_alias)

    member = {
        "id": "root-classification-surface",
        "reader": {"id": "fs.glob", "version": "^1.0.0"},
        "location": {"path": str(root), "patterns": ["fsck.ext2"]},
    }
    procedure = _procedure_root(
        tmp_path / "procedure",
        members=[member],
        verdicts=[_verdict("root-classification-surface", "scope_exited")],
    )
    verdicts = fv.load_frame_verdicts(procedure, now=NOW)

    readable = fv.scope_within_decayed(
        [str(scope_alias)], verdicts, council_root=base, vault_root=base
    )
    assert readable.all_inside is True, "readable baseline reaches the selected file"

    monkeypatch.setattr(
        os,
        "stat",
        # The FIRST root stat is the glob's own `parent_path.is_dir()`, measured rather than
        # guessed: faulting {2} reaches a different refusal, {3} and {7} are admitted, and
        # {4}-{6} are the scope-component resolution. Only {1} isolates this layer, and a row
        # written against a plausible-looking schedule passed for the wrong reason until the
        # mutation said so.
        _StatFaultingOnFirstAttempts(str(root), {1}, OSError(40, "Too many levels of symlinks")),
    )

    with pytest.raises(fv.NonCanonicalScopeRef) as caught:
        fv.scope_within_decayed([str(scope_alias)], verdicts, council_root=base, vault_root=base)
    assert "cannot" in str(caught.value)
    assert caught.value.remedy


def test_row_s2o_absent_observation_refuses_by_name_instead_of_falling_back(tmp_path, monkeypatch):
    """S2o: capability ABSENCE, which nothing exercised and which is not hypothetical.

    Review finding (codex, 2026-09-08, `shared/frame_verdicts.py:2654`) and the coordinator's
    first hold, which are the same point: when the pathlib seam is missing, an earlier revision
    silently used the enumerate-then-verify-separately approach the repair beside it had just
    identified as unsafe. **Reproduced by codex on the installed Python 3.14.4**, where
    `_GLOB_SCAN_SEAM` is false — and `pyproject.toml` permits `>=3.12`, so this is a runtime the
    estate may actually select, not a thought experiment.

    Measured before accepting refusal as the answer: 3.14's `Path.glob` builds a `_StringGlobber`
    inside the call and scans through `os.scandir` on plain strings, with no `Path._scandir` and
    no per-call injection point on the class. So there is no equivalent invocation-local binding
    to qualify there, and the instruction's other branch — a named unsupported refusal — is the
    one that applies. It refuses with the interpreter property named and says not to disable the
    check, rather than degrading to a known fail-open with a comment about it.
    """
    base = tmp_path / "base"
    root = base / "surface"
    root.mkdir(parents=True)
    (root / "leaf.txt").write_bytes(b"NEEDLE\n")
    elsewhere = base / "elsewhere"
    elsewhere.mkdir()
    alias = elsewhere / "alias.txt"
    os.link(root / "leaf.txt", alias)

    member = {
        "id": "unobservable-surface",
        "reader": {"id": "fs.glob", "version": "^1.0.0"},
        "location": {"path": str(root), "patterns": ["*.txt"]},
    }
    procedure = _procedure_root(
        tmp_path / "procedure",
        members=[member],
        verdicts=[_verdict("unobservable-surface", "scope_exited")],
    )
    verdicts = fv.load_frame_verdicts(procedure, now=NOW)

    assert (
        fv.scope_within_decayed(
            [str(alias)], verdicts, council_root=base, vault_root=base
        ).all_inside
        is True
    ), "with the seam present the surface is decided normally"

    monkeypatch.setattr(fv, "_GLOB_SCAN_SEAM", False)

    with pytest.raises(fv.NonCanonicalScopeRef) as caught:
        fv.scope_within_decayed([str(alias)], verdicts, council_root=base, vault_root=base)
    assert "cannot decide containment" in str(caught.value)
    assert "interpreter" in str(caught.value)
    assert "do not disable the check" in caught.value.remedy


def test_row_s2l_an_observed_failure_must_belong_to_the_declared_grammar(tmp_path, monkeypatch):
    """S2l: exception RELEVANCE for `_observed_glob`, which the coordinator asked be qualified.

    Observing the supplying traversal only helps if what it observes is the scope's business.
    The claim that makes it sound is that `Path.glob` visits exactly the directories its pattern
    reaches — so a failure it reports is inside the declared grammar by construction, and no
    relevance filter is needed on top. **That is an argument until a row holds it**, and the
    failure mode it guards against is the one that reddened ten dispatch controls this morning:
    a fault on an unrelated directory refusing a scope that never reads it.

    Here the member is rooted at `surface` with a recursive pattern, and the faulting directory
    is a SIBLING of that root, outside it entirely. The glob never scans it, so nothing is
    recorded and the answer is unchanged — including `all_inside`, which must still be True
    rather than merely un-refused.
    """
    base = tmp_path / "base"
    root = base / "surface"
    inner = root / "inner"
    inner.mkdir(parents=True)
    selected = inner / "leaf.txt"
    selected.write_bytes(b"NEEDLE\n")
    unrelated = base / "unrelated"
    unrelated.mkdir()
    (unrelated / "other.txt").write_bytes(b"NEEDLE\n")
    elsewhere = base / "elsewhere"
    elsewhere.mkdir()
    alias = elsewhere / "alias.txt"
    os.link(selected, alias)

    member = {
        "id": "relevance-surface",
        "reader": {"id": "fs.glob", "version": "^1.0.0"},
        "location": {"path": str(root), "patterns": ["**/*.txt"]},
    }
    procedure = _procedure_root(
        tmp_path / "procedure",
        members=[member],
        verdicts=[_verdict("relevance-surface", "scope_exited")],
    )
    verdicts = fv.load_frame_verdicts(procedure, now=NOW)

    real_scandir = os.scandir

    def refusing(path=".", *args, **kwargs):
        if str(path).rstrip("/") == str(unrelated):
            raise PermissionError(13, "Permission denied")
        return real_scandir(path, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", refusing)

    result = fv.scope_within_decayed([str(alias)], verdicts, council_root=base, vault_root=base)
    assert result.all_inside is True, (
        "a fault outside the member root is not this scope's concern and must not change the "
        "answer, let alone refuse"
    )


def _assert_filesystem_remedy_survived(error: fv.NonCanonicalScopeRef) -> None:
    """The refusal must still name the FILESYSTEM repair, not the class's glob advice.

    Review finding (codex, 2026-09-08, `shared/frame_verdicts.py:2538` and `:2578`):
    `UndecidableScopeContainment` inherits `ValueError`, so the enumeration wrappers caught the
    typed refusal `_require_scannable` had just raised and re-wrapped it. The fact survived and
    the REMEDY did not — a broken read permission was reported as advice to use explicit paths
    or narrower globs, when the scope in the reproduction is already explicit and the access is
    what is broken. An operator following that remedy would edit a correct declaration.
    """
    assert error.remedy, "a refusal must carry a remedy"
    assert "repair read access" in error.remedy, (
        f"the filesystem remedy was replaced by the generic one: {error.remedy!r}"
    )
    assert "narrower globs" not in error.remedy


@pytest.mark.parametrize(
    ("reader", "patterns", "refuses"),
    [
        ("fs.glob", ["**/*.txt"], True),
        ("fs.content_query", ["*.txt"], True),
        ("fs.glob", ["readable/*.txt"], False),
    ],
    ids=["fs.glob-recursive", "content-query-recursive", "fs.glob-never-reaches-it"],
)
def test_row_s2g_an_interior_fault_in_the_member_enumeration_cannot_be_survived_by_a_sibling(
    tmp_path, monkeypatch, reader, patterns, refuses
):
    """S2g: fault a directory BELOW the member root while a readable sibling still yields.

    Review finding (glm, 2026-09-08, `shared/frame_verdicts.py:2490`): the member-side
    enumeration was said to read only the root, so an unreadable interior directory would drop
    the selected entry while the sibling's entries survived — a short surface, `all_inside`
    False, and a decayed hard link admitted. The finding also observed that **no committed row
    injected a mid-tree fault during the member enumeration** with a readable sibling present,
    which was true, and is the reason this row exists whichever way the claim resolves.

    The two recursive rows are the reproduction. They pass only because the guard is handed the
    pattern the enumeration actually used — `rglob(p)` is `glob("**/" + p)`, and the `**` branch
    walks the whole subtree with a per-directory `onerror`. Erase either half of that
    correspondence and these two admit.

    The third row is the must-NOT-refuse control, and it is what keeps this from being a blanket:
    a pattern that never names the faulting directory must not be refused by it. Without that row
    a "fix" that refuses on any unreadable corner of the tree would look correct here — the same
    over-wide shape that reddened ten committed dispatch controls when `_children` asked
    `is_dir()` before matching the name.
    """
    base = tmp_path / "base"
    root = base / "surface"
    readable = root / "readable"
    interior = root / "interior"
    readable.mkdir(parents=True)
    interior.mkdir(parents=True)
    (readable / "keep.txt").write_bytes(b"sibling NEEDLE\n")
    selected = interior / "selected.txt"
    selected.write_bytes(b"selected NEEDLE\n")
    elsewhere = base / "elsewhere"
    elsewhere.mkdir()
    alias = elsewhere / "alias.txt"
    os.link(selected, alias)

    if reader == "fs.content_query":
        location = {"roots": [str(root)], "patterns": patterns, "query": "NEEDLE"}
    else:
        location = {"path": str(root), "patterns": patterns}
    member = {
        "id": "interior-fault-surface",
        "reader": {"id": reader, "version": "^1.0.0"},
        "location": location,
    }
    procedure = _procedure_root(
        tmp_path / "procedure",
        members=[member],
        verdicts=[_verdict("interior-fault-surface", "scope_exited")],
    )
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
    verdicts = fv.load_frame_verdicts(procedure, now=NOW)

    if refuses:
        # With everything readable the alias really is inside, so the refusal below is about the
        # fault and not about a member that never selected the file.
        clean = fv.scope_within_decayed([str(alias)], verdicts, council_root=base, vault_root=base)
        assert clean.all_inside is True, "readable baseline must reach the selected file"

    real_scandir = os.scandir

    def refusing(path=".", *args, **kwargs):
        if str(path).rstrip("/") == str(interior):
            raise PermissionError(13, "Permission denied")
        return real_scandir(path, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", refusing)

    if refuses:
        with pytest.raises(fv.NonCanonicalScopeRef) as caught:
            fv.scope_within_decayed([str(alias)], verdicts, council_root=base, vault_root=base)
        assert "cannot enumerate" in str(caught.value)
        _assert_filesystem_remedy_survived(caught.value)
    else:
        result = fv.scope_within_decayed([str(alias)], verdicts, council_root=base, vault_root=base)
        assert result.all_inside is False, (
            "a pattern that never traverses the faulting directory must not be refused by it"
        )
