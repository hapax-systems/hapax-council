"""hapax-coord-provision.service static contract (reform-improve coord SSOT).

Pins the boot oneshot that materializes the coordination SSOT tree + escape-grant
key. Its legacy automatic activation is parked; provisioning remains available
for U3's governed activation rather than running implicitly on merge or boot.
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


def test_provision_service_is_parked_for_governed_activation() -> None:
    """Keep the provisioner installable without starting it on deployment."""
    text = PROVISION_SERVICE.read_text(encoding="utf-8")
    assert "# Hapax-Parked: true" in text
    assert "# Hapax-Auto-Enable: true" not in text
    assert _load(PROVISION_SERVICE)["Install"]["WantedBy"] == "default.target"


def test_provision_service_does_not_pin_root_owned_var_lib() -> None:
    """The unit must not pin the old root-owned /var/lib/hapax/coord default that
    uid 1000 could never provision — the exact bug this task fixes.
    """
    assert "/var/lib/hapax/coord" not in PROVISION_SERVICE.read_text(encoding="utf-8")
