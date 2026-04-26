"""Tests for ``agents.operator_awareness.omg_lol_fanout``.

Pure-function coverage: render output stays under budget, never
leaks private fields (the constitutional invariant), skip-if-
unchanged gates correctly. The HTTP path is exercised against a
mocked ``requests.Session`` so the test never touches the network.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

from agents.operator_awareness.omg_lol_fanout import (
    STATUS_TEXT_BUDGET,
    _content_hash,
    fanout,
    render_status,
)
from agents.operator_awareness.state import (
    AwarenessState,
    DaimonionBlock,
    HealthBlock,
    RefusalEvent,
    StreamBlock,
)


def _state(**overrides) -> AwarenessState:
    return AwarenessState(
        timestamp=datetime(2026, 4, 26, 2, 0, tzinfo=UTC),
        **overrides,
    )


# ── render_status ───────────────────────────────────────────────────


class TestRenderStatus:
    def test_includes_timestamp(self):
        text = render_status(_state())
        assert "02:00Z" in text

    def test_under_budget(self):
        # Worst case: every block populated.
        text = render_status(
            _state(
                stream=StreamBlock(public=True, live=True, chronicle_events_5min=42),
                daimonion_voice=DaimonionBlock(public=True, stance="ALERT"),
                health_system=HealthBlock(public=True, overall_status="degraded"),
                refusals_recent=[
                    RefusalEvent(
                        timestamp=datetime.now(UTC),
                        surface="x",
                        reason=str(i),
                    )
                    for i in range(10)
                ],
            )
        )
        assert len(text) <= STATUS_TEXT_BUDGET

    def test_omits_unknown_stance(self):
        text = render_status(_state(daimonion_voice=DaimonionBlock(public=True, stance="unknown")))
        assert "stance" not in text

    def test_omits_offline_stream(self):
        text = render_status(_state(stream=StreamBlock(public=True, live=False)))
        assert "stream live" not in text

    def test_no_private_field_reaches_output(self):
        """Constitutional invariant: every block defaults public=False
        and the renderer must not surface any field that
        public_filter would redact. This pins the renderer against
        accidentally bypassing the filter."""
        # All blocks default public=False — anything render emits
        # must come from the filtered (zeroed) view.
        state = _state(
            health_system=HealthBlock(
                public=False,
                overall_status="critical",
                failed_units=99,
                disk_pct_used=88.0,
            ),
            daimonion_voice=DaimonionBlock(public=False, stance="GROUNDING"),
            stream=StreamBlock(public=False, live=True, chronicle_events_5min=999),
        )
        text = render_status(state)
        # Private values must NOT appear.
        assert "critical" not in text
        assert "GROUNDING" not in text
        assert "stream live" not in text
        assert "999" not in text
        assert "88" not in text


# ── _content_hash ───────────────────────────────────────────────────


def test_content_hash_deterministic():
    assert _content_hash("hello") == _content_hash("hello")
    assert _content_hash("hello") != _content_hash("world")


# ── fanout (HTTP path) ──────────────────────────────────────────────


class TestFanout:
    def _mock_session(self, status: int = 200) -> MagicMock:
        sess = MagicMock()
        resp = MagicMock()
        resp.status_code = status
        sess.post.return_value = resp
        return sess

    def test_first_post_succeeds_and_writes_sidecar(self, tmp_path: Path):
        sidecar = tmp_path / "hash.txt"
        sess = self._mock_session(200)
        result = fanout(
            _state(stream=StreamBlock(public=True, live=True)),
            address="hapax",
            token="t",
            last_hash_path=sidecar,
            session=sess,
        )
        assert result == "ok"
        assert sidecar.exists()
        sess.post.assert_called_once()
        called_url = sess.post.call_args.args[0]
        assert "address/hapax/statuses" in called_url

    def test_unchanged_payload_skips(self, tmp_path: Path):
        sidecar = tmp_path / "hash.txt"
        state = _state(stream=StreamBlock(public=True, live=True))
        sess = self._mock_session(200)
        # First call posts.
        assert (
            fanout(state, address="hapax", token="t", last_hash_path=sidecar, session=sess) == "ok"
        )
        sess.post.reset_mock()
        # Identical state → skip.
        assert (
            fanout(state, address="hapax", token="t", last_hash_path=sidecar, session=sess)
            == "skipped"
        )
        sess.post.assert_not_called()

    def test_changed_payload_reposts(self, tmp_path: Path):
        sidecar = tmp_path / "hash.txt"
        sess = self._mock_session(200)
        state_a = _state(stream=StreamBlock(public=True, live=True))
        state_b = _state(stream=StreamBlock(public=True, live=False))
        assert (
            fanout(state_a, address="hapax", token="t", last_hash_path=sidecar, session=sess)
            == "ok"
        )
        sess.post.reset_mock()
        assert (
            fanout(state_b, address="hapax", token="t", last_hash_path=sidecar, session=sess)
            == "ok"
        )
        sess.post.assert_called_once()

    def test_http_error_returns_label_does_not_update_sidecar(self, tmp_path: Path):
        sidecar = tmp_path / "hash.txt"
        sess = self._mock_session(500)
        result = fanout(
            _state(stream=StreamBlock(public=True, live=True)),
            address="hapax",
            token="t",
            last_hash_path=sidecar,
            session=sess,
        )
        assert result == "http_error"
        # Sidecar must remain absent so the next tick retries.
        assert not sidecar.exists()

    def test_network_error_swallowed(self, tmp_path: Path):
        import requests as _requests

        sidecar = tmp_path / "hash.txt"
        sess = MagicMock()
        sess.post.side_effect = _requests.exceptions.ConnectionError("dns down")
        result = fanout(
            _state(stream=StreamBlock(public=True, live=True)),
            address="hapax",
            token="t",
            last_hash_path=sidecar,
            session=sess,
        )
        assert result == "network_error"
        assert not sidecar.exists()

    def test_skip_mastodon_default_true(self, tmp_path: Path):
        """The Mastodon mirror is opt-in by default — Bridgy handles
        cross-posting separately and we don't want double-fanout."""
        sidecar = tmp_path / "hash.txt"
        sess = self._mock_session(200)
        fanout(
            _state(stream=StreamBlock(public=True, live=True)),
            address="hapax",
            token="t",
            last_hash_path=sidecar,
            session=sess,
        )
        body = sess.post.call_args.kwargs["json"]
        assert body["skip_mastodon_post"] is True


