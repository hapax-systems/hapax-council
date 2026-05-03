"""Tests for agents.bluesky_atproto_adapter.publish_artifact.

Mirrors the refusal-brief Zenodo adapter test shape (#1676) — covers
credential resolution, payload composition, result mapping, and
orchestrator dispatch-map registration.
"""

from __future__ import annotations

from unittest.mock import patch

from agents.bluesky_atproto_adapter import (
    APP_PASSWORD_ENV,
    DID_ENV,
    HANDLE_ENV,
    publish_artifact,
)
from agents.publication_bus.publisher_kit import PublisherResult
from shared.preprint_artifact import PreprintArtifact


def _artifact(**overrides) -> PreprintArtifact:
    defaults = dict(
        slug="velocity-paper-shipped",
        title="Velocity findings: 70 PRs/8h sustained",
        abstract="Empirical results on autonomous-loop Hapax operator-mediation.",
        body_md="# Body\n\nFull writeup...\n",
        surfaces_targeted=["bluesky-atproto-multi-identity"],
    )
    defaults.update(overrides)
    return PreprintArtifact(**defaults)


class TestCredentialResolution:
    def test_missing_handle_and_did_returns_auth_error(self, monkeypatch):
        monkeypatch.delenv(HANDLE_ENV, raising=False)
        monkeypatch.delenv(DID_ENV, raising=False)
        monkeypatch.setenv(APP_PASSWORD_ENV, "fake-app-pw")
        assert publish_artifact(_artifact()) == "auth_error"

    def test_missing_app_password_returns_auth_error(self, monkeypatch):
        monkeypatch.setenv(HANDLE_ENV, "oudepode.bsky.social")
        monkeypatch.delenv(APP_PASSWORD_ENV, raising=False)
        assert publish_artifact(_artifact()) == "auth_error"

    def test_did_acceptable_when_handle_missing(self, monkeypatch):
        monkeypatch.delenv(HANDLE_ENV, raising=False)
        monkeypatch.setenv(DID_ENV, "did:plc:fake1234")
        monkeypatch.setenv(APP_PASSWORD_ENV, "fake-app-pw")
        with patch(
            "agents.bluesky_atproto_adapter.BlueskyPublisher.publish",
            return_value=PublisherResult(ok=True),
        ):
            assert publish_artifact(_artifact()) == "ok"

    def test_handle_preferred_over_did(self, monkeypatch):
        monkeypatch.setenv(HANDLE_ENV, "oudepode.bsky.social")
        monkeypatch.setenv(DID_ENV, "did:plc:fake1234")
        monkeypatch.setenv(APP_PASSWORD_ENV, "fake-app-pw")
        captured: dict = {}

        def fake_init(self, *, handle, app_password):
            captured["handle"] = handle
            captured["app_password"] = app_password

        with (
            patch(
                "agents.bluesky_atproto_adapter.BlueskyPublisher.__init__",
                new=fake_init,
            ),
            patch(
                "agents.bluesky_atproto_adapter.BlueskyPublisher.publish",
                return_value=PublisherResult(ok=True),
            ),
        ):
            publish_artifact(_artifact())
        assert captured["handle"] == "oudepode.bsky.social"


class TestResultMapping:
    def _setup_creds(self, monkeypatch):
        monkeypatch.setenv(HANDLE_ENV, "oudepode.bsky.social")
        monkeypatch.setenv(APP_PASSWORD_ENV, "fake-app-pw")

    def test_ok_result(self, monkeypatch):
        self._setup_creds(monkeypatch)
        with patch(
            "agents.bluesky_atproto_adapter.BlueskyPublisher.publish",
            return_value=PublisherResult(ok=True),
        ):
            assert publish_artifact(_artifact()) == "ok"

    def test_refused_allowlist(self, monkeypatch):
        self._setup_creds(monkeypatch)
        with patch(
            "agents.bluesky_atproto_adapter.BlueskyPublisher.publish",
            return_value=PublisherResult(refused=True, detail="allowlist deny"),
        ):
            assert publish_artifact(_artifact()) == "denied"

    def test_refused_no_credentials(self, monkeypatch):
        self._setup_creds(monkeypatch)
        with patch(
            "agents.bluesky_atproto_adapter.BlueskyPublisher.publish",
            return_value=PublisherResult(refused=True, detail="missing Bluesky credentials"),
        ):
            assert publish_artifact(_artifact()) == "auth_error"

    def test_error(self, monkeypatch):
        self._setup_creds(monkeypatch)
        with patch(
            "agents.bluesky_atproto_adapter.BlueskyPublisher.publish",
            return_value=PublisherResult(error=True, detail="HTTP 503"),
        ):
            assert publish_artifact(_artifact()) == "error"


