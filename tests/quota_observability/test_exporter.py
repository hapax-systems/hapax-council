"""Tests for ``agents.quota_observability`` (ytb-001).

Exporter-level tests pin metric translation, alert-threshold logic,
and graceful degradation on Cloud Monitoring read failure. Client
tests pin the request-builder filter shape (mocked GCP client; no
network).
"""

from __future__ import annotations

import math
from unittest import mock

import pytest
from prometheus_client import CollectorRegistry

from agents.quota_observability.client import QuotaClient, QuotaSample, project_id_from_env
from agents.quota_observability.exporter import QuotaExporter


def _make_exporter(
    *,
    sample: QuotaSample | None = None,
    raises: Exception | None = None,
    alert_threshold: float = 0.8,
) -> tuple[QuotaExporter, mock.Mock]:
    client = mock.Mock(spec=QuotaClient)
    client.project_id = "test-project"
    if raises is not None:
        client.read_sample.side_effect = raises
    elif sample is not None:
        client.read_sample.return_value = sample
    exporter = QuotaExporter(
        client=client,
        registry=CollectorRegistry(),
        alert_threshold=alert_threshold,
    )
    return exporter, client


# ── Exporter — metric translation ────────────────────────────────────


class TestPublishedMetrics:
    def test_translates_used_and_remaining(self):
        sample = QuotaSample(
            used_units=2_500.0,
            daily_cap_units=10_000.0,
            rate_per_min=50.0,
            sampled_at=1.0,
        )
        exporter, _ = _make_exporter(sample=sample)
        exporter.tick_once(now=1.0)

        assert exporter.units_used._value.get() == pytest.approx(2_500.0)
        assert exporter.units_remaining._value.get() == pytest.approx(7_500.0)
        assert exporter.rate_per_min._value.get() == pytest.approx(50.0)

    def test_exhaustion_estimate_finite_at_positive_rate(self):
        sample = QuotaSample(
            used_units=8_000.0,
            daily_cap_units=10_000.0,
            rate_per_min=100.0,
            sampled_at=1.0,
        )
        exporter, _ = _make_exporter(sample=sample)
        exporter.tick_once(now=1.0)
        # 2000 units remaining / 100 per min = 20 min = 1200s.
        assert exporter.exhaustion_estimate_s._value.get() == pytest.approx(1_200.0)

    def test_exhaustion_estimate_inf_at_zero_rate(self):
        sample = QuotaSample(
            used_units=0.0,
            daily_cap_units=10_000.0,
            rate_per_min=0.0,
            sampled_at=1.0,
        )
        exporter, _ = _make_exporter(sample=sample)
        exporter.tick_once(now=1.0)
        assert math.isinf(exporter.exhaustion_estimate_s._value.get())

    def test_exhaustion_estimate_zero_when_already_at_cap(self):
        sample = QuotaSample(
            used_units=10_000.0,
            daily_cap_units=10_000.0,
            rate_per_min=50.0,
            sampled_at=1.0,
        )
        exporter, _ = _make_exporter(sample=sample)
        exporter.tick_once(now=1.0)
        assert exporter.exhaustion_estimate_s._value.get() == pytest.approx(0.0)

    def test_negative_used_clamped_to_zero(self):
        sample = QuotaSample(
            used_units=-5.0,  # source returned a negative outlier
            daily_cap_units=10_000.0,
            rate_per_min=0.0,
            sampled_at=1.0,
        )
        exporter, _ = _make_exporter(sample=sample)
        exporter.tick_once(now=1.0)
        assert exporter.units_used._value.get() == pytest.approx(0.0)


# ── Alert-threshold logic ────────────────────────────────────────────


