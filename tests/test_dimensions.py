"""Tests for the dimension registry."""

import pytest

from shared.dimensions import (
    DIMENSIONS,
    get_dimension,
    get_dimension_names,
    get_dimensions_by_kind,
    validate_behavioral_write,
)


def test_dimension_count():
    assert len(DIMENSIONS) == 11


def test_trait_dimensions_count():
    traits = get_dimensions_by_kind("trait")
    assert len(traits) == 5


def test_behavioral_dimensions_count():
    behavioral = get_dimensions_by_kind("behavioral")
    assert len(behavioral) == 6


def test_get_dimension_by_name():
    dim = get_dimension("identity")
    assert dim is not None
    assert dim.kind == "trait"
    assert dim.name == "identity"


def test_get_dimension_unknown_returns_none():
    assert get_dimension("nonexistent") is None


def test_get_dimension_names_returns_all():
    names = get_dimension_names()
    assert len(names) == 11
    assert "identity" in names
    assert "work_patterns" in names


def test_trait_dimension_names():
    traits = get_dimensions_by_kind("trait")
    names = {d.name for d in traits}
    assert names == {
        "identity",
        "neurocognitive",
        "values",
        "communication_style",
        "relationships",
    }


def test_behavioral_dimension_names():
    behavioral = get_dimensions_by_kind("behavioral")
    names = {d.name for d in behavioral}
    assert names == {
        "work_patterns",
        "energy_and_attention",
        "information_seeking",
        "creative_process",
        "tool_usage",
        "communication_patterns",
    }


def test_validate_behavioral_write_accepts_valid():
    # Should not raise
    validate_behavioral_write("work_patterns", "gcalendar_sync")


def test_validate_behavioral_write_rejects_trait():
    with pytest.raises(ValueError, match="trait dimension"):
        validate_behavioral_write("identity", "gcalendar_sync")


def test_validate_behavioral_write_rejects_unknown():
    with pytest.raises(ValueError, match="unknown dimension"):
        validate_behavioral_write("hardware", "gcalendar_sync")


def test_dimension_def_is_frozen():
    dim = get_dimension("identity")
    with pytest.raises(AttributeError):
        dim.name = "changed"


def test_all_dimensions_have_consumers():
    for dim in DIMENSIONS:
        assert len(dim.consumers) > 0, f"{dim.name} has no consumers"


def test_all_dimensions_have_sources():
    for dim in DIMENSIONS:
        assert len(dim.primary_sources) > 0, f"{dim.name} has no sources"


def test_interview_eligible_defaults_true():
    dim = get_dimension("identity")
    assert dim.interview_eligible is True


def test_communication_patterns_not_interview_eligible():
    dim = get_dimension("communication_patterns")
    assert dim.interview_eligible is False


# ── Sync agent behavioral validation ──────────────────────────────────────


def _get_sync_agent_facts(module_name: str, state_factory):
    """Import and call a sync agent's _generate_profile_facts."""
    import importlib

    mod = importlib.import_module(f"agents.{module_name}")
    return mod._generate_profile_facts(state_factory())


def test_all_sync_agent_facts_target_behavioral_dimensions():
    """Every fact produced by sync agents must target a behavioral dimension."""
    from agents.audio_processor import AudioProcessorState, ProcessedFileInfo
    from agents.audio_processor import _generate_profile_facts as audio_facts
    from agents.chrome_sync import ChromeSyncState
    from agents.chrome_sync import _generate_profile_facts as chrome_facts
    from agents.claude_code_sync import ClaudeCodeSyncState, TranscriptMetadata
    from agents.claude_code_sync import _generate_profile_facts as cc_facts
    from agents.gcalendar_sync import CalendarEvent, CalendarSyncState
    from agents.gcalendar_sync import _generate_profile_facts as gcal_facts
    from agents.gmail_sync import EmailMetadata, GmailSyncState
    from agents.gmail_sync import _generate_profile_facts as gmail_facts
    from agents.obsidian_sync import ObsidianSyncState, VaultNote
    from agents.obsidian_sync import _generate_profile_facts as obs_facts
    from agents.youtube_sync import LikedVideo, Subscription, YouTubeSyncState
    from agents.youtube_sync import _generate_profile_facts as yt_facts

    # Build minimal states that produce facts
    gcal_state = CalendarSyncState(
        events={
            "1": CalendarEvent(
                event_id="1",
                summary="standup",
                start="2026-03-10T09:00:00Z",
                end="2026-03-10T09:30:00Z",
                attendees=["a@b.com"],
                recurring=True,
            ),
        }
    )
    gmail_state = GmailSyncState(
        messages={
            "1": EmailMetadata(
                message_id="1",
                thread_id="t1",
                sender="x@y.com",
                subject="hi",
                timestamp="2026-03-10T10:00:00Z",
                labels=["INBOX"],
            ),
        }
    )
    chrome_state = ChromeSyncState(domains={"github.com": 50})
    yt_state = YouTubeSyncState(
        liked_videos={
            "v1": LikedVideo(
                video_id="v1", title="t", channel="ch", tags=["music"], published="2026-01-01"
            )
        },
        subscriptions={"ch1": Subscription(channel_id="ch1", channel_name="Chan")},
    )
    obs_state = ObsidianSyncState(
        notes={
            "n1": VaultNote(
                relative_path="folder/note.md",
                title="note",
                folder="folder",
                content_hash="abc123",
                size=100,
                mtime=1710000000.0,
                tags=["tag"],
            ),
        }
    )
    cc_state = ClaudeCodeSyncState(
        sessions={
            "s1": TranscriptMetadata(session_id="s1", project_name="proj", message_count=10),
        }
    )
    audio_state = AudioProcessorState(
        processed_files={
            "f1": ProcessedFileInfo(
                filename="rec.wav",
                speech_seconds=100,
                music_seconds=50,
                silence_seconds=20,
                segment_count=5,
                speaker_count=2,
            ),
        }
    )

    all_facts = (
        gcal_facts(gcal_state)
        + gmail_facts(gmail_state)
        + chrome_facts(chrome_state)
        + yt_facts(yt_state)
        + obs_facts(obs_state)
        + cc_facts(cc_state)
        + audio_facts(audio_state)
    )

    assert len(all_facts) > 0, "Expected at least one fact from sync agents"
    for fact in all_facts:
        validate_behavioral_write(fact["dimension"], fact.get("source", "test"))
