"""Root repairs for the 00:03Z dual-confirmed criticals.

1. claim-plane must be DECLARED (registry claim_plane block + provenance),
   never derived from backup_policies.
2. hapax-coord.service must resolve through the coord-activation worktree,
   never the mutable dev tree.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT = REPO_ROOT / "scripts" / "codex-claim-audit"
UNIT = REPO_ROOT / "systemd" / "units" / "hapax-coord.service"


def _run(
    registry: Path | None, env_extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = {"PATH": "/usr/bin:/bin"}
    if registry is not None:
        env["HAPAX_HOST_STORAGE_REGISTRY"] = str(registry)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
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


def test_declaration_is_read_with_provenance(tmp_path: Path) -> None:
    reg = tmp_path / "host-storage-registry.json"
    reg.write_text(
        json.dumps(
            {
                "backup_policies": [{"command_host": "zzz", "target_host": "zzz"}],
                "claim_plane": {
                    "hosts": ["hapax-podium", "hapax-appendix"],
                    "source": "test",
                    "declared_at": "2026-09-23T00:00:00Z",
                },
            }
        ),
        encoding="utf-8",
    )
    out = _run(reg)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "hapax-podium hapax-appendix"
    assert "from DECLARATION" in out.stderr
    assert "sha256=" in out.stderr


def test_backup_policies_alone_is_not_a_claim_plane(tmp_path: Path) -> None:
    """A backup topology must NOT be accepted as claim-plane membership."""
    reg = tmp_path / "host-storage-registry.json"
    reg.write_text(
        json.dumps(
            {"backup_policies": [{"command_host": "hapax-podium", "target_host": "hapax-appendix"}]}
        ),
        encoding="utf-8",
    )
    out = _run(reg)
    assert out.returncode != 0, (out.returncode, out.stdout, out.stderr)
    assert "no claim_plane declaration" in out.stderr
    assert "backup_policies is NOT a claim plane" in out.stderr


def test_empty_declaration_is_fatal(tmp_path: Path) -> None:
    reg = tmp_path / "host-storage-registry.json"
    reg.write_text(json.dumps({"claim_plane": {"hosts": []}}), encoding="utf-8")
    out = _run(reg)
    assert out.returncode != 0
    assert "empty" in out.stderr


def test_override_is_labelled_as_override(tmp_path: Path) -> None:
    reg = tmp_path / "host-storage-registry.json"
    reg.write_text(json.dumps({"claim_plane": {"hosts": ["a", "b"]}}), encoding="utf-8")
    out = _run(reg, {"HAPAX_CLAIM_PLANE_HOSTS": "hapax-podium hapax-appendix"})
    assert out.returncode == 0
    assert out.stdout.strip() == "hapax-podium hapax-appendix"
    assert "OVERRIDE" in out.stderr
    assert "DECLARATION" not in out.stderr


def test_shipped_registry_declares_the_plane() -> None:
    reg = REPO_ROOT / "config" / "infrastructure" / "host-storage-registry.json"
    data = json.loads(reg.read_text(encoding="utf-8"))
    plane = data.get("claim_plane")
    assert isinstance(plane, dict), "registry must carry a claim_plane declaration"
    assert plane.get("hosts"), "claim_plane.hosts must be non-empty"
    assert plane.get("source"), "claim_plane.source is the reviewers' provenance handle"
    assert plane.get("declared_at"), "claim_plane.declared_at is required provenance"


def test_hapax_coord_unit_resolves_through_activation_worktree() -> None:
    """#4090 canonical-root: never the mutable dev tree (review 00:03Z)."""
    text = UNIT.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        if "projects/hapax-coord" in line:
            raise AssertionError(f"unit references the mutable dev tree: {line}")
    assert "coord-activation/worktree" in text
    assert "ExecStart=" in text and "coord-activation/worktree/scripts/run-dev.sh" in text
