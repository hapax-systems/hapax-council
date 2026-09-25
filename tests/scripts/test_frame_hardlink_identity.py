"""A hard link is the same file under another name, at receipt-only dispatch.

Row P7 in `test_frame_scope_grammar.py` pins this at the predicate. gemini and glm both called
it critical at `5007ed238`/`ff1f1ba69` that there is no `os.link` regression through `main()`, so
the guard's end-to-end behaviour was asserted nowhere:

    Hard-link identity guard untested and filters before identity check for broad spellings
    — shared/frame_verdicts.py:3019

**The "must refuse for every broad spelling" reading is not the contract, and these rows do not
encode it.** That is the withdrawn `aa5939179` — an alias-overlap veto substituted for the
partial-scope predicate — and it is settled in writing twice over:

    "the consumer refuses wholly decayed scopes and does not replace partial-scope semantics
     with an any-match ban ... It does not require every file in an admitted partial scope to
     be disjoint ... No superseding any-overlap policy is established."
    — FRAME-REVIEW-SCOPE-DISPOSITION-20260907, clarified 2026-09-07T11:30:25Z

Root reproduced that regression through receipt-only `main()` (7 `fs.glob` cases: 6/1 committed,
7 pass with the guard removed, 6/1 restored). Reviewer convergence is evidence about a mechanism,
not authority over a policy — the error the withdrawal names, and the one an "all broad spellings
refuse" control would silently re-commit.

The measured part of the finding does not reproduce: `_identity_reaches_surface` returns True for
the literal, dirlike, `*.txt` and `alias[.]txt` spellings alike, so the `target not in surface`
filter does not stop the identity check from running.

**These rows are NOT coverage of the `:3019` guard, and should not be read as closing that half
of the finding.** Disabling it (`if False and denoted and _identity_reaches_surface(...)`) leaves
every row in this file green, and reddens exactly row P7's two arms in
`test_frame_scope_grammar.py` and nothing else across the frame suites. The guard has no
observable effect at `main()` for these shapes because containment's own identity check —
`_same_existing_file` in `ref_within_member` — refuses the aliased scope first. The guard exists
to stop one source stating a contradiction about one pair (contained=True AND disjoint=True), and
a contradiction between two internal answers is not visible in an exit code. P7 is where it is
tested; that is a fact about where the guard can be observed, not an argument that end-to-end
rows are unnecessary.

What these rows do pin is the end-to-end behaviour for hard links, which genuinely had none.

**What the rows below actually establish, corrected.** An earlier draft of this paragraph claimed
the guard buys a pair — "`aliased/` refuses when the alias is the only thing in it, and admits
when an unselected file sits beside it". **The first half is false and the final row measures the
opposite** (cx-blue, 2026-09-08): a dirlike scope over an alias-only directory is ADMITTED. The
sentence was written from what I expected before measuring and left standing after the
measurement contradicted it, in the same file as the row that contradicts it.

The line that does hold is narrower and is about SPELLING, not about what the directory contains:
a scope denoting exactly one name that is the decayed file under another name refuses (literal,
and a single-choice character class), while a scope denoting unboundedly many names is partial and
admits. Both directories in this module hold an alias; what separates the rows is how much the
scope denotes.

That admission is the ruled semantics, not a tolerated gap: **effect scope is prospective**, and
an outside witness need not already exist, because the scope for creating a file is not its
present filesystem expansion (coordinator ruling, 2026-09-08, `FRAME-SCALAR-HARDLINK-READBACK-
20260908`). It does not establish that any actual operation is outside the member, nor that the
alias is healthy, and a declaration broadened merely to manufacture admission still misstates the
demand.
"""

import os

import pytest

from tests.scripts.test_frame_root_entries import _root_dispatch


def _linked(tmp_path, *, beside: bool):
    """A decayed member selecting `surface/selected.txt`, aliased as `alias/selected-alias.txt`.

    `beside` puts an unselected file in the alias directory, which is the only difference
    between the wholly-decayed and partial-scope rows.
    """
    base = tmp_path / "producer"
    surface = base / "surface"
    surface.mkdir(parents=True, exist_ok=True)
    aliased = base / "aliased"
    aliased.mkdir(exist_ok=True)

    selected = surface / "selected.txt"
    selected.write_bytes(b"NEEDLE\n")
    alias = aliased / "selected-alias.txt"
    os.link(selected, alias)
    assert alias.stat().st_ino == selected.stat().st_ino, "the fixture must be a real hard link"
    assert alias.name != selected.name, "identity must be the only thing that relates them"

    if beside:
        (aliased / "independent.txt").write_bytes(b"UNRELATED\n")
    return base, surface, aliased, alias


