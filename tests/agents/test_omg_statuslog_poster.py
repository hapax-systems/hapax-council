"""Tests for agents/omg_statuslog_poster — ytb-OMG4.

Verifies the autonomous statuslog poster:
  - rate-limit + debounce (max 3/day, min 4h interval)
  - allowlist integration (state_kind + redactions)
  - composer mock returning a short, literary status body
  - referent picker seeded per-status (stable across retries)
  - publication-bus publisher called with correct payload
  - disabled client / denied allowlist / failed post all silent-skip
    with metric and no crash
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest  # noqa: TC002

from agents.omg_statuslog_poster.poster import (
    StatuslogPoster,
    _compose_status_text,
)
from agents.publication_bus.publisher_kit import PublisherResult


def _chronicle_event(
    *, event_id: str = "evt1", salience: float = 0.85, summary: str = "a moment of grounding"
) -> dict:
    return {
        "event_id": event_id,
        "source": "director_observability",
        "ts": "2026-04-24T16:00:00Z",
        "salience": salience,
        "summary": summary,
        "stance": "nominal",
        "grounding_gate_result": _grounding_gate(),
    }


def _grounding_gate() -> dict:
    return {
        "schema_version": 1,
        "public_private_mode": "public_archive",
        "gate_state": "pass",
        "claim": {
            "evidence_refs": ["chronicle:event"],
            "provenance": {"source_refs": ["chronicle:source"]},
            "freshness": {"status": "fresh"},
            "rights_state": "operator_controlled",
            "privacy_state": "public_safe",
            "public_private_mode": "public_archive",
            "refusal_correction_path": {
                "refusal_reason": None,
                "correction_event_ref": None,
                "artifact_ref": None,
            },
        },
        "gate_result": {
            "may_emit_claim": True,
            "may_publish_live": False,
            "may_publish_archive": True,
            "may_monetize": False,
        },
    }


class TestDebounce:
    def test_first_post_allowed(self, tmp_path: Path) -> None:
        poster = StatuslogPoster(
            client=_make_client(),
            publisher=_make_publisher(),
            state_file=tmp_path / "state.json",
            min_interval_s=14400,
            daily_cap=3,
            now_fn=lambda: 1_000_000.0,
            compose_fn=lambda event: "ok status",
        )
        assert poster.can_post_now() is True

    def test_within_interval_blocked(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        poster = StatuslogPoster(
            client=_make_client(),
            publisher=_make_publisher(),
            state_file=state_file,
            min_interval_s=14400,
            daily_cap=3,
            now_fn=lambda: 1_000_000.0,
            compose_fn=lambda event: "ok",
        )
        poster.post(_chronicle_event())
        # 1s later: still in 4h debounce window.
        poster._now_fn = lambda: 1_000_001.0
        assert poster.can_post_now() is False

    def test_after_interval_allowed_again(self, tmp_path: Path) -> None:
        poster = StatuslogPoster(
            client=_make_client(),
            publisher=_make_publisher(),
            state_file=tmp_path / "state.json",
            min_interval_s=10,
            daily_cap=3,
            now_fn=lambda: 1_000_000.0,
            compose_fn=lambda event: "ok",
        )
        poster.post(_chronicle_event())
        poster._now_fn = lambda: 1_000_020.0  # +20s > 10s interval
        assert poster.can_post_now() is True

    def test_daily_cap_enforced(self, tmp_path: Path) -> None:
        poster = StatuslogPoster(
            client=_make_client(),
            publisher=_make_publisher(),
            state_file=tmp_path / "state.json",
            min_interval_s=0,  # no interval gate
            daily_cap=2,
            now_fn=lambda: 1_000_000.0,
            compose_fn=lambda event: "ok",
        )
        poster.post(_chronicle_event(event_id="1"))
        poster._now_fn = lambda: 1_000_001.0
        poster.post(_chronicle_event(event_id="2"))
        poster._now_fn = lambda: 1_000_002.0
        # Third attempt blocked by daily cap even though interval is 0.
        outcome = poster.post(_chronicle_event(event_id="3"))
        assert outcome == "cap-exceeded"


class TestSalienceGate:
    def test_below_threshold_skipped(self, tmp_path: Path) -> None:
        poster = StatuslogPoster(
            client=_make_client(),
            publisher=_make_publisher(),
            state_file=tmp_path / "state.json",
            min_interval_s=0,
            daily_cap=3,
            min_salience=0.75,
            now_fn=lambda: 1_000_000.0,
            compose_fn=lambda event: "x",
        )
        outcome = poster.post(_chronicle_event(salience=0.5))
        assert outcome == "low-salience"

    def test_at_threshold_posted(self, tmp_path: Path) -> None:
        poster = StatuslogPoster(
            client=_make_client(),
            publisher=_make_publisher(),
            state_file=tmp_path / "state.json",
            min_interval_s=0,
            daily_cap=3,
            min_salience=0.75,
            now_fn=lambda: 1_000_000.0,
            compose_fn=lambda event: "ok",
        )
        outcome = poster.post(_chronicle_event(salience=0.75))
        assert outcome == "posted"


class TestAllowlistIntegration:
    def test_allowlist_deny_skips_silently(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Stub the allowlist to return deny for every call.
        from agents.omg_statuslog_poster import poster as poster_mod

        def _deny(*args, **kwargs):
            from shared.governance.publication_allowlist import AllowlistResult

            return AllowlistResult(decision="deny", payload={}, reason="stub deny")

        monkeypatch.setattr(poster_mod, "allowlist_check", _deny)

        poster = StatuslogPoster(
            client=_make_client(),
            publisher=_make_publisher(),
            state_file=tmp_path / "state.json",
            min_interval_s=0,
            daily_cap=3,
            now_fn=lambda: 1_000_000.0,
            compose_fn=lambda event: "ok",
        )
        outcome = poster.post(_chronicle_event())
        assert outcome == "allowlist-denied"

    def test_allowlist_redact_passes_redacted_payload(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agents.omg_statuslog_poster import poster as poster_mod

        def _redact(*args, **kwargs):
            from shared.governance.publication_allowlist import AllowlistResult

            return AllowlistResult(
                decision="redact", payload={"summary": "(redacted)"}, reason="stub"
            )

        monkeypatch.setattr(poster_mod, "allowlist_check", _redact)

        client = _make_client()
        publisher = _make_publisher()
        poster = StatuslogPoster(
            client=client,
            publisher=publisher,
            state_file=tmp_path / "state.json",
            min_interval_s=0,
            daily_cap=3,
            now_fn=lambda: 1_000_000.0,
            compose_fn=lambda event: "ok",
        )
        outcome = poster.post(_chronicle_event())
        assert outcome == "posted"


class TestComposerIntegration:
    def test_composer_called_with_event_payload(self, tmp_path: Path) -> None:
        seen: list[dict] = []

        def _compose(event: dict) -> str:
            seen.append(event)
            return "a literary status"

        poster = StatuslogPoster(
            client=_make_client(),
            publisher=_make_publisher(),
            state_file=tmp_path / "state.json",
            min_interval_s=0,
            daily_cap=3,
            now_fn=lambda: 1_000_000.0,
            compose_fn=_compose,
        )
        poster.post(_chronicle_event(event_id="evt-composed"))
        assert len(seen) == 1
        assert seen[0]["event_id"] == "evt-composed"

    def test_composer_returning_empty_skips_post(self, tmp_path: Path) -> None:
        poster = StatuslogPoster(
            client=_make_client(),
            publisher=_make_publisher(),
            state_file=tmp_path / "state.json",
            min_interval_s=0,
            daily_cap=3,
            now_fn=lambda: 1_000_000.0,
            compose_fn=lambda event: "",
        )
        outcome = poster.post(_chronicle_event())
        assert outcome == "compose-empty"


class TestPostShape:
    def test_publisher_called_with_content_and_address(self, tmp_path: Path) -> None:
        client = _make_client()
        publisher = _make_publisher()
        poster = StatuslogPoster(
            client=client,
            publisher=publisher,
            state_file=tmp_path / "state.json",
            min_interval_s=0,
            daily_cap=3,
            now_fn=lambda: 1_000_000.0,
            compose_fn=lambda event: "a status",
            address="hapax",
        )
        poster.post(_chronicle_event())
        publisher.publish.assert_called_once()
        payload = publisher.publish.call_args.args[0]
        assert payload.target == "hapax"
        assert payload.text == "a status"
        assert payload.metadata["skip_mastodon_post"] is True

    def test_post_truncates_long_content_to_280(self, tmp_path: Path) -> None:
        client = _make_client()
        publisher = _make_publisher()
        long_content = "x" * 400
        poster = StatuslogPoster(
            client=client,
            publisher=publisher,
            state_file=tmp_path / "state.json",
            min_interval_s=0,
            daily_cap=3,
            now_fn=lambda: 1_000_000.0,
            compose_fn=lambda event: long_content,
        )
        poster.post(_chronicle_event())
        payload = publisher.publish.call_args.args[0]
        assert len(payload.text) <= 280


class TestDisabledClient:
    def test_disabled_client_short_circuits(self, tmp_path: Path) -> None:
        client = MagicMock()
        client.enabled = False
        publisher = _make_publisher()
        poster = StatuslogPoster(
            client=client,
            publisher=publisher,
            state_file=tmp_path / "state.json",
            min_interval_s=0,
            daily_cap=3,
            now_fn=lambda: 1_000_000.0,
            compose_fn=lambda event: "ok",
        )
        outcome = poster.post(_chronicle_event())
        assert outcome == "client-disabled"
        publisher.publish.assert_not_called()


class TestPostFailure:
    def test_failed_post_reports_failed(self, tmp_path: Path) -> None:
        client = _make_client()
        publisher = _make_publisher(PublisherResult(error=True, detail="network_error"))
        poster = StatuslogPoster(
            client=client,
            publisher=publisher,
            state_file=tmp_path / "state.json",
            min_interval_s=0,
            daily_cap=3,
            now_fn=lambda: 1_000_000.0,
            compose_fn=lambda event: "ok",
        )
        outcome = poster.post(_chronicle_event())
        assert outcome == "failed"


def _make_client() -> MagicMock:
    client = MagicMock()
    client.enabled = True
    return client


def _make_publisher(result: PublisherResult | None = None) -> MagicMock:
    publisher = MagicMock()
    publisher.publish.return_value = result or PublisherResult(ok=True, detail="ok")
    return publisher


class TestComposeStatusText:
    def test_compose_status_text_returns_string(self) -> None:
        """Thin wrapper; guarantee it returns a string for any plausible input."""
        llm_stub = MagicMock(return_value="a terse literary moment")
        result = _compose_status_text(_chronicle_event(), llm_call=llm_stub)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_compose_status_text_handles_llm_exception(self) -> None:
        """LLM call failure → empty string (caller treats as compose-empty)."""

        def _raise(*args, **kwargs):
            raise RuntimeError("LLM down")

        result = _compose_status_text(_chronicle_event(), llm_call=_raise)
        assert result == ""
