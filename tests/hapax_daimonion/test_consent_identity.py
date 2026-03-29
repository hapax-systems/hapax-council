"""Tests for consent identity resolution — enrollment paradox, guest tracking.

Self-contained, unittest.mock only.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from agents.hapax_daimonion.consent_identity import (
    GuestIdentity,
    GuestTracker,
    enroll_guest_speaker,
    find_enrolled_guests,
    process_curtailed_segments,
    resolve_guest_identity,
)


class TestResolveGuestIdentity(unittest.TestCase):
    def test_operator_always_has_contract(self):
        identity = resolve_guest_identity("operator", confidence=0.9)
        assert identity.person_id == "operator"
        assert identity.has_contract

    def test_unknown_speaker_no_contract(self):
        with patch("shared.governance.consent.load_contracts") as mock:
            mock_reg = MagicMock()
            mock_reg.get_contract_for.return_value = None
            mock.return_value = mock_reg

            identity = resolve_guest_identity("not_operator", confidence=0.3)
            assert identity.person_id == "unknown"
            assert not identity.has_contract

    def test_known_guest_with_contract(self):
        with patch("shared.governance.consent.load_contracts") as mock:
            mock_reg = MagicMock()
            mock_contract = MagicMock()
            mock_contract.active = True
            mock_contract.scope = frozenset({"audio", "video"})
            mock_reg.get_contract_for.return_value = mock_contract
            mock.return_value = mock_reg

            identity = resolve_guest_identity("wife", confidence=0.85)
            assert identity.person_id == "wife"
            assert identity.has_contract
            assert "audio" in identity.contract_scope

    def test_known_guest_revoked_contract(self):
        with patch("shared.governance.consent.load_contracts") as mock:
            mock_reg = MagicMock()
            mock_contract = MagicMock()
            mock_contract.active = False
            mock_reg.get_contract_for.return_value = mock_contract
            mock.return_value = mock_reg

            identity = resolve_guest_identity("wife", confidence=0.85)
            assert not identity.has_contract


class TestGuestTracker(unittest.TestCase):
    def test_empty_tracker(self):
        tracker = GuestTracker()
        assert tracker.guest_count == 0
        assert tracker.all_consented
        assert not tracker.any_pending

    def test_add_guest(self):
        tracker = GuestTracker()
        tracker.add_or_update(GuestIdentity("wife", has_contract=True))
        assert tracker.guest_count == 1
        assert tracker.all_consented

    def test_unconsented_guest(self):
        tracker = GuestTracker()
        tracker.add_or_update(GuestIdentity("unknown", has_contract=False))
        assert not tracker.all_consented
        assert tracker.any_pending
        assert "unknown" in tracker.unconsented_guests

    def test_mixed_consent_state(self):
        tracker = GuestTracker()
        tracker.add_or_update(GuestIdentity("wife", has_contract=True))
        tracker.add_or_update(GuestIdentity("friend", has_contract=False))
        assert not tracker.all_consented
        assert tracker.any_pending
        assert tracker.unconsented_guests == ["friend"]

    def test_update_existing(self):
        tracker = GuestTracker()
        tracker.add_or_update(GuestIdentity("wife", has_contract=False))
        assert not tracker.all_consented
        tracker.add_or_update(GuestIdentity("wife", has_contract=True))
        assert tracker.all_consented

    def test_clear(self):
        tracker = GuestTracker()
        tracker.add_or_update(GuestIdentity("wife", has_contract=True))
        tracker.clear()
        assert tracker.guest_count == 0

    def test_enrollment_queue(self):
        tracker = GuestTracker()
        embedding = np.random.randn(256).astype(np.float32)
        tracker.queue_enrollment("wife", embedding)
        pending = tracker.pop_pending_enrollments()
        assert len(pending) == 1
        assert pending[0][0] == "wife"
        assert tracker.pop_pending_enrollments() == []  # cleared


class TestEnrollGuestSpeaker(unittest.TestCase):
    def test_saves_embedding(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            enrollment_dir = Path(tmpdir)
            embedding = np.random.randn(256).astype(np.float32)

            with patch("agents.hapax_daimonion.consent_identity.ENROLLMENT_DIR", enrollment_dir):
                success = enroll_guest_speaker("wife", embedding)

            assert success
            saved = enrollment_dir / "wife.npy"
            assert saved.exists()
            loaded = np.load(saved)
            # Should be normalized
            assert abs(np.linalg.norm(loaded) - 1.0) < 0.01

    def test_normalizes_embedding(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            enrollment_dir = Path(tmpdir)
            embedding = np.array([3.0, 4.0], dtype=np.float32)  # norm = 5

            with patch("agents.hapax_daimonion.consent_identity.ENROLLMENT_DIR", enrollment_dir):
                enroll_guest_speaker("test", embedding)

            loaded = np.load(enrollment_dir / "test.npy")
            assert abs(np.linalg.norm(loaded) - 1.0) < 0.01


class TestFindEnrolledGuests(unittest.TestCase):
    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("agents.hapax_daimonion.consent_identity.ENROLLMENT_DIR", Path(tmpdir)):
                assert find_enrolled_guests() == []

    def test_finds_guests(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            np.save(d / "wife.npy", np.zeros(10))
            np.save(d / "friend.npy", np.zeros(10))
            np.save(d / "operator.npy", np.zeros(10))  # should be excluded

            with patch("agents.hapax_daimonion.consent_identity.ENROLLMENT_DIR", d):
                guests = find_enrolled_guests()
                assert "wife" in guests
                assert "friend" in guests
                assert "operator" not in guests


class TestProcessCurtailedSegments(unittest.TestCase):
    def test_tags_recent_segments(self):
        import time

        with tempfile.TemporaryDirectory() as tmpdir:
            raw_dir = Path(tmpdir) / "audio-recording" / "raw"
            raw_dir.mkdir(parents=True)

            flac = raw_dir / "rec-20260315-030000.flac"
            flac.write_text("audio data")

            with patch(
                "agents.hapax_daimonion.consent_identity.Path.home",
                return_value=Path(tmpdir),
            ):
                queued = process_curtailed_segments(
                    guest_first_seen=time.time() - 60,
                    person_id="wife",
                    scope=frozenset({"audio", "transcription"}),
                )

            assert queued == 1
            sidecar = flac.with_suffix(".consent.json")
            assert sidecar.exists()

    def test_no_audio_in_scope_skips(self):
        queued = process_curtailed_segments(
            guest_first_seen=0.0,
            person_id="wife",
            scope=frozenset({"video"}),  # no audio
        )
        assert queued == 0


class TestIdentityProperties(unittest.TestCase):
    @given(
        n_consented=st.integers(min_value=0, max_value=5),
        n_unconsented=st.integers(min_value=0, max_value=5),
    )
    @settings(max_examples=50)
    def test_all_consented_iff_none_pending(self, n_consented, n_unconsented):
        """∀ tracker: all_consented ↔ ¬any_pending (when guests exist)."""
        tracker = GuestTracker()
        for i in range(n_consented):
            tracker.add_or_update(GuestIdentity(f"ok-{i}", has_contract=True))
        for i in range(n_unconsented):
            tracker.add_or_update(GuestIdentity(f"no-{i}", has_contract=False))

        if n_consented + n_unconsented > 0:
            assert tracker.all_consented == (not tracker.any_pending)

    @given(
        speaker=st.sampled_from(
            ["operator", "operator", "not_operator", "uncertain", "wife", "friend"]
        ),
    )
    @settings(max_examples=30)
    def test_operator_always_has_contract(self, speaker):
        """∀ speaker: operator labels always resolve to has_contract=True."""
        identity = resolve_guest_identity(speaker)
        if speaker in ("operator", "operator"):
            assert identity.has_contract
            assert identity.person_id == "operator"
