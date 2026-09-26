"""The agentgov licence must be machine-readable, and that claim must be testable.

A licensing claim only a human can verify is the same class of defect as a guard nobody runs:
correct on the day it lands, silently wrong afterwards. These tests make the claim checkable.

Scope: `packages/agentgov/LICENSE`. Documentation surfaces are out of scope for this module —
they are governed by a different authority (`docs_mutation_authorized`) and belong to whatever
task holds it.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTGOV_LICENSE = REPO_ROOT / "packages" / "agentgov" / "LICENSE"

#: SPDX short-form identifier syntax, per the SPDX specification's licence expression grammar.
SPDX_LINE_RE = re.compile(r"^SPDX-License-Identifier:\s*(?P<id>[A-Za-z0-9.\-+()\s]+?)\s*$", re.M)

#: The identifier agentgov actually ships under. A test that accepted any identifier would
#: pass if someone relabelled MIT code as proprietary, which is the mistake worth catching.
EXPECTED_SPDX_ID = "MIT"


def test_agentgov_licence_declares_a_machine_readable_spdx_identifier() -> None:
    text = AGENTGOV_LICENSE.read_text(encoding="utf-8")

    match = SPDX_LINE_RE.search(text)

    assert match is not None, (
        "packages/agentgov/LICENSE carries no SPDX-License-Identifier line; "
        "the machine-readable licensing claim is unverifiable without one"
    )
    assert match.group("id") == EXPECTED_SPDX_ID


def test_the_spdx_identifier_agrees_with_the_licence_text_beside_it() -> None:
    """An identifier that disagrees with its own licence body is worse than none.

    This is the whole point of the change: the identifier is checkable *against the text it
    sits next to*, which is what makes it evidence rather than an assertion.
    """
    text = AGENTGOV_LICENSE.read_text(encoding="utf-8")

    assert text.lstrip().startswith("MIT License"), "licence body is not MIT"
    assert "Permission is hereby granted, free of charge" in text, "MIT grant clause missing"
    assert SPDX_LINE_RE.search(text).group("id") == EXPECTED_SPDX_ID  # type: ignore[union-attr]


def test_adding_an_spdx_identifier_leaves_the_copyright_line_intact() -> None:
    """Adding a licence *identifier* must not become an ownership *determination*.

    Those are different acts with different evidence requirements: which terms apply is
    checkable against the licence text sitting beside it, while who holds the copyright is not
    checkable from anything in this repository. This test pins the boundary between them — it
    asserts the SPDX addition did not disturb the holder, not that any particular holder is
    correct.
    """
    text = AGENTGOV_LICENSE.read_text(encoding="utf-8")

    copyright_lines = [ln for ln in text.splitlines() if ln.startswith("Copyright (c)")]

    assert len(copyright_lines) == 1, "the SPDX addition must not add or remove a copyright line"
    assert SPDX_LINE_RE.search(text) is not None
