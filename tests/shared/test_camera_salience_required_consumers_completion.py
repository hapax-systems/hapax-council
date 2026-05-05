"""Tests for the remaining 5 REQUIRED_CONSUMERS broker wiring.

Cc-task ``bayesian-camera-salience-required-consumers-completion``.
The broker-production-wiring PR wired ``director`` and ``affordance``
into the singleton; this test module verifies that the other five
required consumers (``content_opportunity``, ``voice``, ``wcs_health``,
``archive``, ``visual_variance``) each issue at least one
``broker().query(...)`` on their existing decision cadence AND use the
returned bundle in their downstream payload (no side-effect-only calls).

Each consumer's path is exercised with three MagicMock fixtures:

  * **happy path** — broker returns a bundle, query+use both fire.
  * **None bundle** — broker returns ``None`` (e.g. empty observations);
    the consumer's existing decision still completes and the salience
    field is ``None``.
  * **broker error** — broker raises; the consumer fails closed without
    crashing the existing decision flow.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from shared.bayesian_camera_salience_world_surface import REQUIRED_CONSUMERS

# ── Coverage anchor — keep tests aligned with the REQUIRED_CONSUMERS frozenset.


def test_required_consumers_contract() -> None:
    """REQUIRED_CONSUMERS must include every consumer this test covers."""
    assert (
        frozenset(
            {
                "director",
                "affordance",
                "content_opportunity",
                "voice",
                "wcs_health",
                "archive",
                "visual_variance",
            }
        )
        == REQUIRED_CONSUMERS
    )


# ── 1. content_opportunity → shared.opportunity_to_run_gate ─────────────


class TestContentOpportunityWiring:
    """``evaluate_opportunity`` queries the broker and attaches the WCS
    projection to ``GateResult.camera_salience``."""

    def _opportunity(self) -> object:
        from shared.opportunity_to_run_gate import ContentOpportunity

        return ContentOpportunity(
            opportunity_id="opp:test",
            format_id="react",
            posterior=0.85,
            public_claim_intended=False,
        )

    def _requirement(self) -> object:
        from shared.opportunity_to_run_gate import FormatWcsRequirement

        return FormatWcsRequirement(format_id="react", requires_claim_shape=False)

    def _snapshot(self) -> object:
        from shared.opportunity_to_run_gate import WcsSnapshot

        return WcsSnapshot(claim_shape_declared=True)

    @patch("shared.camera_salience_singleton.broker")
    def test_query_fires_with_consumer_label_and_use_attaches(self, mock_broker_fn) -> None:
        from shared.opportunity_to_run_gate import RunMode, evaluate_opportunity

        mock_singleton = MagicMock()
        mock_bundle = MagicMock()
        mock_bundle.to_wcs_projection_payload.return_value = {
            "bundle_id": "camera-salience-bundle:test.opp",
            "evidence_refs": ["evidence:test"],
            "blocked_or_stale_refs": [],
            "public_claim_ceiling": "no_claim",
            "claim_authorizations": {},
            "recommended_next_probe": "next:test",
        }
        mock_singleton.query.return_value = mock_bundle
        mock_broker_fn.return_value = mock_singleton

        result = evaluate_opportunity(self._opportunity(), self._requirement(), self._snapshot())

        # Query fired with the right consumer label.
        mock_singleton.query.assert_called_once()
        kwargs = mock_singleton.query.call_args.kwargs
        assert kwargs["consumer"] == "content_opportunity"
        assert kwargs["decision_context"].startswith("opportunity_gate:")
        assert "react" in kwargs["candidate_action"]

        # Use: the bundle's projection is attached to the GateResult payload.
        assert result.mode is RunMode.DRY_RUN  # not public-claim → DRY_RUN
        assert result.camera_salience is not None
        assert result.camera_salience["bundle_id"] == "camera-salience-bundle:test.opp"

    @patch("shared.camera_salience_singleton.broker")
    def test_none_bundle_leaves_decision_intact(self, mock_broker_fn) -> None:
        from shared.opportunity_to_run_gate import RunMode, evaluate_opportunity

        mock_singleton = MagicMock()
        mock_singleton.query.return_value = None
        mock_broker_fn.return_value = mock_singleton

        result = evaluate_opportunity(self._opportunity(), self._requirement(), self._snapshot())

        assert result.mode is RunMode.DRY_RUN
        assert result.camera_salience is None

    @patch("shared.camera_salience_singleton.broker")
    def test_broker_error_does_not_break_gate(self, mock_broker_fn) -> None:
        from shared.opportunity_to_run_gate import RunMode, evaluate_opportunity

        mock_broker_fn.side_effect = RuntimeError("broker down")

        result = evaluate_opportunity(self._opportunity(), self._requirement(), self._snapshot())

        assert result.mode is RunMode.DRY_RUN
        assert result.camera_salience is None


# ── 2. voice → agents.hapax_daimonion.vocal_chain ───────────────────────


class TestVoiceWiring:
    """``VocalChainCapability.activate_from_impingement`` queries the broker
    and attaches the projection to the returned payload dict."""

    def _impingement(self) -> object:
        from shared.impingement import Impingement, ImpingementType

        return Impingement(
            timestamp=0.0,
            source="stimmung.shift",
            type=ImpingementType.STATISTICAL_DEVIATION,
            strength=0.7,
            content={"dimensions": {"intensity": 0.5}},
        )

    def _capability(self) -> object:
        from agents.hapax_daimonion.vocal_chain import VocalChainCapability

        return VocalChainCapability(midi_output=MagicMock())

    @patch("shared.camera_salience_singleton.broker")
    def test_query_fires_with_consumer_label_and_use_attaches(self, mock_broker_fn) -> None:
        mock_singleton = MagicMock()
        mock_bundle = MagicMock()
        mock_bundle.to_wcs_projection_payload.return_value = {
            "bundle_id": "camera-salience-bundle:test.voice",
            "evidence_refs": [],
            "blocked_or_stale_refs": [],
            "public_claim_ceiling": "no_claim",
            "claim_authorizations": {},
            "recommended_next_probe": "next:voice",
        }
        mock_singleton.query.return_value = mock_bundle
        mock_broker_fn.return_value = mock_singleton

        cap = self._capability()
        result = cap.activate_from_impingement(self._impingement())

        # Query fired with the right consumer label.
        mock_singleton.query.assert_called_once()
        kwargs = mock_singleton.query.call_args.kwargs
        assert kwargs["consumer"] == "voice"
        assert kwargs["decision_context"].startswith("vocal_chain_activate:")
        assert kwargs["candidate_action"] == "modulate_vocal_dimensions"

        # Use: the bundle's projection is attached to the activation payload.
        assert result["camera_salience"] is not None
        assert result["camera_salience"]["bundle_id"] == "camera-salience-bundle:test.voice"
        assert result["activated"] is True

    @patch("shared.camera_salience_singleton.broker")
    def test_none_bundle_leaves_payload_intact(self, mock_broker_fn) -> None:
        mock_singleton = MagicMock()
        mock_singleton.query.return_value = None
        mock_broker_fn.return_value = mock_singleton

        cap = self._capability()
        result = cap.activate_from_impingement(self._impingement())

        assert result["camera_salience"] is None
        assert result["activated"] is True

    @patch("shared.camera_salience_singleton.broker")
    def test_broker_error_does_not_break_activation(self, mock_broker_fn) -> None:
        mock_broker_fn.side_effect = RuntimeError("broker down")

        cap = self._capability()
        result = cap.activate_from_impingement(self._impingement())

        assert result["camera_salience"] is None
        assert result["activated"] is True


# ── 3. wcs_health → shared.world_surface_temporal_perceptual_health ─────


class TestWcsHealthWiring:
    """``project_temporal_perceptual_health_envelope_with_camera_salience``
    queries the broker and surfaces the projection alongside the envelope."""

    @patch("shared.camera_salience_singleton.broker")
    def test_query_fires_and_projection_returned(self, mock_broker_fn) -> None:
        from shared.world_surface_temporal_perceptual_health import (
            project_temporal_perceptual_health_envelope_with_camera_salience,
        )

        mock_singleton = MagicMock()
        mock_bundle = MagicMock()
        mock_bundle.to_wcs_projection_payload.return_value = {
            "bundle_id": "camera-salience-bundle:test.wcs_health",
            "evidence_refs": [],
            "blocked_or_stale_refs": [],
            "public_claim_ceiling": "no_claim",
            "claim_authorizations": {},
            "recommended_next_probe": "next:wcs_health",
        }
        mock_singleton.query.return_value = mock_bundle
        mock_broker_fn.return_value = mock_singleton

        out = project_temporal_perceptual_health_envelope_with_camera_salience()

        # Query fired with the right consumer label.
        mock_singleton.query.assert_called_once()
        kwargs = mock_singleton.query.call_args.kwargs
        assert kwargs["consumer"] == "wcs_health"
        assert kwargs["decision_context"].startswith("wcs_health_envelope:")
        assert kwargs["candidate_action"] == "project_temporal_perceptual_health"

        # Use: the projection is the second key of the returned dict.
        assert "envelope" in out
        assert out["camera_salience"] is not None
        assert out["camera_salience"]["bundle_id"] == "camera-salience-bundle:test.wcs_health"

    @patch("shared.camera_salience_singleton.broker")
    def test_none_bundle_leaves_envelope_intact(self, mock_broker_fn) -> None:
        from shared.world_surface_temporal_perceptual_health import (
            project_temporal_perceptual_health_envelope_with_camera_salience,
        )

        mock_singleton = MagicMock()
        mock_singleton.query.return_value = None
        mock_broker_fn.return_value = mock_singleton

        out = project_temporal_perceptual_health_envelope_with_camera_salience()

        assert "envelope" in out
        assert out["camera_salience"] is None

    @patch("shared.camera_salience_singleton.broker")
    def test_broker_error_does_not_break_envelope(self, mock_broker_fn) -> None:
        from shared.world_surface_temporal_perceptual_health import (
            project_temporal_perceptual_health_envelope_with_camera_salience,
        )

        mock_broker_fn.side_effect = RuntimeError("broker down")

        out = project_temporal_perceptual_health_envelope_with_camera_salience()

        assert "envelope" in out
        assert out["camera_salience"] is None


# ── 4. archive → agents.studio_compositor.hls_archive ───────────────────


class TestArchiveWiring:
    """``_load_stimmung_snapshot`` queries the broker and embeds the
    projection into the per-segment sidecar stimmung dict."""

    @patch("shared.camera_salience_singleton.broker")
    def test_query_fires_and_projection_embedded(self, mock_broker_fn, tmp_path) -> None:
        from agents.studio_compositor.hls_archive import _load_stimmung_snapshot

        mock_singleton = MagicMock()
        mock_bundle = MagicMock()
        mock_bundle.to_wcs_projection_payload.return_value = {
            "bundle_id": "camera-salience-bundle:test.archive",
            "evidence_refs": [],
            "blocked_or_stale_refs": [],
            "public_claim_ceiling": "no_claim",
            "claim_authorizations": {},
            "recommended_next_probe": "next:archive",
        }
        mock_singleton.query.return_value = mock_bundle
        mock_broker_fn.return_value = mock_singleton

        # Pass a missing path so the loader exercises the absent-stimmung branch.
        snapshot = _load_stimmung_snapshot(stimmung_path=tmp_path / "missing.json")

        # Query fired with the right consumer label.
        mock_singleton.query.assert_called_once()
        kwargs = mock_singleton.query.call_args.kwargs
        assert kwargs["consumer"] == "archive"
        assert kwargs["decision_context"] == "hls_segment_rotation"
        assert kwargs["candidate_action"] == "archive_segment"

        # Use: the projection is embedded in the stimmung dict that the
        # rotator passes into ``build_sidecar`` and ultimately into the
        # per-segment sidecar's ``stimmung_snapshot`` field.
        assert snapshot["camera_salience"]["bundle_id"] == "camera-salience-bundle:test.archive"

    @patch("shared.camera_salience_singleton.broker")
    def test_none_bundle_omits_camera_salience_key(self, mock_broker_fn, tmp_path) -> None:
        # Contract: absent salience MUST NOT serialize as
        # ``"camera_salience": null`` in the archive sidecar — the key
        # is omitted entirely. Pinned by archive lifecycle integration
        # test asserting ``stimmung_snapshot == {}``.
        from agents.studio_compositor.hls_archive import _load_stimmung_snapshot

        mock_singleton = MagicMock()
        mock_singleton.query.return_value = None
        mock_broker_fn.return_value = mock_singleton

        snapshot = _load_stimmung_snapshot(stimmung_path=tmp_path / "missing.json")

        assert "camera_salience" not in snapshot
        assert snapshot == {}

    @patch("shared.camera_salience_singleton.broker")
    def test_broker_error_omits_camera_salience_key(self, mock_broker_fn, tmp_path) -> None:
        from agents.studio_compositor.hls_archive import _load_stimmung_snapshot

        mock_broker_fn.side_effect = RuntimeError("broker down")

        snapshot = _load_stimmung_snapshot(stimmung_path=tmp_path / "missing.json")

        assert "camera_salience" not in snapshot
        assert snapshot == {}


# ── 5. visual_variance → shared.gem_frame_variance ──────────────────────


class TestVisualVarianceWiring:
    """``project_variance_with_camera_salience`` queries the broker and
    surfaces the projection alongside the variance report."""

    def _texts(self) -> list[str]:
        return [
            "the operator is rendering the surface",
            "the surface attends to the operator",
            "evidence flows through the broker",
        ]

    @patch("shared.camera_salience_singleton.broker")
    def test_query_fires_and_projection_returned(self, mock_broker_fn) -> None:
        from shared.gem_frame_variance import (
            VarianceReport,
            project_variance_with_camera_salience,
        )

        mock_singleton = MagicMock()
        mock_bundle = MagicMock()
        mock_bundle.to_wcs_projection_payload.return_value = {
            "bundle_id": "camera-salience-bundle:test.variance",
            "evidence_refs": [],
            "blocked_or_stale_refs": [],
            "public_claim_ceiling": "no_claim",
            "claim_authorizations": {},
            "recommended_next_probe": "next:variance",
        }
        mock_singleton.query.return_value = mock_bundle
        mock_broker_fn.return_value = mock_singleton

        out = project_variance_with_camera_salience(self._texts())

        # Query fired with the right consumer label.
        mock_singleton.query.assert_called_once()
        kwargs = mock_singleton.query.call_args.kwargs
        assert kwargs["consumer"] == "visual_variance"
        assert kwargs["decision_context"] == "gem_frame_variance_projection"
        assert kwargs["candidate_action"] == "score_recent_emissions"

        # Use: projection sits beside the variance report in the result dict.
        assert isinstance(out["variance_report"], VarianceReport)
        assert out["camera_salience"] is not None
        assert out["camera_salience"]["bundle_id"] == "camera-salience-bundle:test.variance"

    @patch("shared.camera_salience_singleton.broker")
    def test_none_bundle_leaves_variance_intact(self, mock_broker_fn) -> None:
        from shared.gem_frame_variance import (
            VarianceReport,
            project_variance_with_camera_salience,
        )

        mock_singleton = MagicMock()
        mock_singleton.query.return_value = None
        mock_broker_fn.return_value = mock_singleton

        out = project_variance_with_camera_salience(self._texts())

        assert isinstance(out["variance_report"], VarianceReport)
        assert out["camera_salience"] is None

    @patch("shared.camera_salience_singleton.broker")
    def test_broker_error_does_not_break_variance(self, mock_broker_fn) -> None:
        from shared.gem_frame_variance import (
            VarianceReport,
            project_variance_with_camera_salience,
        )

        mock_broker_fn.side_effect = RuntimeError("broker down")

        out = project_variance_with_camera_salience(self._texts())

        assert isinstance(out["variance_report"], VarianceReport)
        assert out["camera_salience"] is None
