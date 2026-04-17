"""Tests for LRR Phase 6 §4.F — Gmail + Calendar tool handlers broadcast-safe.

When stream is publicly visible, handle_get_calendar_today and
handle_search_emails must return a fixed redacted stub, never calling Google
APIs. When stream is private (or off), they proceed normally.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


class _FakeParams:
    """Minimal stand-in for pipecat FunctionCallParams."""

    def __init__(self, arguments: dict):
        self.arguments = arguments
        self.result_callback = AsyncMock()


# ── Calendar handler ────────────────────────────────────────────────────────


class TestCalendarBroadcastRedaction:
    @pytest.mark.asyncio
    async def test_public_returns_stub(self, monkeypatch):
        """stream publicly visible → stub response, no Google API call."""
        monkeypatch.setattr(
            "agents.hapax_daimonion.tools._stream_is_publicly_visible", lambda: True
        )
        # If this path tries to hit Google, we fail the test loudly
        monkeypatch.setattr(
            "agents.hapax_daimonion.tools.build_service",
            lambda *a, **kw: pytest.fail("build_service called — should short-circuit"),
        )

        from agents.hapax_daimonion import tools

        params = _FakeParams({"days_ahead": 2})
        await tools.handle_get_calendar_today(params)

        params.result_callback.assert_awaited_once()
        (call_arg,), _ = params.result_callback.call_args_list[0]
        assert "not broadcast-safe" in call_arg.lower()
        assert "calendar" in call_arg.lower()
        # No event titles, no attendees, no locations leak
        for leak_marker in ("@", "with ", "event:"):
            assert leak_marker not in call_arg

    @pytest.mark.asyncio
    async def test_private_proceeds_normally(self, monkeypatch):
        """stream NOT publicly visible → handler runs normally (exercised here
        by asserting it makes the build_service call and then propagates
        whatever the fake service returns)."""
        monkeypatch.setattr(
            "agents.hapax_daimonion.tools._stream_is_publicly_visible", lambda: False
        )

        class _FakeEvents:
            def list(self, **kw):
                return self

            def execute(self):
                return {"items": []}

        class _FakeService:
            def events(self):
                return _FakeEvents()

        monkeypatch.setattr(
            "agents.hapax_daimonion.tools.build_service", lambda *a, **kw: _FakeService()
        )

        from agents.hapax_daimonion import tools

        params = _FakeParams({"days_ahead": 2})
        await tools.handle_get_calendar_today(params)

        params.result_callback.assert_awaited_once()
        (call_arg,), _ = params.result_callback.call_args_list[0]
        # Normal path returns "calendar is clear" on empty events
        assert "calendar is clear" in call_arg.lower()


# ── Email handler ───────────────────────────────────────────────────────────


class TestEmailBroadcastRedaction:
    @pytest.mark.asyncio
    async def test_public_returns_stub(self, monkeypatch):
        monkeypatch.setattr(
            "agents.hapax_daimonion.tools._stream_is_publicly_visible", lambda: True
        )
        # No Qdrant or Gmail should be called
        monkeypatch.setattr(
            "agents.hapax_daimonion.tools.embed",
            lambda *a, **kw: pytest.fail("embed called — should short-circuit"),
        )
        monkeypatch.setattr(
            "agents.hapax_daimonion.tools.get_qdrant_grpc",
            lambda *a, **kw: pytest.fail("get_qdrant_grpc called — should short-circuit"),
        )
        monkeypatch.setattr(
            "agents.hapax_daimonion.tools.build_service",
            lambda *a, **kw: pytest.fail("build_service called — should short-circuit"),
        )

        from agents.hapax_daimonion import tools

        params = _FakeParams({"query": "quarterly review", "recent_only": False})
        await tools.handle_search_emails(params)

        params.result_callback.assert_awaited_once()
        (call_arg,), _ = params.result_callback.call_args_list[0]
        assert "not broadcast-safe" in call_arg.lower()
        assert "email" in call_arg.lower()
        # No From:, Subject:, or body leakage
        for leak_marker in ("from:", "subject:", "@"):
            assert leak_marker not in call_arg.lower()

    @pytest.mark.asyncio
    async def test_public_redacts_regardless_of_recent_only_mode(self, monkeypatch):
        """Both Qdrant path (recent_only=False) and Gmail API path
        (recent_only=True) redact on public."""
        monkeypatch.setattr(
            "agents.hapax_daimonion.tools._stream_is_publicly_visible", lambda: True
        )

        from agents.hapax_daimonion import tools

        for recent_only in (True, False):
            params = _FakeParams({"query": "anything", "recent_only": recent_only})
            await tools.handle_search_emails(params)
            params.result_callback.assert_awaited()
            (call_arg,), _ = params.result_callback.call_args_list[-1]
            assert "not broadcast-safe" in call_arg.lower()


# ── Fail-closed import shim ─────────────────────────────────────────────────


class TestFailClosedImport:
    def test_import_error_fails_closed_to_public(self, monkeypatch):
        """If shared.stream_mode can't be imported, _stream_is_publicly_visible
        must return True (most restrictive). Phase 6 fail-closed invariant."""
        # Simulate import failure by patching the import to raise
        import builtins

        real_import = builtins.__import__

        def raising_import(name, *a, **kw):
            if name == "shared.stream_mode":
                raise ImportError("simulated")
            return real_import(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", raising_import)

        from agents.hapax_daimonion import tools

        assert tools._stream_is_publicly_visible() is True
