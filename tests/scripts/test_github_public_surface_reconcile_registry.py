"""Pin the reconcile script's registry loader for expected-detection pins.

The unit tests in tests/shared/test_github_public_surface.py construct
``LocalPublicSurfaceEvidence`` directly; these tests exercise the REAL
generator path — ``_registry()`` reading ``docs/repo-pres/repo-registry.yaml``
and ``_local_evidence()`` threading the pin map — so a YAML key typo or a
loader omission cannot silently fall back to policy comparison and
reintroduce the NOASSERTION false drift.
"""

from __future__ import annotations

import runpy
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "github-public-surface-reconcile.py"


def _module() -> dict:
    return runpy.run_path(str(SCRIPT))


def test_registry_loader_reads_expected_detection_pins() -> None:
    registry = _module()["_registry"](REPO_ROOT)
    pins = registry["expected_detection_by_repo"]

    # PolyForm/BSL repos pin NOASSERTION (licensee cannot detect them).
    for repo in ("hapax-council", "hapax-officium", "hapax-watch", "hapax-phone", "reins"):
        assert pins[repo] == "NOASSERTION", repo
    assert pins["hapax-spine"] == "NOASSERTION"
    # Licensee-detectable licenses pin their own detection.
    assert pins["agentgov"] == "MIT"
    assert pins["hapax-mcp"] == "MIT"
    assert pins["hapax-research-ledger"] == "CC0-1.0"
    # Post-split expectation for the constitution (waiver-covered until then).
    assert pins["hapax-constitution"] == "NOASSERTION"


def test_local_evidence_threads_pin_map() -> None:
    module = _module()
    evidence = module["_local_evidence"](REPO_ROOT)
    registry = module["_registry"](REPO_ROOT)

    assert evidence.registry_expected_detection_by_repo == registry["expected_detection_by_repo"]
    assert evidence.registry_expected_detection_by_repo, "pin map must not be empty"
    # Every pinned repo must also carry a policy license (pins never stand alone).
    for name in evidence.registry_expected_detection_by_repo:
        assert name in evidence.registry_license_by_repo, name
