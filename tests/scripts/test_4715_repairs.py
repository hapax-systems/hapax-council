"""4715 review repairs â€” claim_plane_hosts must prove the plane, never no-op.

Review findings (22:32Z): (1) dev-tree fallback violates #4090 canonical-root;
(2) claim-plane from backup_policies unverified / working pin removed;
(3) empty-string exit-0 silently degrades to no-op self-reconcile.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT = REPO_ROOT / "scripts" / "codex-claim-audit"


def _run(script: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            "-c",
            (f'source <(sed -n "/^claim_plane_hosts()/,/^}}/p" "{script}")\nclaim_plane_hosts\n'),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
        check=False,
    )


def test_pin_wins_over_registry(tmp_path: Path) -> None:
    reg = tmp_path / "host-storage-registry.json"
    reg.write_text(
        '{"claim_plane":{"hosts":["zzz"],"source":"t","declared_at":"2026-09-23T00:00:00Z"}}',
        encoding="utf-8",
    )
    env = {
        "PATH": "/usr/bin:/bin",
        "HAPAX_CLAIM_PLANE_HOSTS": "hapax-podium hapax-appendix",
        "HAPAX_HOST_STORAGE_REGISTRY": str(reg),
    }
    out = _run(AUDIT, env)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "hapax-podium hapax-appendix"


def test_registry_derivation_succeeds_and_logs_source(tmp_path: Path) -> None:
    reg = tmp_path / "host-storage-registry.json"
    reg.write_text(
        '{"claim_plane":{"hosts":["hapax-podium","hapax-appendix","beelink1"],"source":"t","declared_at":"2026-09-23T00:00:00Z"}}',
        encoding="utf-8",
    )
    env = {"PATH": "/usr/bin:/bin", "HAPAX_HOST_STORAGE_REGISTRY": str(reg)}
    out = _run(AUDIT, env)
    assert out.returncode == 0, out.stderr
    assert (
        "hapax-podium" in out.stdout and "hapax-appendix" in out.stdout and "beelink1" in out.stdout
    )
    assert "DECLARATION" in out.stderr


def test_missing_registry_without_council_dir_is_fatal() -> None:
    """No pin + no HAPAX_COUNCIL_DIR must not silently return empty."""
    env = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent-home-for-test"}
    env.pop("HAPAX_CLAIM_PLANE_HOSTS", None)
    env.pop("HAPAX_HOST_STORAGE_REGISTRY", None)
    env.pop("HAPAX_COUNCIL_DIR", None)
    out = _run(AUDIT, env)
    assert out.returncode != 0, (out.returncode, out.stdout, out.stderr)
    assert out.stdout.strip() == ""
    assert "FATAL" in out.stderr


def test_empty_registry_plane_is_fatal(tmp_path: Path) -> None:
    """A registry that yields no hosts must error closed, not no-op."""
    reg = tmp_path / "host-storage-registry.json"
    reg.write_text(
        '{"claim_plane":{"hosts":[],"source":"t","declared_at":"2026-09-23T00:00:00Z"}}',
        encoding="utf-8",
    )
    env = {"PATH": "/usr/bin:/bin", "HAPAX_HOST_STORAGE_REGISTRY": str(reg)}
    out = _run(AUDIT, env)
    assert out.returncode != 0, (out.returncode, out.stdout, out.stderr)
    assert "empty" in out.stderr


def test_no_dev_tree_fallback(tmp_path: Path) -> None:
    """HAPAX_COUNCIL_DIR is required; the mutable dev tree is never assumed."""
    reg_missing = tmp_path / "nope" / "host-storage-registry.json"
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "HAPAX_HOST_STORAGE_REGISTRY": str(reg_missing),
    }
    out = _run(AUDIT, env)
    assert out.returncode != 0
    assert "mutable dev tree" in out.stderr or "registry not found" in out.stderr
    assert "projects/hapax-council" not in out.stderr.replace("HAPAX_COUNCIL_DIR", "")


def test_council_dir_registry_path(tmp_path: Path) -> None:
    council = tmp_path / "worktree"
    (council / "config" / "infrastructure").mkdir(parents=True)
    (council / "config" / "infrastructure" / "host-storage-registry.json").write_text(
        '{"claim_plane":{"hosts":["hapax-podium","hapax-appendix"],"source":"t","declared_at":"2026-09-23T00:00:00Z"}}',
        encoding="utf-8",
    )
    env = {"PATH": "/usr/bin:/bin", "HAPAX_COUNCIL_DIR": str(council)}
    env.pop("HAPAX_HOST_STORAGE_REGISTRY", None)
    env.pop("HAPAX_CLAIM_PLANE_HOSTS", None)
    out = _run(AUDIT, env)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "hapax-podium hapax-appendix"
