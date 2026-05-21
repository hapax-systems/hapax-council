"""Static check: launcher-generated bootstrap text must not contain stale self-claim instructions."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

LAUNCHERS = [
    REPO_ROOT / "scripts" / "hapax-antigrav",
    REPO_ROOT / "scripts" / "hapax-vibe",
]

FORBIDDEN_PATTERNS = [
    "self-claim highest",
    "self-select highest",
    "self-claim.*highest.*WSJF",
]


@pytest.mark.parametrize(
    "launcher",
    [p for p in LAUNCHERS if p.exists()],
    ids=lambda p: p.name,
)
def test_no_stale_self_claim_instructions(launcher: Path) -> None:
    text = launcher.read_text()
    for pattern in FORBIDDEN_PATTERNS:
        import re

        assert not re.search(pattern, text, re.IGNORECASE), (
            f"{launcher.name} contains stale self-claim pattern: {pattern!r}"
        )


@pytest.mark.parametrize(
    "launcher",
    [p for p in LAUNCHERS if p.exists()],
    ids=lambda p: p.name,
)
def test_no_fail_open_task_pickup(launcher: Path) -> None:
    text = launcher.read_text()
    assert "self-claim highest eligible WSJF" not in text, (
        f"{launcher.name} contains fail-open WSJF self-claim instruction"
    )
