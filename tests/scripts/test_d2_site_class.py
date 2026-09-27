"""D2 red-before-green: site-class semantics, not host-name inheritance.

G1 census defect: `HAPAX_LOCAL_DEV_MAINTENANCE_MODE=appendix-only` folds
`remote`/`thin-client` into the *same suppress class* as appendix via host-name
string matching. Successor: explicit site classes. `remote-client` keeps the
same suppress *policy* (thin clients do not launch local lanes) but is a
distinct class so a future policy split is one map entry.

These tests fail on the literal host-name fold and pass once `site_class`
distinguishes the two.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR = REPO_ROOT / "scripts" / "hapax-lane-supervisor"
WATCHDOG = REPO_ROOT / "scripts" / "hapax-lane-idle-watchdog"


def _site_class(script: Path, mode: str) -> str:
    """Return ``site_class`` output for ``mode`` without running the whole script.

    Sourcing just the function keeps the probe off the real vault/launchers.
    """
    result = subprocess.run(
        [
            "bash",
            "-c",
            (
                f'source <(sed -n "/^site_class()/,/^}}/p" "{script}")\n'
                f'HAPAX_LOCAL_DEV_MAINTENANCE_MODE="{mode}"\n'
                f"unset HAPAX_DEFAULT_DISPATCH_HOST HAPAX_DISPATCH_HOST\n"
                f"site_class\n"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_supervisor_site_class_remote_client_is_not_appendix_only() -> None:
    """thin-client must classify as remote-client, not appendix-only."""
    assert _site_class(SUPERVISOR, "thin-client") == "remote-client"


def test_supervisor_site_class_remote_is_not_appendix_only() -> None:
    """remote must classify as remote-client, not appendix-only."""
    assert _site_class(SUPERVISOR, "remote") == "remote-client"


def test_supervisor_site_class_appendix_stays_appendix_only() -> None:
    """appendix identifiers still map to the appendix-only class."""
    for mode in ("appendix-only", "appendix", "hapax-appendix"):
        assert _site_class(SUPERVISOR, mode) == "appendix-only", mode


def test_supervisor_site_class_default_is_local() -> None:
    """Unknown mode is the local site class (maintains and launches)."""
    assert _site_class(SUPERVISOR, "local") == "local"


def test_watchdog_site_class_remote_client_is_not_appendix_only() -> None:
    """idle-watchdog uses the same site-class map."""
    assert _site_class(WATCHDOG, "thin-client") == "remote-client"


def test_watchdog_site_class_appendix_stays_appendix_only() -> None:
    assert _site_class(WATCHDOG, "appendix-only") == "appendix-only"
