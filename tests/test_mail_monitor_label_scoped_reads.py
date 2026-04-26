"""CI guard: mail-monitor Gmail API calls must be label-scoped to Hapax/*.

Per cc-task ``mail-monitor-refused-out-of-label-read`` (mail-monitoring
research §Anti-patterns #6 — most load-bearing of the seven mail-
monitor refusals).

The OAuth scope ``gmail.modify`` does not natively scope-restrict to
labels; the daemon's discipline is the sole guarantee that operator's
non-Hapax mail (personal correspondence, etc.) stays unread.

This guard enforces scope-control mechanism #3 of 5: "Daemon code
never calls ``messages.list`` without ``q:label:Hapax/*``."

Phase 1 (this guard) ships a regex-based static scan. Phase 2 will
add AST-based depth checking + a mocked-Gmail-API integration test.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

MAIL_MONITOR_PATH: Final[str] = "agents/mail_monitor"


_MESSAGES_LIST_RE = re.compile(
    r"messages\(\s*\)\s*\.\s*list\s*\((?P<args>[^)]*)\)",
    re.DOTALL,
)
"""Match ``messages().list(...)`` calls (Gmail API client chain
shape); capture the args substring for q-parameter inspection."""

_THREADS_RE = re.compile(r"threads\(\s*\)\s*\.\s*(list|get)\s*\(")
"""Threads cross labels by design — any ``threads().list()`` /
``threads().get()`` call is forbidden in mail_monitor."""

_HISTORY_LIST_RE = re.compile(
    r"history\(\s*\)\s*\.\s*list\s*\((?P<args>[^)]*)\)",
    re.DOTALL,
)
"""``history().list(...)`` must include ``labelId=`` argument scoped
to a Hapax label."""


def _scan_unsafe_gmail_calls(
    *,
    repo_root: Path = REPO_ROOT,
) -> list[tuple[Path, int, str, str]]:
    """Walk mail_monitor for unsafe Gmail API call patterns.

    Returns ``(path, line_no, kind, line)`` tuples for matches.
    """
    findings: list[tuple[Path, int, str, str]] = []
    scope = repo_root / MAIL_MONITOR_PATH
    if not scope.is_dir():
        return findings
    for py_file in scope.rglob("*.py"):
        try:
            text = py_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        # threads.* are never permitted
        for line_no, line in enumerate(text.splitlines(), 1):
            if _THREADS_RE.search(line):
                findings.append((py_file, line_no, "threads", line.strip()))

        # messages().list(...) without label:Hapax in args
        for match in _MESSAGES_LIST_RE.finditer(text):
            args = match.group("args") or ""
            if "label:Hapax" not in args:
                line_no = text[: match.start()].count("\n") + 1
                findings.append((py_file, line_no, "messages.list", match.group(0).strip()))

        # history().list(...) without labelId=
        for match in _HISTORY_LIST_RE.finditer(text):
            args = match.group("args") or ""
            if "labelId" not in args:
                line_no = text[: match.start()].count("\n") + 1
                findings.append((py_file, line_no, "history.list", match.group(0).strip()))
    return findings


class TestMailMonitorLabelScopedReads:
    def test_mail_monitor_only_label_scoped_gmail_calls(self) -> None:
        """All Gmail API list/get calls in mail_monitor must be scoped to Hapax/*."""
        findings = _scan_unsafe_gmail_calls()
        assert findings == [], (
            "Out-of-label Gmail API calls detected in mail_monitor:\n"
            + "\n".join(
                f"  {path}:{line_no} ({kind}): {snippet}"
                for path, line_no, kind, snippet in findings
            )
            + "\n\n"
            "Per mail-monitor-refused-out-of-label-read, the daemon must NEVER "
            "call messages.list without q:label:Hapax/*, must NEVER use "
            "threads.* (threads cross labels), and must NEVER call history.list "
            "without labelId=. The OAuth scope is mailbox-wide; daemon "
            "discipline is the sole privacy guarantee."
        )

    def test_scanner_detects_unscoped_messages_list(self, tmp_path: Path) -> None:
        """Self-test: planted unscoped messages.list call is detected."""
        mm_dir = tmp_path / "agents" / "mail_monitor"
        mm_dir.mkdir(parents=True)
        bad_file = mm_dir / "bad.py"
        bad_file.write_text(
            "def fetch():\n"
            '    return service.users().messages().list(q="from:operator@example.com").execute()\n'
        )
        findings = _scan_unsafe_gmail_calls(repo_root=tmp_path)
        assert any(kind == "messages.list" for _, _, kind, _ in findings)

    def test_scanner_passes_label_scoped_messages_list(self, tmp_path: Path) -> None:
        """Self-test: properly-scoped messages.list is NOT flagged."""
        mm_dir = tmp_path / "agents" / "mail_monitor"
        mm_dir.mkdir(parents=True)
        ok_file = mm_dir / "ok.py"
        ok_file.write_text(
            "def fetch():\n"
            '    return service.users().messages().list(q="label:Hapax/Verify").execute()\n'
        )
        findings = _scan_unsafe_gmail_calls(repo_root=tmp_path)
        assert findings == []

    def test_scanner_detects_threads_call(self, tmp_path: Path) -> None:
        """Self-test: any threads.list / threads.get call is flagged."""
        mm_dir = tmp_path / "agents" / "mail_monitor"
        mm_dir.mkdir(parents=True)
        bad_file = mm_dir / "bad.py"
        bad_file.write_text("def fetch():\n    return service.users().threads().list().execute()\n")
        findings = _scan_unsafe_gmail_calls(repo_root=tmp_path)
        assert any(kind == "threads" for _, _, kind, _ in findings)

    def test_scanner_detects_unscoped_history_list(self, tmp_path: Path) -> None:
        """Self-test: history.list without labelId is flagged."""
        mm_dir = tmp_path / "agents" / "mail_monitor"
        mm_dir.mkdir(parents=True)
        bad_file = mm_dir / "bad.py"
        bad_file.write_text(
            'def fetch():\n    return service.users().history().list(startHistoryId="123").execute()\n'
        )
        findings = _scan_unsafe_gmail_calls(repo_root=tmp_path)
        assert any(kind == "history.list" for _, _, kind, _ in findings)
