"""The agentgov licence must be machine-readable, and that claim must be testable.

The PR asserted "say the licence where a machine can read it" and shipped no way to check it.
A licensing claim that only a human can verify is the same class of defect as a guard nobody
runs: it is correct on the day it lands and silently wrong afterwards.

Scope note: this covers `packages/agentgov/LICENSE` only. The council README's SPDX line was
removed from this change because the governing task records `mutation_surface: source` and
`docs_mutation_authorized: false`, and a public documentation surface is not authorized by
source-mutation authority. Both reviewer families raised that independently as a critical.
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


def test_the_licence_states_no_copyright_holder_this_change_did_not_verify() -> None:
    """The ownership line is deliberately untouched.

    An earlier revision of this PR reassigned the copyright holder. Both reviewer families
    called that an ownership determination unsupported by anything in the diff, and they were
    right — the repository names three different holders across `LICENSE`, `CITATION.cff` and
    `.zenodo.json`, so the change introduced the inconsistency it claimed to remove.

    This test pins the holder as it stands so a future "tidy-up" has to argue with a failing
    test rather than a comment.
    """
    text = AGENTGOV_LICENSE.read_text(encoding="utf-8")

    assert "Copyright (c) 2026 Ryan Lee" in text
