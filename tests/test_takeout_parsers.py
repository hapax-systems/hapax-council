"""Tests for shared.takeout parsers with synthetic fixtures."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime

from shared.takeout.models import ServiceConfig
from shared.takeout.parsers import (
    activity,
    calendar,
    chat,
    chrome,
    contacts,
    drive,
    gmail,
    keep,
    tasks,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def make_zip(files: dict[str, str | bytes]) -> zipfile.ZipFile:
    """Create an in-memory ZIP with the given files."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            if isinstance(content, str):
                content = content.encode("utf-8")
            zf.writestr(name, content)
    buf.seek(0)
    return zipfile.ZipFile(buf, "r")


# ── Activity parser ──────────────────────────────────────────────────────────


class TestActivityParser:
    SEARCH_CONFIG = ServiceConfig(
        parser="activity",
        takeout_path="My Activity/Search",
        tier=1,
        data_path="structured",
        modality_defaults=["text", "behavioral", "knowledge", "temporal"],
        content_type="search_query",
    )

    YOUTUBE_CONFIG = ServiceConfig(
        parser="activity",
        takeout_path="My Activity/YouTube",
        tier=1,
        data_path="structured",
        modality_defaults=["media", "behavioral", "temporal"],
        content_type="video_watch",
    )

    def test_parse_json_search(self):
        data = json.dumps(
            [
                {
                    "header": "Search",
                    "title": "Searched for pydantic ai tutorial",
                    "time": "2025-06-15T10:30:00.000Z",
                    "products": ["Search"],
                },
                {
                    "header": "Search",
                    "title": "Searched for MIDI routing linux",
                    "time": "2025-06-15T11:00:00.000Z",
                    "titleUrl": "https://www.google.com/search?q=MIDI+routing+linux",
                    "products": ["Search"],
                },
            ]
        )
        zf = make_zip({"Takeout/My Activity/Search/MyActivity.json": data})
        records = list(activity.parse(zf, self.SEARCH_CONFIG))
        assert len(records) == 2
        assert records[0].service == "search"
        assert records[0].content_type == "search_query"
        assert records[0].timestamp == datetime(2025, 6, 15, 10, 30)
        assert "behavioral" in records[0].modality_tags

    def test_parse_json_youtube(self):
        data = json.dumps(
            [
                {
                    "header": "YouTube",
                    "title": "Watched SP-404 MK2 tutorial",
                    "time": "2025-06-15T20:00:00Z",
                    "titleUrl": "https://www.youtube.com/watch?v=abc123",
                    "subtitles": [{"name": "MPC Channel"}],
                    "products": ["YouTube"],
                },
            ]
        )
        zf = make_zip({"Takeout/My Activity/YouTube/MyActivity.json": data})
        records = list(activity.parse(zf, self.YOUTUBE_CONFIG))
        assert len(records) == 1
        assert records[0].service == "youtube"
        assert "MPC Channel" in records[0].text
        assert records[0].structured_fields.get("url") == "https://www.youtube.com/watch?v=abc123"

    def test_parse_html_fallback(self):
        html = """
        <html><body>
        <div class="content-cell mdl-cell">
            Searched for pydantic ai
            <br>Jun 15, 2025, 10:30:00 AM
        </div>
        <div class="content-cell mdl-cell">
            Searched for MIDI routing
            <br>Jun 15, 2025, 11:00:00 AM
        </div>
        </body></html>
        """
        zf = make_zip({"Takeout/My Activity/Search/MyActivity.html": html})
        records = list(activity.parse(zf, self.SEARCH_CONFIG))
        assert len(records) == 2
        assert "pydantic" in records[0].text.lower()

    def test_empty_entries_skipped(self):
        data = json.dumps(
            [
                {"title": ""},
                {"header": "Search"},  # no title
                {"title": "Valid entry", "time": "2025-06-15T10:00:00Z"},
            ]
        )
        zf = make_zip({"Takeout/My Activity/Search/MyActivity.json": data})
        records = list(activity.parse(zf, self.SEARCH_CONFIG))
        assert len(records) == 1

    def test_no_files(self):
        zf = make_zip({"Takeout/Other/file.txt": "nothing"})
        records = list(activity.parse(zf, self.SEARCH_CONFIG))
        assert records == []

    def test_without_takeout_prefix(self):
        data = json.dumps([{"title": "Test", "time": "2025-01-01T00:00:00Z"}])
        zf = make_zip({"My Activity/Search/MyActivity.json": data})
        records = list(activity.parse(zf, self.SEARCH_CONFIG))
        assert len(records) == 1


