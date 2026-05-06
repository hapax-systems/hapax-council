"""Regression tests for shared/anti_personification_linter.py.

Companion to tests/axioms/test_persona_description.py and
tests/studio_compositor/test_posture_vocabulary_hygiene.py. Enforces the
Phase 7 discriminator from the redesign spec §6: analogies that describe
architectural fact pass; analogies that claim inner life fail.

Source: docs/superpowers/specs/2026-04-18-anti-personification-linter-design.md
Plan:   docs/superpowers/plans/2026-04-18-anti-personification-linter-plan.md
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.anti_personification_linter import (
    Finding,
    _load_file_scope_allowlist,
    lint_path,
    lint_text,
)

# ---------------------------------------------------------------------------
# Deny-list: canonical offenders each produce at least one Finding
# ---------------------------------------------------------------------------

CANONICAL_OFFENDERS: list[tuple[str, str]] = [
    # (rule_id suffix, offender text)
    ("inner_life_first_person.feel_verb", "I feel wonder at this."),
    ("inner_life_first_person.belief_verb", "I wondered if it matters."),
    ("inner_life_first_person.belief_verb", "I trust this source."),
    ("inner_life_first_person.belief_verb", "I remember this moment."),
    ("inner_life_first_person.belief_verb", "I prefer the second ranking."),
    ("inner_life_first_person.im_affect", "I'm excited about this."),
    ("inner_life_first_person.affect_verb", "I love this beat."),
    ("inner_life_first_person.my_inner", "my feelings on this are mixed."),
    ("inner_life_first_person.my_inner", "my taste says this belongs in S-tier."),
    ("inner_life_first_person.my_inner", "my memory of this source is clear."),
    ("second_person_inner_life.you_feel", "you feel the room shift."),
    ("second_person_inner_life.your_inner", "your personality shines."),
    ("second_person_inner_life.you_have_personality", "you have personality here."),
    ("second_person_inner_life.you_are_affect", "you are warm and kind."),
    ("second_person_inner_life.be_affect", "be yourself always."),
    ("personification_nouns.personality_noun", "Document your personality."),
    ("personification_nouns.archetype_noun", "Your archetype is Socrates."),
    ("personification_nouns.dry_wit", "Shows dry wit in replies."),
    ("personification_nouns.genuine_curiosity", "Shows genuine curiosity about X."),
    ("personification_nouns.intellectual_honesty", "Shows intellectual honesty here."),
    ("personification_nouns.warm_but_concise", "Be warm but concise please."),
    ("personification_nouns.friendly_not_chatty", "Be friendly without being chatty."),
    ("personification_nouns.hapax_inner", "Hapax feels wonder about this."),
    ("personification_nouns.hapax_inner", "Hapax trusts this thinker."),
    ("personification_nouns.hapax_inner", "Hapax finds this framing hollow."),
    ("personification_nouns.hapax_inner", "Hapax remembers the source."),
    ("anthropic_pronouns.hapax_gendered", "Hapax, he is ready."),
]


@pytest.mark.parametrize(("rule_id", "text"), CANONICAL_OFFENDERS)
def test_canonical_offender_produces_finding(rule_id: str, text: str) -> None:
    findings = lint_text(text)
    assert findings, f"no finding for offender: {text!r}"
    assert any(f.rule_id == rule_id for f in findings), (
        f"expected rule {rule_id} not among {[f.rule_id for f in findings]!r} "
        f"for offender: {text!r}"
    )


# ---------------------------------------------------------------------------
# Clean analogues: zero findings
# ---------------------------------------------------------------------------

CANONICAL_CLEAN: list[str] = [
    "SEEKING stance halves the recruitment threshold.",
    "Hapax IS an executive-function prosthetic for a single operator.",
    "The recruitment threshold drops when boredom rises.",
    "Curious translates the SEEKING architectural state.",
    "By analogy, curiosity pressure means the recruitment threshold drops.",
    "Hapax rejects that framing because the cited source changes the claim scope.",
    "The segment voice can be forceful without claiming a human feeling state.",
    "Stimmung dimensions modulate the affordance pipeline score.",
    "Qdrant stores the affordances collection for retrieval.",
]


@pytest.mark.parametrize("text", CANONICAL_CLEAN)
def test_clean_analogues_produce_no_findings(text: str) -> None:
    findings = lint_text(text)
    assert findings == [], f"false positive on clean text {text!r}: {findings!r}"


# ---------------------------------------------------------------------------
# Finding shape
# ---------------------------------------------------------------------------


def test_finding_has_required_fields() -> None:
    findings = lint_text("you have personality here.", path="example.md")
    assert findings
    f = findings[0]
    assert isinstance(f, Finding)
    assert f.file_path == "example.md"
    assert f.line == 1
    assert f.col >= 0
    assert f.rule_id.startswith("second_person_inner_life.")
    assert "personality" in f.matched_text
    assert f.severity == "warn"


# ---------------------------------------------------------------------------
# Context-window carve-out
# ---------------------------------------------------------------------------


def test_rejection_keyword_NOT_suppresses() -> None:
    text = "Do NOT write 'I feel wonder' in persona docs."
    assert lint_text(text) == []


def test_forbidden_keyword_suppresses() -> None:
    text = "The following phrasing is forbidden: 'you have personality'."
    assert lint_text(text) == []


def test_rejected_keyword_suppresses() -> None:
    text = "This line is rejected: Hapax feels wonder about beats."
    assert lint_text(text) == []


def test_drift_keyword_suppresses() -> None:
    text = "Persona drift example — 'I'm excited about this.' must not ship."
    assert lint_text(text) == []


def test_rejection_window_is_bounded() -> None:
    # Filler >200 chars pushes the keyword outside the window → hit reported.
    filler = "x" * 300
    text = f"I feel wonder. {filler} forbidden"
    findings = lint_text(text)
    assert any(f.rule_id.endswith(".feel_verb") for f in findings), (
        f"filler>200 chars should NOT suppress; got {findings!r}"
    )


# ---------------------------------------------------------------------------
# Speaker-prefix carve-out
# ---------------------------------------------------------------------------


def test_operator_speaker_prefix_passes() -> None:
    text = "operator: I feel weird today.\nhapax: architectural state noted."
    findings = lint_text(text)
    assert not any(f.line == 1 for f in findings), (
        f"operator-prefixed line 1 should be carved out: {findings!r}"
    )


# ---------------------------------------------------------------------------
# SEEKING-stance translation carve-out
# ---------------------------------------------------------------------------


def test_seeking_stance_translation_passes() -> None:
    text = "'curious' is a translation label for the SEEKING stance, not an inner claim."
    assert lint_text(text) == []


# ---------------------------------------------------------------------------
# File-level pragma
# ---------------------------------------------------------------------------


def test_markdown_pragma_suppresses(tmp_path: Path) -> None:
    md = tmp_path / "pragma_sample.md"
    md.write_text("<!-- anti-personification: allow -->\n\nyou have personality.\n")
    assert lint_path(md) == []


def test_python_pragma_suppresses(tmp_path: Path) -> None:
    py = tmp_path / "pragma_sample.py"
    py.write_text(
        "# anti-personification: allow\n"
        '"""Module-level docstring."""\n'
        'X = "you have personality here."\n'
    )
    assert lint_path(py) == []


# ---------------------------------------------------------------------------
# Python AST: _LEGACY_* literals are skipped
# ---------------------------------------------------------------------------


def test_legacy_prefix_literals_skipped(tmp_path: Path) -> None:
    py = tmp_path / "legacy_sample.py"
    py.write_text(
        '"""Module."""\n'
        '_LEGACY_SYSTEM_PROMPT = "you have personality: dry wit."\n'
        '_ACTIVE = "Hapax is an executive-function prosthetic."\n'
    )
    assert lint_path(py) == []


def test_non_legacy_literal_is_scanned(tmp_path: Path) -> None:
    py = tmp_path / "active_sample.py"
    py.write_text('"""Module."""\nACTIVE_PROMPT = "you have personality: dry wit."\n')
    findings = lint_path(py)
    assert findings, "non-legacy top-level string must be scanned"
    assert any(f.rule_id.endswith(".you_have_personality") for f in findings)


# ---------------------------------------------------------------------------
# Markdown fenced code-blocks are not scanned
# ---------------------------------------------------------------------------


def test_markdown_fenced_block_not_scanned(tmp_path: Path) -> None:
    md = tmp_path / "fenced.md"
    md.write_text(
        "# Title\n"
        "\n"
        "Architectural prose passes cleanly.\n"
        "\n"
        "```bash\n"
        "echo 'you have personality'\n"
        "```\n"
    )
    findings = lint_path(md)
    assert findings == [], f"fenced block should not be scanned: {findings!r}"


def test_markdown_fenced_block_not_scanned_but_prose_still_is(tmp_path: Path) -> None:
    md = tmp_path / "mixed.md"
    md.write_text(
        "# Title\n"
        "\n"
        "you have personality.\n"  # prose — should fire
        "\n"
        "```bash\n"
        "echo 'you have personality'\n"  # fenced — should NOT fire
        "```\n"
    )
    findings = lint_path(md)
    # The prose line fires two overlapping rules (you_have_personality +
    # personality_noun); that is correct deny-list behaviour. Both findings
    # must live on the prose line — zero hits inside the fenced block.
    assert findings, f"expected at least one finding on prose line; got {findings!r}"
    assert all(f.line == 3 for f in findings), (
        f"all findings must come from the prose line, not the fence: {findings!r}"
    )
    assert any(f.rule_id.endswith(".you_have_personality") for f in findings)


# ---------------------------------------------------------------------------
# YAML frontmatter / body is scanned
# ---------------------------------------------------------------------------


def test_yaml_body_is_scanned(tmp_path: Path) -> None:
    y = tmp_path / "sample.yaml"
    y.write_text("roles:\n  - name: companion\n    description: you have personality here.\n")
    findings = lint_path(y)
    assert findings, "YAML scalar should be scanned"
    assert any(f.rule_id.endswith(".you_have_personality") for f in findings)


def test_markdown_frontmatter_is_scanned(tmp_path: Path) -> None:
    md = tmp_path / "frontmatter.md"
    md.write_text(
        "---\ntitle: sample\ndescription: you have personality here.\n---\n\nBody prose.\n"
    )
    findings = lint_path(md)
    assert findings, "Markdown YAML frontmatter must be scanned"
    assert any(f.rule_id.endswith(".you_have_personality") for f in findings)


# ---------------------------------------------------------------------------
# Path-level allowlist (YAML)
# ---------------------------------------------------------------------------


def test_allowlist_yaml_suppresses_by_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    suppressed = tmp_path / "quarantined.md"
    suppressed.write_text("you have personality here.\n")
    # Sanity: the file does produce a finding without the allowlist.
    monkeypatch.delenv("HAPAX_ANTI_PERSONIFICATION_ALLOWLIST", raising=False)

    allowlist = tmp_path / "allowlist.yaml"
    allowlist.write_text(
        "suppressions:\n"
        f"  - path: {suppressed.resolve()}\n"
        "    reason: 'superseded spec, provenance only'\n"
        "    scope: file\n"
    )
    monkeypatch.setenv("HAPAX_ANTI_PERSONIFICATION_ALLOWLIST", str(allowlist))
    # Clear any cached allowlist state between tests — current impl reloads.
    assert lint_path(suppressed) == []


def test_load_file_scope_allowlist_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "HAPAX_ANTI_PERSONIFICATION_ALLOWLIST",
        str(tmp_path / "does-not-exist.yaml"),
    )
    assert _load_file_scope_allowlist() == set()
