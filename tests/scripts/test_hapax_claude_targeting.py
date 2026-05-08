"""Regression tests for Claude coordinator target selection."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
SEND = REPO_ROOT / "scripts" / "hapax-claude-send"
HEALTH = REPO_ROOT / "scripts" / "hapax-claude-health"


def _write_exe(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def _env(tmp_path: Path, bin_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["XDG_CACHE_HOME"] = str(tmp_path / ".cache")
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return env


def test_send_rejects_stale_tmux_shell_as_claude_target(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "tmux.log"
    _write_exe(
        bin_dir / "tmux",
        f"""#!/usr/bin/env bash
echo "$*" >> {log}
case "$1" in
  has-session) exit 0 ;;
  display-message) echo fish; exit 0 ;;
  *) exit 0 ;;
esac
""",
    )
    _write_exe(bin_dir / "hyprctl", "#!/usr/bin/env bash\nprintf '[]\\n'\n")

    result = subprocess.run(
        [
            "bash",
            str(SEND),
            "--session",
            "alpha",
            "--transport",
            "auto",
            "--no-submit",
            "--",
            "msg",
        ],
        capture_output=True,
        text=True,
        env=_env(tmp_path, bin_dir),
        timeout=5,
    )

    assert result.returncode == 11
    assert "pane_current_command=fish" in result.stderr
    assert "load-buffer" not in log.read_text(encoding="utf-8")


def test_send_falls_back_to_visible_foot_title_when_tmux_is_absent(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sent = tmp_path / "sent.txt"
    shortcuts = tmp_path / "shortcuts.log"
    _write_exe(
        bin_dir / "tmux",
        """#!/usr/bin/env bash
case "$1" in
  has-session) exit 1 ;;
  *) exit 1 ;;
esac
""",
    )
    _write_exe(
        bin_dir / "hyprctl",
        f"""#!/usr/bin/env bash
if [ "$1" = "clients" ]; then
  cat <<'JSON'
[{{"class":"foot","title":"✳ alpha","address":"0xabc","at":[0,0],"size":[1200,800]}}]
JSON
  exit 0
fi
if [ "$1" = "dispatch" ]; then
  echo "$*" >> {shortcuts}
  echo ok
  exit 0
fi
if [ "$1" = "activewindow" ]; then
  echo '{{"address":"0xabc"}}'
  exit 0
fi
exit 1
""",
    )
    _write_exe(bin_dir / "wl-copy", f"#!/usr/bin/env bash\ncat > {sent}\n")
    _write_exe(bin_dir / "wl-paste", "#!/usr/bin/env bash\nexit 1\n")

    result = subprocess.run(
        [
            "bash",
            str(SEND),
            "--session",
            "alpha",
            "--transport",
            "auto",
            "--no-submit",
            "--",
            "msg",
        ],
        capture_output=True,
        text=True,
        env=_env(tmp_path, bin_dir),
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert sent.read_text(encoding="utf-8") == "msg"
    assert "sendshortcut" in shortcuts.read_text(encoding="utf-8")


def test_health_reports_visible_title_and_stale_tmux(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_exe(
        bin_dir / "tmux",
        """#!/usr/bin/env bash
case "$1" in
  has-session) exit 0 ;;
  display-message) echo fish; exit 0 ;;
  *) exit 1 ;;
esac
""",
    )
    _write_exe(
        bin_dir / "hyprctl",
        """#!/usr/bin/env bash
cat <<'JSON'
[{"class":"foot","title":"✳ alpha","address":"0xabc"}]
JSON
""",
    )

    result = subprocess.run(
        [str(HEALTH), "alpha"],
        capture_output=True,
        text=True,
        env=_env(tmp_path, bin_dir),
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "alpha: tmux=False foot=True" in result.stdout
    assert "stale_tmux_not_claude:fish" in result.stdout