# ── Chrome parser ─────────────────────────────────────────────────────────────


class TestChromeParser:
    CONFIG = ServiceConfig(
        parser="chrome",
        takeout_path="Chrome",
        tier=1,
        data_path="structured",
        modality_defaults=["text", "behavioral", "knowledge"],
        content_type="browser_history",
    )

    def test_parse_history(self):
        data = json.dumps(
            {
                "Browser History": [
                    {
                        "title": "GitHub",
                        "url": "https://github.com",
                        "time_usec": 13370000000000000,  # Some Chrome time
                        "page_transition": "LINK",
                    },
                    {
                        "title": "Stack Overflow",
                        "url": "https://stackoverflow.com",
                        "time_usec": 13370000000000000,
                        "page_transition": "TYPED",
                    },
                ]
            }
        )
        zf = make_zip({"Takeout/Chrome/BrowserHistory.json": data})
        records = list(chrome.parse(zf, self.CONFIG))
        assert len(records) == 2
        assert records[0].service == "chrome"
        assert records[0].content_type == "browser_history"
        urls = {r.structured_fields["url"] for r in records}
        assert "https://github.com" in urls

    def test_dedup_by_url(self):
        """Multiple visits to same URL should produce one record with visit count."""
        data = json.dumps(
            {
                "Browser History": [
                    {
                        "title": "GitHub",
                        "url": "https://github.com",
                        "time_usec": 13370000000000000,
                    },
                    {
                        "title": "GitHub",
                        "url": "https://github.com",
                        "time_usec": 13370001000000000,
                    },
                    {
                        "title": "GitHub",
                        "url": "https://github.com",
                        "time_usec": 13370002000000000,
                    },
                ]
            }
        )
        zf = make_zip({"Takeout/Chrome/BrowserHistory.json": data})
        records = list(chrome.parse(zf, self.CONFIG))
        assert len(records) == 1
        assert records[0].structured_fields["visit_count"] == 3

    def test_parse_bookmarks(self):
        html = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
        <META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
        <DL><p>
            <DT><A HREF="https://example.com" ADD_DATE="1718456400">Example Site</A>
            <DT><A HREF="https://docs.python.org" ADD_DATE="1718456500">Python Docs</A>
        </DL>
        """
        zf = make_zip({"Takeout/Chrome/Bookmarks.html": html})
        records = list(chrome.parse(zf, self.CONFIG))
        assert len(records) == 2
        assert records[0].content_type == "bookmark"

    def test_empty_history(self):
        data = json.dumps({"Browser History": []})
        zf = make_zip({"Takeout/Chrome/BrowserHistory.json": data})
        records = list(chrome.parse(zf, self.CONFIG))
        assert records == []

    def test_history_timestamps_are_utc(self):
        """Chrome timestamps should be timezone-aware UTC."""
        data = json.dumps(
            {
                "Browser History": [
                    {
                        "title": "Test",
                        "url": "https://example.com",
                        "time_usec": 13370000000000000,
                        "page_transition": "LINK",
                    },
                ]
            }
        )
        zf = make_zip({"Takeout/Chrome/BrowserHistory.json": data})
        records = list(chrome.parse(zf, self.CONFIG))
        assert len(records) == 1
        ts = records[0].timestamp
        assert ts is not None
        assert ts.tzinfo is not None
        assert ts.tzinfo == UTC

    def test_bookmark_timestamps_are_utc(self):
        """Bookmark ADD_DATE timestamps should be timezone-aware UTC."""

        from shared.takeout.parsers.chrome import _chrome_time_to_datetime

        # Test via _chrome_time_to_datetime directly (history path)
        dt = _chrome_time_to_datetime(13370000000000000)
        assert dt is not None
        assert dt.tzinfo == UTC
        # Test bookmark path via fromtimestamp with tz
        dt2 = datetime.fromtimestamp(1718456400, tz=UTC)
        assert dt2.tzinfo == UTC


# ── Keep parser ───────────────────────────────────────────────────────────────


class TestKeepParser:
    CONFIG = ServiceConfig(
        parser="keep",
        takeout_path="Keep",
        tier=1,
        data_path="unstructured",
        modality_defaults=["text", "knowledge"],
        content_type="note",
    )

    def test_parse_text_note(self):
        note = json.dumps(
            {
                "title": "Music Ideas",
                "textContent": "Try chopping that Madlib sample at 90bpm",
                "labels": [{"name": "music"}, {"name": "production"}],
                "userEditedTimestampUsec": 1718456400000000,
                "isPinned": True,
                "isTrashed": False,
            }
        )
        zf = make_zip({"Takeout/Keep/note1.json": note})
        records = list(keep.parse(zf, self.CONFIG))
        assert len(records) == 1
        r = records[0]
        assert r.service == "keep"
        assert r.title == "Music Ideas"
        assert "Madlib" in r.text
        assert "music" in r.categories
        assert r.structured_fields.get("pinned") is True

    def test_parse_checklist(self):
        note = json.dumps(
            {
                "title": "Gear Setup",
                "textContent": "",
                "listContent": [
                    {"text": "Connect OXI One MIDI out", "isChecked": True},
                    {"text": "Route SP-404 audio", "isChecked": False},
                ],
                "userEditedTimestampUsec": 1718456400000000,
            }
        )
        zf = make_zip({"Takeout/Keep/checklist.json": note})
        records = list(keep.parse(zf, self.CONFIG))
        assert len(records) == 1
        assert "[x] Connect OXI" in records[0].text
        assert "[ ] Route SP-404" in records[0].text

    def test_skip_trashed(self):
        note = json.dumps(
            {
                "title": "Deleted Note",
                "textContent": "Gone",
                "isTrashed": True,
            }
        )
        zf = make_zip({"Takeout/Keep/trashed.json": note})
        records = list(keep.parse(zf, self.CONFIG))
        assert records == []

    def test_skip_empty_note(self):
        note = json.dumps(
            {
                "title": "",
                "textContent": "",
            }
        )
        zf = make_zip({"Takeout/Keep/empty.json": note})
        records = list(keep.parse(zf, self.CONFIG))
        assert records == []

    def test_note_with_annotations(self):
        note = json.dumps(
            {
                "title": "Links",
                "textContent": "Some useful links",
                "annotations": [
                    {"url": "https://example.com", "title": "Example"},
                ],
                "userEditedTimestampUsec": 1718456400000000,
            }
        )
        zf = make_zip({"Takeout/Keep/links.json": note})
        records = list(keep.parse(zf, self.CONFIG))
        assert len(records) == 1
        assert "example.com" in records[0].text


# ── Calendar parser ───────────────────────────────────────────────────────────


class TestCalendarParser:
    CONFIG = ServiceConfig(
        parser="calendar",
        takeout_path="Calendar",
        tier=1,
        data_path="structured",
        modality_defaults=["temporal", "social"],
        content_type="calendar_event",
    )

    def test_parse_basic_event(self):
        ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:event1@google.com
SUMMARY:Music Production Session
DTSTART:20250615T140000Z
DTEND:20250615T160000Z
LOCATION:Home Studio
DESCRIPTION:Work on new beats
END:VEVENT
END:VCALENDAR"""
        zf = make_zip({"Takeout/Calendar/calendar.ics": ics})
        records = list(calendar.parse(zf, self.CONFIG))
        assert len(records) == 1
        r = records[0]
        assert r.title == "Music Production Session"
        assert r.location == "Home Studio"
        assert r.timestamp == datetime(2025, 6, 15, 14, 0)
        assert r.structured_fields.get("duration_minutes") == 120

    def test_parse_with_attendees(self):
        ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:event2@google.com
