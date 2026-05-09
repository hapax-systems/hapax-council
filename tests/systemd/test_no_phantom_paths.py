"""Regression gate: no systemd unit may reference the phantom path
``~/.local/share/hapax-council`` or use ``.venv/bin/python`` directly
in combination with that path.

The phantom path was never provisioned. The 8 audio services that
referenced it are fixed by AVSDLC-002-S9 (CASE-AVSDLC-001) to use
the rebuild worktree with ``uv run``.

The broader ``.venv/bin/python`` migration for all services is tracked
under CASE-SDLC-REFORM-001 (consumer audit plan). This test gates only
the phantom path and prevents new services from combining
``.venv/bin/python`` with non-canonical worktree paths.
"""

from __future__ import annotations

from pathlib import Path

UNITS_DIR = Path(__file__).resolve().parents[2] / "systemd" / "units"


def _unit_files() -> list[Path]:
    return sorted(p for p in UNITS_DIR.iterdir() if p.suffix in {".service", ".timer", ".target"})


def test_no_phantom_local_share_path() -> None:
    offenders: list[tuple[str, int, str]] = []
    for unit in _unit_files():
        for i, line in enumerate(unit.read_text().splitlines(), 1):
            if ".local/share/hapax-council" in line and not line.lstrip().startswith("#"):
                offenders.append((unit.name, i, line.strip()))
    assert not offenders, (
        "Unit file(s) reference the phantom path ~/.local/share/hapax-council "
        f"which was never provisioned: {offenders}"
    )


def test_no_venv_python_with_phantom_path() -> None:
    offenders: list[tuple[str, int, str]] = []
    for unit in _unit_files():
        text = unit.read_text()
        if ".local/share/hapax-council" not in text:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if ".venv/bin/python" in line and not line.lstrip().startswith("#"):
                offenders.append((unit.name, i, line.strip()))
    assert not offenders, (
        f"Unit file(s) combine .venv/bin/python with the phantom path: {offenders}"
    )
