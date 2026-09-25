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
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT = REPO_ROOT / "scripts" / "codex-claim-audit"
UNIT = REPO_ROOT / "systemd" / "units" / "codex-claim-audit.service"


def _write_registry(path: Path, hosts: list[str]) -> None:
    """Minimal host-storage-registry shape: an explicit claim_plane declaration."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "claim_plane": {
                    "hosts": hosts,
                    "source": "test",
                    "declared_at": "2026-09-23T00:00:00Z",
                }
            }
        ),
        encoding="utf-8",
    )


def _claim_plane_hosts(registry: Path, env_value: str | None) -> str:
    env = {"PATH": "/usr/bin:/bin"}
    if env_value is not None:
        env["HAPAX_CLAIM_PLANE_HOSTS"] = env_value
    env["HAPAX_HOST_STORAGE_REGISTRY"] = str(registry)
    result = subprocess.run(
        [
            "bash",
            "-c",
            (f'source <(sed -n "/^claim_plane_hosts()/,/^}}/p" "{AUDIT}")\nclaim_plane_hosts\n'),
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


def _run_audit_guard(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the full script with --version to probe the top-level plane guard.

    The guard executes before arg parsing, so --version exits 0 only when the
    guard lets a plane-less run proceed.
    """
    return subprocess.run(
        [str(AUDIT), "--version"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": "/tmp", **env},
        timeout=15,
        check=False,
    )


def test_bare_ad_hoc_run_proceeds_without_a_plane() -> None:
    """No plane signal (no env/registry/council dir) must not be fatal.

    CI full-suite, tests and operator ad-hoc audits invoke the script bare;
    those runs stay plane-less with peer reconciliation off.
    """
    out = _run_audit_guard({})
    assert out.returncode == 0, (out.returncode, out.stdout, out.stderr)
    assert "ad-hoc run, peer reconciliation off" in out.stderr, out.stderr


def test_broken_declared_context_is_fatal() -> None:
    """A plane context that cannot resolve a plane fails closed.

    HAPAX_COUNCIL_DIR set with no registry claim_plane declaration must abort
    the run rather than silently skipping peer reconciliation.
    """
    empty_dir = Path("/nonexistent-audit-context")
    out = _run_audit_guard({"HAPAX_COUNCIL_DIR": str(empty_dir)})
    assert out.returncode == 2, (out.returncode, out.stdout, out.stderr)
    assert "FATAL" in out.stderr, out.stderr