SUMMARY:Team Meeting
DTSTART:20250615T100000Z
DTEND:20250615T110000Z
ATTENDEE;CN=Alice:mailto:alice@example.com
ATTENDEE;CN=Bob:mailto:bob@example.com
END:VEVENT
END:VCALENDAR"""
        zf = make_zip({"Takeout/Calendar/cal.ics": ics})
        records = list(calendar.parse(zf, self.CONFIG))
        assert len(records) == 1
        assert "alice@example.com" in records[0].people
        assert "bob@example.com" in records[0].people

    def test_parse_recurring_event(self):
        ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:recurring1@google.com
SUMMARY:Weekly Standup
DTSTART:20250615T090000Z
DTEND:20250615T093000Z
RRULE:FREQ=WEEKLY;BYDAY=MO
END:VEVENT
END:VCALENDAR"""
        zf = make_zip({"Takeout/Calendar/cal.ics": ics})
        records = list(calendar.parse(zf, self.CONFIG))
        assert len(records) == 1
        assert records[0].structured_fields.get("recurring") is True

    def test_multiple_events(self):
        ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:e1@google.com
SUMMARY:Event 1
DTSTART:20250615T100000Z
END:VEVENT
BEGIN:VEVENT
UID:e2@google.com
SUMMARY:Event 2
DTSTART:20250616T100000Z
END:VEVENT
END:VCALENDAR"""
        zf = make_zip({"Takeout/Calendar/cal.ics": ics})
        records = list(calendar.parse(zf, self.CONFIG))
        assert len(records) == 2

    def test_date_only_event(self):
        ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:allday@google.com
SUMMARY:Birthday
DTSTART;VALUE=DATE:20250615
END:VEVENT
END:VCALENDAR"""
        zf = make_zip({"Takeout/Calendar/cal.ics": ics})
        records = list(calendar.parse(zf, self.CONFIG))
        assert len(records) == 1
        assert records[0].timestamp == datetime(2025, 6, 15)


