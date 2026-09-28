"""The outbound_message_egress_sensitive class's evidence: the send-surface diff scan.

release-mitigation-gate-audio-or-live-egress-20260927, item (3): the check names
the send surfaces a PR adds, removes or changes, and fails on an unreviewed new
send path.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from shared.outbound_send_surface import (
    UnparseableSource,
    assess_diff,
    parse_registry,
    send_vectors,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check-outbound-send-surface-diff.py"

GMAIL_SEND = b"svc.users().messages().send(userId='me', body={}).execute()\n"
GMAIL_SEND_ALIASED = b"mr = svc.users().messages()\nmr.send(userId='me', body={})\n"
DRAFT_CREATE = b"svc.users().drafts().create(userId='me', body={})\n"
REST_SEND = b"URL = 'https://gmail.googleapis.com/gmail/v1/users/me/messages/send'\n"
SMTP_SEND = b"import smtplib\ns = smtplib.SMTP('h')\ns.send_message(msg)\n"
LLM_CALL = b"client.messages.create(model='m', messages=[])\n"
RELAY_SEND = b"bus.send_message('lane', payload)\n"


@pytest.mark.parametrize(
    ("source", "vector"),
    [
        (GMAIL_SEND, "gmail-api-send"),
        (GMAIL_SEND_ALIASED, "gmail-api-send"),
        (DRAFT_CREATE, "gmail-api-draft"),
        (REST_SEND, "gmail-rest-send"),
        (SMTP_SEND, "smtp-send"),
    ],
)
def test_python_send_vectors_are_named(source: bytes, vector: str) -> None:
    assert vector in send_vectors("scripts/sender.py", source)


@pytest.mark.parametrize("source", [LLM_CALL, RELAY_SEND, b"x = 1\n"])
def test_non_mail_calls_are_not_send_vectors(source: bytes) -> None:
    # messages.create is the LLM SDK shape; a bare send_message is the relay bus.
    assert send_vectors("shared/thing.py", source) == frozenset()


def test_script_send_vector_needs_an_executable_or_script_suffix() -> None:
    body = b"#!/usr/bin/env bash\nprintf '%s' \"$m\" | sendmail -t\n"
    assert send_vectors("scripts/hapax-notify", body, executable=True) == {"script-send"}
    assert send_vectors("scripts/notify.sh", body) == {"script-send"}
    assert send_vectors("config/notes.conf", body) == frozenset()


@pytest.mark.parametrize("path", ["tests/test_x.py", "docs/mail.md", "notes.txt"])
def test_tests_and_docs_are_outside_the_scan(path: str) -> None:
    assert send_vectors(path, GMAIL_SEND) == frozenset()


def test_unparseable_python_fails_loudly() -> None:
    with pytest.raises(UnparseableSource):
        send_vectors("scripts/broken.py", b"def (:\n")


def _one(path: str, base: bytes | None, head: bytes | None) -> dict:
    return {path: (path, base, head, False, False)}


def test_a_new_unregistered_send_path_is_unreviewed() -> None:
    # Unsafe case: a PR adding a send path with no reviewed registration FAILS.
    verdict = assess_diff(
        _one("scripts/new-sender.py", None, GMAIL_SEND),
        base_registry=frozenset(),
        head_registry=frozenset(),
    )
    assert not verdict.ok
    assert [(c.path, c.kind) for c in verdict.unreviewed] == [("scripts/new-sender.py", "added")]


def test_a_send_vector_added_to_an_existing_file_is_unreviewed() -> None:
    verdict = assess_diff(
        _one("shared/notify.py", b"x = 1\n", SMTP_SEND),
        base_registry=frozenset(),
        head_registry=frozenset(),
    )
    assert not verdict.ok


def test_a_new_send_path_registered_in_the_diff_passes_and_is_named() -> None:
    verdict = assess_diff(
        _one("scripts/new-sender.py", None, GMAIL_SEND),
        base_registry=frozenset(),
        head_registry=frozenset({"scripts/new-sender.py"}),
    )
    assert verdict.ok
    assert verdict.registered_in_diff == ("scripts/new-sender.py",)


def test_a_retired_send_path_passes_as_removed() -> None:
    # #4768's shape: the send path leaves the file; nothing new is opened.
    verdict = assess_diff(
        _one("scripts/send-stakeholder-revenue-brief.py", GMAIL_SEND, b"print('dry run')\n"),
        base_registry=frozenset({"scripts/send-stakeholder-revenue-brief.py"}),
        head_registry=frozenset({"scripts/send-stakeholder-revenue-brief.py"}),
    )
    assert verdict.ok
    assert [c.kind for c in verdict.changes] == ["removed"]


def test_unparseable_changed_file_fails_the_verdict() -> None:
    verdict = assess_diff(
        _one("scripts/broken.py", None, b"def (:\n"),
        base_registry=frozenset(),
        head_registry=frozenset(),
    )
    assert not verdict.ok
    assert verdict.unparseable


def test_registry_entries_need_a_path_and_a_reason() -> None:
    assert parse_registry("surfaces:\n  - path: a.py\n    reason: r\n") == {"a.py"}
    with pytest.raises(ValueError):
        parse_registry("surfaces:\n  - path: a.py\n")
    with pytest.raises(ValueError):
        parse_registry("nope: []\n")


def test_the_repo_registry_names_every_send_surface_at_head() -> None:
    # The baseline: every file the scan would flag today is a reviewed surface.
    registry = parse_registry((REPO_ROOT / "config/outbound-send-surfaces.yaml").read_text())
    tracked = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files"], capture_output=True, text=True, check=True
    ).stdout.split()
    flagged = set()
    for rel in tracked:
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        if send_vectors(rel, path.read_bytes(), executable=path.stat().st_mode & 0o111 != 0):
            flagged.add(rel)
    assert flagged <= registry, f"unregistered send surfaces: {sorted(flagged - registry)}"


# ── the CLI over a real git diff ─────────────────────────────────────────


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "config").mkdir()
    (tmp_path / "config/outbound-send-surfaces.yaml").write_text("surfaces: []\n")
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared/core.py").write_text("x = 1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def _scan(repo: Path, base: str, head: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "--base", base, "--head", head],
        capture_output=True,
        text=True,
    )


def test_cli_fails_on_an_unreviewed_new_send_path(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "shared/mailer.py").write_bytes(GMAIL_SEND)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add a sender")
    result = _scan(repo, base, "HEAD")
    assert result.returncode == 1, result.stdout
    assert "added" in result.stdout and "shared/mailer.py [UNREVIEWED]" in result.stdout


def test_cli_passes_a_registered_send_path_and_names_it(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "shared/mailer.py").write_bytes(GMAIL_SEND)
    (repo / "config/outbound-send-surfaces.yaml").write_text(
        "surfaces:\n  - path: shared/mailer.py\n    reason: reviewed here\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add a registered sender")
    result = _scan(repo, base, "HEAD")
    assert result.returncode == 0, result.stdout
    assert "registry+ shared/mailer.py" in result.stdout


def test_cli_passes_a_diff_with_no_send_surface(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "shared/core.py").write_text("x = 2\n")
    _git(repo, "commit", "-q", "-am", "edit")
    result = _scan(repo, base, "HEAD")
    assert result.returncode == 0, result.stdout
    assert "no send surface added, removed or changed" in result.stdout


def test_cli_refuses_when_an_added_blob_cannot_be_read(repo: Path) -> None:
    # Fail-open fix (release-gate-scanner-fail-closed-followup-20260927 item 1):
    # the diff says the file exists at head, but its blob is unreadable. The scan
    # must refuse (exit 2), never read the side as absent and skip the file.
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "shared/mailer.py").write_bytes(GMAIL_SEND)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add a sender")
    blob = _git(repo, "rev-parse", "HEAD:shared/mailer.py")
    (repo / ".git/objects" / blob[:2] / blob[2:]).unlink()
    result = _scan(repo, base, "HEAD")
    assert result.returncode == 2, result.stdout
    assert "PASS" not in result.stdout


def test_cli_refuses_when_the_registry_is_missing_at_head(repo: Path) -> None:
    # Item 2: deleting the registry is a loud error, never an empty registry.
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "rm", "-q", "config/outbound-send-surfaces.yaml")
    _git(repo, "commit", "-q", "-m", "drop the registry")
    result = _scan(repo, base, "HEAD")
    assert result.returncode == 2, result.stdout
    assert "registry" in result.stderr


def test_cli_names_a_deleted_extensionless_script_sender_as_removed(repo: Path) -> None:
    # Item 3: the base image is classified with the BASE executable bit. A
    # deleted extensionless script has no head bit to borrow.
    script = repo / "scripts/hapax-mailer"
    script.parent.mkdir()
    script.write_text('#!/usr/bin/env bash\nsendmail -t < "$1"\n')
    script.chmod(0o755)
    (repo / "config/outbound-send-surfaces.yaml").write_text(
        "surfaces:\n  - path: scripts/hapax-mailer\n    reason: reviewed\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "a registered script sender")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "rm", "-q", "scripts/hapax-mailer")
    _git(repo, "commit", "-q", "-m", "retire it")
    result = _scan(repo, base, "HEAD")
    assert result.returncode == 0, result.stdout
    assert "removed  scripts/hapax-mailer" in result.stdout


def test_cli_errors_on_a_malformed_registry(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "config/outbound-send-surfaces.yaml").write_text("surfaces:\n  - path: x.py\n")
    _git(repo, "commit", "-q", "-am", "break the registry")
    assert _scan(repo, base, "HEAD").returncode == 2
