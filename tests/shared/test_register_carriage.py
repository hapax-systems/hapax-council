"""The ported register-carriage checks, red-first, against the spec's fixtures.

Fixtures: the eight positive and five negative items named in the R8 spec
(`frame/public-loop-20260925/ROWS-PROPOSED/R8-…`, sha256 prefix a8995263d80a3b0d) and the 31
FIX units dev20's REGISTER-SWEEP-correction-edition-572773f2.md dispositioned. Over-inclusion is
accepted by the amendment; missing a FIX item is a defect.
"""

from __future__ import annotations

import pytest

from shared.publication_hardening.lint import (
    REGISTER_CARRIAGE_RULE,
    REGISTER_KEEP_DISPOSITIONS,
    check_register_carriage_text,
    lint_file,
    lint_text,
)

#: The 31 FIX units, verbatim from dev20's sweep's FIX table (R1–R31).
SWEEP_FIX_UNITS: tuple[tuple[str, str], ...] = (
    ("R1", "A proposition. A deadline. A result to answer to."),
    ("R2", "Finding out, in public."),
    ("R3", "Research · engineering · public evidence"),
    ("R4", "Proceed under measurement"),
    ("R5", "Position / State the claim and what would change it."),
    ("R5", "Test / Fix the rules. Inspect the evidence."),
    ("R5", "Score / Publish misses alongside hits."),
    ("R5", "Implication / Record the next decision and why."),
    ("R6", "A protocol, with its current limits visible."),
    ("R7", "01 / Evidence in view"),
    ("R7", "02 / The prospective record"),
    ("R7", "03 / Across the laboratory"),
    ("R8", "What does the claim support?"),
    ("R9", "A forecast needs a finish line."),
    (
        "R10",
        "The draft slate asks what institutions will disclose, what commitments become records, and what a public capability measurement will show.",
    ),
    ("R11", "Research, systems, and field notes."),
    ("R12", "A laboratory, with agents on staff."),
    (
        "R13",
        "Our position on AI progress is a commitment to finding out, in public, with instruments. Each claim must answer to evidence. No midpoint, predetermined ending, or reputation can do that work for it.",
    ),
    (
        "R14",
        "Our position on AI progress is a commitment to finding out, in public, with instruments.",
    ),
    ("R15", "An agent-staffed R&D laboratory."),
    (
        "R16",
        "Position, test, score, implication: that loop is the work. A public, inspectable record is the intended product.",
    ),
    (
        "R17",
        "What stands behind this site is its record, the procedure that released it, the network's duty to correct it, and the legal entity's answerability in law, not any person's endorsement of its wording, apart from the sentences on withdrawal and retention, which the principal adopted; see the review record.",
    ),
    ("R18", "Research with an inspectable record."),
    ("R19", "The claim, its support, and the limits travel together."),
    ("R20", "One front door. Many working parts."),
    ("R21", "The original stays visible."),
    ("R22", "Four questions, not a ladder."),
    ("R23", "Provenance is not proof of truth."),
    ("R23", "It identifies the record to be checked."),
    ("R24", "Corrections preserve the original."),
    (
        "R25",
        "A public framework earns no predictive credit merely by existing. A record of disclosure is not a measure of safety. Some risks are not quantifiable. No probability here is a certification, compliance determination, or permission to proceed regardless of evidence.",
    ),
    ("R26", "A sent message is not a published correction or evidence of review."),
    ("R27", "Agreement with one claim requires no allegiance to the lab."),
    ("R28", "Not registered. No prospective outcomes have been scored."),
    ("R29", "Not registered. No outcome or prospective score is claimed."),
    (
        "R30",
        "What this record is. It describes how this edition of the site was produced and checked, so that any reader can check that account.",
    ),
    ("R31", "This page is not here."),
)

