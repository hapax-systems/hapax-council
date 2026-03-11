"""Tests for gdrive_sync — schemas, MIME classification, metadata stubs."""

from __future__ import annotations

from agents.gdrive_sync import (
    EXPORT_MIMES,
    SIZE_THRESHOLD,
    DriveFile,
    SyncState,
)


def test_drive_file_defaults():
    f = DriveFile(drive_id="abc", name="test.pdf", mime_type="application/pdf")
    assert f.is_metadata_only is False
    assert f.size == 0
    assert f.folder_path == ""


def test_sync_state_empty():
    s = SyncState()
    assert s.start_page_token == ""
    assert s.files == {}


def test_export_mimes_covers_google_types():
    assert "application/vnd.google-apps.document" in EXPORT_MIMES
    assert "application/vnd.google-apps.spreadsheet" in EXPORT_MIMES
    assert "application/vnd.google-apps.presentation" in EXPORT_MIMES


def test_size_threshold():
    assert SIZE_THRESHOLD == 25 * 1024 * 1024


# ── State Management & Folder Resolution ────────────────────────────────────


def test_load_state_empty(tmp_path):
    """Loading state from nonexistent file returns empty SyncState."""
    from agents.gdrive_sync import _load_state

    state = _load_state(tmp_path / "state.json")
    assert state.files == {}
    assert state.start_page_token == ""


def test_save_load_roundtrip(tmp_path):
    """State survives save/load roundtrip."""
    from agents.gdrive_sync import _load_state, _save_state

    state_file = tmp_path / "state.json"
    state = SyncState(start_page_token="tok123")
    state.files["abc"] = DriveFile(
        drive_id="abc",
        name="test.txt",
        mime_type="text/plain",
    )
    _save_state(state, state_file)
    loaded = _load_state(state_file)
    assert loaded.start_page_token == "tok123"
    assert "abc" in loaded.files


def test_resolve_folder_path():
    """Folder path resolution builds full path from parent chain."""
    from agents.gdrive_sync import _resolve_folder_path

    folder_names = {"root": "My Drive", "a": "Projects", "b": "Client X"}
    # b -> a -> root
    folder_parents = {"b": "a", "a": "root"}
    path = _resolve_folder_path("b", folder_names, folder_parents)
    assert path == "My Drive/Projects/Client X"


def test_resolve_folder_path_no_parent():
    """Folder with no parent returns just its name."""
    from agents.gdrive_sync import _resolve_folder_path

    path = _resolve_folder_path("a", {"a": "Orphan"}, {})
    assert path == "Orphan"


# ── MIME Classification ──────────────────────────────────────────────────────


def test_classify_document():
    from agents.gdrive_sync import _classify_file

    tier, ctype, tags = _classify_file("report.pdf", "application/pdf", 1000)
    assert tier == "document"
    assert ctype == "document"
    assert "text" in tags


def test_classify_large_audio():
    from agents.gdrive_sync import _classify_file

    tier, ctype, tags = _classify_file("beat.wav", "audio/wav", 50_000_000)
    assert tier == "metadata_only"
    assert ctype == "audio"
    assert "binary" in tags


def test_classify_google_doc():
    from agents.gdrive_sync import _classify_file

    tier, ctype, tags = _classify_file("My Doc", "application/vnd.google-apps.document", 0)
    assert tier == "document"
    assert ctype == "document"


def test_classify_small_image():
    from agents.gdrive_sync import _classify_file

    tier, ctype, tags = _classify_file("photo.jpg", "image/jpeg", 2_000_000)
    assert tier == "document"
    assert ctype == "image"
    assert "visual" in tags


def test_classify_large_unknown():
    from agents.gdrive_sync import _classify_file

    tier, ctype, tags = _classify_file("blob.bin", "application/octet-stream", 100_000_000)
    assert tier == "metadata_only"


def test_generate_metadata_stub():
    from agents.gdrive_sync import _generate_metadata_stub

    stub = _generate_metadata_stub(
        DriveFile(
            drive_id="abc123",
            name="drum-break.wav",
            mime_type="audio/wav",
            size=52_428_800,
            modified_time="2026-01-15T10:30:00.000Z",
            folder_path="My Drive/Samples/Drum Breaks",
            web_view_link="https://drive.google.com/file/d/abc123/view",
        )
    )
    assert "platform: google" in stub
    assert "service: drive" in stub
    assert "source_service: gdrive" in stub
    assert "drum-break.wav" in stub
    assert "audio/wav" in stub
    assert "Drum Breaks" in stub
    assert "abc123" in stub


# ── Profiler Bridge ──────────────────────────────────────────────────────────


def test_ingest_auto_tags_drive_files():
    """Files from rag-sources/gdrive/ get source_service auto-tagged."""
    from pathlib import Path

    from agents.ingest import enrich_payload

    payload = {
        "source": str(Path.home() / "documents/rag-sources/gdrive/My Drive/Projects/report.pdf"),
        "filename": "report.pdf",
    }
    result = enrich_payload(payload, {})
    assert result.get("source_service") == "gdrive"
    assert result.get("gdrive_folder") == "My Drive"


def test_ingest_auto_tags_calendar_files():
    """Files from rag-sources/gcalendar/ get source_service auto-tagged."""
    from pathlib import Path

    from agents.ingest import enrich_payload

    payload = {
        "source": str(Path.home() / "documents/rag-sources/gcalendar/2026-03-10-standup.md"),
        "filename": "2026-03-10-standup.md",
    }
    result = enrich_payload(payload, {})
    assert result.get("source_service") == "gcalendar"


def test_ingest_no_auto_tag_other_files():
    """Files outside rag-sources service dirs are not auto-tagged."""
    from agents.ingest import enrich_payload

    payload = {
        "source": "/home/user/documents/rag-sources/captures/screenshot.md",
        "filename": "screenshot.md",
    }
    result = enrich_payload(payload, {})
    assert "source_service" not in result or result.get("source_service") == ""


def test_ingest_frontmatter_overrides_auto_tag():
    """Frontmatter source_service takes precedence over path auto-detection."""
    from pathlib import Path

    from agents.ingest import enrich_payload

    payload = {
        "source": str(Path.home() / "documents/rag-sources/gdrive/My Drive/report.pdf"),
        "filename": "report.pdf",
    }
    frontmatter = {"source_service": "custom_service"}
    result = enrich_payload(payload, frontmatter)
    assert result.get("source_service") == "custom_service"


def test_generate_profile_facts():
    from agents.gdrive_sync import _generate_profile_facts

    state = SyncState()
    state.files = {
        "1": DriveFile(
            drive_id="1",
            name="beat.wav",
            mime_type="audio/wav",
            size=50_000_000,
            folder_path="Samples/Drums",
        ),
        "2": DriveFile(
            drive_id="2",
            name="notes.md",
            mime_type="text/markdown",
            size=1000,
            folder_path="Projects/Track1",
        ),
        "3": DriveFile(
            drive_id="3",
            name="synth.wav",
            mime_type="audio/wav",
            size=30_000_000,
            folder_path="Samples/Synths",
        ),
    }
    facts = _generate_profile_facts(state)
    assert len(facts) > 0
    dims = {f["dimension"] for f in facts}
    assert "information_seeking" in dims or "tool_usage" in dims
    assert all(f["confidence"] == 0.95 for f in facts)
