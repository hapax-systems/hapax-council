"""Route recomposition must not offer a lane a route that lane cannot run.

Measured 2026-08-10, appendix: the coordinator made 2,590 dispatch attempts in 24 hours and was
refused 2,590 times, every one of them `codex.headless.full -> epsilon`. Over 7 days: 7,238 ticks
at `dispatched=0` against 6 at `dispatched=1`.

The mechanism is an ordering defect, not a bad guard.
`_availability_recomposition_candidate_requests` builds candidates with the lane FIXED and no
lane-compatibility filter; `adapter.admit` then selects the best-scoring route from that unfiltered
set; and only afterwards does `platform_lane_compatibility_reason` refuse the selection. The
predicate is correct and runs downstream of the choice it should have constrained -- its own
"Next action" text even names the remedy ("rerun route selection for a route compatible with the
requested lane"), which never happens.

epsilon is a Claude lane (tmux session `hapax-claude-epsilon`; the coordinator's fallback roster
assigns `platform="claude"` to all eight greek roles). It can never satisfy a
`codex.headless.full` selection, so every recomposition onto that route is dead on arrival.

Self-contained per the repo testing convention (no shared conftest fixtures).
"""

from __future__ import annotations

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType, SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-methodology-dispatch"


def _load() -> ModuleType:
    name = "hapax_methodology_dispatch_lane_test_module"
    sys.modules.pop(name, None)
    loader = SourceFileLoader(name, str(SCRIPT))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def _route(platform: str, mode: str = "headless", profile: str = "full"):
    """A minimal stand-in carrying only what the compatibility predicate reads."""
    return SimpleNamespace(platform=platform, mode=mode, profile=profile, mutable=True)


# --- the predicate itself, which is correct and must stay correct ------------------------


def test_greek_lane_cannot_run_a_codex_route() -> None:
    module = _load()
    reason = module.platform_lane_compatibility_reason("epsilon", _route("codex"))
    assert reason is not None
    assert "cx-*" in reason


def test_cx_lane_can_run_a_codex_route() -> None:
    module = _load()
    assert module.platform_lane_compatibility_reason("cx-crit", _route("codex")) is None


def test_greek_lane_can_run_a_claude_route() -> None:
    module = _load()
    assert module.platform_lane_compatibility_reason("epsilon", _route("claude")) is None


def test_cx_lane_cannot_run_a_claude_route() -> None:
    module = _load()
    assert module.platform_lane_compatibility_reason("cx-crit", _route("claude")) is not None


# --- the ordering defect: selection must consult the predicate ---------------------------


def test_lane_can_run_helper_agrees_with_the_predicate() -> None:
    """The filter selection uses must be the SAME predicate that refuses afterwards.

    A second, separately-maintained notion of compatibility would drift from the one that
    actually gates dispatch, and the drift would be invisible until it refused again.
    """
    module = _load()
    assert hasattr(module, "_lane_can_run"), (
        "_lane_can_run must exist: recomposition has to filter candidates by lane compatibility "
        "BEFORE admission selects among them"
    )
    for lane, platform, expected in (
        ("epsilon", "codex", False),
        ("epsilon", "claude", True),
        ("cx-crit", "codex", True),
        ("cx-crit", "claude", False),
    ):
        route = _route(platform)
        assert module._lane_can_run(lane, route) is expected, f"{lane}/{platform}"
        assert module._lane_can_run(lane, route) is (
            module.platform_lane_compatibility_reason(lane, route) is None
        ), "the filter and the refusal must be the same predicate"


def test_recomposition_filters_candidates_by_lane_compatibility() -> None:
    """Structural pin on the ordering, which is the whole defect.

    The candidate builder must consult lane compatibility. Without it the unfiltered set reaches
    `admit`, admission picks the highest-scoring route, and the lane check refuses it after the
    fact -- 2,590 times a day, measured.
    """
    module = _load()
    assert module is not None
    source = SCRIPT.read_text(encoding="utf-8")
    start = source.index("def _availability_recomposition_candidate_requests")
    end = source.index("\ndef ", start + 1)
    body = source[start:end]
    assert "_lane_can_run" in body, (
        "_availability_recomposition_candidate_requests must filter by lane compatibility; "
        "otherwise admission selects a route the lane cannot run and the guard refuses it "
        "after the fact"
    )
