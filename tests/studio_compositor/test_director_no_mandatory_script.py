"""Regression pin for 2026-04-23 Gemini-audit Phase 1.

The Showrunner subsystem that Gemini shipped in commit 7b96fccb7
(reverted in this phase) injected a ``MANDATORY VERBAL SCRIPT`` block
into the director prompt, forcing the LLM to read Hapax's words from
a pre-computed show plan rather than ground its narration in the
current perceptual field.

That inversion of the grounding-first architecture is forbidden by
``feedback_grounding_exhaustive``: every LLM utterance must be
grounded in the current impingement / perceptual state, never
dictated by an upstream script.

This test asserts the pattern never reappears: no file in
``agents/studio_compositor/director_loop.py`` (or the whole
studio_compositor package) contains the ``MANDATORY VERBAL SCRIPT``
literal, and no code path reads ``/dev/shm/hapax-compositor/active-beat.json``
to inject into director prompts.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).parents[2]
_STUDIO_COMPOSITOR = _REPO_ROOT / "agents" / "studio_compositor"


def test_director_loop_has_no_mandatory_script_injection() -> None:
    director_loop = _STUDIO_COMPOSITOR / "director_loop.py"
    assert director_loop.exists(), f"missing {director_loop}"
    text = director_loop.read_text()
    forbidden_patterns = [
        "MANDATORY VERBAL SCRIPT",
        "active-beat.json",
        "show-plan.json",
        "content_programmer",
    ]
    for pattern in forbidden_patterns:
        assert pattern not in text, (
            f"director_loop.py must not contain {pattern!r} — grounding-first "
            "architecture forbids script-injection into director prompts. "
            "See docs/superpowers/specs/2026-04-23-gemini-audit-remediation-design.md."
        )


def test_no_showrunner_package_in_tree() -> None:
    """The ``agents/showrunner/`` package is forbidden.

    It was an unauthorized parallel subsystem to ``ProgrammePlanner``
    (task #164, still pending). Re-landing content programming should
    extend ``ProgrammePlanner`` + ``ContentScheduler``, not introduce
    a second runtime.
    """
    showrunner_dir = _REPO_ROOT / "agents" / "showrunner"
    assert not showrunner_dir.exists(), (
        f"{showrunner_dir} reappeared. Content programming belongs inside "
        "agents/programme_manager/ (ProgrammePlanner + ProgrammePlanStore). "
        "See task #164."
    )


def test_studio_compositor_package_has_no_showrunner_imports() -> None:
    """No module in ``agents/studio_compositor/`` imports showrunner."""
    for py in _STUDIO_COMPOSITOR.rglob("*.py"):
        text = py.read_text()
        assert "from agents.showrunner" not in text, (
            f"{py.relative_to(_REPO_ROOT)} imports from the forbidden "
            "agents/showrunner package. Revert and re-design under "
            "programme_manager."
        )
        assert "import agents.showrunner" not in text, (
            f"{py.relative_to(_REPO_ROOT)} imports agents.showrunner. "
            "Revert and re-design under programme_manager."
        )
