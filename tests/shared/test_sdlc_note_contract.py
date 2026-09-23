"""The note contract is a leaf, and its frozen predecessors stay unreachable.

``shared/sdlc_lifecycle.py`` is a Gate 0A canon byte-hashed source, so the
corrected definitions live in ``shared/sdlc_note_contract.py`` and the canon
module keeps its pre-correction copies under the same names. That duplication is
the price of the freeze, and it is only safe while nothing imports the frozen
side — which is a checkable property, not a convention, so it is checked here.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from shared import sdlc_lifecycle, sdlc_note_contract

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Names the canon module still defines but whose live definition moved here.
#: Importing one of these from ``shared.sdlc_lifecycle`` gets the frozen
#: behaviour: the fence scan that reads ``---extra: abc`` as a closing fence,
#: the floor-only receipt predicate that let a row declaring
#: ``independent_review_required`` close unreviewed, and the release-arm writer
#: that logged success without arming.
SUPERSEDED_NAMES = frozenset(
    {
        "acceptance_receipt_blockers",
        "apply_release_auto_arm",
        "frontmatter_from_text",
        "requires_acceptance_receipt",
    }
)

#: Source trees where a stale import would reach production. Tests are included:
#: a test asserting against the frozen copy would pass while the live path drifts.
SEARCH_ROOTS = ("agents", "logos", "packages", "scripts", "shared", "tests")

SKIP_FILES = frozenset(
    {
        # Defines them; the whole point.
        REPO_ROOT / "shared" / "sdlc_lifecycle.py",
        # Names them as strings to assert this very property.
        Path(__file__).resolve(),
    }
)


def _python_files() -> list[Path]:
    files: list[Path] = []
    for root in SEARCH_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            if path.resolve() not in SKIP_FILES and ".venv" not in path.parts:
                files.append(path)
    return files


def _superseded_imports(path: Path) -> set[str]:
    """Names imported FROM ``shared.sdlc_lifecycle`` that have moved."""

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "shared.sdlc_lifecycle":
            found |= {alias.name for alias in node.names} & SUPERSEDED_NAMES
    return found


def test_no_module_imports_the_superseded_definitions() -> None:
    offenders = {
        str(path.relative_to(REPO_ROOT)): sorted(names)
        for path in _python_files()
        if (names := _superseded_imports(path))
    }

    assert offenders == {}, (
        "these import the FROZEN pre-correction definitions from the canon module; "
        f"import them from shared.sdlc_note_contract instead: {offenders}"
    )


@pytest.mark.parametrize("name", sorted(SUPERSEDED_NAMES))
def test_the_superseded_names_really_are_still_defined_in_the_canon_module(name: str) -> None:
    """Otherwise the guard above passes vacuously.

    If a future canon supersession deletes these, this test fails and says so —
    at which point the guard has nothing left to protect and both should go.
    """

    assert hasattr(sdlc_lifecycle, name)
    assert hasattr(sdlc_note_contract, name)


def test_the_two_definitions_actually_differ() -> None:
    """The guard is only worth having while the frozen copies are wrong.

    Read on the note shape the whole PR turns on: a legal ``---extra: abc``
    mapping key. The canon parser truncates the block there and loses every
    field below it; this module's does not.
    """

    note = (
        "---\n"
        "task_id: t\n"
        "---extra: abc\n"
        "quality_floor: verification_receipt\n"
        "review_requirement:\n"
        "  independent_review_required: true\n"
        "---\n"
        "\n"
        "body\n"
    )

    frozen = sdlc_lifecycle.frontmatter_from_text(note)
    live = sdlc_note_contract.frontmatter_from_text(note)

    assert "review_requirement" not in frozen
    assert live["review_requirement"] == {"independent_review_required": True}
    assert sdlc_lifecycle.requires_acceptance_receipt(frozen) is False
    assert sdlc_note_contract.requires_acceptance_receipt(live) is True


def test_the_canonical_parser_depends_on_this_leaf_not_the_other_way() -> None:
    """Direction stated and pinned, so the next editor does not re-derive it.

    ``shared/frontmatter.py`` reaches ``shared.governance.consent_label`` and
    therefore AGENTGOV; ``scripts/cc-close`` runs the close gate under a bare
    ``python3``. So the fence grammar lives in the leaf and the canonical parser
    imports it, never the reverse.
    """

    contract = ast.parse((REPO_ROOT / "shared" / "sdlc_note_contract.py").read_text("utf-8"))
    contract_imports = {
        node.module for node in ast.walk(contract) if isinstance(node, ast.ImportFrom)
    }
    assert "shared.frontmatter" not in contract_imports

    canonical = ast.parse((REPO_ROOT / "shared" / "frontmatter.py").read_text("utf-8"))
    canonical_imports = {
        node.module for node in ast.walk(canonical) if isinstance(node, ast.ImportFrom)
    }
    assert "shared.sdlc_note_contract" in canonical_imports
    assert "shared.sdlc_lifecycle" not in canonical_imports
