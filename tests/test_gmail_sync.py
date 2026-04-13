"""Tests for gmail_sync — schemas, formatting, profiler facts."""

from __future__ import annotations


def test_email_metadata_defaults():
    from agents.gmail_sync import EmailMetadata

    e = EmailMetadata(
        message_id="abc123",
        thread_id="thread1",
        subject="Test Subject",
        sender="alice@company.com",
        timestamp="2026-03-10T09:00:00Z",
    )
    assert e.labels == []
    assert e.recipients == []
    assert e.is_unread is False
    assert e.thread_length == 1
    assert e.has_attachments is False


def test_gmail_sync_state_empty():
    from agents.gmail_sync import GmailSyncState

    s = GmailSyncState()
    assert s.history_id == ""
    assert s.messages == {}


def test_email_metadata_with_labels():
    from agents.gmail_sync import EmailMetadata

    e = EmailMetadata(
        message_id="def456",
        thread_id="thread2",
        subject="Important",
        sender="boss@company.com",
        timestamp="2026-03-10T10:00:00Z",
        labels=["IMPORTANT", "INBOX"],
        is_unread=True,
    )
    assert "IMPORTANT" in e.labels
    assert e.is_unread is True


def test_format_email_markdown_metadata_only():
    from agents.gmail_sync import EmailMetadata, _format_email_markdown

    e = EmailMetadata(
        message_id="msg1",
        thread_id="thread1",
        subject="Q1 Budget Review",
        sender="alice@company.com",
        timestamp="2026-03-10T09:00:00Z",
        recipients=["bob@company.com"],
        labels=["INBOX", "IMPORTANT"],
        is_unread=True,
        snippet="Please review the attached budget...",
    )
    md = _format_email_markdown(e)
    assert "platform: google" in md
    assert "service: gmail" in md
    assert "source_service: gmail" in md
    assert "people: [alice@company.com, bob@company.com]" in md
    assert "Q1 Budget Review" in md
    assert "alice@company.com" in md


def test_format_email_no_recipients():
    from agents.gmail_sync import EmailMetadata, _format_email_markdown

    e = EmailMetadata(
        message_id="msg2",
        thread_id="thread2",
        subject="Newsletter",
        sender="news@example.com",
        timestamp="2026-03-10T12:00:00Z",
        labels=["CATEGORY_PROMOTIONS"],
    )
    md = _format_email_markdown(e)
    assert "Newsletter" in md
    assert "people: [news@example.com]" in md


def test_generate_gmail_profile_facts():
    from agents.gmail_sync import (
        EmailMetadata,
        GmailSyncState,
        _generate_profile_facts,
    )

    state = GmailSyncState()
    state.messages = {
        "1": EmailMetadata(
            message_id="1",
            thread_id="t1",
            subject="Budget Review",
            sender="alice@company.com",
            timestamp="2026-03-10T09:00:00Z",
            labels=["INBOX", "IMPORTANT"],
        ),
        "2": EmailMetadata(
            message_id="2",
            thread_id="t2",
            subject="Standup Notes",
            sender="bob@company.com",
            timestamp="2026-03-10T10:00:00Z",
            labels=["INBOX"],
        ),
        "3": EmailMetadata(
            message_id="3",
            thread_id="t1",
            subject="Re: Budget Review",
            sender="alice@company.com",
            timestamp="2026-03-10T11:00:00Z",
            labels=["INBOX"],
        ),
    }
    facts = _generate_profile_facts(state)
    assert len(facts) > 0
    dims = {f["dimension"] for f in facts}
    assert "communication_patterns" in dims
    assert all(f["confidence"] == 0.95 for f in facts)


# ---------------------------------------------------------------------------
# Idempotent _write_recent_emails — BETA-FINDING-2026-04-13-B regression guard
# ---------------------------------------------------------------------------
#
# The previous implementation wiped rag-sources/gmail/*.md and rewrote every
# file from scratch on each sync, generating ~12k inotify events per cycle
# and starving the reactive engine / logos-api event loop. These tests lock
# in the new idempotent contract so the flood pattern cannot reappear.


def _make_email(message_id: str, subject: str, timestamp: str) -> object:
    from agents.gmail_sync import EmailMetadata

    return EmailMetadata(
        message_id=message_id,
        thread_id=f"thread-{message_id}",
        subject=subject,
        sender="alice@example.com",
        timestamp=timestamp,
        recipients=["bob@example.com"],
    )


def _recent_iso(days_ago: int = 0) -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


