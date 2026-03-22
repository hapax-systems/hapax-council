"""Tests for audio-related reactive rules (Batch 5).

Imports reactive_rules directly (not via logos.engine package)
to avoid the watchdog dependency.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

# Mock watchdog before any logos.engine import
_watchdog_mock = MagicMock()
sys.modules.setdefault("watchdog", _watchdog_mock)
sys.modules.setdefault("watchdog.events", _watchdog_mock)
sys.modules.setdefault("watchdog.observers", _watchdog_mock)
sys.modules.setdefault("watchdog.observers.polling", _watchdog_mock)

from logos.engine.models import ChangeEvent  # noqa: E402


def _make_event(path_str, event_type="created"):
    return ChangeEvent(
        path=Path(path_str),
        event_type=event_type,
        doc_type=None,
        frontmatter=None,
        timestamp=datetime.now(),
    )


def test_audio_archive_sidecar_filter_matches():
    from logos.engine.reactive_rules import _audio_archive_sidecar_filter

    event = _make_event("/home/operator/audio-recording/archive/rec-20260308.md")
    assert _audio_archive_sidecar_filter(event) is True


def test_audio_archive_sidecar_filter_rejects_non_md():
    from logos.engine.reactive_rules import _audio_archive_sidecar_filter

    event = _make_event("/home/operator/audio-recording/archive/rec-20260308.flac")
    assert _audio_archive_sidecar_filter(event) is False


def test_audio_archive_sidecar_filter_rejects_modified():
    from logos.engine.reactive_rules import _audio_archive_sidecar_filter

    event = _make_event(
        "/home/operator/audio-recording/archive/rec-20260308.md",
        event_type="modified",
    )
    assert _audio_archive_sidecar_filter(event) is False


def test_audio_archive_sidecar_filter_rejects_wrong_dir():
    from logos.engine.reactive_rules import _audio_archive_sidecar_filter

    event = _make_event("/home/operator/documents/rag-sources/audio/sample-20260308.md")
    assert _audio_archive_sidecar_filter(event) is False


def test_audio_clap_indexed_filter_matches_listening():
    from logos.engine.reactive_rules import _audio_clap_indexed_filter

    event = _make_event(
        "/home/operator/documents/rag-sources/audio/listening-rec-20260308-s000000.md"
    )
    assert _audio_clap_indexed_filter(event) is True


def test_audio_clap_indexed_filter_matches_sample():
    from logos.engine.reactive_rules import _audio_clap_indexed_filter

    event = _make_event("/home/operator/documents/rag-sources/audio/sample-rec-20260308-s000530.md")
    assert _audio_clap_indexed_filter(event) is True


def test_audio_clap_indexed_filter_matches_note():
    from logos.engine.reactive_rules import _audio_clap_indexed_filter

    event = _make_event("/home/operator/documents/rag-sources/audio/note-rec-20260308-s000530.md")
    assert _audio_clap_indexed_filter(event) is True


def test_audio_clap_indexed_filter_matches_conv():
    from logos.engine.reactive_rules import _audio_clap_indexed_filter

    event = _make_event("/home/operator/documents/rag-sources/audio/conv-rec-20260308-s000530.md")
    assert _audio_clap_indexed_filter(event) is True


def test_audio_clap_indexed_filter_rejects_non_audio():
    from logos.engine.reactive_rules import _audio_clap_indexed_filter

    event = _make_event("/home/operator/documents/rag-sources/gdrive/meeting-notes.md")
    assert _audio_clap_indexed_filter(event) is False


def test_audio_clap_indexed_filter_rejects_modified():
    from logos.engine.reactive_rules import _audio_clap_indexed_filter

    event = _make_event(
        "/home/operator/documents/rag-sources/audio/listening-rec-20260308.md",
        event_type="modified",
    )
    assert _audio_clap_indexed_filter(event) is False


def test_audio_rules_registered():
    """Both audio rules are present in ALL_RULES."""
    from logos.engine.reactive_rules import ALL_RULES

    rule_names = {r.name for r in ALL_RULES}
    assert "audio-archive-sidecar" in rule_names
    assert "audio-clap-indexed" in rule_names


def test_audio_archive_sidecar_produce_phase0():
    from logos.engine.reactive_rules import _audio_archive_sidecar_produce

    event = _make_event("/home/operator/audio-recording/archive/rec-20260308.md")
    actions = _audio_archive_sidecar_produce(event)
    assert len(actions) == 1
    assert actions[0].phase == 0


def test_audio_clap_indexed_produce_phase1():
    from logos.engine.reactive_rules import _audio_clap_indexed_produce

    event = _make_event("/home/operator/documents/rag-sources/audio/listening-rec-20260308.md")
    actions = _audio_clap_indexed_produce(event)
    assert len(actions) == 1
    assert actions[0].phase == 1