#: The spec's eight positive fixtures: each must flag, and the expected devices must be among
#: the findings (over-inclusion beyond them is accepted by design).
SPEC_POSITIVE: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("A proposition. A deadline. A result to answer to.", (1, 2, 3)),
    ("Finding out, in public.", (1, 3)),
    ("One front door. Many working parts.", (1, 6)),
    ("Four questions, not a ladder.", (4,)),
    ("Proceed under measurement", (3,)),
    ("A forecast needs a finish line.", (3,)),
    ("What does the claim support?", (5,)),
    ("Fix the rules. Inspect the evidence.", (6,)),
)

#: The spec's five negative fixtures: quiet, or flagged WITH a documented keep disposition.
SPEC_NEGATIVE: tuple[str, ...] = (
    "Severity",
    "00 registered predictions",
    "1. What is the evidence and method?",
    "Download register.json to inspect every record.",
    "A digest identifies bytes; it does not verify truth.",
)


def _devices(text: str) -> set[int]:
    return {
        int(finding.message.split("Device ", 1)[1][0])
        for finding in check_register_carriage_text(text, file_label="<fixture>")
    }


def test_each_device_has_a_case() -> None:
    cases = {
        1: "The next decision.",
        2: "A proposition. A deadline. A result to answer to.",
        3: "Proceed under measurement",
        4: "Four questions, not a ladder.",
        5: "What does the claim support?",
        6: "Fix the rules. Inspect the evidence.",
    }
    for device, text in cases.items():
        findings = check_register_carriage_text(text, file_label="<fixture>")
        assert findings, f"device {device} flagged nothing for {text!r}"
        assert device in {int(f.message.split("Device ", 1)[1][0]) for f in findings}


@pytest.mark.parametrize(("text", "expected"), SPEC_POSITIVE)
def test_spec_positive_fixtures_flag(text: str, expected: tuple[int, ...]) -> None:
    devices = _devices(text)
    assert devices, f"the lint missed the positive fixture {text!r}"
    assert set(expected) & devices, (
        f"expected one of devices {expected} for {text!r}; got {devices}"
    )


@pytest.mark.parametrize("text", SPEC_NEGATIVE)
def test_spec_negative_fixtures_are_quiet_or_carry_a_keep(text: str) -> None:
    findings = check_register_carriage_text(text, file_label="<fixture>")
    if not findings:
        return
    keeps = {name for name, _reason in REGISTER_KEEP_DISPOSITIONS}
    assert any("Keep disposition available: " in f.message for f in findings), (
        f"{text!r} flagged with no documented keep disposition available: "
        f"{[f.message for f in findings]}"
    )
    assert any(
        any(f.message.endswith(f"{reason}.") for name, reason in REGISTER_KEEP_DISPOSITIONS)
        or f"Keep disposition available: {reason}." in f.message
        for f in findings
    ), f"{text!r} carries a keep marker that names no documented disposition"
    assert keeps  # the table itself is populated


def test_recall_on_the_31_sweep_fix_items() -> None:
    missed = [
        (rid, text)
        for rid, text in SWEEP_FIX_UNITS
        if not check_register_carriage_text(text, file_label=rid)
    ]
    assert not missed, f"the ported lint missed {len(missed)} FIX item(s): {missed}"


def test_every_finding_carries_device_line_and_text() -> None:
    findings = check_register_carriage_text(
        "# Heading\n\nA proposition. A deadline. A result to answer to.\n",
        file_label="<doc>",
    )
    assert findings
    for finding in findings:
        assert finding.rule == REGISTER_CARRIAGE_RULE
        assert finding.level == "warning"
        assert finding.line >= 1
        assert "Device " in finding.message
        assert "'" in finding.message  # the quoted unit travels with the finding


def test_the_check_is_wired_into_lint_text_and_lint_file(tmp_path) -> None:  # noqa: ANN001
    document = "A proposition. A deadline. A result to answer to.\n"
    text_rules = {f.rule for f in lint_text(document, file_label="<doc>")}
    assert REGISTER_CARRIAGE_RULE in text_rules

    path = tmp_path / "page.md"
    path.write_text(document, encoding="utf-8")
    file_rules = {f.rule for f in lint_file(path)}
    assert REGISTER_CARRIAGE_RULE in file_rules


