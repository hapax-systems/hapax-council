"""CI guard: nothing that loads mail-monitor credentials may send mail.

WHY THIS EXISTS ALONGSIDE ``test_forbidden_mail_monitor_send_imports.py``

That guard is **directory-scoped** — it scans only ``agents/mail_monitor/``, and says
so. kimi/auditor's 2026-08-18 audit showed the scope is insufficient twice over:

1. ``gmail.modify`` is send-sufficient per Google's scope table, so "the daemon holds
   no send scope" was never a real defence.
2. A working send vector already exists **outside** that directory:
   ``scripts/send-stakeholder-revenue-brief.py`` imports
   ``agents.mail_monitor.oauth.load_credentials`` and calls
   ``service.users().messages().send(...)``. The directory guard cannot see it.

The old guard also matched only SMTP *library imports* — blind to the Gmail API send
path, to draft creation, and to direct REST, which is how the one real vector sends.

So this guard is scoped by **credential** rather than by directory: any file that
loads mail-monitor Google credentials, anywhere, must not contain a send vector.

## Why AST and not regex (PR #4580 review, Major/security)

The first implementation matched **physical lines**. That is evadable, and the
evasion is not exotic — both of these are ordinary formatting, and the line-based
scanner returned a clean result for a file containing both:

    from agents.mail_monitor.oauth import (
        load_credentials,
    )
    service.users() \\
        .messages() \\
        .send(userId="me", body={})

It also silently skipped any file that raised ``UnicodeDecodeError``, so a PEP-263
declared non-UTF-8 source was simply invisible to it. A guard with a known bypass is
worse than no guard, because it is trusted.

This version parses with ``ast`` (structure, not layout) and reads with
``tokenize.open`` (honours the PEP-263 coding declaration), and **fails loudly** when
a file cannot be decoded or parsed rather than skipping it.

## The quarantine is not a hole

``scripts/send-stakeholder-revenue-brief.py`` is real, implemented and dormant
(manual ``--send``, never scheduled). Its disposition is an open precondition in
kimi's audit, so this does not delete it or pretend it is absent. It is
**quarantined**: named, enumerable, asserted to still exist. The value is the
derivative — today's set is frozen at exactly one, and a second cannot appear without
turning this suite red. ``test_quarantine_has_not_rotted`` fails if an entry stops
existing or stops holding a vector, so the allowlist cannot decay into a silent
licence.
"""

from __future__ import annotations

import ast
import os
import tokenize
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

#: Modules whose import means "this file can obtain mail-monitor Google credentials".
CREDENTIAL_MODULES: Final[tuple[str, ...]] = (
    "agents.mail_monitor.oauth",
    "agents.mail_monitor",
)
#: pass(1) entries that are the credentials themselves, referenced as string literals.
CREDENTIAL_LITERALS: Final[tuple[str, ...]] = (
    "mail-monitor/google-refresh-token",
    "mail-monitor/google-client-id",
    "mail-monitor/google-client-secret",
)
#: SMTP libraries — an import alone is a send capability.
SMTP_MODULES: Final[frozenset[str]] = frozenset({"smtplib", "aiosmtplib"})
#: Bare call names that send regardless of receiver.
SEND_FUNCS: Final[frozenset[str]] = frozenset({"sendmail", "send_message"})
#: Attribute chains: terminal attr -> an ancestor attr that makes it a MAIL send.
#: Guards against flagging every unrelated ``.send()`` in the tree.
MAIL_CHAIN_ANCHORS: Final[frozenset[str]] = frozenset({"messages", "drafts"})
#: Direct REST, bypassing any client library.
REST_SEND_FRAGMENT: Final[str] = "/messages/send"

QUARANTINED_SEND_VECTORS: Final[frozenset[str]] = frozenset(
    {
        # Dormant, manual --send only, never scheduled. Disposition is an open
        # precondition in kimi/auditor's 2026-08-18 mail-subsystem audit.
        "scripts/send-stakeholder-revenue-brief.py",
    }
)

SKIP_DIR_PARTS: Final[frozenset[str]] = frozenset(
    {".venv", "node_modules", "__pycache__", ".git", "site-packages", "build", "dist"}
)


class UnparseableSource(Exception):
    """A file in scope could not be read or parsed. Never silently skipped."""


