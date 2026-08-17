"""The codex frontier pair is declared in four places; this pins them equal.

WHY THIS TEST EXISTS. ``scripts/codex-frontier-selection.sh`` was created to end a
"shared contract — keep in sync" comment that had already failed between two launchers.
It unified those two. It did not unify the other three sites that also state which model
and effort a governed Codex session runs under, and review found the drift immediately:

  1. ``scripts/codex-frontier-selection.sh`` — the builtins, the intended single source
  2. ``config/codex/config.toml``            — installed verbatim to ``~/.codex/config.toml``
                                               by ``scripts/install-codex-config.sh``; read by
                                               every ad-hoc ``codex`` / ``codex exec`` call
  3. ``config/platform-capability-registry.json`` — the governed declaration every routing,
                                               fit, receipt and admission consumer reads
  4. ``shared/capability_harness_seed.py``   — the capability descriptor for the same route

At the head this test was written against, (1) said gpt-5.6-sol/ultra while (2), (3) and (4)
all still said gpt-5.5/xhigh. Consequences, in ascending order of harm: the harness seed and
registry described an execution subject no process ran under, and running the installer
actively REGRESSED a live host off the frontier — an unstated downgrade, which is the precise
act (1) refuses when a launcher attempts it.

Four sites and one hazard is not a case for a fifth comment. The parity is now a predicate,
because human discipline is the bottom of the mechanism ladder and this file is the proof:
the estate had already written "keep in sync" once and it did not hold.

Renaming a builtin or moving a declaration should BREAK this test loudly rather than let it
silently stop checking, so every extractor asserts it found something before comparing.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from shared.capability_harness_seed import SEED_CAPABILITY_DESCRIPTORS
from shared.platform_capability_registry import Effort, ModelId

REPO_ROOT = Path(__file__).resolve().parents[1]
SELECTION_SH = REPO_ROOT / "scripts" / "codex-frontier-selection.sh"
CODEX_CONFIG = REPO_ROOT / "config" / "codex" / "config.toml"
REGISTRY = REPO_ROOT / "config" / "platform-capability-registry.json"

ROUTE_ID = "codex.headless.full"


def _shell_builtin(name: str) -> str:
    """Read a top-level ``NAME="value"`` assignment out of the selection script.

    Deliberately anchored at line start and to a double-quoted literal: the builtins are the
    baseline a guard compares against, so a value arriving any other way (computed, sourced,
    conditional) is a design change that must fail here rather than be silently accepted.
    """
    pattern = re.compile(rf'^{re.escape(name)}="([^"]*)"$', re.MULTILINE)
    matches = pattern.findall(SELECTION_SH.read_text(encoding="utf-8"))
    assert matches, f"{name} is no longer a plain top-level literal in {SELECTION_SH.name}"
    assert len(matches) == 1, f"{name} is assigned {len(matches)} times in {SELECTION_SH.name}"
    return matches[0]


def _registry_route() -> dict:
    routes = {r["route_id"]: r for r in json.loads(REGISTRY.read_text(encoding="utf-8"))["routes"]}
    assert ROUTE_ID in routes, f"{ROUTE_ID} vanished from the registry"
    return routes[ROUTE_ID]


def _seed_descriptor():
    matches = [d for d in SEED_CAPABILITY_DESCRIPTORS if getattr(d, "route_id", None) == ROUTE_ID]
    assert len(matches) == 1, f"expected exactly one harness descriptor for {ROUTE_ID}"
    return matches[0]


def test_frontier_pair_is_spellable_in_the_governed_vocabulary() -> None:
    """The enums must be able to NAME the pair the launchers run.

    This is the failure that let the drift persist: ``ultra`` was not an Effort member, so the
    registry could not have recorded the true value even had someone tried. A closed vocabulary
    that cannot spell the live value does not constrain routing, it only hides the subject.
    """
    assert _shell_builtin("HAPAX_CODEX_FRONTIER_MODEL_BUILTIN") in {m.value for m in ModelId}
    assert _shell_builtin("HAPAX_CODEX_FRONTIER_EFFORT_BUILTIN") in {e.value for e in Effort}


def test_installed_codex_config_matches_the_frontier_builtins() -> None:
    """``config/codex/config.toml`` is what ad-hoc ``codex exec`` reads — the population that
    bypasses both launchers. If it disagrees with the builtins, installing it is a downgrade."""
    config = tomllib.loads(CODEX_CONFIG.read_text(encoding="utf-8"))
    assert config["model"] == _shell_builtin("HAPAX_CODEX_FRONTIER_MODEL_BUILTIN")
    assert config["model_reasoning_effort"] == _shell_builtin("HAPAX_CODEX_FRONTIER_EFFORT_BUILTIN")


def test_registry_route_descriptor_matches_the_frontier_builtins() -> None:
    """Every governed consumer — supply vectors, fit decisions, capability receipts — reasons
    from this descriptor. It must name the process that actually launches."""
    descriptor = _registry_route()["execution_descriptor"]
    assert descriptor["model_id"] == _shell_builtin("HAPAX_CODEX_FRONTIER_MODEL_BUILTIN")
    assert descriptor["effort"] == _shell_builtin("HAPAX_CODEX_FRONTIER_EFFORT_BUILTIN")


def test_registry_free_text_model_matches_its_own_structured_descriptor() -> None:
    """``model_or_engine`` is the coarse free-text field the structured descriptor replaced. It
    survives for display, so it must not become a second, disagreeing declaration."""
    route = _registry_route()
    descriptor = route["execution_descriptor"]
    assert route["model_or_engine"] == f"{descriptor['model_id']}-{descriptor['effort']}"


def test_capability_harness_seed_matches_the_frontier_builtins() -> None:
    descriptor = _seed_descriptor()
    assert descriptor.model == _shell_builtin("HAPAX_CODEX_FRONTIER_MODEL_BUILTIN")
    assert descriptor.effort == _shell_builtin("HAPAX_CODEX_FRONTIER_EFFORT_BUILTIN")


def test_registry_notes_do_not_restate_the_pair_as_a_literal() -> None:
    """The note that rotted said 'Default Codex SOP: GPT-5.5 xhigh'. A prose restatement of a
    value declared elsewhere is a copy that no predicate checks, so it is refused: the note may
    POINT at the selection script, but it may not spell a model version.

    Scoped to the two codex routes — other routes legitimately name their own model in prose.
    """
    routes = json.loads(REGISTRY.read_text(encoding="utf-8"))["routes"]
    model_version = re.compile(r"gpt-\d", re.IGNORECASE)
    for route in routes:
        if not route["route_id"].startswith("codex."):
            continue
        # the spark route's launcher names its model as a real argument; only prose is checked
        assert not model_version.search(route["notes"]), (
            f"{route['route_id']} notes restate a model version in prose; "
            "point at scripts/codex-frontier-selection.sh instead"
        )
