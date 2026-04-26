"""CI guard: no ntfy ``X-Actions`` headers or action-button payloads.

Per cc-task ``awareness-refused-ntfy-action-buttons`` (drop-6 §10
anti-pattern #2): ntfy "tap-to-act" buttons
(``X-Actions: action=http,...``) are in-loop by construction. Every
button creates an action point that requires operator-physical
decision on the phone screen.

Existing ntfy use (disk-full alerts, hard-fail publication, etc.)
remains permitted — but as **plain notifications**, never with
action buttons. This guard scans the repo for any ntfy POST
pattern that includes ``X-Actions`` or ``actions[``-style action
arrays.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

SCAN_ROOTS: Final[tuple[str, ...]] = (
    "agents",
    "shared",
    "scripts",
    "logos",
)
"""Source-code directories scanned. Tests are excluded; this guard
file itself defines the patterns and would self-match."""

EXCLUDE_FILE_NAMES: Final[frozenset[str]] = frozenset(
    {
        # Brief itself documents the forbidden patterns
        "awareness-ntfy-action-buttons.md",
    }
)


_NTFY_ACTION_HEADER_RE = re.compile(r'["\']X-Actions["\']\s*[:=]')
"""Match a literal ``X-Actions`` HTTP header in code (string-keyed)."""

_NTFY_ACTIONS_PAYLOAD_RE = re.compile(
    r'["\']actions["\']\s*:\s*\[',
)
"""Match a JSON ``"actions": [`` key in code (the ntfy v2 action-array
shape)."""


def _scan_for_ntfy_action_buttons(
    *,
    repo_root: Path = REPO_ROOT,
) -> list[tuple[Path, int, str]]:
    """Walk source roots looking for ntfy action-button patterns.

    Returns a list of ``(path, line_no, line)`` tuples for matches.
    """
    findings: list[tuple[Path, int, str]] = []
    for root_name in SCAN_ROOTS:
        root = repo_root / root_name
        if not root.is_dir():
            continue
        for py_file in root.rglob("*.py"):
            if py_file.name in EXCLUDE_FILE_NAMES:
                continue
            try:
                text = py_file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            # Restrict to lines that mention ntfy in context to avoid
            # false-positives from unrelated `actions: [...]` arrays
            # (the surface registry, the awareness doc, etc.).
            mentions_ntfy = "ntfy" in text.lower()
            if not mentions_ntfy:
                continue
            for line_no, line in enumerate(text.splitlines(), 1):
                # Comments are documentation; not actionable code
                stripped = line.lstrip()
                if stripped.startswith("#") or stripped.startswith('"'):
                    continue
                if _NTFY_ACTION_HEADER_RE.search(line) or _NTFY_ACTIONS_PAYLOAD_RE.search(line):
                    findings.append((py_file, line_no, line.strip()))
    return findings


class TestForbiddenNtfyActionButtons:
    def test_codebase_has_no_ntfy_action_buttons(self) -> None:
        """Codebase must not include ntfy X-Actions headers or
        actions[]-array payloads.

        Existing plain ntfy notifications are permitted; only the
        action-button affordances (which create operator-physical
        decision points) are refused.
        """
        findings = _scan_for_ntfy_action_buttons()
        assert findings == [], (
            "ntfy action-button patterns detected:\n"
            + "\n".join(f"  {path}:{line_no}: {snippet}" for path, line_no, snippet in findings)
            + "\n\n"
            "Per awareness-refused-ntfy-action-buttons (drop-6 §10 #2), "
            "ntfy notifications must be plain — no X-Actions headers "
            "and no actions[] arrays. Use the daemon's decision logic, "
            "not operator-physical phone-tap decisions."
        )

    def test_scanner_detects_x_actions_header(self, tmp_path: Path) -> None:
        """Self-test: planted X-Actions header in ntfy code is detected."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        bad_file = agents_dir / "bad_ntfy.py"
        bad_file.write_text(
            "import requests\n"
            "def alert():\n"
            '    requests.post("https://ntfy.sh/topic", headers={"X-Actions": "view, View, https://example.com"})\n'
        )
        findings = _scan_for_ntfy_action_buttons(repo_root=tmp_path)
        assert len(findings) == 1

    def test_scanner_detects_actions_array(self, tmp_path: Path) -> None:
        """Self-test: planted actions array in ntfy POST is detected."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        bad_file = agents_dir / "bad_ntfy.py"
        bad_file.write_text(
            "import requests\n"
            "def alert():\n"
            '    body = {"topic": "x", "actions": [{"action": "view"}]}\n'
            "    requests.post('https://ntfy.sh', json=body)\n"
        )
        findings = _scan_for_ntfy_action_buttons(repo_root=tmp_path)
        assert len(findings) == 1

    def test_scanner_skips_non_ntfy_files(self, tmp_path: Path) -> None:
        """Self-test: ``actions: [`` in unrelated code (no ntfy mention)
        is NOT flagged."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        unrelated_file = agents_dir / "unrelated.py"
        unrelated_file.write_text('config = {"actions": [{"name": "scrape"}]}\n')
        findings = _scan_for_ntfy_action_buttons(repo_root=tmp_path)
        assert findings == []

    def test_scanner_skips_plain_ntfy_notifications(self, tmp_path: Path) -> None:
        """Self-test: ntfy POST without action buttons is NOT flagged."""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        ok_file = agents_dir / "ok_ntfy.py"
        ok_file.write_text(
            "import requests\n"
            "def alert(message):\n"
            '    requests.post("https://ntfy.sh/topic", data=message)\n'
        )
        findings = _scan_for_ntfy_action_buttons(repo_root=tmp_path)
        assert findings == []
