"""Tests for agents/omg_purl_registrar — ytb-OMG7."""

from __future__ import annotations

from unittest.mock import MagicMock

from agents.omg_purl_registrar.registrar import (
    PurlRegistrar,
    PurlSpec,
    build_initial_purls,
)


def _make_client(*, enabled: bool = True, existing: list[dict] | None = None) -> MagicMock:
    client = MagicMock()
    client.enabled = enabled
    client.list_purls.return_value = {"response": {"purls": list(existing or [])}}
    client.create_purl.return_value = {
        "request": {"statusCode": 200},
        "response": {"name": "x", "url": "x"},
    }
    return client


class TestBuildInitialPurls:
    def test_returns_canonical_set(self) -> None:
        purls = build_initial_purls()
        slugs = {p.slug for p in purls}
        # All documented slugs present.
        assert {"stream", "geal", "vocab", "axioms", "research", "now", "mail"}.issubset(slugs)

    def test_each_target_is_a_url_or_mailto(self) -> None:
        for p in build_initial_purls():
            assert p.target.startswith(("https://", "http://", "mailto:"))

    def test_credits_slug_included_post_omg_credits(self) -> None:
        purls = build_initial_purls()
        assert any(p.slug == "credits" for p in purls)


class TestRegisterSingle:
    def test_new_slug_creates(self) -> None:
        client = _make_client(existing=[])
        reg = PurlRegistrar(client)
        outcome = reg.register(PurlSpec(slug="geal", target="https://example.com/spec"))
        assert outcome == "created"
        client.create_purl.assert_called_once()

    def test_existing_same_target_is_unchanged(self) -> None:
        client = _make_client(existing=[{"name": "geal", "url": "https://example.com/spec"}])
        reg = PurlRegistrar(client)
        outcome = reg.register(PurlSpec(slug="geal", target="https://example.com/spec"))
        assert outcome == "unchanged"
        client.create_purl.assert_not_called()

    def test_existing_drifted_target_is_skipped_without_force(self) -> None:
        client = _make_client(existing=[{"name": "geal", "url": "https://example.com/old-spec"}])
        reg = PurlRegistrar(client)
        outcome = reg.register(PurlSpec(slug="geal", target="https://example.com/new-spec"))
        assert outcome == "drift-skipped"
        client.create_purl.assert_not_called()

    def test_existing_drifted_target_overwrites_with_force(self) -> None:
        client = _make_client(existing=[{"name": "geal", "url": "https://example.com/old-spec"}])
        reg = PurlRegistrar(client)
        outcome = reg.register(
            PurlSpec(slug="geal", target="https://example.com/new-spec"),
            force=True,
        )
        assert outcome == "drift-overwritten"
        client.create_purl.assert_called_once()

    def test_disabled_client_returns_disabled(self) -> None:
        client = _make_client(enabled=False)
        reg = PurlRegistrar(client)
        outcome = reg.register(PurlSpec(slug="x", target="https://y"))
        assert outcome == "disabled"
        client.create_purl.assert_not_called()
        client.list_purls.assert_not_called()

    def test_create_purl_failure_reports_failed(self) -> None:
        client = _make_client(existing=[])
        client.create_purl.return_value = None
        reg = PurlRegistrar(client)
        outcome = reg.register(PurlSpec(slug="geal", target="https://x"))
        assert outcome == "failed"

    def test_create_purl_receives_correct_arguments(self) -> None:
        client = _make_client(existing=[])
        reg = PurlRegistrar(client, address="hapax")
        reg.register(PurlSpec(slug="geal", target="https://spec.example"))
        client.create_purl.assert_called_once_with("hapax", name="geal", url="https://spec.example")


class TestSeed:
    def test_seed_empty_upstream_creates_all(self) -> None:
        client = _make_client(existing=[])
        reg = PurlRegistrar(client)
        outcomes = reg.seed()
        # Every outcome is "created" since the upstream was empty.
        assert all(v == "created" for v in outcomes.values())
        assert client.create_purl.call_count == len(outcomes)

    def test_seed_with_partial_upstream_marks_unchanged(self) -> None:
        # Upstream already has `stream` registered correctly.
        existing = [{"name": "stream", "url": "https://www.youtube.com/@LegomenaLive"}]
        client = _make_client(existing=existing)
        reg = PurlRegistrar(client)
        outcomes = reg.seed()
        assert outcomes["stream"] == "unchanged"
        # Every other slug should be "created".
        created_count = sum(1 for v in outcomes.values() if v == "created")
        unchanged_count = sum(1 for v in outcomes.values() if v == "unchanged")
        assert unchanged_count == 1
        assert created_count == len(outcomes) - 1

    def test_seed_accepts_custom_spec_list(self) -> None:
        client = _make_client(existing=[])
        reg = PurlRegistrar(client)
        custom = [PurlSpec(slug="only", target="https://only.example")]
        outcomes = reg.seed(custom)
        assert outcomes == {"only": "created"}
        assert client.create_purl.call_count == 1


class TestExistingUnwrap:
    def test_handles_missing_response_wrapper(self) -> None:
        # Some API surfaces return {"purls": [...]} at top level.
        client = MagicMock()
        client.enabled = True
        client.list_purls.return_value = {"purls": [{"name": "x", "url": "https://y"}]}
        client.create_purl.return_value = {}
        reg = PurlRegistrar(client)
        outcome = reg.register(PurlSpec(slug="x", target="https://y"))
        assert outcome == "unchanged"

    def test_handles_null_list_response(self) -> None:
        client = MagicMock()
        client.enabled = True
        client.list_purls.return_value = None
        client.create_purl.return_value = {}
        reg = PurlRegistrar(client)
        outcome = reg.register(PurlSpec(slug="x", target="https://y"))
        assert outcome == "created"
