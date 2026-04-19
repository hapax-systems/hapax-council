"""Fail-mode tests — #155 Stage 4 flip.

Verifies the ``lint_mode`` parameter on ``lint_text`` / ``lint_path`` and
the ``AntiPersonificationViolation`` exception. Backward compatibility:
``lint_mode="warn"`` (default) must continue to return findings without
raising.

Spec: docs/superpowers/specs/2026-04-18-anti-personification-linter-design.md
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.anti_personification_linter import (
    AntiPersonificationViolation,
    Finding,
    lint_path,
    lint_text,
)

# ---------------------------------------------------------------------------
# fail mode raises with populated findings
# ---------------------------------------------------------------------------


def test_fail_mode_raises_with_populated_findings() -> None:
    text = "you have personality here."
    with pytest.raises(AntiPersonificationViolation) as exc:
        lint_text(text, path="<t>", lint_mode="fail")
    assert exc.value.findings, "violation must carry findings list"
    assert all(isinstance(f, Finding) for f in exc.value.findings)
    assert any(f.rule_id.endswith(".you_have_personality") for f in exc.value.findings)
    # severity flips to 'error' in fail mode so consumers can distinguish.
    assert all(f.severity == "error" for f in exc.value.findings)


def test_fail_mode_clean_input_returns_empty_no_raise() -> None:
    text = "SEEKING stance halves the recruitment threshold."
    out = lint_text(text, path="<t>", lint_mode="fail")
    assert out == []


# ---------------------------------------------------------------------------
# backward compat: warn mode default
# ---------------------------------------------------------------------------


def test_warn_mode_default_returns_findings_no_raise() -> None:
    text = "you have personality here."
    # No lint_mode — default is warn.
    findings = lint_text(text, path="<t>")
    assert findings, "warn mode must still surface findings by default"
    assert all(f.severity == "warn" for f in findings)


def test_warn_mode_explicit_returns_findings_no_raise() -> None:
    text = "I feel wonder at this."
    findings = lint_text(text, path="<t>", lint_mode="warn")
    assert findings, "explicit warn mode must return findings list"
    # Explicit warn mode must NOT raise.


# ---------------------------------------------------------------------------
# all 4 deny-list pattern families raise in fail mode
# ---------------------------------------------------------------------------


FAMILY_OFFENDERS: list[tuple[str, str]] = [
    ("inner_life_first_person", "I feel wonder at this."),
    ("second_person_inner_life", "you have personality here."),
    ("personification_nouns", "Shows dry wit in replies."),
    ("anthropic_pronouns", "Hapax, he is ready."),
]


@pytest.mark.parametrize(("family", "text"), FAMILY_OFFENDERS)
def test_each_deny_family_triggers_fail_mode(family: str, text: str) -> None:
    with pytest.raises(AntiPersonificationViolation) as exc:
        lint_text(text, path="<t>", lint_mode="fail")
    assert any(f.rule_id.startswith(f"{family}.") for f in exc.value.findings), (
        f"expected family {family} among {[f.rule_id for f in exc.value.findings]!r}"
    )


# ---------------------------------------------------------------------------
# Carve-out windows do NOT trigger raise in fail mode
# ---------------------------------------------------------------------------


def test_rejection_keyword_NOT_suppresses_in_fail_mode() -> None:
    text = "Do NOT write 'I feel wonder' in persona docs."
    # LRR-mentioned governance text: rejection keywords carve out the hit.
    assert lint_text(text, path="<t>", lint_mode="fail") == []


def test_forbidden_keyword_suppresses_in_fail_mode() -> None:
    text = "The following phrasing is forbidden: 'you have personality'."
    assert lint_text(text, path="<t>", lint_mode="fail") == []


def test_rejected_keyword_suppresses_in_fail_mode() -> None:
    text = "This line is rejected: Hapax feels wonder about beats."
    assert lint_text(text, path="<t>", lint_mode="fail") == []


def test_drift_keyword_suppresses_in_fail_mode() -> None:
    text = "Persona drift example — 'I'm excited about this.' must not ship."
    assert lint_text(text, path="<t>", lint_mode="fail") == []


def test_seeking_stance_translation_suppresses_in_fail_mode() -> None:
    text = "'curious' is a translation label for the SEEKING stance, not an inner claim."
    assert lint_text(text, path="<t>", lint_mode="fail") == []


def test_operator_speaker_prefix_suppresses_in_fail_mode() -> None:
    text = "operator: I feel weird today.\nhapax: architectural state noted."
    # operator-prefixed quotation is carved out in both modes; line 2 has
    # no deny-list hit.
    assert lint_text(text, path="<t>", lint_mode="fail") == []


# ---------------------------------------------------------------------------
# lint_path fail mode
# ---------------------------------------------------------------------------


def test_lint_path_fail_mode_raises(tmp_path: Path) -> None:
    py = tmp_path / "offender.py"
    py.write_text('"""Module."""\nACTIVE = "you have personality here."\n')
    with pytest.raises(AntiPersonificationViolation) as exc:
        lint_path(py, lint_mode="fail")
    assert exc.value.findings


def test_lint_path_fail_mode_clean_returns_empty(tmp_path: Path) -> None:
    py = tmp_path / "clean.py"
    py.write_text('"""Module."""\nACTIVE = "Hapax is an executive-function prosthetic."\n')
    assert lint_path(py, lint_mode="fail") == []


def test_lint_path_warn_mode_default_returns_findings(tmp_path: Path) -> None:
    py = tmp_path / "offender.py"
    py.write_text('"""Module."""\nACTIVE = "you have personality here."\n')
    # Default lint_mode="warn" — backward compat regression pin.
    findings = lint_path(py)
    assert findings
    assert all(f.severity == "warn" for f in findings)


# ---------------------------------------------------------------------------
# Exception shape
# ---------------------------------------------------------------------------


def test_violation_str_includes_preview() -> None:
    with pytest.raises(AntiPersonificationViolation) as exc:
        lint_text("you have personality here.", path="<t>", lint_mode="fail")
    msg = str(exc.value)
    assert "anti-personification" in msg
    assert "you have personality" in msg


def test_violation_findings_attribute_is_list() -> None:
    try:
        lint_text("I feel wonder.", path="<t>", lint_mode="fail")
    except AntiPersonificationViolation as e:
        assert isinstance(e.findings, list)
        assert e.findings
        return
    raise AssertionError("expected AntiPersonificationViolation")