class TestPostTextComposition:
    def _capture(self, monkeypatch, artifact):
        monkeypatch.setenv(HANDLE_ENV, "x")
        monkeypatch.setenv(APP_PASSWORD_ENV, "y")
        captured = {}

        def fake_publish(self, payload):
            captured["payload"] = payload
            return PublisherResult(ok=True)

        with patch(
            "agents.bluesky_atproto_adapter.BlueskyPublisher.publish",
            new=fake_publish,
        ):
            publish_artifact(artifact)
        return captured["payload"]

    def test_short_title_plus_abstract_used_verbatim(self, monkeypatch):
        p = self._capture(
            monkeypatch,
            _artifact(title="hi", abstract="short"),
        )
        assert p.text == "hi\n\nshort"

    def test_long_text_truncated_to_280_chars(self, monkeypatch):
        long_abstract = "a" * 500
        p = self._capture(monkeypatch, _artifact(abstract=long_abstract))
        assert len(p.text) <= 280
        assert p.text.endswith("...")

    def test_target_is_artifact_slug(self, monkeypatch):
        p = self._capture(monkeypatch, _artifact(slug="my-slug"))
        assert p.target == "my-slug"


class TestDispatchAndWireStatus:
    def test_bluesky_in_dispatch_map(self):
        from agents.publish_orchestrator.orchestrator import SURFACE_REGISTRY

        assert "bluesky-atproto-multi-identity" in SURFACE_REGISTRY
        assert SURFACE_REGISTRY["bluesky-atproto-multi-identity"].endswith(":publish_artifact")

    def test_wire_status_now_wired(self):
        from agents.publication_bus.wire_status import PUBLISHER_WIRE_REGISTRY

        entry = PUBLISHER_WIRE_REGISTRY["agents.publication_bus.bluesky_publisher"]
        assert entry.status == "WIRED"
        assert entry.pass_key_required is None


# ── Oudepode identity (cc-task bluesky-atproto-oudepode-identity-followup) ──