# ── Contacts parser ──────────────────────────────────────────────────────────


class TestContactsParser:
    CONFIG = ServiceConfig(
        parser="contacts",
        takeout_path="Contacts",
        tier=1,
        data_path="structured",
        modality_defaults=["social"],
        content_type="contact",
    )

    def test_parse_basic_contact(self):
        vcf = """BEGIN:VCARD
VERSION:3.0
FN:Alice Smith
EMAIL:alice@example.com
TEL:+1-555-0100
ORG:Acme Corp
TITLE:Engineer
END:VCARD"""
        zf = make_zip({"Takeout/Contacts/contacts.vcf": vcf})
        records = list(contacts.parse(zf, self.CONFIG))
        assert len(records) == 1
        r = records[0]
        assert r.title == "Alice Smith"
        assert "alice@example.com" in r.people
        assert r.structured_fields["organization"] == "Acme Corp"

    def test_multiple_contacts(self):
        vcf = """BEGIN:VCARD
FN:Alice
EMAIL:alice@example.com
END:VCARD
BEGIN:VCARD
FN:Bob
EMAIL:bob@example.com
TEL:+1-555-0200
END:VCARD"""
        zf = make_zip({"Takeout/Contacts/contacts.vcf": vcf})
        records = list(contacts.parse(zf, self.CONFIG))
        assert len(records) == 2

    def test_skip_empty_contact(self):
        vcf = """BEGIN:VCARD
VERSION:3.0
END:VCARD"""
        zf = make_zip({"Takeout/Contacts/contacts.vcf": vcf})
        records = list(contacts.parse(zf, self.CONFIG))
        assert records == []

    def test_contact_with_categories(self):
        vcf = """BEGIN:VCARD
FN:Charlie
EMAIL:charlie@example.com
CATEGORIES:Friends,Music
END:VCARD"""
        zf = make_zip({"Takeout/Contacts/contacts.vcf": vcf})
        records = list(contacts.parse(zf, self.CONFIG))
        assert len(records) == 1
        assert "Friends" in records[0].categories
        assert "Music" in records[0].categories

    def test_multiple_emails(self):
        vcf = """BEGIN:VCARD
FN:Dave
EMAIL;TYPE=HOME:dave@home.com
EMAIL;TYPE=WORK:dave@work.com
END:VCARD"""
        zf = make_zip({"Takeout/Contacts/contacts.vcf": vcf})
        records = list(contacts.parse(zf, self.CONFIG))
        assert len(records) == 1
        assert len(records[0].people) == 2


