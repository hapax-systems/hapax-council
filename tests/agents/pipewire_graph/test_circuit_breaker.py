from __future__ import annotations

from dataclasses import replace

from agents.pipewire_graph.circuit_breaker import (
    EgressCircuitBreaker,
    EgressFailureMode,
    EgressHealth,
)


def _health(
    *,
    rms: float = -20.0,
    peak: float = -3.0,
    crest: float = 3.0,
    zcr: float = 0.1,
    ts: str = "2026-05-05T00:00:00.000Z",
) -> EgressHealth:
    return EgressHealth(
        rms_dbfs=rms,
        peak_dbfs=peak,
        crest_factor=crest,
        zcr=zcr,
        timestamp_utc=ts,
        sample_count=24000,
    )


def test_amplified_clipping_sustained_enters_shadow_alert() -> None:
    alerts = []
    breaker = EgressCircuitBreaker(on_shadow_alert=alerts.append)

    for t in (0.0, 0.5, 1.0, 1.5):
        assert breaker.observe(_health(crest=6.2, rms=-18.0), now_s=t) is None

    alert = breaker.observe(_health(crest=6.2, rms=-18.0), now_s=2.0)

    assert alert is not None
    assert alert.mode == EgressFailureMode.CLIPPING_NOISE
    assert breaker.state == EgressFailureMode.CLIPPING_NOISE
    assert alerts == [alert]
    assert alert.health.amplified_clipping_candidate is True


def test_format_artifact_candidate_is_logged_and_can_fire_clipping_shadow() -> None:
    breaker = EgressCircuitBreaker()
    sample = _health(crest=3.4, rms=-18.0, zcr=0.32)

    assert sample.format_artifact_candidate is True
    assert sample.amplified_clipping_candidate is False

    for t in (0.0, 0.5, 1.0, 1.5):
        breaker.observe(sample, now_s=t)
    alert = breaker.observe(sample, now_s=2.0)

    assert alert is not None
    assert alert.mode == EgressFailureMode.CLIPPING_NOISE


def test_silence_requires_livestream_and_sustain_window() -> None:
    breaker = EgressCircuitBreaker(livestream_active=lambda: True)

    for t in (0.0, 1.0, 2.0, 3.0, 4.0):
        assert breaker.observe(_health(rms=-80.0, crest=0.0), now_s=t) is None

    alert = breaker.observe(_health(rms=-80.0, crest=0.0), now_s=5.0)

    assert alert is not None
    assert alert.mode == EgressFailureMode.SILENCE
    assert breaker.state == EgressFailureMode.SILENCE


def test_silence_does_not_fire_when_livestream_inactive() -> None:
    breaker = EgressCircuitBreaker(livestream_active=lambda: False)

    for t in (0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0):
        assert breaker.observe(_health(rms=-80.0, crest=0.0), now_s=t) is None

    assert breaker.state == EgressFailureMode.NOMINAL


def test_track_change_transient_does_not_false_positive() -> None:
    breaker = EgressCircuitBreaker()

    breaker.observe(_health(crest=7.0, rms=-18.0), now_s=0.0)
    breaker.observe(_health(crest=7.0, rms=-18.0), now_s=0.5)
    breaker.observe(_health(crest=7.0, rms=-18.0), now_s=1.0)
    breaker.observe(_health(crest=3.2, rms=-22.0), now_s=1.5)
    breaker.observe(_health(crest=3.1, rms=-21.0), now_s=2.0)

    assert breaker.state == EgressFailureMode.NOMINAL


def test_probe_errors_do_not_drive_silence_alert() -> None:
    breaker = EgressCircuitBreaker(livestream_active=lambda: True)
    errored = replace(_health(rms=-120.0, crest=0.0), error="parecord target missing")

    for t in (0.0, 1.0, 2.0, 3.0, 4.0, 5.0):
        assert breaker.observe(errored, now_s=t) is None

    assert breaker.state == EgressFailureMode.NOMINAL
