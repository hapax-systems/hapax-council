"""Stage 2 regression pins — #155 anti-personification refactor.

The two files below were the live-violation offenders identified in the
research dossier (/tmp/cvs-research-155.md §3). After Stage 2 refactor
(conversational_policy._OPERATOR_STYLE rewritten, _CHILD_STYLE replaced
by _CHILD_POLICY; _EXPERIMENT_STYLE de-personified) and Stage 3 refactor
(both LOCAL-tier prompt sites in conversation_pipeline.py route through
compose_persona_prompt(role_id="partner-in-conversation", compressed=True)),
the linter MUST return zero findings. Drift here means the refactor was
reverted, bypassed, or a new personification slogan slipped in.

Plan: docs/superpowers/plans/2026-04-18-anti-personification-linter-plan.md
  Task 6 + Task 7
"""

from __future__ import annotations

from pathlib import Path

from shared.anti_personification_linter import lint_path, lint_text
from shared.persona_prompt_composer import compose_persona_prompt

_REPO_ROOT = Path(__file__).resolve().parents[2]


class TestStage2Regression:
    def test_conversational_policy_has_no_personification(self) -> None:
        path = _REPO_ROOT / "agents" / "hapax_daimonion" / "conversational_policy.py"
        findings = lint_path(path)
        assert findings == [], (
            "Stage 2 refactor should leave conversational_policy.py clean; "
            f"got {len(findings)} findings: {findings!r}"
        )

    def test_conversation_pipeline_has_no_personification(self) -> None:
        path = _REPO_ROOT / "agents" / "hapax_daimonion" / "conversation_pipeline.py"
        findings = lint_path(path)
        assert findings == [], (
            "Stage 3 refactor should leave conversation_pipeline.py clean; "
            f"got {len(findings)} findings: {findings!r}"
        )

    def test_compressed_persona_prompt_is_clean(self) -> None:
        """The shared compressed fragment every LOCAL-tier caller will receive
        must itself pass the linter — otherwise routing through it just moves
        the violation one hop downstream.
        """
        text = compose_persona_prompt(role_id="partner-in-conversation", compressed=True)
        findings = lint_text(text, path="<compressed>")
        assert findings == [], (
            f"compose_persona_prompt(compressed=True) must be linter-clean; got {findings!r}"
        )