def _read_source(path: Path) -> str:
    """Read honouring any PEP-263 coding declaration.

    ``tokenize.open`` detects the declared encoding; a plain ``read_text`` assumes
    UTF-8 and raises on a latin-1 declared file, which the old guard then swallowed.
    """
    try:
        with tokenize.open(path) as fh:
            return fh.read()
    except (UnicodeDecodeError, SyntaxError, ValueError, OSError) as exc:
        raise UnparseableSource(f"{path}: {type(exc).__name__}: {exc}") from exc


def _attr_chain(node: ast.AST) -> list[str]:
    """Collect attribute names down a call/attribute chain, outermost first."""
    names: list[str] = []
    cur: ast.AST | None = node
    while cur is not None:
        if isinstance(cur, ast.Attribute):
            names.append(cur.attr)
            cur = cur.value
        elif isinstance(cur, ast.Call):
            cur = cur.func
        else:
            if isinstance(cur, ast.Name):
                names.append(cur.id)
            break
    return names


def _package_parts(path: Path, repo_root: Path) -> list[str]:
    """The dotted package a module lives in, for resolving relative imports.

    ``agents/mail_monitor/foo.py`` -> ``["agents", "mail_monitor"]``.
    """
    try:
        rel = path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return []
    return list(rel.parent.parts)


def _absolute_import_targets(node: ast.ImportFrom, pkg_parts: list[str]) -> set[str]:
    """Every dotted name an ``ImportFrom`` can bind, with relative levels resolved.

    ``from .oauth import load_credentials`` inside ``agents/mail_monitor/`` means
    ``agents.mail_monitor.oauth`` — invisible to a check that reads only
    ``node.module``, which is how the first version missed it.
    """
    if node.level > 1:
        base = pkg_parts[: len(pkg_parts) - (node.level - 1)]
    elif node.level == 1:
        base = pkg_parts
    else:
        base = []
    prefix = base + (node.module.split(".") if node.module else [])
    module = ".".join(prefix)
    targets = {module} if module else set()
    # ``from . import oauth`` binds the submodule through the alias, not .module
    if prefix:
        targets |= {".".join(prefix + [a.name]) for a in node.names}
    return targets


def _mail_resource_aliases(tree: ast.AST) -> set[str]:
    """Names bound to a Gmail ``messages()``/``drafts()`` resource.

    ``mr = service.users().messages()`` then ``mr.send(...)`` splits the chain across
    two statements, so a check that inspects only the current chain sees nothing.
    Chained rebinding (``a = ...messages(); b = a``) is followed to a fixpoint.
    """
    aliases: set[str] = set()
    for _ in range(4):  # depth beyond this is not worth the complexity
        grew = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            chain = set(_attr_chain(node.value))
            if not (MAIL_CHAIN_ANCHORS & chain or aliases & chain):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id not in aliases:
                    aliases.add(target.id)
                    grew = True
        if not grew:
            break
    return aliases


def _loads_credentials(tree: ast.AST, pkg_parts: list[str]) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if _absolute_import_targets(node, pkg_parts) & set(CREDENTIAL_MODULES):
                return True
        elif isinstance(node, ast.Import):
            if any(a.name in CREDENTIAL_MODULES for a in node.names):
                return True
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if any(lit in node.value for lit in CREDENTIAL_LITERALS):
                return True
    return False


def _send_vectors(tree: ast.AST) -> list[tuple[str, int]]:
    """Return (vector_name, line) for every send capability in the parsed source."""
    hits: list[tuple[str, int]] = []
    aliases = _mail_resource_aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in SMTP_MODULES:
                    hits.append(("smtp-import", node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in SMTP_MODULES:
                hits.append(("smtp-import", node.lineno))
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in SEND_FUNCS:
                hits.append(("smtp-sendmail", node.lineno))
            elif isinstance(func, ast.Attribute):
                if func.attr in SEND_FUNCS:
                    hits.append(("smtp-sendmail", node.lineno))
                elif func.attr in {"send", "create"}:
                    chain = set(_attr_chain(func))
                    # `aliases` catches the two-statement form, where the anchor was
                    # bound to a name in an earlier statement and is not in this chain.
                    if MAIL_CHAIN_ANCHORS & chain or aliases & chain:
                        name = (
                            "gmail-api-drafts" if "drafts" in chain else "gmail-api-messages-send"
                        )
                        hits.append((name, node.lineno))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if REST_SEND_FRAGMENT in node.value:
                hits.append(("gmail-rest-send", node.lineno))
    return hits


SCRIPT_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".sh", ".bash", ".zsh", ".fish", ".js", ".mjs", ".ts", ".rb", ".pl", ".php"}
)
#: Cap on bytes read from a non-Python file. Credential + endpoint both appear near
#: the top of any real sender; this stops the guard walking large data files.
NON_PYTHON_READ_CAP: Final[int] = 256 * 1024


