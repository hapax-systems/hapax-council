from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"

DECOMMISSIONED_UNITS = {
    "hapax-logos.service",
    "hapax-build-reload.path",
    "hapax-build-reload.service",
    "logos-dev.service",
}


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_decommissioned_units_are_not_install_visible() -> None:
    for unit in sorted(DECOMMISSIONED_UNITS):
        assert not (UNITS_DIR / unit).exists(), f"{unit} must not exist under systemd/units"
        assert not (REPO_ROOT / "systemd" / unit).exists(), f"{unit} must not have root shadow"


def test_visual_stack_target_cannot_pull_tauri_runtime() -> None:
    body = _read("systemd/units/hapax-visual-stack.target")
    for unit in DECOMMISSIONED_UNITS:
        assert unit not in body
    assert "studio-compositor.service" in body
    assert "hapax-imagination.service" in body


def test_install_units_removes_and_masks_decommissioned_units() -> None:
    body = _read("systemd/scripts/install-units.sh")
    for unit in sorted(DECOMMISSIONED_UNITS):
        assert unit in body
    assert "DECOMMISSIONED_UNITS=(" in body
    assert 'systemctl --user disable --now "$name"' in body
    assert 'systemctl --user mask "$name"' in body
    assert "skipped decommissioned unit" in body


def test_post_merge_deploy_does_not_unmask_or_enable_retired_units() -> None:
    body = _read("scripts/hapax-post-merge-deploy")
    for unit in sorted(DECOMMISSIONED_UNITS):
        assert f"unmask {unit}" not in body
        assert f"enable --now {unit}" not in body
        assert f"enable {unit}" not in body


def test_rebuild_and_reload_scripts_do_not_build_or_restart_tauri() -> None:
    rebuild = _read("scripts/rebuild-logos.sh")
    assert "just install-imagination" in rebuild
    assert "just install 2>" not in rebuild
    assert "for svc in hapax-imagination hapax-logos" not in rebuild
    assert "systemctl --user restart hapax-logos" not in rebuild

    reload = _read("scripts/reload-after-build.sh")
    assert "hapax-logos.service" not in reload
    assert ".local/bin/hapax-logos" not in reload

    freshness = _read("scripts/freshness-check.sh")
    assert "LOGOS_BIN" not in freshness
    assert "for svc in hapax-imagination hapax-logos" not in freshness


def test_rebuild_logos_quarantines_corrupted_scratch_worktree() -> None:
    rebuild = _read("scripts/rebuild-logos.sh")
    assert "quarantine_build_worktree()" in rebuild
    assert 'mv "$BUILD_WORKTREE" "$tombstone"' in rebuild
    assert 'rm -rf "$BUILD_WORKTREE" 2>/dev/null' in rebuild
    assert "could not clear build worktree" in rebuild
    assert 'quarantine_build_worktree "initial create" || exit 0' in rebuild
    assert 'quarantine_build_worktree "reset failure" || exit 0' in rebuild


def test_hapax_logos_justfile_installs_imagination_only_by_default() -> None:
    body = _read("hapax-logos/justfile")
    assert "build: imagination" in body
    assert "build: imagination logos" not in body
    assert "install: install-imagination" in body
    install_block = body.split("install-imagination:", 1)[1].split("# ── Rollback", 1)[0]
    assert "LOGOS_SRC" not in install_block
    assert "LOGOS_DST" not in install_block


def test_tauri_binary_install_script_is_explicit_dev_only() -> None:
    body = _read("hapax-logos/scripts/install.sh")
    assert "HAPAX_ALLOW_TAURI_BINARY_INSTALL" in body
    assert "hapax-logos.service" not in body
    assert "systemctl --user start hapax-logos" not in body
    assert "systemctl --user enable hapax-logos" not in body


def test_operator_command_defaults_do_not_use_retired_relay_port() -> None:
    runtime_paths = [
        "agents/streamdeck_adapter/adapter.py",
        "agents/streamdeck_adapter/__init__.py",
        "agents/stream_deck/adapter.py",
        "agents/stream_deck/__init__.py",
        "agents/kdeconnect_bridge/bridge.py",
        "agents/kdeconnect_bridge/__init__.py",
        "config/streamdeck.yaml",
        "config/stream-deck/manifest.yaml",
    ]
    for path in runtime_paths:
        body = _read(path)
        assert ":8052" not in body, f"{path} still names retired command relay"
        assert "ws://127.0.0.1:8052" not in body


def test_studio_compositor_no_longer_pushes_to_tauri_frame_relay() -> None:
    body = _read("agents/studio_compositor/snapshots.py")
    assert "8054" not in body
    assert "socket.AF_INET" not in body
    assert "fx-snapshot.jpg" in body


def test_legacy_logos_directive_bridge_fails_closed() -> None:
    route = _read("logos/api/routes/logos.py")
    browser_agent = _read("agents/browser_agent.py")
    assert "status_code=410" in route
    assert "/dev/shm/hapax-logos" not in route
    assert "BrowserAgentUnavailable" in browser_agent
    assert "/dev/shm/hapax-logos" not in browser_agent


def test_visual_audit_and_runbook_validate_retired_ports() -> None:
    audit = _read("scripts/visual-audit.sh")
    runbook = _read("docs/runbooks/tauri-logos-decommission.md")
    for port in ("8052", "8053", "8054", "5173"):
        assert port in audit
        assert port in runbook
    assert "/dev/video42" in runbook
    assert "logos-api :8051" in runbook
