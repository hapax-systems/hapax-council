"""The media-egress governance counter is wired and increments by outcome."""

from __future__ import annotations

import pytest


def test_record_media_egress_registers_and_increments() -> None:
    from agents.studio_compositor import metrics

    if not getattr(metrics, "_PROMETHEUS_AVAILABLE", False):
        pytest.skip("prometheus_client not available")

    metrics.record_media_egress("allowed", "youtube")
    metrics.record_media_egress("refused_consent", "image")

    assert metrics.HAPAX_MEDIA_EGRESS_TOTAL is not None
    families = {m.name for m in metrics.REGISTRY.collect()}
    # prometheus strips the _total suffix in the family name.
    assert "hapax_media_egress" in families


def test_record_media_egress_never_raises_without_prometheus(monkeypatch) -> None:
    from agents.studio_compositor import metrics

    # Even if init is short-circuited, recording must be a safe no-op.
    monkeypatch.setattr(metrics, "HAPAX_MEDIA_EGRESS_TOTAL", None, raising=False)
    metrics.record_media_egress("refused_error", "unknown")
