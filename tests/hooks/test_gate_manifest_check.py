"""Gate manifest drift checker tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "gate-manifest-check.py"
MANIFEST = REPO_ROOT / "hooks" / "gate-manifest.yaml"


def _run(*args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python", str(SCRIPT), "--repo-root", str(REPO_ROOT), *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def _manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def _write_claude_settings(tmp_path: Path, *, drop_last_pretool_hook: bool = False) -> Path:
    phases = _manifest()["runtimes"]["claude"]["phases"]
    settings = {"hooks": {}}
    for phase, entries in phases.items():
        settings["hooks"][phase] = []
        for entry in entries:
            hook_names = list(entry["hooks"])
            if drop_last_pretool_hook and phase == "PreToolUse" and hook_names:
                hook_names = hook_names[:-1]
                drop_last_pretool_hook = False
            settings["hooks"][phase].append(
                {
                    "matcher": entry["matcher"],
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"/tmp/hapax-hooks/{hook_name}",
                        }
                        for hook_name in hook_names
                    ],
                }
            )
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings), encoding="utf-8")
    return path


def test_repo_gate_manifest_is_current() -> None:
    result = _run("--skip-claude-settings")

    assert result.returncode == 0, result.stderr
    assert "gate-manifest-check: OK" in result.stdout


def test_claude_settings_fixture_matches_manifest(tmp_path: Path) -> None:
    settings = _write_claude_settings(tmp_path)
    result = _run("--claude-settings", settings)

    assert result.returncode == 0, result.stderr


def test_claude_settings_drift_fails(tmp_path: Path) -> None:
    settings = _write_claude_settings(tmp_path, drop_last_pretool_hook=True)
    result = _run("--claude-settings", settings)

    assert result.returncode == 1
    assert "claude PreToolUse drift" in result.stderr


def test_codex_adapter_drift_fails(tmp_path: Path) -> None:
    adapter = tmp_path / "codex-hook-adapter.sh"
    source = (REPO_ROOT / "hooks" / "scripts" / "codex-hook-adapter.sh").read_text(encoding="utf-8")
    adapter.write_text(source.replace("pip-guard.sh", ""), encoding="utf-8")

    result = _run("--skip-claude-settings", "--codex-adapter", adapter)

    assert result.returncode == 1
    assert "codex adapter PreToolUse drift" in result.stderr
    assert "pip-guard.sh" in result.stderr


def test_antigravity_cli_and_ide_marker_drift_fails(tmp_path: Path) -> None:
    launcher = tmp_path / "hapax-antigrav"
    source = (REPO_ROOT / "scripts" / "hapax-antigrav").read_text(encoding="utf-8")
    launcher.write_text(source.replace(".agents/workflows", ".agents/disabled"), encoding="utf-8")

    result = _run("--skip-claude-settings", "--antigravity-launcher", launcher)

    assert result.returncode == 1
    assert "antigravity capability marker drift" in result.stderr
    assert ".agents/workflows" in result.stderr


def test_vibe_capability_marker_drift_fails(tmp_path: Path) -> None:
    launcher = tmp_path / "hapax-vibe"
    source = (REPO_ROOT / "scripts" / "hapax-vibe").read_text(encoding="utf-8")
    launcher.write_text(source.replace("--trust", "--no-trust"), encoding="utf-8")

    result = _run("--skip-claude-settings", "--vibe-launcher", launcher)

    assert result.returncode == 1
    assert "vibe capability marker drift" in result.stderr
    assert "--trust" in result.stderr


def test_gemini_capability_marker_drift_fails(tmp_path: Path) -> None:
    launcher = tmp_path / "hapax-gemini"
    source = (REPO_ROOT / "scripts" / "hapax-gemini").read_text(encoding="utf-8")
    launcher.write_text(source.replace("--approval-mode", "--review-mode"), encoding="utf-8")

    result = _run("--skip-claude-settings", "--gemini-launcher", launcher)

    assert result.returncode == 1
    assert "gemini capability marker drift" in result.stderr
    assert "--approval-mode" in result.stderr


def test_ci_job_drift_fails(tmp_path: Path) -> None:
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text())
    workflow["jobs"].pop("security")
    path = tmp_path / "ci.yml"
    path.write_text(yaml.safe_dump(workflow, sort_keys=False), encoding="utf-8")

    result = _run("--skip-claude-settings", "--ci-workflow", path)

    assert result.returncode == 1
    assert "ci jobs drift" in result.stderr
