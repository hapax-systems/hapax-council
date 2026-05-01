"""Cross-cutting pin: no systemd unit file in repo shadows a DECOMMISSIONED entry.

The install-units.sh script maintains a ``DECOMMISSIONED_UNITS`` array of
unit names that get actively removed + disabled + masked from
``~/.config/systemd/user/`` on every install run. Two parallel concerns
must stay in sync:

1. **install-units.sh** treats the unit name as decommissioned: skips
   linking + actively cleans existing symlinks + masks.
2. **hapax-post-merge-deploy** copies any modified ``systemd/units/*.service``
   file to the user systemd dir and tries to restart it.

If a unit file with a DECOMMISSIONED basename re-appears in
``systemd/units/``, the two scripts disagree: install-units skips it
(safe), but hapax-post-merge-deploy copies + restarts (unsafe). The
unit was decommissioned for a reason and shouldn't come back via the
deploy path either.

This test enforces the invariant: every name in ``DECOMMISSIONED_UNITS``
must be absent from ``systemd/units/``.

Existing per-decommission pins (``test_tauri_logos_decommission.py``,
``test_tabbyapi_hermes8b_decommission.py``,
``test_discord_webhook_decommission.py``) each enforce this for one
specific unit; this test is the cross-cutting pin so future
decommissions are caught even if their per-unit test forgot the
file-absence assertion.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SCRIPT = REPO_ROOT / "systemd" / "scripts" / "install-units.sh"
UNITS_DIR = REPO_ROOT / "systemd" / "units"


def _parse_decommissioned_units(script_body: str) -> list[str]:
    """Extract the DECOMMISSIONED_UNITS bash array entries.

    The array shape is::

        DECOMMISSIONED_UNITS=(
            unit-name.service
            other.path
            ...
        )

    We grep for the array opener and take every non-blank, non-comment
    line until the closing paren.
    """
    match = re.search(r"DECOMMISSIONED_UNITS=\(\n(.*?)\n\)", script_body, re.DOTALL)
    assert match, "DECOMMISSIONED_UNITS=(...) array not found in install-units.sh"
    units = []
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        units.append(line)
    return units


def test_decommissioned_units_array_is_parseable() -> None:
    body = INSTALL_SCRIPT.read_text(encoding="utf-8")
    units = _parse_decommissioned_units(body)
    assert units, (
        "DECOMMISSIONED_UNITS array is empty — at minimum the historical retirements should be present"
    )
    # Sanity: each entry should look like a systemd unit name.
    for name in units:
        assert re.match(r"^[a-zA-Z0-9_-]+\.(service|timer|path|target)$", name), (
            f"DECOMMISSIONED_UNITS entry {name!r} doesn't look like a systemd unit name"
        )


def test_no_decommissioned_unit_shadows_in_repo() -> None:
    """Every DECOMMISSIONED unit name must be absent from systemd/units/.

    A unit file appearing in repo while its name is in DECOMMISSIONED_UNITS
    is a contradictory state: install-units.sh skips it but
    hapax-post-merge-deploy installs it.
    """
    body = INSTALL_SCRIPT.read_text(encoding="utf-8")
    units = _parse_decommissioned_units(body)
    shadows = [name for name in units if (UNITS_DIR / name).exists()]
    assert not shadows, (
        f"Decommissioned units shadow-resurrected in systemd/units/: {shadows}. "
        "Either remove the file (preferred) or remove the name from "
        "DECOMMISSIONED_UNITS in install-units.sh + delete the per-decommission "
        "regression test. Two scripts disagree on the file's status."
    )


def test_known_decommissioned_units_present() -> None:
    """Spot-check: the historically-decommissioned units stay listed.

    Prevents accidental DECOMMISSIONED_UNITS array corruption that would
    let a long-retired unit re-appear without anyone noticing.
    """
    body = INSTALL_SCRIPT.read_text(encoding="utf-8")
    units = set(_parse_decommissioned_units(body))
    # Tauri/WebKit retirement (PR #1080-area)
    assert "hapax-logos.service" in units
    assert "logos-dev.service" in units
    # Hermes8B retirement (cc-task retire-tabbyapi-hermes8b-audit-unit, PR #1950)
    assert "tabbyapi-hermes8b.service" in units
    # Future retirements add their own per-unit pins (e.g.
    # ``test_discord_webhook_decommission.py``); the cross-cutting
    # invariants above (array parses, no shadows) cover them at the
    # cross-decommission level without needing per-unit assertions in
    # this file.