class TestAlertActive:
    def test_below_threshold_alert_off(self):
        sample = QuotaSample(
            used_units=7_000.0,  # 70% — below 80% default
            daily_cap_units=10_000.0,
            rate_per_min=10.0,
            sampled_at=1.0,
        )
        exporter, _ = _make_exporter(sample=sample)
        exporter.tick_once(now=1.0)
        assert exporter.alert_active._value.get() == 0.0

    def test_at_threshold_alert_on(self):
        sample = QuotaSample(
            used_units=8_000.0,  # exactly 80%
            daily_cap_units=10_000.0,
            rate_per_min=10.0,
            sampled_at=1.0,
        )
        exporter, _ = _make_exporter(sample=sample)
        exporter.tick_once(now=1.0)
        assert exporter.alert_active._value.get() == 1.0

    def test_above_threshold_alert_on(self):
        sample = QuotaSample(
            used_units=9_500.0,  # 95%
            daily_cap_units=10_000.0,
            rate_per_min=10.0,
            sampled_at=1.0,
        )
        exporter, _ = _make_exporter(sample=sample)
        exporter.tick_once(now=1.0)
        assert exporter.alert_active._value.get() == 1.0

    def test_zero_cap_disables_alert(self):
        # Defensive: avoid div-by-zero false alarm when cap unknown
        # (e.g., GCP returned the metric series empty during cold-start).
        sample = QuotaSample(
            used_units=100.0,
            daily_cap_units=0.0,
            rate_per_min=10.0,
            sampled_at=1.0,
        )
        exporter, _ = _make_exporter(sample=sample)
        exporter.tick_once(now=1.0)
        assert exporter.alert_active._value.get() == 0.0

    def test_custom_threshold(self):
        sample = QuotaSample(
            used_units=5_500.0,  # 55% — above a 50% custom threshold
            daily_cap_units=10_000.0,
            rate_per_min=10.0,
            sampled_at=1.0,
        )
        exporter, _ = _make_exporter(sample=sample, alert_threshold=0.5)
        exporter.tick_once(now=1.0)
        assert exporter.alert_active._value.get() == 1.0

    def test_invalid_threshold_rejected(self):
        client = mock.Mock(spec=QuotaClient)
        client.project_id = "test-project"
        for bad in (0.0, -0.1, 1.1, 2.0):
            with pytest.raises(ValueError):
                QuotaExporter(
                    client=client,
                    registry=CollectorRegistry(),
                    alert_threshold=bad,
                )


# ── Graceful degradation ─────────────────────────────────────────────


class TestReadFailure:
    def test_failure_keeps_previous_gauge_values(self):
        good = QuotaSample(
            used_units=2_500.0,
            daily_cap_units=10_000.0,
            rate_per_min=50.0,
            sampled_at=1.0,
        )
        client = mock.Mock(spec=QuotaClient)
        client.project_id = "test-project"
        client.read_sample.return_value = good
        exporter = QuotaExporter(client=client, registry=CollectorRegistry())

        exporter.tick_once(now=1.0)
        snapshot = exporter.units_used._value.get()

        # Next tick raises; gauge should not change.
        client.read_sample.side_effect = RuntimeError("monitoring API down")
        exporter.tick_once(now=2.0)
        assert exporter.units_used._value.get() == snapshot

    def test_failure_throttles_warning_state(self, caplog):
        exporter, _ = _make_exporter(raises=RuntimeError("transport error"))
        with caplog.at_level("WARNING"):
            exporter.tick_once(now=1.0)
            exporter.tick_once(now=2.0)
            exporter.tick_once(now=3.0)
        # Only the first failure should log a warning; subsequent are
        # squelched until recovery.
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1, (
            f"expected 1 throttled warning across 3 failed ticks, saw {len(warnings)}"
        )

    def test_recovery_resets_warning_state(self, caplog):
        good = QuotaSample(
            used_units=100.0,
            daily_cap_units=10_000.0,
            rate_per_min=1.0,
            sampled_at=1.0,
        )
        client = mock.Mock(spec=QuotaClient)
        client.project_id = "test-project"
        exporter = QuotaExporter(client=client, registry=CollectorRegistry())

        with caplog.at_level("WARNING"):
            client.read_sample.side_effect = RuntimeError("first outage")
            exporter.tick_once(now=1.0)  # warns
            client.read_sample.side_effect = None
            client.read_sample.return_value = good
            exporter.tick_once(now=2.0)  # recovers; resets warned flag
            client.read_sample.side_effect = RuntimeError("second outage")
            exporter.tick_once(now=3.0)  # warns again

        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 2


