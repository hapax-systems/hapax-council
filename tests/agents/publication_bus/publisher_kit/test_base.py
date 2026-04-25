"""Tests for ``agents.publication_bus.publisher_kit.base.Publisher``.

The Publisher ABC enforces three invariants in its ``publish()``
superclass method (allowlist gate, legal-name-leak guard, counter).
Subclass code overrides ``_emit()`` only. These tests pin the
invariant-enforcement contract.
"""

from __future__ import annotations

import pytest  # noqa: TC002 — used as runtime fixture marker in test parameters

from agents.publication_bus.publisher_kit import (
    AllowlistGate,
    Publisher,
    PublisherPayload,
    PublisherResult,
)


def _make_allowlist(*permitted: str) -> AllowlistGate:
    return AllowlistGate(surface_name="test-surface", permitted=frozenset(permitted))


class _FakePublisher(Publisher):
    """Minimal subclass exposing _emit calls for assertion."""

    surface_name = "test-surface"
    allowlist = _make_allowlist("permitted-target")
    requires_legal_name = False

    def __init__(self) -> None:
        self.emit_calls: list[PublisherPayload] = []
        self._next_result: PublisherResult = PublisherResult(ok=True, detail="emit ok")

    def _emit(self, payload: PublisherPayload) -> PublisherResult:
        self.emit_calls.append(payload)
        return self._next_result


class TestAllowlistGate:
    def test_permits_registered_target(self) -> None:
        pub = _FakePublisher()
        result = pub.publish(PublisherPayload(target="permitted-target", text="hello"))
        assert result.ok
        assert len(pub.emit_calls) == 1

    def test_refuses_unregistered_target(self) -> None:
        pub = _FakePublisher()
        result = pub.publish(PublisherPayload(target="other-target", text="hello"))
        assert result.refused
        assert not result.ok
        assert len(pub.emit_calls) == 0  # _emit was NOT called
        assert "allowlist" in result.detail.lower()

    def test_refused_emits_no_legal_name_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Allowlist refusal short-circuits before the legal-name guard."""
        # Set a legal-name pattern that the text would match — proves
        # the guard isn't reached.
        monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Test Operator")
        pub = _FakePublisher()
        result = pub.publish(PublisherPayload(target="bad-target", text="Hello Test Operator"))
        # Refused for allowlist, NOT for legal-name leak
        assert result.refused
        assert "allowlist" in result.detail.lower()


class TestLegalNameLeakGuard:
    def test_passes_when_text_clean(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Test Operator")
        pub = _FakePublisher()
        result = pub.publish(PublisherPayload(target="permitted-target", text="hello world"))
        assert result.ok

    def test_refuses_on_leak(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Test Operator")
        pub = _FakePublisher()
        result = pub.publish(PublisherPayload(target="permitted-target", text="from Test Operator"))
        assert result.refused
        assert not result.ok
        assert len(pub.emit_calls) == 0  # _emit was NOT called
        assert "legal-name" in result.detail.lower()

    def test_skipped_when_requires_legal_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Surface that formally requires legal name (Zenodo creators)
        bypasses the guard. The legal name in the text is expected."""
        monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Test Operator")

        class _ZenodoLikePublisher(_FakePublisher):
            requires_legal_name = True

        pub = _ZenodoLikePublisher()
        result = pub.publish(PublisherPayload(target="permitted-target", text="from Test Operator"))
        assert result.ok
        assert len(pub.emit_calls) == 1


class TestCounterEmission:
    """The superclass increments the Prometheus counter per publish-event.

    These tests verify the counter is incremented at all three
    outcomes (ok / refused / error). Direct counter inspection is
    deferred to integration tests; the unit-level pin is that
    publish() does not raise on counter operations.
    """

    def test_ok_outcome_does_not_raise(self) -> None:
        pub = _FakePublisher()
        result = pub.publish(PublisherPayload(target="permitted-target", text="x"))
        assert result.ok

    def test_refused_outcome_does_not_raise(self) -> None:
        pub = _FakePublisher()
        result = pub.publish(PublisherPayload(target="bad", text="x"))
        assert result.refused

    def test_error_outcome_does_not_raise(self) -> None:
        class _RaisingPublisher(_FakePublisher):
            def _emit(self, payload: PublisherPayload) -> PublisherResult:
                raise RuntimeError("transport failed")

        pub = _RaisingPublisher()
        result = pub.publish(PublisherPayload(target="permitted-target", text="x"))
        assert result.error
        assert "raised" in result.detail.lower()


class TestSubclassOverrideContract:
    def test_emit_receives_payload(self) -> None:
        pub = _FakePublisher()
        payload = PublisherPayload(
            target="permitted-target",
            text="body",
            metadata={"key": "value"},
        )
        pub.publish(payload)
        assert len(pub.emit_calls) == 1
        assert pub.emit_calls[0] is payload

    def test_emit_can_return_refused(self) -> None:
        """Subclass can return refused for surface-specific reasons
        (e.g., upstream rate-limit); superclass forwards the result."""
        pub = _FakePublisher()
        pub._next_result = PublisherResult(refused=True, detail="rate-limited")
        result = pub.publish(PublisherPayload(target="permitted-target", text="x"))
        assert result.refused
        assert "rate-limited" in result.detail
