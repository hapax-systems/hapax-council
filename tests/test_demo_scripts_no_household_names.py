"""Regression guard for the household-name-exposure gap scrub.

Reuses the installed matcher ``scripts/check-legal-name-leaks.sh`` — which reads
registered given names from the LOCAL registry at runtime and the legal name from
its own patterns — rather than embedding any name literal. The scrubbed demo
scripts must stay free of registered/legal names. On a host without the local
registry (CI, fresh clones) the scanner falls back to the legal-name patterns
only, so the test still enforces the surname guard and never sees a given name.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCANNER = ROOT / "scripts" / "check-legal-name-leaks.sh"

# The demo surface this row's gap scrub cleaned (opaque-id names only).
SCRUBBED = (
    "scripts/render_principal_c1_demo.py",
    "hapax-logos/src/demo/scripts/principal-c1.ts",
)


def test_scrubbed_demo_scripts_carry_no_registered_or_legal_name() -> None:
    for rel in SCRUBBED:
        assert (ROOT / rel).is_file(), f"expected scrubbed file is missing: {rel}"
    proc = subprocess.run(
        ["bash", str(SCANNER), *SCRUBBED],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    # Exit 0 == no leak. The scanner withholds names/paths (path_sha256 only), so
    # its stderr is safe to surface on failure.
    assert proc.returncode == 0, proc.stderr