# ── Tasks parser ──────────────────────────────────────────────────────────────


class TestTasksParser:
    CONFIG = ServiceConfig(
        parser="tasks",
        takeout_path="Tasks",
        tier=1,
        data_path="unstructured",
        modality_defaults=["text", "knowledge", "behavioral"],
        content_type="task",
    )

    def test_parse_task_list(self):
        data = json.dumps(
            {
                "kind": "tasks#taskList",
                "items": [
                    {
                        "id": "task1",
                        "title": "Set up MIDI routing",
                        "status": "needsAction",
                        "updated": "2025-06-15T10:00:00Z",
                        "notes": "OXI One → SP-404 → Digitakt",
                    },
                    {
                        "id": "task2",
                        "title": "Sample vinyl records",
                        "status": "completed",
                        "updated": "2025-06-14T18:00:00Z",
                        "due": "2025-06-15",
                    },
                ],
            }
        )
        zf = make_zip({"Takeout/Tasks/tasks.json": data})
        records = list(tasks.parse(zf, self.CONFIG))
        assert len(records) == 2
        assert records[0].title == "Set up MIDI routing"
        assert "OXI One" in records[0].text
        assert records[1].structured_fields.get("status") == "completed"

    def test_skip_empty_title(self):
        data = json.dumps(
            {
                "items": [
                    {"id": "t1", "title": ""},
                    {"id": "t2", "title": "Valid task"},
                ]
            }
        )
        zf = make_zip({"Takeout/Tasks/tasks.json": data})
        records = list(tasks.parse(zf, self.CONFIG))
        assert len(records) == 1

    def test_parse_raw_list(self):
        """Some exports have a raw list instead of {items: [...]}."""
        data = json.dumps(
            [
                {"id": "t1", "title": "Task A", "status": "needsAction"},
                {"id": "t2", "title": "Task B", "status": "completed"},
            ]
        )
        zf = make_zip({"Takeout/Tasks/tasks.json": data})
        records = list(tasks.parse(zf, self.CONFIG))
        assert len(records) == 2


# ── Gmail parser ──────────────────────────────────────────────────────────────


class TestGmailParser:
    CONFIG = ServiceConfig(
        parser="gmail",
        takeout_path="Mail",
        tier=2,
        data_path="unstructured",
        modality_defaults=["text", "social", "temporal"],
        content_type="email",
    )

    def _make_mbox_content(self, messages: list[dict]) -> bytes:
        """Build a simple MBOX file from message dicts."""
        lines: list[str] = []
        for msg in messages:
            from_addr = msg.get("from", "test@example.com")
            to_addr = msg.get("to", "user@example.com")
            subject = msg.get("subject", "Test")
            body = msg.get("body", "Hello")
            date = msg.get("date", "Mon, 15 Jun 2025 10:30:00 +0000")

            lines.append(f"From {from_addr} Mon Jun 15 10:30:00 2025")
            lines.append(f"From: {from_addr}")
            lines.append(f"To: {to_addr}")
            lines.append(f"Subject: {subject}")
            lines.append(f"Date: {date}")
            lines.append(f"Message-ID: <{subject.replace(' ', '-')}@test.com>")
            lines.append("Content-Type: text/plain; charset=utf-8")
            lines.append("")
            lines.append(body)
            lines.append("")

        return "\n".join(lines).encode("utf-8")

    def test_parse_basic_email(self):
        mbox = self._make_mbox_content(
            [
                {"from": "alice@example.com", "subject": "Hello", "body": "Hi there"},
            ]
        )
        zf = make_zip({"Takeout/Mail/All mail.mbox": mbox})
        records = list(gmail.parse(zf, self.CONFIG))
        assert len(records) == 1
        r = records[0]
        assert r.service == "gmail"
        assert r.content_type == "email"
        assert "alice@example.com" in r.people

    def test_skip_automated_sender(self):
        mbox = self._make_mbox_content(
            [
                {"from": "noreply@github.com", "subject": "Notification"},
                {"from": "alice@example.com", "subject": "Real email"},
            ]
        )
        zf = make_zip({"Takeout/Mail/All mail.mbox": mbox})
        records = list(gmail.parse(zf, self.CONFIG))
        assert len(records) == 1
        assert "alice@example.com" in records[0].people

    def test_multiple_emails(self):
        mbox = self._make_mbox_content(
            [
                {"from": "alice@example.com", "subject": "First"},
                {"from": "bob@example.com", "subject": "Second"},
            ]
        )
        zf = make_zip({"Takeout/Mail/All mail.mbox": mbox})
        records = list(gmail.parse(zf, self.CONFIG))
        assert len(records) == 2


