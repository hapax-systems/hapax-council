"""Regression guard for the household-name-exposure gap scrub.

Reuses the installed matcher ``scripts/check-legal-name-leaks.sh``. It GLOBS the
demo-script surfaces (self-maintaining — a new demo file is covered automatically)
rather than a hardcoded list, and asserts they carry no registered/legal name.

Scope (seat ruling 2026-10-04, #5024 re-round): the repo-wide, registered-given-name
half of the guard is enforced by the pre-push hook
(``hooks/scripts/name-leak-pre-push.sh``, ``--diff`` against the LOCAL registry), which
every estate-lane push runs; names are never sent to a third party, so CI carries no
registry and the CI guard step skips with an explicit reason. On a host without the
local registry (CI, fresh clones) this test's scanner therefore enforces the
legal-name patterns across the demo surfaces; the given-name half is the pre-push
hook's. ``check-legal-name-leaks.sh --all`` is the audit tool for the legacy-corpus
scrub follow-up.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCANNER = ROOT / "scripts" / "check-legal-name-leaks.sh"

# The demo-script surfaces the gap scrub cleaned, matched by glob so the list does
# not drift as demo files are added or renamed.
DEMO_GLOBS = ("hapax-logos/src/demo/scripts/*.ts", "scripts/render_*_demo.py")


def _demo_surfaces() -> list[str]:
    return sorted({p.relative_to(ROOT).as_posix() for g in DEMO_GLOBS for p in ROOT.glob(g)})


def test_demo_surfaces_carry_no_registered_or_legal_name() -> None:
    surfaces = _demo_surfaces()
    assert surfaces, (
        "no demo surfaces matched the globs, so nothing is being guarded. "
        "Next action: confirm hapax-logos/src/demo/scripts/*.ts and "
        "scripts/render_*_demo.py exist, or update DEMO_GLOBS in this test."
    )
    proc = subprocess.run(
        ["bash", str(SCANNER), *surfaces],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    # Exit 0 == no leak. The scanner withholds names/paths (path_sha256 only), so its
    # stderr is safe to surface on failure.
    assert proc.returncode == 0, (
        "a household/legal name was found in a demo surface. Next action: scrub it to "
        "the opaque principal-<id> vocabulary (see gap-scrub PR #5024) and re-run. "
        f"Scanner output (names/paths withheld):\n{proc.stderr}"
    )