class TestOudepodeIdentitySelection:
    """Pin the multi-identity contract: oudepode entry-point uses
    OUDEPODE-prefixed env vars exclusively. Cross-contamination across
    identities (operator creds answering oudepode dispatch or vice
    versa) is the load-bearing failure mode this suite catches."""

    def test_oudepode_missing_handle_returns_auth_error(self, monkeypatch):
        from agents.bluesky_atproto_adapter import (
            OUDEPODE_APP_PASSWORD_ENV,
            OUDEPODE_DID_ENV,
            OUDEPODE_HANDLE_ENV,
            publish_artifact_oudepode,
        )

        monkeypatch.delenv(OUDEPODE_HANDLE_ENV, raising=False)
        monkeypatch.delenv(OUDEPODE_DID_ENV, raising=False)
        monkeypatch.setenv(OUDEPODE_APP_PASSWORD_ENV, "fake-pw")
        # Operator creds present must NOT satisfy oudepode dispatch.
        monkeypatch.setenv(HANDLE_ENV, "operator.bsky.social")
        monkeypatch.setenv(APP_PASSWORD_ENV, "operator-pw")
        assert publish_artifact_oudepode(_artifact()) == "auth_error"

    def test_oudepode_missing_app_password_returns_auth_error(self, monkeypatch):
        from agents.bluesky_atproto_adapter import (
            OUDEPODE_APP_PASSWORD_ENV,
            OUDEPODE_HANDLE_ENV,
            publish_artifact_oudepode,
        )

        monkeypatch.setenv(OUDEPODE_HANDLE_ENV, "oudepode.bsky.social")
        monkeypatch.delenv(OUDEPODE_APP_PASSWORD_ENV, raising=False)
        assert publish_artifact_oudepode(_artifact()) == "auth_error"

    def test_oudepode_creds_resolve_independently_from_operator(self, monkeypatch):
        """Pin the identity-isolation invariant: oudepode dispatch
        constructs the publisher with OUDEPODE handle + app-password,
        NEVER the operator's. Cross-contamination would silently post
        from the wrong account — this is the load-bearing failure mode
        the cc-task wants prevented."""
        from agents.bluesky_atproto_adapter import (
            OUDEPODE_APP_PASSWORD_ENV,
            OUDEPODE_HANDLE_ENV,
            publish_artifact_oudepode,
        )

        monkeypatch.setenv(HANDLE_ENV, "operator.bsky.social")
        monkeypatch.setenv(APP_PASSWORD_ENV, "operator-pw")
        monkeypatch.setenv(OUDEPODE_HANDLE_ENV, "oudepode.bsky.social")
        monkeypatch.setenv(OUDEPODE_APP_PASSWORD_ENV, "oudepode-pw")
        captured: dict = {}

        def fake_init(self, *, handle, app_password):
            captured["handle"] = handle
            captured["app_password"] = app_password

        with (
            patch(
                "agents.bluesky_atproto_adapter.BlueskyPublisher.__init__",
                new=fake_init,
            ),
            patch(
                "agents.bluesky_atproto_adapter.BlueskyPublisher.publish",
                return_value=PublisherResult(ok=True),
            ),
        ):
            publish_artifact_oudepode(_artifact())
        assert captured["handle"] == "oudepode.bsky.social", (
            "oudepode dispatch must use OUDEPODE handle, not operator's"
        )
        assert captured["app_password"] == "oudepode-pw", (
            "oudepode dispatch must use OUDEPODE app password, not operator's"
        )

    def test_operator_creds_resolve_independently_from_oudepode(self, monkeypatch):
        """Inverse pin: operator dispatch constructs the publisher with
        OPERATOR handle + app-password, NEVER oudepode's. Catches the
        symmetric cross-contamination."""
        from agents.bluesky_atproto_adapter import (
            OUDEPODE_APP_PASSWORD_ENV,
            OUDEPODE_HANDLE_ENV,
        )

        monkeypatch.setenv(HANDLE_ENV, "operator.bsky.social")
        monkeypatch.setenv(APP_PASSWORD_ENV, "operator-pw")
        monkeypatch.setenv(OUDEPODE_HANDLE_ENV, "oudepode.bsky.social")
        monkeypatch.setenv(OUDEPODE_APP_PASSWORD_ENV, "oudepode-pw")
        captured: dict = {}

        def fake_init(self, *, handle, app_password):
            captured["handle"] = handle
            captured["app_password"] = app_password

        with (
            patch(
                "agents.bluesky_atproto_adapter.BlueskyPublisher.__init__",
                new=fake_init,
            ),
            patch(
                "agents.bluesky_atproto_adapter.BlueskyPublisher.publish",
                return_value=PublisherResult(ok=True),
            ),
        ):
            publish_artifact(_artifact())
        assert captured["handle"] == "operator.bsky.social"
        assert captured["app_password"] == "operator-pw"

    def test_oudepode_did_acceptable_when_handle_missing(self, monkeypatch):
        from agents.bluesky_atproto_adapter import (
            OUDEPODE_APP_PASSWORD_ENV,
            OUDEPODE_DID_ENV,
            OUDEPODE_HANDLE_ENV,
            publish_artifact_oudepode,
        )

        monkeypatch.delenv(OUDEPODE_HANDLE_ENV, raising=False)
        monkeypatch.setenv(OUDEPODE_DID_ENV, "did:plc:oudepode1234")
        monkeypatch.setenv(OUDEPODE_APP_PASSWORD_ENV, "fake-pw")
        with patch(
            "agents.bluesky_atproto_adapter.BlueskyPublisher.publish",
            return_value=PublisherResult(ok=True),
        ):
            assert publish_artifact_oudepode(_artifact()) == "ok"

    def test_oudepode_in_surface_registry(self):
        """Oudepode identity is registered as a parallel FULL_AUTO
        surface alongside the operator surface."""
        from agents.publication_bus.surface_registry import SURFACE_REGISTRY

        assert "oudepode-bluesky-atproto" in SURFACE_REGISTRY
        spec = SURFACE_REGISTRY["oudepode-bluesky-atproto"]
        assert spec.dispatch_entry.endswith(":publish_artifact_oudepode")
        assert spec.api == "ATProto"
        assert "music" in (spec.scope_note or "").lower()
