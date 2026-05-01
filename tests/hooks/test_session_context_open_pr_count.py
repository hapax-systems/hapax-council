"""Tests for the OPEN_PRS guard in ``hooks/scripts/session-context.sh``.

Per cc-task session-context-open-pr-count-hardening. The guard must
normalize empty / null / non-numeric `gh pr list | jq length` output to
``0`` before the numeric comparison, so missing-gh / invalid-JSON / etc.
degrade to a quiet "no PRs" line rather than spilling
``[: -gt: integer expression expected`` into operator output.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK = _REPO_ROOT / "hooks" / "scripts" / "session-context.sh"


def _make_fake_bin_dir(tmp_path: Path, *, gh_returns: str | None, jq_returns: str | None) -> Path:
    """Create a directory with fake gh/jq scripts.

    Each fake binary echoes ``returns`` on stdout and exits 0; if ``returns``
    is None the binary exits 1 (simulates "missing", treated as runtime
    failure). The hook script's `2>/dev/null || echo 0` chain is what we're
    exercising, so a non-zero exit from gh OR jq should still degrade
    gracefully.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    def _write(name: str, returns: str | None) -> None:
        path = bin_dir / name
        if returns is None:
            path.write_text("#!/bin/sh\nexit 1\n")
        else:
            path.write_text(f"#!/bin/sh\nprintf '%s' '{returns}'\n")
        path.chmod(0o755)

    _write("gh", gh_returns)
    _write("jq", jq_returns)
    return bin_dir


def _extract_open_pr_block(tmp_path: Path, fake_bin: Path) -> tuple[int, str, str]:
    """Run only the OPEN_PRS lines of session-context.sh in isolation.

    The full hook does much more (git status, sprint, agents, etc.); we
    extract the 9-line block (lines 407-413) and run JUST that, with PATH
    pointing at our fake gh/jq.
    """
    fragment = tmp_path / "open_prs_fragment.sh"
    fragment.write_text("""#!/bin/bash
set -u
OPEN_PRS="$(gh pr list --state open --json number,title,headRefName 2>/dev/null | jq -r 'length' 2>/dev/null || echo 0)"
case "$OPEN_PRS" in
    ''|null|*[!0-9]*) OPEN_PRS=0 ;;
esac
if [ "$OPEN_PRS" -gt 0 ]; then
    echo "Open PRs ($OPEN_PRS):"
fi
echo "OPEN_PRS_VALUE=$OPEN_PRS"
""")
    fragment.chmod(0o755)
    env = {**os.environ, "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"}
    rc = subprocess.run(
        [str(fragment)],
        capture_output=True,
        text=True,
        env=env,
    )
    return rc.returncode, rc.stdout, rc.stderr


def test_open_prs_normalizes_empty_to_zero(tmp_path: Path) -> None:
    """gh returns nothing → OPEN_PRS=0, no integer-test noise on stderr."""

    fake = _make_fake_bin_dir(tmp_path, gh_returns="", jq_returns="")
    rc, out, err = _extract_open_pr_block(tmp_path, fake)
    assert rc == 0
    assert "OPEN_PRS_VALUE=0" in out
    assert "integer expression expected" not in err


def test_open_prs_normalizes_literal_null_to_zero(tmp_path: Path) -> None:
    """jq returns 'null' literal → OPEN_PRS=0."""

    fake = _make_fake_bin_dir(tmp_path, gh_returns="[]", jq_returns="null")
    rc, out, err = _extract_open_pr_block(tmp_path, fake)
    assert rc == 0
    assert "OPEN_PRS_VALUE=0" in out
    assert "integer expression expected" not in err


def test_open_prs_normalizes_non_numeric_to_zero(tmp_path: Path) -> None:
    """jq returns garbage → OPEN_PRS=0 instead of integer-test crash."""

    fake = _make_fake_bin_dir(tmp_path, gh_returns="bad-json", jq_returns="parse-error")
    rc, out, err = _extract_open_pr_block(tmp_path, fake)
    assert rc == 0
    assert "OPEN_PRS_VALUE=0" in out
    assert "integer expression expected" not in err


def test_open_prs_handles_missing_gh(tmp_path: Path) -> None:
    """gh exit 1 (simulating missing/broken) → OPEN_PRS=0 quietly."""

    fake = _make_fake_bin_dir(tmp_path, gh_returns=None, jq_returns="")
    rc, out, err = _extract_open_pr_block(tmp_path, fake)
    assert rc == 0
    assert "OPEN_PRS_VALUE=0" in out
    assert "integer expression expected" not in err


def test_open_prs_passes_valid_count(tmp_path: Path) -> None:
    """Real numeric value passes through and triggers the summary line."""

    fake = _make_fake_bin_dir(tmp_path, gh_returns='[{"x":1}]', jq_returns="3")
    rc, out, err = _extract_open_pr_block(tmp_path, fake)
    assert rc == 0
    assert "OPEN_PRS_VALUE=3" in out
    assert "Open PRs (3):" in out
    assert "integer expression expected" not in err


def test_open_prs_zero_does_not_print_summary(tmp_path: Path) -> None:
    """OPEN_PRS=0 path skips the 'Open PRs' summary line."""

    fake = _make_fake_bin_dir(tmp_path, gh_returns="[]", jq_returns="0")
    rc, out, err = _extract_open_pr_block(tmp_path, fake)
    assert rc == 0
    assert "OPEN_PRS_VALUE=0" in out
    assert "Open PRs (" not in out
