"""CI guard: nothing that loads mail-monitor credentials may send mail.

WHY THIS EXISTS ALONGSIDE ``test_forbidden_mail_monitor_send_imports.py``

That guard is **directory-scoped** — it scans only ``agents/mail_monitor/`` and
says so in its own docstring. kimi/auditor's 2026-08-18 audit showed the scope is
insufficient in two independent ways:

1. ``gmail.modify`` is send-sufficient per Google's scope table, so "the daemon
   holds no send scope" was never a real defence.
2. A working send vector already exists **outside** that directory:
   ``scripts/send-stakeholder-revenue-brief.py`` imports
   ``agents.mail_monitor.oauth.load_credentials`` and calls
   ``service.users().messages().send(...)``. The directory guard cannot see it.

The existing guard also only catches SMTP *library imports*. It is blind to the
Gmail API send path, to draft creation, and to direct REST — which is how the one
real vector in this repo actually sends.

So this guard is scoped by **credential** rather than by directory: any file that
loads mail-monitor Google credentials, anywhere in the tree, must not contain a
send vector. That follows the capability rather than the file layout, which is
the property that actually matters.

## The quarantine, and why it is not a hole

``scripts/send-stakeholder-revenue-brief.py`` is a real, implemented, dormant
send vector (manual ``--send``, never scheduled). Its disposition is an open
question in kimi's audit — one of the listed preconditions for re-authorising
mail-monitor at all — so this guard does NOT delete it and does not pretend it is
absent. It is **quarantined**: named, enumerable, and asserted to still exist.

The point is the *derivative*: today's set of send vectors is frozen at exactly
one, and a second one cannot appear without turning this suite red. An allowlist
that is never checked for staleness rots into a permanent exemption, so
``test_quarantine_has_not_rotted`` fails if a quarantined file stops existing or
stops containing a vector — forcing the entry to be removed rather than
lingering as a silent licence.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

# A file is in scope iff it reaches for mail-monitor Google credentials.
# Anchored on the oauth module and the pass entries rather than a bare
# ``load_credentials``, which false-positives on unrelated code
# (e.g. scripts/youtube-player.py defines its own ``_load_credentials``).
CREDENTIAL_MARKERS: Final[tuple[str, ...]] = (
    "agents.mail_monitor.oauth",
    "from agents.mail_monitor import oauth",
    "mail-monitor/google-refresh-token",
    "mail-monitor/google-client-id",
    "mail-monitor/google-client-secret",
)

# Send vectors, in the shapes this repo could plausibly use. The Gmail API entry
# is first because it is the one that actually exists here — the pre-existing
# guard checked only SMTP libraries and would have missed it.
SEND_VECTORS: Final[tuple[tuple[str, str], ...]] = (
    (r"\.messages\s*\(\s*\)\s*\.\s*send\b", "gmail-api-messages-send"),
    (r"\.drafts\s*\(\s*\)\s*\.\s*(?:create|send)\b", "gmail-api-drafts"),
    (
        r"^\s*(?:from\s+(?:smtplib|aiosmtplib)\s+import|import\s+(?:smtplib|aiosmtplib))\b",
        "smtp-import",
    ),
    (r"\bsendmail\s*\(", "smtp-sendmail"),
    (r"/gmail/v1/users/[^\"']*/messages/send", "gmail-rest-send"),
)

# Repo-relative paths permitted to hold a send vector today. Adding to this set
# is a governance decision, not a convenience: each entry is a live path from
# mail-monitor credentials to an outbound message.
QUARANTINED_SEND_VECTORS: Final[frozenset[str]] = frozenset(
    {
        # Dormant, manual --send only, never scheduled. Disposition is an open
        # precondition in kimi/auditor's 2026-08-18 mail-subsystem audit.
        "scripts/send-stakeholder-revenue-brief.py",
    }
)

SKIP_DIR_PARTS: Final[frozenset[str]] = frozenset(
    {".venv", "node_modules", "__pycache__", ".git", "site-packages"}
)


def _in_scope(text: str) -> bool:
    return any(marker in text for marker in CREDENTIAL_MARKERS)


def _find_send_vectors(text: str) -> list[tuple[str, int, str]]:
    """Return (vector_name, line_no, line) for each send vector in ``text``."""
    hits: list[tuple[str, int, str]] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        for pattern, name in SEND_VECTORS:
            if re.search(pattern, line):
                hits.append((name, line_no, line.strip()))
    return hits


def scan(repo_root: Path = REPO_ROOT) -> dict[str, list[tuple[str, int, str]]]:
    """Map repo-relative path -> send vectors, for credential-loading files only.

    Excludes THIS file specifically. The guard necessarily contains both the
    credential markers and every send-vector shape it hunts — in its docstring
    and in its self-test fixtures, as inert string literals — so it would
    otherwise flag itself and nothing else could ever be green.

    The exclusion is deliberately by exact resolved path rather than by a
    "skip tests/" rule: a test that genuinely loads mail-monitor credentials and
    sends mail IS a violation, and must stay in scope.
    """
    self_path = Path(__file__).resolve()
    findings: dict[str, list[tuple[str, int, str]]] = {}
    for py_file in repo_root.rglob("*.py"):
        if SKIP_DIR_PARTS & set(py_file.parts):
            continue
        if py_file.resolve() == self_path:
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if not _in_scope(text):
            continue
        hits = _find_send_vectors(text)
        if hits:
            findings[str(py_file.relative_to(repo_root))] = hits
    return findings


class TestCredentialScopedSendGuard:
    def test_no_unquarantined_send_vectors(self) -> None:
        """No NEW path from mail-monitor credentials to an outbound message."""
        findings = scan()
        offenders = {p: v for p, v in findings.items() if p not in QUARANTINED_SEND_VECTORS}
        assert offenders == {}, (
            "Send vector(s) found in files that load mail-monitor credentials:\n"
            + "\n".join(
                f"  {path}:{line_no}: {line}  [{name}]"
                for path, hits in sorted(offenders.items())
                for name, line_no, line in hits
            )
            + "\n\n"
            "mail-monitor holds gmail.modify, which IS send-sufficient. A file that "
            "loads those credentials and can send mail is a path from inbound "
            "processing to outbound correspondence the operator never authored — "
            "the management_governance axiom forbids it.\n"
            "If this is deliberate, it needs an entry in QUARANTINED_SEND_VECTORS "
            "and an operator decision recorded, not a silent addition."
        )

    def test_quarantine_has_not_rotted(self) -> None:
        """Every quarantined path must still exist AND still hold a vector.

        Without this, a quarantine entry outlives the thing it excuses and
        becomes a standing licence for a file nobody has looked at in a year.
        """
        findings = scan()
        stale: list[str] = []
        for path in sorted(QUARANTINED_SEND_VECTORS):
            if not (REPO_ROOT / path).exists():
                stale.append(f"{path}: file no longer exists")
            elif path not in findings:
                stale.append(f"{path}: no send vector remains")
        assert stale == [], (
            "QUARANTINED_SEND_VECTORS is stale — remove these entries:\n"
            + "\n".join(f"  {s}" for s in stale)
        )

    def test_the_known_vector_is_still_detected(self) -> None:
        """Pins the audit's actual finding, so a refactor cannot hide it."""
        findings = scan()
        assert "scripts/send-stakeholder-revenue-brief.py" in findings
        names = {name for name, _, _ in findings["scripts/send-stakeholder-revenue-brief.py"]}
        assert "gmail-api-messages-send" in names

    def test_scanner_flags_a_planted_gmail_api_send(self, tmp_path: Path) -> None:
        """Self-test: the vector the OLD guard was blind to is caught."""
        f = tmp_path / "sneaky.py"
        f.write_text(
            "from agents.mail_monitor.oauth import load_credentials\n"
            "service.users().messages().send(userId='me', body={})\n"
        )
        findings = scan(repo_root=tmp_path)
        assert "sneaky.py" in findings
        assert findings["sneaky.py"][0][0] == "gmail-api-messages-send"

    def test_scanner_flags_direct_rest_send(self, tmp_path: Path) -> None:
        """Self-test: bypassing googleapiclient entirely is still caught."""
        f = tmp_path / "rest.py"
        f.write_text(
            "from agents.mail_monitor.oauth import load_credentials\n"
            'httpx.post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send")\n'
        )
        findings = scan(repo_root=tmp_path)
        assert "rest.py" in findings

    def test_scanner_ignores_send_without_mail_monitor_credentials(self, tmp_path: Path) -> None:
        """Self-test: unrelated senders are out of scope.

        The publication bus legitimately sends. This guard follows the
        CREDENTIAL, not the verb.
        """
        f = tmp_path / "publication.py"
        f.write_text("import smtplib\nsmtplib.SMTP().sendmail('a', 'b', 'c')\n")
        assert scan(repo_root=tmp_path) == {}

    def test_scanner_ignores_credentials_without_send(self, tmp_path: Path) -> None:
        """Self-test: merely loading the credentials is not a violation."""
        f = tmp_path / "reader.py"
        f.write_text(
            "from agents.mail_monitor.oauth import load_credentials\ncreds = load_credentials()\n"
        )
        assert scan(repo_root=tmp_path) == {}

    def test_bare_load_credentials_is_not_in_scope(self, tmp_path: Path) -> None:
        """Self-test: precision. An unrelated ``_load_credentials`` is not scope.

        scripts/youtube-player.py defines its own ``_load_credentials`` and must
        not be dragged in — a guard with false positives gets suppressed.
        """
        f = tmp_path / "player.py"
        f.write_text(
            "class P:\n"
            "    def _load_credentials(self): ...\n"
            "    def go(self): self.svc.messages().send()\n"
        )
        assert scan(repo_root=tmp_path) == {}
