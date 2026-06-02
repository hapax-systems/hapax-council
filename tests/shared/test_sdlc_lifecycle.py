"""Unit tests for the SDLC lifecycle vocabulary SSOT (shared/sdlc_lifecycle.py).

Pins the three coordination-plane vocabularies so the gate, dispatch, and
autoqueue provably consume ONE source: the status frozensets, the named
dispatch-plane PR-action vocabulary, and the dispatchable-status set. This is
the additive, behavior-preserving slice of bb-status-ssot — the canonical
status->stage projection is intentionally NOT shipped here (a pre-flight over
the live vault showed status->stage is not a function; see
~/Documents/Personal/30-areas/hapax/bb-status-ssot-preflight-stop-2026-06-02.md).
"""

from __future__ import annotations

import ast
from pathlib import Path

from shared.sdlc_lifecycle import PR_ACTIONS

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestPrActions:
    def test_pr_actions_names_the_seven_dispatch_plane_actions(self) -> None:
        assert (
            frozenset(
                {
                    "queue",
                    "enable_auto_merge",
                    "disable_auto_merge",
                    "dequeue",
                    "already_queued",
                    "already_auto_merge_enabled",
                    "blocked",
                }
            )
            == PR_ACTIONS
        )

    def test_classify_pr_emits_only_pr_actions(self) -> None:
        """Totality: every action string classify_pr can emit is in PR_ACTIONS.

        Source-introspection (no import of the heavy autoqueue module): parse the
        ``classify_pr`` function body for ``action=<literal>`` and assert the set
        is covered. A new action added without updating PR_ACTIONS fails here.
        """

        src = (REPO_ROOT / "scripts" / "cc-pr-autoqueue.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        classify = next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == "classify_pr"
            ),
            None,
        )
        assert classify is not None, "classify_pr not found (autoqueue source drift)"
        emitted = {
            kw.value.value
            for sub in ast.walk(classify)
            if isinstance(sub, ast.Call)
            for kw in sub.keywords
            if kw.arg == "action"
            and isinstance(kw.value, ast.Constant)
            and isinstance(kw.value.value, str)
        }
        assert emitted, "no action= literals found in classify_pr (parser drift)"
        assert emitted <= PR_ACTIONS, (
            f"classify_pr emits actions outside PR_ACTIONS: {emitted - PR_ACTIONS}"
        )
