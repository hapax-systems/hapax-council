"""Lint the SHIPPED no-op canary registry against the live repo.

Healthy-code invariant (canary-on-the-canary): every pinned target sha
must match the working tree. When an edit to a pinned target lands, this
test fails loudly — refresh the pin ONLY after re-verifying the template's
complaint still does not reproduce. Silent drift would let a decoy ship a
complaint that has become true.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from noop_canary.registry import load_registry, template_health  # noqa: E402

REGISTRY_PATH = REPO_ROOT / "config" / "failure-taxonomy" / "noop-canaries.yaml"

# Words that would fingerprint a minted decoy note to the receiving lane.
FORBIDDEN_MARKERS = ("canary", "decoy", "no-op", "noop", "fixing-correct-code", "taxonomy")


def test_shipped_registry_loads() -> None:
    registry = load_registry(REGISTRY_PATH)
    assert registry.platform_tiers, "registry must target at least one platform tier"
    # ALPHA TAKES IT TOO — the orchestrator carries the bias-toward-action
    # directive before any lane does.
    assert "alpha" in registry.platform_tiers
    assert len(registry.templates) >= 3, "rotation needs a meaningful template pool"


def test_shipped_templates_are_healthy_against_repo() -> None:
    registry = load_registry(REGISTRY_PATH)
    unhealthy = {
        tpl.id: template_health(tpl, repo_root=REPO_ROOT).reason
        for tpl in registry.templates
        if not template_health(tpl, repo_root=REPO_ROOT).healthy
    }
    assert not unhealthy, (
        f"pinned targets drifted: {unhealthy} — re-verify each complaint does NOT "
        "reproduce, then refresh target_sha256 in config/failure-taxonomy/noop-canaries.yaml"
    )


def test_shipped_templates_carry_no_fingerprint() -> None:
    registry = load_registry(REGISTRY_PATH)
    for tpl in registry.templates:
        rendered = " ".join((tpl.task_id_pattern, tpl.title, tpl.complaint)).lower()
        for marker in FORBIDDEN_MARKERS:
            assert marker not in rendered, (
                f"template {tpl.id}: {marker!r} would fingerprint the minted note"
            )
        assert "{yyyymm}" in tpl.task_id_pattern, (
            f"template {tpl.id}: task_id_pattern must vary by month"
        )
