"""D4 red-before-green: claim-plane hosts from the registry, not a literal pair.

G1: `HAPAX_CLAIM_PLANE_HOSTS=hapax-podium hapax-appendix` in
`systemd/units/codex-claim-audit.service` is a pair-not-mesh pin. Successor:
derive the expandable host list from the host registry. Env stays an override.

These tests fail while the unit pins the pair and the script trusts only the
env string, and pass once ``claim_plane_hosts`` reads the registry.
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT = REPO_ROOT / "scripts" / "codex-claim-audit"
UNIT = REPO_ROOT / "systemd" / "units" / "codex-claim-audit.service"


def _write_registry(path: Path, hosts: list[str]) -> None:
    """Minimal host-storage-registry shape: one row per host as target_host."""
    rows = [
        {
            "cadence": "daily",
            "command_host": h,
            "target_host": h,
            "locality_class": "same_host",
            "method": "restic-nas",
            "store_id": f"store-{h}",
            "unit_name": "hapax-backup-local.timer",
            "intended_state": "enabled",
        }
        for h in hosts
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"backup_policies": rows}), encoding="utf-8")


def _claim_plane_hosts(registry: Path, env_value: str | None) -> str:
    env = {"PATH": "/usr/bin:/bin"}
    if env_value is not None:
        env["HAPAX_CLAIM_PLANE_HOSTS"] = env_value
    env["HAPAX_HOST_STORAGE_REGISTRY"] = str(registry)
    result = subprocess.run(
        [
            "bash",
            "-c",
            (
                f'source <(sed -n "/^claim_plane_hosts()/,/^}}/p" "{AUDIT}")\n'
                f"claim_plane_hosts\n"
            ),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
        check=False,
    )
    return result.stdout.strip()


def test_registry_supplies_claim_plane_hosts(tmp_path: Path) -> None:
    """A third registry host must appear in the derived claim plane."""
    reg = tmp_path / "host-storage-registry.json"
    _write_registry(reg, ["hapax-podium", "hapax-appendix", "beelink1"])
    out = _claim_plane_hosts(reg, None)
    assert "hapax-podium" in out, out
    assert "hapax-appendix" in out, out
    assert "beelink1" in out, out


def test_env_stays_an_override(tmp_path: Path) -> None:
    """An explicit env list wins over the registry (override, not law)."""
    reg = tmp_path / "host-storage-registry.json"
    _write_registry(reg, ["hapax-podium", "hapax-appendix", "beelink1"])
    out = _claim_plane_hosts(reg, "hapax-podium hapax-appendix")
    assert "beelink1" not in out, out
    assert "hapax-podium" in out, out


def test_unit_does_not_pin_the_pair() -> None:
    """The unit must not hard-code the two-host claim plane as identity."""
    text = UNIT.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        if "HAPAX_CLAIM_PLANE_HOSTS=hapax-podium hapax-appendix" in line:
            raise AssertionError(f"unit still pins the pair: {line}")


def test_audit_declares_claim_plane_hosts() -> None:
    text = AUDIT.read_text(encoding="utf-8")
    assert "claim_plane_hosts" in text