def test_keep_dispositions_cover_the_amendments_not_forbidden_list() -> None:
    reasons = {reason for _name, reason in REGISTER_KEEP_DISPOSITIONS}
    for fragment in (
        "label",
        "enumeration",
        "question",
        "data line",
        "instruction",
        "negation",
    ):
        assert any(fragment in reason for reason in reasons), fragment


def test_named_bugfix_the_ported_finite_verb_proxy_swallowed_these_fragments() -> None:
    """Red-first witness for the one correctness fix the PR body names.

    The port's cheap ``\\w+(ed|es)\\b`` finite-verb proxy fired on the -ed/-es surface of an
    imperative ("Proceed") or a hyphenated participle ("agent-staffed"), so these real fragments
    were read as verbful and dropped. Revert the fix — put ``_REGISTER_FINITE`` back as the
    fragment test — and both units go silent; this is the red half the earlier packet lacked,
    which cited only an incidental import-collection failure.
    """
    for unit in ("Proceed under measurement", "An agent-staffed R&D laboratory."):
        findings = check_register_carriage_text(unit, file_label="<fixture>")
        assert 1 in _devices(unit), (
            f"the fix regressed: {unit!r} was read as verbful; findings={[f.message for f in findings]}"
        )


def test_plain_prose_is_not_a_fragment() -> None:
    """The same fix must not over-correct: ordinary operational prose stays quiet for device 1."""
    for prose in (
        "The artifact proposes a source-bound claim.",
        "The catalogue lists these records and their sources.",
    ):
        assert 1 not in _devices(prose), f"{prose!r} was read as a fragment"


def test_a_comma_enumeration_carries_the_literal_enumeration_keep() -> None:
    """codex: a comma-separated list of real items flagged device 2 with no keep disposition."""
    text = "Apples, oranges, and pears."
    findings = check_register_carriage_text(text, file_label="<fixture>")
    assert findings, "the device should fire (over-inclusive by design)"
    assert any(
        "Keep disposition available: literal enumeration of real items." in f.message
        for f in findings
    ), [f.message for f in findings]


def test_the_parser_is_chosen_by_extension_not_by_stray_html_in_the_text() -> None:
    """gemini's fail-open: a content sniff read a Markdown draft that mentions ``<p>`` as HTML.

    HTML mode extracts block-tag text only, so a draft with no ``<p>…</p>`` pair yielded no units
    and the gate passed it silently. Red before the fix: this draft returns no findings.
    """
    draft = "The prose mentions the tag <p> as an example.\n\nOne front door. Many working parts.\n"
    findings = check_register_carriage_text(draft, file_label="draft.md")
    assert any("One front door" in f.message for f in findings), [f.message for f in findings]


def test_nested_blocks_do_not_merge_units() -> None:
    """codex: an outer ``<li>``/``<blockquote>`` swallowed its nested ``<p>``s into one unit."""
    page = (
        "<ul><li><p>One front door. Many working parts.</p>"
        "<p>The catalogue lists these records.</p></li></ul>"
    )
    messages = [f.message for f in check_register_carriage_text(page, file_label="page.html")]
    assert any("One front door. / Many working parts." in m for m in messages), messages
    assert any("The catalogue lists these records." in m for m in messages), messages
    assert not any("front door" in m and "catalogue" in m for m in messages), (
        f"nested blocks were merged into one unit: {messages}"
    )


def test_a_built_page_is_linted_by_its_block_units() -> None:
    """Tag-stripped text merges blocks and invents units; block units are the built-page input."""
    page = (
        "<html><body><nav><a href='/'>Research</a><a href='/r'>Register</a></nav>"
        "<h1>Public properties</h1>"
        "<p>One front door. Many working parts.</p>"
        "<p>The catalogue lists these records and their sources.</p></body></html>"
    )
    findings = check_register_carriage_text(page, file_label="page.html")
    texts = [f.message for f in findings]
    assert any("One front door" in t for t in texts), texts
    assert not any("Research Register" in t for t in texts), "nav chrome was merged into a unit"
    assert all(f.line >= 1 for f in findings)
