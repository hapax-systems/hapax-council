from __future__ import annotations

import hashlib
import unittest
import uuid
from datetime import UTC, datetime, timedelta

from shared.relay_mq_envelope import (
    PRIORITY_FRESHNESS,
    Envelope,
    TransitionError,
    deserialize_tags,
    serialize_tags,
    validate_transition,
)


def _make_envelope(**overrides) -> Envelope:
    defaults: dict = {
        "sender": "test",
        "message_type": "advisory",
        "subject": "test message",
        "recipients_spec": "alpha",
        "payload": "test payload",
    }
    defaults.update(overrides)
    return Envelope(**defaults)


class TestEnvelopeValid(unittest.TestCase):
    def test_advisory_envelope_valid(self) -> None:
        env = _make_envelope()
        self.assertEqual(env.message_type, "advisory")
        self.assertIsNotNone(env.payload_hash)

    def test_dispatch_requires_authority_case(self) -> None:
        with self.assertRaises(ValueError, msg="Dispatch without authority_case should raise"):
            _make_envelope(message_type="dispatch")

    def test_dispatch_with_authority_case_valid(self) -> None:
        env = _make_envelope(
            message_type="dispatch",
            authority_case="CASE-001",
        )
        self.assertEqual(env.authority_case, "CASE-001")


class TestPayloadExclusivity(unittest.TestCase):
    def test_payload_exclusivity_both_set(self) -> None:
        with self.assertRaises(ValueError):
            _make_envelope(payload="data", payload_path="/some/path")

    def test_payload_exclusivity_neither_set(self) -> None:
        with self.assertRaises(ValueError):
            _make_envelope(payload=None, payload_path=None)


class TestPayloadHash(unittest.TestCase):
    def test_payload_hash_auto_computed(self) -> None:
        env = _make_envelope(payload="hello world")
        self.assertIsNotNone(env.payload_hash)

    def test_payload_hash_matches_content(self) -> None:
        content = "hello world"
        env = _make_envelope(payload=content)
        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
        self.assertEqual(env.payload_hash, expected)


class TestFreshness(unittest.TestCase):
    def test_default_freshness_p0(self) -> None:
        env = _make_envelope(priority=0)
        stale_offset, expire_offset = PRIORITY_FRESHNESS[0]
        expected_stale = env.created_at + timedelta(seconds=stale_offset)
        expected_expire = env.created_at + timedelta(seconds=expire_offset)
        self.assertEqual(env.stale_after, expected_stale)
        self.assertEqual(env.expires_at, expected_expire)

    def test_default_freshness_p2(self) -> None:
        env = _make_envelope(priority=2)
        stale_offset, expire_offset = PRIORITY_FRESHNESS[2]
        expected_stale = env.created_at + timedelta(seconds=stale_offset)
        expected_expire = env.created_at + timedelta(seconds=expire_offset)
        self.assertEqual(env.stale_after, expected_stale)
        self.assertEqual(env.expires_at, expected_expire)

    def test_explicit_freshness_overrides_default(self) -> None:
        explicit = datetime(2099, 1, 1, tzinfo=UTC)
        env = _make_envelope(expires_at=explicit)
        self.assertEqual(env.expires_at, explicit)


class TestNormalization(unittest.TestCase):
    def test_sender_normalization(self) -> None:
        env = _make_envelope(sender="Alpha")
        self.assertEqual(env.sender, "alpha")

        env2 = _make_envelope(sender="cx_red")
        self.assertEqual(env2.sender, "cx-red")

    def test_subject_truncation(self) -> None:
        long_subject = "a" * 300
        env = _make_envelope(subject=long_subject)
        self.assertEqual(len(env.subject), 200)


class TestValidation(unittest.TestCase):
    def test_priority_range(self) -> None:
        with self.assertRaises(ValueError):
            _make_envelope(priority=-1)
        with self.assertRaises(ValueError):
            _make_envelope(priority=4)

    def test_message_type_enum(self) -> None:
        with self.assertRaises(ValueError):
            _make_envelope(message_type="invalid")


class TestTransitions(unittest.TestCase):
    def test_valid_transitions(self) -> None:
        valid_pairs = [
            ("offered", "read", None),
            ("read", "accepted", None),
            ("read", "deferred", "reason"),
            ("read", "escalated", "reason"),
            ("accepted", "processed", None),
            ("accepted", "deferred", "reason"),
            ("accepted", "escalated", "reason"),
            ("deferred", "accepted", None),
            ("deferred", "escalated", "reason"),
        ]
        for current, target, reason in valid_pairs:
            validate_transition(current, target, reason)

    def test_invalid_transitions(self) -> None:
        invalid_pairs = [
            ("offered", "accepted"),
            ("offered", "processed"),
            ("offered", "deferred"),
            ("offered", "escalated"),
            ("read", "offered"),
            ("read", "processed"),
            ("processed", "offered"),
            ("processed", "read"),
            ("processed", "accepted"),
            ("processed", "deferred"),
            ("processed", "escalated"),
            ("escalated", "offered"),
            ("escalated", "read"),
            ("escalated", "accepted"),
            ("escalated", "deferred"),
            ("escalated", "processed"),
        ]
        for current, target in invalid_pairs:
            with self.assertRaises(TransitionError, msg=f"{current} -> {target} should fail"):
                validate_transition(current, target, reason="some reason")

    def test_reason_required_for_deferred(self) -> None:
        with self.assertRaises(ValueError):
            validate_transition("read", "deferred", reason=None)

    def test_reason_required_for_escalated(self) -> None:
        with self.assertRaises(ValueError):
            validate_transition("read", "escalated", reason=None)


class TestTagsSerialization(unittest.TestCase):
    def test_tags_serialization_roundtrip(self) -> None:
        tags = ["foo", "bar", "baz"]
        raw = serialize_tags(tags)
        self.assertEqual(deserialize_tags(raw), tags)

    def test_tags_none_serialization(self) -> None:
        self.assertIsNone(serialize_tags(None))
        self.assertIsNone(deserialize_tags(None))


class TestUUID(unittest.TestCase):
    def test_uuid_v7_format(self) -> None:
        env = _make_envelope()
        parsed = uuid.UUID(env.message_id)
        version_bits = (parsed.int >> 76) & 0xF
        self.assertEqual(version_bits, 7)
        variant_bits = (parsed.int >> 62) & 0x3
        self.assertEqual(variant_bits, 2)
        ts_ms = (parsed.int >> 80) & 0xFFFFFFFFFFFF
        self.assertGreater(ts_ms, 0)


if __name__ == "__main__":
    unittest.main()
