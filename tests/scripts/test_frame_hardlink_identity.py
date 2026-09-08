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

What the guard actually buys is the pair below: **`elsewhere/` refuses when the alias is the only
thing in it, and admits when an unselected file sits beside it.** Nothing about the NAMES differs
between those two cases — only identity can tell them apart, and only partial-scope semantics can
admit the second.
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
    """A dirlike scope over a directory holding ONLY the alias is admitted. Open question.

    This row asserts the MEASUREMENT and deliberately does not assert that it is correct, in
    either direction, because which answer is right is a policy question I cannot settle:

    - Under the language reading it is right. `aliased/` denotes unboundedly many names, most of
      which no member selects, so it is a partial scope — and partial scopes are admitted because
      moving things out of a decayed member is legitimate work.
    - Under the filesystem reading it is wrong. Every file the directory currently holds is the
      decayed file under another name, so the dispatch proceeds over a wholly decayed surface.

    The mechanism is measured and is not in doubt: the observed-entry strategy correctly finds no
    witness (`selected-alias.txt` -> disjoint_established=None), and the generated-name strategy
    then supplies `scope`, which does not exist, as the outside witness. That also falsified the
    claim `_local_partial_scope_established` used to make in its own docstring, corrected in the
    same commit.

    Asserting a refusal here would substitute an alias-overlap veto for the partial-scope
    predicate, which is the withdrawn `aa5939179` — root reproduced it as a regression through
    receipt-only `main()` (6/1 committed, 7 pass guard-removed, 6/1 restored), and
    FRAME-REVIEW-SCOPE-DISPOSITION-20260907 states no superseding any-overlap policy is
    established. Two families reporting this does not make it a policy decision; it makes it a
    measurement, which is what this row is.
    """
    base, surface, aliased, _alias = _linked(tmp_path, beside=False)
    assert sorted(p.name for p in aliased.iterdir()) == ["selected-alias.txt"], (
        "the whole point of this row is that the directory holds nothing but the alias"
    )

    rc, err = _dispatch(tmp_path, monkeypatch, capsys, surface, base, f"{aliased}/")
    with capsys.disabled():
        print(f"alias-only directory, dirlike: main()={rc}  (recorded, not endorsed)")

    assert rc == 0 and not err, (
        "MEASUREMENT CHANGED: the alias-only dirlike scope no longer admits. That may be the "
        "right answer, but it is a policy change and must be made deliberately with the "
        "disposition amended — not arrive as a side effect. See this row's docstring."
    )