class TestWriteRecentEmailsIdempotent:
    def _patch_gmail_dir(self, monkeypatch, tmp_path):
        from agents import gmail_sync

        target = tmp_path / "rag-sources" / "gmail"
        monkeypatch.setattr(gmail_sync, "GMAIL_DIR", target)

        # Stub ConsentRegistry so the tests don't need axioms/contracts
        # on disk. gmail_sync uses `from shared.consent import ConsentRegistry`
        # so the name lives in the agents.gmail_sync namespace.
        class _PermissiveRegistry:
            def load(self) -> None:
                return None

            def contract_check(self, _who: str, _kind: str) -> bool:
                return True

        monkeypatch.setattr(gmail_sync, "ConsentRegistry", _PermissiveRegistry)
        return target

    def test_first_run_writes_all_files_in_window(self, tmp_path, monkeypatch):
        from agents.gmail_sync import GmailSyncState, _write_recent_emails

        target = self._patch_gmail_dir(monkeypatch, tmp_path)
        state = GmailSyncState()
        state.messages = {
            "m1": _make_email("m1", "First email", _recent_iso(1)),
            "m2": _make_email("m2", "Second email", _recent_iso(2)),
        }

        count = _write_recent_emails(state)

        assert count == 2
        files = sorted(target.glob("*.md"))
        assert len(files) == 2
        assert all(f.stat().st_size > 0 for f in files)

    def test_second_run_with_identical_state_writes_zero_files(self, tmp_path, monkeypatch, caplog):
        """The critical regression guard: same state in → zero file writes out.

        This is the ONLY property that defeats BETA-FINDING-B. Without it the
        reactive engine sees a write event per email on every sync cycle even
        when no content actually changed.
        """
        import logging

        from agents.gmail_sync import GmailSyncState, _write_recent_emails

        target = self._patch_gmail_dir(monkeypatch, tmp_path)
        state = GmailSyncState()
        state.messages = {
            f"m{i}": _make_email(f"m{i}", f"Email {i}", _recent_iso(1)) for i in range(20)
        }

        # First run — establishes the baseline
        _write_recent_emails(state)
        first_mtimes = {f.name: f.stat().st_mtime_ns for f in target.glob("*.md")}
        assert len(first_mtimes) == 20

        # Second run — same state. Capture the log to verify unchanged counter.
        caplog.set_level(logging.INFO, logger="agents.gmail_sync")
        _write_recent_emails(state)

        # No file mtime should have moved — the key property a filesystem
        # watcher cares about. atime/ctime may update on POSIX read-only
        # access but mtime is the one inotify raises MODIFIED for.
        second_mtimes = {f.name: f.stat().st_mtime_ns for f in target.glob("*.md")}
        assert second_mtimes == first_mtimes, (
            "idempotent sync must not touch any file mtime when state is unchanged"
        )

        # And the log line names the unchanged count explicitly
        log_messages = [rec.message for rec in caplog.records if "Gmail RAG sync" in rec.message]
        assert log_messages, "expected a 'Gmail RAG sync' summary log line"
        assert "rewritten=0" in log_messages[-1]
        assert "unchanged=20" in log_messages[-1]

    def test_email_content_change_rewrites_only_that_file(self, tmp_path, monkeypatch):
        from agents.gmail_sync import GmailSyncState, _write_recent_emails

        target = self._patch_gmail_dir(monkeypatch, tmp_path)
        state = GmailSyncState()
        state.messages = {
            "m1": _make_email("m1", "Keep this", _recent_iso(1)),
            "m2": _make_email("m2", "Also keep", _recent_iso(1)),
            "m3": _make_email("m3", "Will change", _recent_iso(1)),
        }
        _write_recent_emails(state)
        baseline = {f.name: f.stat().st_mtime_ns for f in target.glob("*.md")}
        # Force a deterministic mtime gap so the regression check is robust
        # on fast filesystems.
        import time as _time

        _time.sleep(0.01)

        # Rewrite m3 with different content. The filename derives from
        # (date, subject, message_id[:8]) so the same message_id keeps the
        # date and id prefixes but the subject slug changes — both old and
        # new filenames contain "m3"-derived "Will-change" prefix variants.
        state.messages["m3"] = _make_email("m3", "Will change — edited", _recent_iso(1))
        _write_recent_emails(state)

        after = {f.name: f.stat().st_mtime_ns for f in target.glob("*.md")}
        # The two kept files must not have moved (mtime unchanged).
        m1_name = next(n for n in after if "Keep-this" in n)
        m2_name = next(n for n in after if "Also-keep" in n)
        assert after[m1_name] == baseline[m1_name], "m1 should not have been rewritten"
        assert after[m2_name] == baseline[m2_name], "m2 should not have been rewritten"
        # m3's new file should exist under the edited subject slug
        assert any("edited" in n for n in after), "m3 edited file should exist"

    def test_aged_out_emails_are_unlinked(self, tmp_path, monkeypatch):
        """Emails that fall outside the recency window are removed from disk."""
        from agents.gmail_sync import GmailSyncState, _write_recent_emails

        target = self._patch_gmail_dir(monkeypatch, tmp_path)
        state = GmailSyncState()
        state.messages = {
            "recent": _make_email("recent", "Still in window", _recent_iso(1)),
            "old": _make_email("old", "Just aged out", _recent_iso(1)),
        }
        _write_recent_emails(state)
        assert len(list(target.glob("*.md"))) == 2

        # "old" now drops from the state (simulating the 7-day window rolling past it)
        del state.messages["old"]
        _write_recent_emails(state)

        files = list(target.glob("*.md"))
        assert len(files) == 1
        assert "Still-in-window" in files[0].name

    def test_does_not_wipe_unrelated_emails_on_empty_state(self, tmp_path, monkeypatch):
        """Empty state removes everything — expected because the window is empty."""
        from agents.gmail_sync import GmailSyncState, _write_recent_emails

        target = self._patch_gmail_dir(monkeypatch, tmp_path)
        state = GmailSyncState()
        state.messages = {"m1": _make_email("m1", "Something", _recent_iso(1))}
        _write_recent_emails(state)
        assert len(list(target.glob("*.md"))) == 1

        state.messages = {}
        _write_recent_emails(state)
        assert list(target.glob("*.md")) == []