# ── fanout_once / CLI entry ────────────────────────────────────────


class TestFanoutOnce:
    """Exercises the systemd-timer-driven entry point."""

    def test_no_creds_returns_skip(self, tmp_path, monkeypatch):
        from agents.operator_awareness.omg_lol_fanout import fanout_once

        monkeypatch.delenv("HAPAX_OMG_LOL_ADDRESS", raising=False)
        monkeypatch.delenv("HAPAX_OMG_LOL_TOKEN", raising=False)
        outcome = fanout_once(
            state_path=tmp_path / "state.json",
            last_hash_path=tmp_path / "hash.txt",
        )
        assert outcome == "no_creds"

    def test_no_state_returns_skip(self, tmp_path):
        from agents.operator_awareness.omg_lol_fanout import fanout_once

        outcome = fanout_once(
            state_path=tmp_path / "absent.json",
            address="hapax",
            token="t",
            last_hash_path=tmp_path / "hash.txt",
        )
        assert outcome == "no_state"

    def test_malformed_state_returns_no_state(self, tmp_path):
        from agents.operator_awareness.omg_lol_fanout import fanout_once

        path = tmp_path / "state.json"
        path.write_text("not json", encoding="utf-8")
        outcome = fanout_once(
            state_path=path,
            address="hapax",
            token="t",
            last_hash_path=tmp_path / "hash.txt",
        )
        assert outcome == "no_state"

    def test_main_exits_zero_even_on_skip(self, monkeypatch):
        """systemd timer should not see an exit code that triggers
        backoff just because there are no creds yet (catch-22 during
        bootstrap). main() always returns 0."""
        from agents.operator_awareness.omg_lol_fanout import main

        monkeypatch.delenv("HAPAX_OMG_LOL_ADDRESS", raising=False)
        monkeypatch.delenv("HAPAX_OMG_LOL_TOKEN", raising=False)
        assert main() == 0