def _is_script(path: Path) -> bool:
    """A non-Python file that can execute: known suffix, or executable with a shebang."""
    if path.suffix.lower() in SCRIPT_SUFFIXES:
        return True
    if path.suffix or not os.access(path, os.X_OK):
        return False
    try:
        with path.open("rb") as fh:
            return fh.read(2) == b"#!"
    except OSError:
        return False


def _non_python_vectors(path: Path) -> list[tuple[str, int]]:
    """Coarse text check for a shell/JS sender. Requires credential AND endpoint.

    ``pass show mail-monitor/google-refresh-token`` piped into a ``curl`` against the
    Gmail REST endpoint is a complete send vector that never enters the Python AST
    path. This check is deliberately blunter than the AST one — it cannot know a
    language's grammar — so it fires only when a credential literal and a send
    endpoint BOTH appear in the same file, which keeps it from flagging every script
    that merely mentions one of them.
    """
    try:
        blob = path.read_bytes()[:NON_PYTHON_READ_CAP]
    except OSError:
        return []
    if b"\x00" in blob:  # binary
        return []
    text = blob.decode("utf-8", "replace")
    if not any(lit in text for lit in CREDENTIAL_LITERALS):
        return []
    hits: list[tuple[str, int]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if REST_SEND_FRAGMENT in line:
            hits.append(("gmail-rest-send-nonpython", lineno))
        elif "sendmail" in line or "/drafts/send" in line:
            hits.append(("smtp-sendmail-nonpython", lineno))
    return hits


def scan(repo_root: Path = REPO_ROOT) -> dict[str, list[tuple[str, int]]]:
    """Map repo-relative path -> send vectors, for credential-loading files only.

    Excludes THIS file by exact resolved path: the guard necessarily contains every
    shape it hunts, in its docstring and fixtures. The exclusion is deliberately NOT
    a "skip tests/" rule — a test that genuinely loads mail-monitor credentials and
    sends mail IS a violation and stays in scope.
    """
    self_path = Path(__file__).resolve()
    findings: dict[str, list[tuple[str, int]]] = {}
    unparseable: list[str] = []

    for py_file in sorted(repo_root.rglob("*.py")):
        if SKIP_DIR_PARTS & set(py_file.parts):
            continue
        if py_file.resolve() == self_path:
            continue
        try:
            source = _read_source(py_file)
            tree = ast.parse(source, filename=str(py_file))
        except UnparseableSource as exc:
            unparseable.append(str(exc))
            continue
        except SyntaxError as exc:
            unparseable.append(f"{py_file}: SyntaxError: {exc}")
            continue
        if not _loads_credentials(tree, _package_parts(py_file, repo_root)):
            continue
        hits = _send_vectors(tree)
        if hits:
            findings[str(py_file.relative_to(repo_root))] = hits

    for other in sorted(repo_root.rglob("*")):
        if other.suffix == ".py" or not other.is_file():
            continue
        if SKIP_DIR_PARTS & set(other.parts):
            continue
        if not _is_script(other):
            continue
        hits = _non_python_vectors(other)
        if hits:
            findings[str(other.relative_to(repo_root))] = hits

    if unparseable:
        # Fail loudly. The old guard swallowed UnicodeDecodeError, which made a
        # PEP-263 non-UTF-8 file invisible to a security check.
        raise UnparseableSource(
            "guard could not parse these files, so it cannot vouch for them:\n  "
            + "\n  ".join(unparseable)
        )
    return findings


class TestCredentialScopedSendGuard:
    def test_no_unquarantined_send_vectors(self) -> None:
        findings = scan()
        offenders = {p: v for p, v in findings.items() if p not in QUARANTINED_SEND_VECTORS}
        assert offenders == {}, (
            "Send vector(s) in files that load mail-monitor credentials:\n"
            + "\n".join(
                f"  {path}:{line}  [{name}]"
                for path, hits in sorted(offenders.items())
                for name, line in hits
            )
            + "\n\nmail-monitor holds gmail.modify, which IS send-sufficient. A file that "
            "loads those credentials and can send mail is a path from inbound processing "
            "to outbound correspondence the operator never authored.\n"
            "If deliberate, it needs a QUARANTINED_SEND_VECTORS entry and a recorded "
            "operator decision — not a silent addition."
        )

    def test_quarantine_has_not_rotted(self) -> None:
        findings = scan()
        stale = [
            f"{p}: {'file no longer exists' if not (REPO_ROOT / p).exists() else 'no send vector remains'}"
            for p in sorted(QUARANTINED_SEND_VECTORS)
            if not (REPO_ROOT / p).exists() or p not in findings
        ]
        assert stale == [], "QUARANTINED_SEND_VECTORS is stale — remove:\n  " + "\n  ".join(stale)

    def test_the_known_vector_is_still_detected(self) -> None:
        findings = scan()
        assert "scripts/send-stakeholder-revenue-brief.py" in findings
        names = {n for n, _ in findings["scripts/send-stakeholder-revenue-brief.py"]}
        assert "gmail-api-messages-send" in names

    # -- the evasions the line-based version missed (PR #4580 review) --

    def test_catches_multiline_import_and_multiline_send_chain(self, tmp_path: Path) -> None:
        """Both are ordinary formatting; the regex version returned a clean result."""
        (tmp_path / "evade.py").write_text(
            "from agents.mail_monitor.oauth import (\n"
            "    load_credentials,\n"
            ")\n"
            "service.users() \\\n"
            "    .messages() \\\n"
            "    .send(userId='me', body={})\n"
        )
        findings = scan(repo_root=tmp_path)
        assert "evade.py" in findings, "multiline evasion must be caught"
        assert findings["evade.py"][0][0] == "gmail-api-messages-send"

    def test_catches_parenthesised_chain(self, tmp_path: Path) -> None:
        (tmp_path / "paren.py").write_text(
            "from agents.mail_monitor import oauth\n"
            "(\n    service\n    .users()\n    .messages()\n    .send()\n)\n"
        )
        assert "paren.py" in scan(repo_root=tmp_path)

    def test_non_utf8_source_fails_loudly(self, tmp_path: Path) -> None:
        """The old guard swallowed UnicodeDecodeError and skipped the file silently."""
        bad = tmp_path / "latin.py"
        bad.write_bytes(b"# -*- coding: utf-8 -*-\nx = '\xff\xfe not utf-8'\n")
        with pytest.raises(UnparseableSource):
            scan(repo_root=tmp_path)

    def test_syntax_error_fails_loudly(self, tmp_path: Path) -> None:
        (tmp_path / "broken.py").write_text("def f(:\n")
        with pytest.raises(UnparseableSource):
            scan(repo_root=tmp_path)

    # -- precision: the guard must not cry wolf --

    def test_ignores_send_without_mail_monitor_credentials(self, tmp_path: Path) -> None:
        """The publication bus legitimately sends. This follows the CREDENTIAL."""
        (tmp_path / "publication.py").write_text(
            "import smtplib\nsmtplib.SMTP().sendmail('a', 'b', 'c')\n"
        )
        assert scan(repo_root=tmp_path) == {}

    def test_ignores_credentials_without_send(self, tmp_path: Path) -> None:
        (tmp_path / "reader.py").write_text(
            "from agents.mail_monitor.oauth import load_credentials\ncreds = load_credentials()\n"
        )
        assert scan(repo_root=tmp_path) == {}

    def test_bare_load_credentials_is_not_in_scope(self, tmp_path: Path) -> None:
        """scripts/youtube-player.py defines its own _load_credentials — not scope."""
        (tmp_path / "player.py").write_text(
            "class P:\n"
            "    def _load_credentials(self): ...\n"
            "    def go(self): self.svc.messages().send()\n"
        )
        assert scan(repo_root=tmp_path) == {}

    def test_unrelated_dot_send_is_not_flagged(self, tmp_path: Path) -> None:
        """A socket/queue ``.send()`` must not trip a MAIL guard."""
        (tmp_path / "sock.py").write_text(
            "from agents.mail_monitor.oauth import load_credentials\n"
            "sock.send(b'bytes')\nqueue.send(item)\n"
        )
        assert scan(repo_root=tmp_path) == {}

    def test_catches_relative_credential_import(self, tmp_path: Path) -> None:
        """`from .oauth import ...` inside agents/mail_monitor is the same capability."""
        pkg = tmp_path / "agents" / "mail_monitor"
        pkg.mkdir(parents=True)
        (pkg / "sender.py").write_text(
            "from .oauth import load_credentials\n"
            "service.users().messages().send(userId='me', body={})\n"
        )
        assert "agents/mail_monitor/sender.py" in scan(repo_root=tmp_path)

    def test_catches_from_dot_import_oauth(self, tmp_path: Path) -> None:
        pkg = tmp_path / "agents" / "mail_monitor"
        pkg.mkdir(parents=True)
        (pkg / "s2.py").write_text("from . import oauth\nservice.users().messages().send()\n")
        assert "agents/mail_monitor/s2.py" in scan(repo_root=tmp_path)

    def test_catches_parent_relative_import(self, tmp_path: Path) -> None:
        pkg = tmp_path / "agents" / "mail_monitor" / "sub"
        pkg.mkdir(parents=True)
        (pkg / "s3.py").write_text(
            "from ..oauth import load_credentials\nservice.users().messages().send()\n"
        )
        assert "agents/mail_monitor/sub/s3.py" in scan(repo_root=tmp_path)

    def test_catches_aliased_message_resource(self, tmp_path: Path) -> None:
        """The anchor is bound in an earlier statement, so it is not in the send chain."""
        (tmp_path / "alias.py").write_text(
            "from agents.mail_monitor.oauth import load_credentials\n"
            "message_resource = service.users().messages()\n"
            "message_resource.send(userId='me', body={})\n"
        )
        found = scan(repo_root=tmp_path)
        assert "alias.py" in found
        assert found["alias.py"][0][0] == "gmail-api-messages-send"

    def test_catches_transitively_aliased_resource(self, tmp_path: Path) -> None:
        (tmp_path / "alias2.py").write_text(
            "from agents.mail_monitor.oauth import load_credentials\n"
            "a = service.users().messages()\nb = a\nb.send()\n"
        )
        assert "alias2.py" in scan(repo_root=tmp_path)

    def test_catches_shell_script_sender(self, tmp_path: Path) -> None:
        """A shell sender never enters the AST path — .py-only scanning missed it."""
        sh = tmp_path / "send.sh"
        sh.write_text(
            "#!/usr/bin/env bash\n"
            "TOKEN=$(pass show mail-monitor/google-refresh-token)\n"
            'curl -H "Authorization: Bearer $TOKEN" \\\n'
            "  https://gmail.googleapis.com/gmail/v1/users/me/messages/send\n"
        )
        found = scan(repo_root=tmp_path)
        assert "send.sh" in found
        assert found["send.sh"][0][0] == "gmail-rest-send-nonpython"

    def test_catches_extensionless_executable_sender(self, tmp_path: Path) -> None:
        exe = tmp_path / "mailer"
        exe.write_text(
            "#!/bin/sh\npass show mail-monitor/google-client-secret\ncurl .../messages/send\n"
        )
        exe.chmod(0o755)
        assert "mailer" in scan(repo_root=tmp_path)

    def test_non_python_needs_both_credential_and_endpoint(self, tmp_path: Path) -> None:
        """docs/specs/2026-04-25-mail-monitor.md names the credential and must not trip."""
        (tmp_path / "doc.sh").write_text(
            "#!/bin/sh\n# reads pass show mail-monitor/google-refresh-token\n"
        )
        (tmp_path / "unrelated.sh").write_text("#!/bin/sh\ncurl .../messages/send\n")
        assert scan(repo_root=tmp_path) == {}

    def test_catches_rest_send_and_drafts(self, tmp_path: Path) -> None:
        (tmp_path / "rest.py").write_text(
            "from agents.mail_monitor.oauth import load_credentials\n"
            "httpx.post('https://gmail.googleapis.com/gmail/v1/users/me/messages/send')\n"
        )
        (tmp_path / "draft.py").write_text(
            "from agents.mail_monitor.oauth import load_credentials\n"
            "service.users().drafts().create(userId='me', body={})\n"
        )
        found = scan(repo_root=tmp_path)
        assert "rest.py" in found and "draft.py" in found
        assert found["draft.py"][0][0] == "gmail-api-drafts"
