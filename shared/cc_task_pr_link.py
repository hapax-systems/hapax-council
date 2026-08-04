"""One definition of a cc-task's PR link: the number, and the repository it lives in.

A bare PR number is NOT a link. `cc-pr-merge-watcher` queries merged PRs in one repository, so
matching a task on the number alone let a merged `hapax-council#6` close a task meaning `reins#6`
while that PR was still open (measured 2026-08-04, twice).

This module exists because THREE definitions of "absent" had already appeared across the two gates
that read this field, and they had already diverged:

    cc-pr-merge-watcher._NULLISH          {"", "null", "none", "~", "nil"}
    cc-pr-merge-watcher._PR_NULL_NULLISH  {"", "null", "none", "~"}
    cc-close-pr-merge-check._nullish      {"", "null", "none", "~"}

One gate treating a value as undeclared while another treats it as declared reintroduces exactly
the silent mismatch the repo-qualification fix removes, so the definition is written once here and
imported. A test asserts every call site resolves through it.
"""

from __future__ import annotations

import re

#: YAML spellings of "no value". A field holding one of these has not been declared.
#:
#: `nil` is included deliberately: YAML 1.1 implementations accept it, and a reader that treats it
#: as a repository NAME would compare it against a real repo, never match, and never say why.
NULLISH: frozenset[str] = frozenset({"", "null", "none", "~", "nil"})

#: `[ \t]*`, NOT `\s*`. `\s` matches newlines, so `pr_repo:` followed by a value on the NEXT line
#: captured that line -- an empty field reading as a declared repository, which is the forgery this
#: module exists to prevent, arriving through a character class.
PR_REPO_PATTERN = re.compile(r"^pr_repo:[ \t]*(\S+)[ \t]*$", flags=re.MULTILINE)
PR_NUMBER_PATTERN = re.compile(r"^pr:[ \t]*(\S+)[ \t]*$", flags=re.MULTILINE)


#: YAML scalars may be quoted. `pr_repo: "owner/name"` must equal `pr_repo: owner/name`, or the
#: same note is declared to one gate and undeclared to the other -- the disagreement this module
#: was written to remove. cc-close-pr-merge-check already stripped quotes; this did not.
def unquote(value: str) -> str:
    """A YAML scalar's value, with matched surrounding quotes removed."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def is_nullish(value: str | None) -> bool:
    """True when `value` is absent or one of YAML's spellings of absent."""
    return value is None or value.strip().lower() in NULLISH


#: An opening `---` alone on the first line, and a closing `---` alone on a later line.
_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)^---[ \t]*\r?$", flags=re.DOTALL | re.MULTILINE)


def frontmatter(text: str) -> str:
    """The YAML frontmatter block, or "" when the note has none.

    A note's BODY is prose. It routinely contains lines that look like fields -- this change's own
    task note says "Add `pr_repo: <owner>/<name>`" in three places -- and reading those as
    declarations is not a parsing nicety: it lets body text qualify a task that its frontmatter
    never qualified.

    THE DELIMITERS MUST BE STANDALONE LINES. The first version tested `startswith("---")` and
    closed at the first `\n---` anywhere, so `---not-a-fence` opened a block and `---also-not`
    closed one: body text between two lines that merely BEGIN with three dashes was read as
    frontmatter. That is the forgery this function was added to stop, reachable through the
    function itself. Found in review.
    """
    m = _FRONTMATTER.match(text)
    if not m:
        return ""
    # CRLF is normalized here rather than tolerated in every field pattern. A stray \r left the
    # value unmatched, which reads as UNDECLARED -- so a note with Windows line endings would
    # silently never close, and the diagnosis would be "the gate is broken" rather than "the file
    # has carriage returns". One normalization beats four patterns each remembering to allow it.
    return m.group(1).replace("\r\n", "\n").replace("\r", "\n")


def same_repo(left: str, right: str) -> bool:
    """Whether two `owner/name` strings name the SAME GitHub repository.

    CASE-INSENSITIVE, because GitHub is. `Hapax-Systems/Reins` and `hapax-systems/reins` are one
    repository, and a plain `!=` treated them as different -- so a note whose pr_repo differed only
    in capitalization was read as belonging elsewhere and was never closed, silently, forever. A
    task stranded by capitalization is the fail-quiet family this module exists to remove, arriving
    through a comparison operator. Found in review.

    casefold() rather than lower(): casefold is the comparison-oriented mapping, and while these
    names are ASCII today, a comparison that is right for the wrong reason is one waiting to be
    wrong.
    """
    return left.strip().casefold() == right.strip().casefold()


def declared_pr_repo(text: str) -> str:
    """The repository a task note's FRONTMATTER declares, or "" if it declares none.

    FRONTMATTER ONLY. This searched the whole note, so a body line -- in prose, an example, or a
    fenced block -- could qualify a task whose frontmatter did not. Worse, cc-close-pr-merge-check
    reads frontmatter only, so the two gates would disagree about the same note: the watcher would
    consider it qualified and try to close it, the check would consider it undeclared and refuse.
    That disagreement between gates is the precise failure this change exists to remove, so having
    it reappear through a parsing shortcut would have undone the point. Found in review.

    "" means UNDECLARED, and callers must treat that as "we do not know" rather than defaulting to
    any repository. Defaulting an absent field to a wrong non-empty value is what closed an open
    PR's task twice; it fails in the direction that marks work DONE.
    """
    m = PR_REPO_PATTERN.search(frontmatter(text))
    if not m:
        return ""
    value = unquote(m.group(1))
    return "" if is_nullish(value) else value


#: `owner/name` — GitHub's own character set for both halves, and exactly one slash.
REPO_PATTERN = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


def is_well_formed_repo(value: str) -> bool:
    """True for `owner/name`. A malformed value must never reach a lookup.

    `gh` returns nothing useful for "garbage", and a caller that reads a failed lookup as
    "could not verify, allowing" turns a typo into an unverified closure. Shape is checkable
    without the network, so it is checked first and refused loudly.
    """
    return bool(REPO_PATTERN.match(value.strip()))