# ── Client wrapper — request shape + env loading ─────────────────────


class TestQuotaClient:
    def test_rejects_empty_project_id(self):
        with pytest.raises(ValueError):
            QuotaClient(project_id="")

    def test_filter_includes_youtube_quota(self):
        client = QuotaClient(project_id="proj-1")
        f = client._series_filter("serviceruntime.googleapis.com/quota/allocation/usage")
        assert "youtube.googleapis.com/quota/requests" in f
        assert "serviceruntime.googleapis.com/quota/allocation/usage" in f

    def test_returns_default_on_read_exception(self):
        gcp = mock.Mock()
        gcp.list_time_series.side_effect = RuntimeError("transient")
        client = QuotaClient(project_id="proj-1", client=gcp)
        # Patch builder to avoid touching real google.cloud import.
        with mock.patch.object(client, "_build_list_request", return_value=mock.Mock()):
            value = client._latest_point(
                metric_type="serviceruntime.googleapis.com/quota/limit",
                since_s=0.0,
                now=1.0,
                default=42.0,
            )
        assert value == 42.0

    def test_returns_default_when_series_empty(self):
        gcp = mock.Mock()
        gcp.list_time_series.return_value = iter([])  # empty pager
        client = QuotaClient(project_id="proj-1", client=gcp)
        with mock.patch.object(client, "_build_list_request", return_value=mock.Mock()):
            value = client._latest_point(
                metric_type="serviceruntime.googleapis.com/quota/allocation/usage",
                since_s=0.0,
                now=1.0,
                default=7.0,
            )
        assert value == 7.0

    def test_latest_point_returns_first_observed(self):
        point = mock.Mock()
        point.value.double_value = 123.0
        point.value.int64_value = 0
        series = mock.Mock()
        series.points = [point]
        gcp = mock.Mock()
        gcp.list_time_series.return_value = iter([series])
        client = QuotaClient(project_id="proj-1", client=gcp)
        with mock.patch.object(client, "_build_list_request", return_value=mock.Mock()):
            value = client._latest_point(
                metric_type="serviceruntime.googleapis.com/quota/allocation/usage",
                since_s=0.0,
                now=1.0,
                default=0.0,
            )
        assert value == pytest.approx(123.0)

    def test_read_sample_aggregates_three_metrics(self):
        gcp = mock.Mock()

        def _series(value: float):
            point = mock.Mock()
            point.value.double_value = value
            point.value.int64_value = 0
            series = mock.Mock()
            series.points = [point]
            return iter([series])

        # Order matches `read_sample()` calls: used, rate (per-second),
        # cap.
        gcp.list_time_series.side_effect = [
            _series(2_500.0),  # used
            _series(0.5),  # rate per-second → ×60 → 30 per-min
            _series(20_000.0),  # cap (operator-extended)
        ]
        client = QuotaClient(project_id="proj-1", client=gcp)
        with mock.patch.object(client, "_build_list_request", return_value=mock.Mock()):
            sample = client.read_sample(now=1.0)

        assert sample.used_units == pytest.approx(2_500.0)
        assert sample.daily_cap_units == pytest.approx(20_000.0)
        assert sample.rate_per_min == pytest.approx(30.0)
        assert sample.sampled_at == 1.0


class TestProjectIdFromEnv:
    def test_reads_env(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "ops-prod-1")
        assert project_id_from_env() == "ops-prod-1"

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "  ops-prod-1  ")
        assert project_id_from_env() == "ops-prod-1"

    def test_raises_when_missing(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        with pytest.raises(RuntimeError, match="GOOGLE_CLOUD_PROJECT"):
            project_id_from_env()
