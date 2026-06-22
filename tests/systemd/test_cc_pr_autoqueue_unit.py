"""Regression pin for the AVSDLC intent-gate env-consistency (cutover gap #2).

The autoqueue unit and the in-session keystroke hook (pr-release-gate.sh) BOTH
evaluate ``evaluate_avsdlc_release_gate()``, which reads
``HAPAX_AVSDLC_REQUIRE_INTENT_PREDICATE``. The gate now resolves the flag from
the canonical hapax-secrets.env regardless of caller (see
``_env_or_secrets_flag``); this test pins that the autoqueue unit ALSO sources
that same secrets env directly — matching its sibling
``hapax-avsdlc-runtime-witness.service`` — so the unit's own process env is
consistent with every other hapax service and the flag is never process-blind.

cc-task: avsdlc-intent-cutover-envfile (CASE-AVSDLC-VISUAL-INTENT-20260622).
Self-contained per workspace test convention.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT = REPO_ROOT / "systemd" / "units" / "hapax-cc-pr-autoqueue.service"


def test_autoqueue_unit_sources_hapax_secrets_env() -> None:
    text = UNIT.read_text(encoding="utf-8")
    # Same source the witness daemon (hapax-avsdlc-runtime-witness.service) uses.
    assert "EnvironmentFile=-/run/user/1000/hapax-secrets.env" in text


def test_autoqueue_unit_runs_against_detached_deploy_tree() -> None:
    # The gate consumers evaluate against the CAPTURE-SAFE deploy tree, not a dev
    # worktree — pin that the unit's WorkingDirectory + ExecStart point there.
    text = UNIT.read_text(encoding="utf-8")
    assert "source-activation/worktree" in text