# ── Drive parser ──────────────────────────────────────────────────────────────


class TestDriveParser:
    CONFIG = ServiceConfig(
        parser="drive",
        takeout_path="Drive",
        tier=2,
        data_path="unstructured",
        modality_defaults=["text", "knowledge"],
        content_type="document",
    )

    def test_parse_text_file(self):
        zf = make_zip(
            {
                "Takeout/Drive/notes/ideas.md": "# Ideas\n\nSome creative thoughts",
            }
        )
        records = list(drive.parse(zf, self.CONFIG))
        assert len(records) == 1
        assert records[0].title == "ideas.md"
        assert "creative thoughts" in records[0].text
        assert records[0].data_path == "unstructured"

    def test_metadata_only_for_pdf(self):
        # Create a fake PDF (just bytes, won't be read as text)
        zf = make_zip(
            {
                "Takeout/Drive/docs/report.pdf": b"%PDF-1.4 fake content",
            }
        )
        records = list(drive.parse(zf, self.CONFIG))
        assert len(records) == 1
        assert records[0].data_path == "structured"
        assert records[0].structured_fields["extension"] == ".pdf"

    def test_skip_images(self):
        zf = make_zip(
            {
                "Takeout/Drive/photos/pic.jpg": b"\xff\xd8\xff fake jpeg",
            }
        )
        records = list(drive.parse(zf, self.CONFIG))
        assert records == []

    def test_multiple_files(self):
        zf = make_zip(
            {
                "Takeout/Drive/notes.txt": "Some notes",
                "Takeout/Drive/todo.md": "# TODO\n- stuff",
                "Takeout/Drive/data.csv": "a,b,c\n1,2,3",
            }
        )
        records = list(drive.parse(zf, self.CONFIG))
        assert len(records) == 3


# ── Chat parser ───────────────────────────────────────────────────────────────