def _member(surface) -> dict:
    return {"path": str(surface), "patterns": ["*.txt"]}


def _dispatch(tmp_path, monkeypatch, capsys, surface, base, candidate):
    return _root_dispatch(
        tmp_path,
        monkeypatch,
        capsys,
        _member(surface),
        reader="fs.glob",
        cwd=base,
        candidate=candidate,
    )


@pytest.mark.parametrize("spelling", ["literal", "glob-class"])
def test_main_a_wholly_aliased_scope_refuses(tmp_path, monkeypatch, capsys, spelling):
    """Every name the scope denotes IS the decayed file, so the scope is wholly decayed.

    By name, nothing here is selected: the member selects `surface/selected.txt` and the scope
    names `aliased/selected-alias.txt`, a different directory and a different basename. Only
    file identity relates them, so admitting this would be a dispatch over a decayed surface
    proven by string comparison.

    Both spellings denote exactly one name — `selected-alias[.]txt` is a character class with a
    single choice — which is what makes them wholly decayed. **`aliased/` is deliberately absent
    from this row**; see the open question recorded below.
    """
    base, surface, aliased, alias = _linked(tmp_path, beside=False)
    candidate = {
        "literal": str(alias),
        "glob-class": str(aliased / "selected-alias[.]txt"),
    }[spelling]

    rc, err = _dispatch(tmp_path, monkeypatch, capsys, surface, base, candidate)
    with capsys.disabled():
        print(f"wholly aliased, {spelling:11s}: main()={rc}")

    assert rc != 0, (
        f"{spelling}: a scope whose every file is the DECAYED file under another name was "
        "admitted; identity was decided by name rather than by file"
    )
    assert err, "a refusal must carry its reason"


@pytest.mark.parametrize("spelling", ["dirlike", "glob"])
def test_main_a_partial_scope_over_the_alias_is_still_admitted(
    tmp_path, monkeypatch, capsys, spelling
):
    """The same spelling admits once an unselected file sits beside the alias.

    This is the half an any-match ban would break, and it is the contract: admission needs an
    established basis under every plausible interpretation — disjointness OR the partial-scope
    predicate with a common outside witness — and it "does not require every file in an admitted
    partial scope to be disjoint" (FRAME-REVIEW-SCOPE-DISPOSITION-20260907). Moving things out
    of a decayed member is legitimate work.
    """
    base, surface, aliased, _alias = _linked(tmp_path, beside=True)
    candidate = {"dirlike": f"{aliased}/", "glob": str(aliased / "*.txt")}[spelling]

    rc, err = _dispatch(tmp_path, monkeypatch, capsys, surface, base, candidate)
    with capsys.disabled():
        print(f"partial scope,  {spelling:11s}: main()={rc}")

    assert rc == 0, (
        f"{spelling}: a partial scope was refused; substituting an alias-overlap veto for the "
        "partial-scope predicate is the withdrawn aa5939179 regression"
    )
    assert not err


def test_main_an_independent_file_beside_the_alias_is_admitted(tmp_path, monkeypatch, capsys):
    """A file that is not the decayed file under any name is outside the member."""
    base, surface, aliased, _alias = _linked(tmp_path, beside=True)

    rc, err = _dispatch(
        tmp_path, monkeypatch, capsys, surface, base, str(aliased / "independent.txt")
    )
    with capsys.disabled():
        print(f"independent file beside the alias: main()={rc}")
    assert rc == 0
    assert not err


