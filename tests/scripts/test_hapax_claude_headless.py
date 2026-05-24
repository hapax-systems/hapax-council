import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-claude-headless"
VISIBLE = REPO_ROOT / "scripts" / "hapax-claude"


def test_headless_defaults_to_disabled_without_governed_enable(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = "/usr/bin:/bin"
    env.pop("HAPAX_CLAUDE_HEADLESS_ALLOW", None)
    env.pop("HAPAX_CLAUDE_HEADLESS_ENABLE_FILE", None)

    result = subprocess.run(
        [str(SCRIPT), "beta", "governed prompt"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 77
    assert "disabled until governed enable exists" in result.stderr


def test_headless_source_prepends_workdir_scripts_to_path() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'PATH="$WORKDIR/scripts:$PATH"' in text, (
        "headless wrapper must prepend $WORKDIR/scripts to PATH"
    )


def test_headless_source_contains_no_generic_work_pool_prompt() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "claim the next" not in text
    assert "highest-WSJF" not in text
    assert "Never stop" not in text
    assert "governed initial message required" in text
    assert "refusing mutating launch without --task" in text
    assert "Do not create, select, or claim other work from the task pool." in text
    assert "--task TASK_ID" in text
    assert "HAPAX_METHODOLOGY_DISPATCH_TASK" in text


def test_headless_source_supports_governed_model_profile_env() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'MODEL="${HAPAX_CLAUDE_MODEL:-}"' in text
    assert 'CLAUDE_ARGS+=(--model "$MODEL")' in text


def test_visible_claude_launcher_requires_task_or_readonly() -> None:
    text = VISIBLE.read_text(encoding="utf-8")

    assert "--task TASK_ID|--readonly" in text
    assert "refusing mutating visible lane without governed task binding" in text
    assert "hapax-methodology-dispatch" in text
    assert "HAPAX_METHODOLOGY_DISPATCH_TASK" in text
    assert 'CLAUDE_TASK="$CLAIMED_TASK"' in text


def test_headless_refuses_without_task_or_existing_claim(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "projects" / "hapax-council--beta").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    claude = bin_dir / "claude"
    claude.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    claude.chmod(0o755)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    env["HAPAX_CLAUDE_HEADLESS_ALLOW"] = "1"

    result = subprocess.run(
        [str(SCRIPT), "beta", "Task: fake\nAuthorityCase: fake\nParent spec: fake"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 15
    assert "without --task" in result.stderr
