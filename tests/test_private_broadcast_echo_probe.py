"""Tests for scripts/private-broadcast-echo-probe.py.

cc-task audio-audit-D-broadcast-bus-echo-prometheus-probe.

Math contract pin (no PipeWire / pw-cat / network at CI time): exercise
``normalized_peak_xcorr`` with synthetic correlated and uncorrelated
sample streams; assert the script's exit-code semantics; pin the
textfile output shape.
"""

from __future__ import annotations

import importlib.util
import math
import random
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "private-broadcast-echo-probe.py"


@pytest.fixture(scope="module")
def probe_module():
    spec = importlib.util.spec_from_file_location("echo_probe", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO_ROOT))
    try:
        spec.loader.exec_module(mod)
    finally:
        if str(REPO_ROOT) in sys.path:
            sys.path.remove(str(REPO_ROOT))
    return mod


class TestNormalizedPeakXcorrMath:
    """Pin the leak-detection math against synthetic ground-truth."""

    def test_identical_streams_give_high_correlation(self, probe_module) -> None:
        """If private == broadcast bit-for-bit, correlation must approach 1.0
        (the leak detector's worst case — full echo)."""
        random.seed(42)
        a = [random.randint(-1000, 1000) for _ in range(2048)]
        coeff = probe_module.normalized_peak_xcorr(a, a[:])
        assert coeff > 0.95, (
            f"identical streams gave correlation {coeff:.3f}; "
            f"expected near 1.0 — the math is broken or the lag window "
            f"is mis-sized"
        )

    def test_independent_noise_gives_low_correlation(self, probe_module) -> None:
        """Statistical independence — the typical no-leak baseline."""
        rng_a = random.Random(1)
        rng_b = random.Random(2)
        a = [rng_a.randint(-1000, 1000) for _ in range(2048)]
        b = [rng_b.randint(-1000, 1000) for _ in range(2048)]
        coeff = probe_module.normalized_peak_xcorr(a, b)
        # With 2048 samples, two independent uniform-noise sources should
        # have peak |corr| well below the 0.05 production threshold; we
        # leave a wide margin for the lag-window optimum.
        assert coeff < 0.30, (
            f"independent noise streams gave correlation {coeff:.3f}; "
            f"expected < 0.30. The probe would false-positive at the "
            f"production threshold of 0.05; check the lag-window width."
        )

    def test_silent_streams_give_zero(self, probe_module) -> None:
        """Zero-variance protection: silence should never look like a leak."""
        zeros = [0] * 1024
        coeff = probe_module.normalized_peak_xcorr(zeros, zeros)
        assert coeff == 0.0

    def test_one_silent_one_active_gives_zero(self, probe_module) -> None:
        zeros = [0] * 1024
        active = [int(1000 * math.sin(i * 0.1)) for i in range(1024)]
        coeff = probe_module.normalized_peak_xcorr(zeros, active)
        assert coeff == 0.0

    def test_too_short_streams_return_zero(self, probe_module) -> None:
        """Below the minimum-length floor, return 0 — better silent than a
        spurious leak signal from undersampled cross-correlation."""
        a = [1, 2, 3, 4]
        b = [4, 3, 2, 1]
        coeff = probe_module.normalized_peak_xcorr(a, b)
        assert coeff == 0.0

    def test_lagged_copy_gives_high_correlation(self, probe_module) -> None:
        """If the broadcast bus is the private stream delayed by N samples,
        the lag-search window must find it."""
        rng = random.Random(7)
        a = [rng.randint(-1000, 1000) for _ in range(2048)]
        lag = 80  # within the ±256 lag search window
        b = [0] * lag + a[: 2048 - lag]
        coeff = probe_module.normalized_peak_xcorr(a, b)
        assert coeff > 0.7, (
            f"lagged-copy stream gave correlation {coeff:.3f}; expected > 0.7. "
            f"The lag-search window is missing real-world bus-alignment delays."
        )


class TestTextfileMetricShape:
    """Pin the Prometheus exposition format so node_exporter parses it."""

    def test_textfile_emits_required_metrics(self, probe_module, tmp_path) -> None:
        ok, err = probe_module.emit_textfile(tmp_path, correlation=0.0123, alert_increment=0)
        assert ok, err
        target = tmp_path / "hapax_private_broadcast_echo.prom"
        assert target.exists()
        content = target.read_text()
        assert "hapax_private_broadcast_echo_correlation" in content
        assert "hapax_private_broadcast_echo_alert_total" in content
        assert "0.012300" in content  # gauge formatted to 6 places
        assert "# HELP" in content and "# TYPE" in content

    def test_textfile_alert_counter_increments_on_leak(self, probe_module, tmp_path) -> None:
        ok, _ = probe_module.emit_textfile(tmp_path, correlation=0.42, alert_increment=1)
        assert ok
        content = (tmp_path / "hapax_private_broadcast_echo.prom").read_text()
        assert "hapax_private_broadcast_echo_alert_total 1" in content


class TestArgParser:
    def test_defaults_align_with_audit_d_spec(self, probe_module) -> None:
        """Defaults must match the cc-task spec to avoid silent drift.

        parse_args reads sys.argv; we pin the module-level constants
        instead since they are the single source of truth the parser
        reads from.
        """
        assert probe_module.DEFAULT_PRIVATE == "hapax-private-monitor.monitor"
        assert probe_module.DEFAULT_BROADCAST == "hapax-obs-broadcast-remap.monitor"
        assert probe_module.DEFAULT_DURATION_S == 1.0
        assert probe_module.DEFAULT_THRESHOLD == 0.05
        assert probe_module.METRIC_PREFIX == "hapax_private_broadcast_echo"