def test_the_alias_only_directory_is_recorded_not_asserted(tmp_path, monkeypatch, capsys):
    """A dirlike scope over a directory holding ONLY the alias is admitted, and that is the rule.

    Committed first as a recorded measurement I declined to endorse, because deciding it either
    way was the move that got `aa5939179` withdrawn. **The coordinator has since ruled it**
    (2026-09-08, `FRAME-SCALAR-HARDLINK-READBACK-20260908`): effect scope is PROSPECTIVE, an
    outside witness need not already exist, and the scope for creating a file is not that
    directory's present filesystem expansion. So the admission is the semantics, not a gap, and
    this row now asserts it as such.

    What the ruling does NOT establish, kept explicit because the admission is easy to over-read:
    that any actual operation is outside the member, or that the existing alias is healthy. A
    declaration broadened merely to manufacture admission still misstates the demand.

    The mechanism, measured: the observed-entry strategy correctly finds no witness
    (`selected-alias.txt` -> disjoint_established=None), and the generated-name strategy supplies
    `scope`, a name that does not exist. That is the prospective reading in the code. It also
    falsified the claim `_local_partial_scope_established` made in its own docstring — "a scope
    whose entries are all decayed finds nothing here" — corrected in the same commit, since the
    sentence is false even under the ruling that keeps the behaviour.

    Refusing here would substitute an alias-overlap veto for the partial-scope predicate: root
    reproduced that as a regression through receipt-only `main()` (6/1 committed, 7 pass
    guard-removed, 6/1 restored), and no superseding any-overlap policy is established.
    """
    base, surface, aliased, _alias = _linked(tmp_path, beside=False)
    assert sorted(p.name for p in aliased.iterdir()) == ["selected-alias.txt"], (
        "the whole point of this row is that the directory holds nothing but the alias"
    )

    rc, err = _dispatch(tmp_path, monkeypatch, capsys, surface, base, f"{aliased}/")
    with capsys.disabled():
        print(f"alias-only directory, dirlike: main()={rc}  (prospective effect scope)")

    assert rc == 0 and not err, (
        "the alias-only dirlike scope no longer admits: effect scope is prospective, so an "
        "outside witness need not already exist. Refusing here reinstates the alias-overlap "
        "veto withdrawn at aa5939179; it is a policy change and must be made deliberately with "
        "the ruling amended, not arrive as a side effect. See this row's docstring."
    )


def test_main_an_unbounded_glob_over_only_aliases_is_admitted(tmp_path, monkeypatch, capsys):
    """The receipt-only `main()` case for a glob whose outside witness does not exist yet.

    `*.txt` denotes an unbounded language: every `.txt` file that could ever sit in this
    directory, none of which the member selects. Its CURRENT expansion is nothing but a hard link
    to a decayed file, and the containment predicate used to read that expansion as a proof of
    whole-scope containment — so the glob was refused while the directory spelling of the same
    arrangement was admitted (codex at `81962feab`, reproduced on `/usr/bin` `fsck.ext2`/`e2fsck`).

    The coordinator's 2026-09-08 ruling settles it: prospective effect scope is not restricted to
    trailing-slash notation and applies to a declared glob's denoted language, so today's
    expansions cannot establish exhaustive containment of an unbounded scope.

    `aliased/` and `aliased/*.txt` are NOT the same language merely because their present contents
    coincide; each separately has a future outside witness, and that is what admits each.
    """
    base, surface, aliased, _alias = _linked(tmp_path, beside=False)
    assert sorted(p.name for p in aliased.iterdir()) == ["selected-alias.txt"], (
        "the directory must hold nothing but the alias, so only the LANGUAGE can admit it"
    )

    rc, err = _dispatch(tmp_path, monkeypatch, capsys, surface, base, str(aliased / "*.txt"))
    with capsys.disabled():
        print(f"unbounded glob over only aliases: main()={rc}")

    assert rc == 0 and not err, (
        "an unbounded glob's present expansion cannot prove exhaustive containment; refusing "
        "here is the all(expansions) shortcut the ruling removed"
    )


@pytest.mark.parametrize(
    "spelling", ["selected-alias.txt", "selected-alias[.]txt", "selected-alias.tx[t]"]
)
def test_main_a_finite_name_over_an_alias_still_refuses(tmp_path, monkeypatch, capsys, spelling):
    """The negative controls: a FINITE language keeps its whole-language containment proof.

    The ruling preserves literal and single-choice-name refusal explicitly, and does not
    authorize indiscriminate broad admission. Each spelling here denotes exactly one name — a
    character class with a single choice enlarges nothing — and that name is the decayed file
    under another name, so the whole scope really is inside and must refuse.

    Without these rows, "admit every broad spelling" would satisfy the unbounded case above.
    """
    base, surface, aliased, _alias = _linked(tmp_path, beside=False)

    rc, err = _dispatch(tmp_path, monkeypatch, capsys, surface, base, str(aliased / spelling))
    with capsys.disabled():
        print(f"finite name {spelling!r}: main()={rc}")

    assert rc != 0, (
        f"{spelling}: a finite language whose every name is the decayed file under another name "
        "is wholly inside, and the ruling preserves that proof"
    )
    assert err