class TestChatParser:
    CONFIG = ServiceConfig(
        parser="chat",
        takeout_path="Google Chat",
        tier=2,
        data_path="unstructured",
        modality_defaults=["text", "social", "temporal"],
        content_type="chat_message",
    )

    def test_parse_messages(self):
        data = json.dumps(
            {
                "messages": [
                    {
                        "creator": {"name": "Alice", "email": "alice@example.com"},
                        "created_date": "2025-06-15T10:30:00Z",
                        "text": "Hey, have you tried the new sampler?",
                    },
                    {
                        "creator": {"name": "Bob"},
                        "created_date": "2025-06-15T10:31:00Z",
                        "text": "Yeah, the SP-404 MK2 is amazing!",
                    },
                ]
            }
        )
        zf = make_zip({"Takeout/Google Chat/Groups/Music Producers/messages.json": data})
        records = list(chat.parse(zf, self.CONFIG))
        assert len(records) == 2
        assert "Alice" in records[0].people
        assert "SP-404" in records[1].text

    def test_parse_raw_list(self):
        data = json.dumps(
            [
                {"creator": "user1", "text": "Hello", "created_date": "2025-01-01T00:00:00Z"},
            ]
        )
        zf = make_zip({"Takeout/Google Chat/DMs/chat/messages.json": data})
        records = list(chat.parse(zf, self.CONFIG))
        assert len(records) == 1

    def test_skip_empty_messages(self):
        data = json.dumps(
            {
                "messages": [
                    {"creator": {"name": "Alice"}, "text": ""},
                    {"creator": {"name": "Bob"}, "text": "Valid message"},
                ]
            }
        )
        zf = make_zip({"Takeout/Google Chat/Groups/Test/messages.json": data})
        records = list(chat.parse(zf, self.CONFIG))
        assert len(records) == 1

    def test_extract_space_name(self):
        data = json.dumps(
            {
                "messages": [
                    {
                        "creator": {"name": "Alice"},
                        "text": "Hello",
                        "created_date": "2025-01-01T00:00:00Z",
                    },
                ]
            }
        )
        zf = make_zip({"Takeout/Google Chat/Groups/Team Chat/messages.json": data})
        records = list(chat.parse(zf, self.CONFIG))
        assert len(records) == 1
        assert records[0].structured_fields["space"] == "Team Chat"


# ── End-to-end processor test ────────────────────────────────────────────────


class TestProcessorEndToEnd:
    """Test the processor with a synthetic ZIP containing multiple services."""

    def test_process_multi_service_zip(self, tmp_path):
        from shared.takeout.processor import process_takeout

        # Build synthetic ZIP
        files = {
            "Takeout/My Activity/Search/MyActivity.json": json.dumps(
                [
                    {"title": "Searched for SP-404 tips", "time": "2025-06-15T10:00:00Z"},
                ]
            ),
            "Takeout/Keep/note1.json": json.dumps(
                {
                    "title": "Beat Ideas",
                    "textContent": "Try 85bpm boom bap with vinyl crackle",
                    "userEditedTimestampUsec": 1718456400000000,
                }
            ),
            "Takeout/Tasks/tasks.json": json.dumps(
                {
                    "items": [
                        {"id": "t1", "title": "Buy new cables", "status": "needsAction"},
                    ],
                }
            ),
        }
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        buf.seek(0)

        zip_path = tmp_path / "test-takeout.zip"
        zip_path.write_bytes(buf.getvalue())

        structured_path = tmp_path / "structured.jsonl"

        result = process_takeout(
            zip_path,
            output_dir=tmp_path / "output",
            structured_path=structured_path,
        )

        assert "search" in result.services_found
        assert "keep" in result.services_found
        assert "tasks" in result.services_found
        assert result.records_written > 0

    def test_dry_run(self, tmp_path):
        from shared.takeout.processor import process_takeout

        files = {
            "Takeout/Keep/note.json": json.dumps(
                {
                    "title": "Test",
                    "textContent": "Hello",
                    "userEditedTimestampUsec": 1718456400000000,
                }
            ),
        }
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        buf.seek(0)

        zip_path = tmp_path / "test.zip"
        zip_path.write_bytes(buf.getvalue())

        result = process_takeout(
            zip_path,
            output_dir=tmp_path / "output",
            dry_run=True,
        )

        assert result.records_written == 1
        # Verify no files were actually created
        assert not (tmp_path / "output").exists()

    def test_since_filter(self, tmp_path):
        from shared.takeout.processor import process_takeout

        files = {
            "Takeout/My Activity/Search/MyActivity.json": json.dumps(
                [
                    {"title": "Old search", "time": "2024-01-01T10:00:00Z"},
                    {"title": "New search", "time": "2025-06-15T10:00:00Z"},
                ]
            ),
        }
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        buf.seek(0)

        zip_path = tmp_path / "test.zip"
        zip_path.write_bytes(buf.getvalue())

        structured_path = tmp_path / "structured.jsonl"

        result = process_takeout(
            zip_path,
            since="2025-01-01",
            output_dir=tmp_path / "output",
            structured_path=structured_path,
        )

        assert result.records_written == 1
        assert result.records_skipped == 1
