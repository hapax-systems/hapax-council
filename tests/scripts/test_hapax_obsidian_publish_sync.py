"""Tests for the Obsidian Publish sync wrapper."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-obsidian-publish-sync"
CONFIG_DIR = REPO_ROOT / "config" / "obsidian-publish"


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    obsidian_dir = vault / ".obsidian"
    obsidian_dir.mkdir(parents=True)
    (obsidian_dir / "publish.json").write_text(
        '{"siteId":"test-site","host":"publish-01.obsidian.md","included":[],"excluded":[]}\n',
        encoding="utf-8",
    )
    return vault


def test_script_is_executable() -> None:
    assert SCRIPT.exists()
    assert SCRIPT.stat().st_mode & 0o111


def test_install_assets_only_copies_home_and_publish_css(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    env = os.environ | {
        "HAPAX_OBSIDIAN_VAULT": str(vault),
        "HAPAX_OBSIDIAN_PUBLISH_CONFIG": str(CONFIG_DIR),
        "HAPAX_OBSIDIAN_SKIP_NODE_CHECK": "1",
    }

    result = subprocess.run(
        [str(SCRIPT), "--install-assets-only"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert (vault / "Home.md").read_text(encoding="utf-8") == (CONFIG_DIR / "Home.md").read_text(
        encoding="utf-8"
    )
    assert (vault / "publish.css").read_text(encoding="utf-8") == (
        CONFIG_DIR / "publish.css"
    ).read_text(encoding="utf-8")


def test_dry_run_invokes_obsidian_headless_publish_without_yes(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    fake_ob = tmp_path / "ob"
    log_path = tmp_path / "ob-argv.txt"
    fake_ob.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" > "$HAPAX_OBSIDIAN_FAKE_OB_LOG"\n',
        encoding="utf-8",
    )
    fake_ob.chmod(0o755)
    env = os.environ | {
        "HAPAX_OBSIDIAN_VAULT": str(vault),
        "HAPAX_OBSIDIAN_PUBLISH_CONFIG": str(CONFIG_DIR),
        "HAPAX_OBSIDIAN_HEADLESS_BIN": str(fake_ob),
        "HAPAX_OBSIDIAN_FAKE_OB_LOG": str(log_path),
        "HAPAX_OBSIDIAN_SKIP_NODE_CHECK": "1",
    }

    result = subprocess.run(
        [str(SCRIPT), "--dry-run", "--skip-assets"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    argv = log_path.read_text(encoding="utf-8").splitlines()
    assert argv == ["publish", "--path", str(vault), "--dry-run"]
    assert "--yes" not in argv


def test_missing_headless_publish_setup_uses_vault_site_id(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    fake_ob = tmp_path / "ob"
    log_path = tmp_path / "ob-calls.txt"
    setup_state = tmp_path / "setup-done"
    fake_ob.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >> "$HAPAX_OBSIDIAN_FAKE_OB_LOG"\n'
        'if [ "$1" = publish-config ] && [ ! -f "$HAPAX_OBSIDIAN_FAKE_SETUP_STATE" ]; then exit 1; fi\n'
        'if [ "$1" = publish-setup ]; then touch "$HAPAX_OBSIDIAN_FAKE_SETUP_STATE"; fi\n',
        encoding="utf-8",
    )
    fake_ob.chmod(0o755)
    env = os.environ | {
        "HAPAX_OBSIDIAN_VAULT": str(vault),
        "HAPAX_OBSIDIAN_PUBLISH_CONFIG": str(CONFIG_DIR),
        "HAPAX_OBSIDIAN_HEADLESS_BIN": str(fake_ob),
        "HAPAX_OBSIDIAN_FAKE_OB_LOG": str(log_path),
        "HAPAX_OBSIDIAN_FAKE_SETUP_STATE": str(setup_state),
        "HAPAX_OBSIDIAN_SKIP_NODE_CHECK": "1",
    }

    result = subprocess.run(
        [str(SCRIPT), "--dry-run", "--skip-assets"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    calls = log_path.read_text(encoding="utf-8").splitlines()
    assert calls == [
        f"publish-config --path {vault}",
        f"publish-setup --site test-site --path {vault}",
        f"publish-config --path {vault} --includes  --excludes ",
        f"publish --path {vault} --dry-run",
    ]
