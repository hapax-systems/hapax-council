"""hapax-coord-provision.service static contract (reform-improve coord SSOT).

Pins the boot oneshot that materializes the coordination SSOT tree + escape-grant
key so the R2 event log and the R3 daemon-independent escape grant are LIVE on
boot without manual intervention — and that it carries the deploy auto-enable
marker so a freshly-merged unit is `enable --now`'d, not installed-but-sleeping.
"""

from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
PROVISION_SERVICE = UNITS_DIR / "hapax-coord-provision.service"


def _load(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # preserve case (systemd keys are CamelCase)
    parser.read(path, encoding="utf-8")
    return parser


def test_provision_service_is_oneshot_running_the_provisioner() -> None:
    assert PROVISION_SERVICE.exists()
    unit = _load(PROVISION_SERVICE)
    assert unit["Service"]["Type"] == "oneshot"
    # A oneshot that should stay "active" after success so deploy's verify can see it.
    assert unit["Service"]["RemainAfterExit"] == "yes"
    exec_start = unit["Service"]["ExecStart"]
    assert exec_start.endswith("scripts/coord-boot-reconcile --provision"), exec_start


def test_provision_service_orders_after_secrets() -> None:
    """The grant key + tree must be provisioned after hapax-secrets (the chain
    head), per the parent spec's remediation #2.
    """
    unit = _load(PROVISION_SERVICE)
    assert "hapax-secrets.service" in unit["Unit"]["After"]


def test_provision_service_is_marked_auto_enable() -> None:
    """reform-improve-deploy-activation: the deploy auto-enables units carrying a
    `# Hapax-Auto-Enable: true` marker, so the SSOT is provisioned on merge/boot
    instead of installed-but-sleeping. The marker needs an [Install] section.
    """
    markers = [
        line.strip()
        for line in PROVISION_SERVICE.read_text(encoding="utf-8").splitlines()
        if line.lstrip().startswith("#") and "hapax-auto-enable" in line.lower()
    ]
    assert markers, "hapax-coord-provision.service must carry a `# Hapax-Auto-Enable` marker"
    assert any("true" in marker.lower() for marker in markers)
    assert _load(PROVISION_SERVICE)["Install"]["WantedBy"] == "default.target"


def test_provision_service_does_not_pin_root_owned_var_lib() -> None:
    """The unit must not pin the old root-owned /var/lib/hapax/coord default that
    uid 1000 could never provision — the exact bug this task fixes.
    """
    assert "/var/lib/hapax/coord" not in PROVISION_SERVICE.read_text(encoding="utf-8")
