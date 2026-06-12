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

    def test_textfile_emits_collect_timestamp(self, probe_module, tmp_path) -> None:
        """W4 probe-inertness rule (HapaxEchoProbeStale) alerts when
        time() - collect_ts > 300 — detecting the watcher itself dying,
        the audit's universal failure class. The gauge must be written on
        EVERY tick, alert or not."""
        ok, err = probe_module.emit_textfile(
            tmp_path, correlation=0.001, alert_increment=0, collect_ts=1765500000.0
        )
        assert ok, err
        content = (tmp_path / "hapax_private_broadcast_echo.prom").read_text()
        assert "hapax_private_broadcast_echo_collect_ts 1765500000" in content
        assert "# TYPE hapax_private_broadcast_echo_collect_ts gauge" in content

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

        Threshold history: 0.05 (audit-D initial) sat INSIDE the ambient
        correlated-hum noise band (witnessed 0.033-0.066 on clean ticks),
        producing ~2,000 LEAK ntfys/day. W4 recalibrated to 0.15 — above
        the noise band, well below the witnessed real-leak band of the
        Jun 9-10 incident (0.21-1.00). Task audit-w4-observability-honesty.
        """
        assert probe_module.DEFAULT_PRIVATE == "hapax-private.monitor"
        assert probe_module.DEFAULT_BROADCAST == "hapax-obs-broadcast-remap"
        assert probe_module.DEFAULT_DURATION_S == 1.0
        assert probe_module.DEFAULT_THRESHOLD == 0.15
        assert probe_module.METRIC_PREFIX == "hapax_private_broadcast_echo"

    def test_alert_gating_defaults(self, probe_module) -> None:
        """W4 alert-design constants: 3 consecutive breach ticks before the
        first ntfy (kills single-tick noise spikes), then >=15 min between
        ntfys within one breach episode (kills alert fatigue; the textfile
        gauge keeps every tick regardless, so Prometheus sees everything)."""
        assert probe_module.DEFAULT_BREACH_TICKS == 3
        assert probe_module.DEFAULT_NTFY_COOLDOWN_S == 900


class TestAlertGating:
    """decide_alert(state, leaked, now) — hysteresis + per-episode cooldown.

    Pure function over an explicit state dict so the per-tick oneshot can
    persist it across invocations via load_state/save_state.
    """

    def test_first_breach_ticks_below_floor_do_not_alert(self, probe_module) -> None:
        state: dict = {}
        for tick in range(2):  # ticks 1 and 2 of 3
            should, state = probe_module.decide_alert(state, leaked=True, now=100.0 + 30 * tick)
            assert should is False, f"ntfy fired on breach tick {tick + 1}, before the floor of 3"
        assert state["streak"] == 2

    def test_third_consecutive_breach_tick_alerts(self, probe_module) -> None:
        state: dict = {}
        decisions = []
        for tick in range(3):
            should, state = probe_module.decide_alert(state, leaked=True, now=100.0 + 30 * tick)
            decisions.append(should)
        assert decisions == [False, False, True]
        assert state["last_ntfy"] == 100.0 + 60

    def test_episode_start_is_first_breach_tick(self, probe_module) -> None:
        state: dict = {}
        _, state = probe_module.decide_alert(state, leaked=True, now=500.0)
        _, state = probe_module.decide_alert(state, leaked=True, now=530.0)
        assert state["episode_start"] == 500.0

    def test_cooldown_suppresses_repeat_ntfy_within_episode(self, probe_module) -> None:
        state: dict = {}
        now = 0.0
        for _ in range(3):
            should, state = probe_module.decide_alert(state, leaked=True, now=now)
            now += 30.0
        # episode continues; within the 900s cooldown nothing more fires
        for _ in range(10):
            should, state = probe_module.decide_alert(state, leaked=True, now=now)
            assert should is False, f"ntfy re-fired at t={now}, inside the 900s cooldown"
            now += 30.0

    def test_ntfy_refires_after_cooldown_if_episode_persists(self, probe_module) -> None:
        state: dict = {}
        now = 0.0
        fired_at = []
        while now <= 1000.0:
            should, state = probe_module.decide_alert(state, leaked=True, now=now)
            if should:
                fired_at.append(now)
            now += 30.0
        assert fired_at[0] == 60.0  # third tick
        assert len(fired_at) == 2, f"expected exactly 2 ntfys in 1000s, got {fired_at}"
        assert fired_at[1] - fired_at[0] >= 900.0

    def test_clean_tick_resets_streak_and_episode(self, probe_module) -> None:
        state: dict = {}
        for tick in range(2):
            _, state = probe_module.decide_alert(state, leaked=True, now=100.0 + 30 * tick)
        _, state = probe_module.decide_alert(state, leaked=False, now=160.0)
        assert state["streak"] == 0
        assert state["episode_start"] is None
        # a fresh breach run must climb the full floor again
        should, state = probe_module.decide_alert(state, leaked=True, now=190.0)
        assert should is False

    def test_tolerates_garbage_state_dict(self, probe_module) -> None:
        """A corrupt persisted state must degrade to fresh-state behavior,
        never crash the probe (the probe is the last line of the privacy
        invariant — it must keep measuring)."""
        garbage = {"streak": "not-an-int", "episode_start": [], "last_ntfy": {}}
        should, state = probe_module.decide_alert(garbage, leaked=True, now=10.0)
        assert should is False
        assert state["streak"] == 1


def _wav_bytes(samples: list[int]) -> bytes:
    """Build a mono 16-bit 48k WAV buffer from int samples."""
    import array
    import io
    import wave as wave_mod

    buf = io.BytesIO()
    with wave_mod.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(48000)
        wf.writeframes(array.array("h", samples).tobytes())
    return buf.getvalue()


class TestMainWiring:
    """Drive main() with record_pair stubbed (review round 2, PR #4106):
    the two PR claims — gauge written unconditionally BEFORE gating, and
    exit codes bypassing decide_alert entirely — must be pinned through
    the real wiring, not inspection."""

    def _run_main(self, probe_module, monkeypatch, tmp_path, samples_pair, extra_args=()):
        wav_a = _wav_bytes(samples_pair[0])
        wav_b = _wav_bytes(samples_pair[1])
        monkeypatch.setattr(probe_module, "record_pair", lambda *a, **k: (wav_a, wav_b))
        argv = [
            "echo-probe",
            "--textfile-dir",
            str(tmp_path / "textfiles"),
            "--state-file",
            str(tmp_path / "state.json"),
            "--ntfy-topic",
            "",
            "--json",
            *extra_args,
        ]
        monkeypatch.setattr(sys, "argv", argv)
        return probe_module.main()

    def test_leak_tick_exits_2_even_while_ntfy_suppressed(
        self, probe_module, monkeypatch, tmp_path, capsys
    ) -> None:
        random.seed(3)
        leak = [random.randint(-1000, 1000) for _ in range(4096)]
        rc = self._run_main(probe_module, monkeypatch, tmp_path, (leak, leak[:]))
        assert rc == 2, "first leak tick must exit 2 — exit codes bypass the ntfy gating"
        prom = (tmp_path / "textfiles" / "hapax_private_broadcast_echo.prom").read_text()
        assert "hapax_private_broadcast_echo_correlation" in prom
        assert "hapax_private_broadcast_echo_collect_ts" in prom

    def test_clean_tick_exits_0_and_still_writes_gauge(
        self, probe_module, monkeypatch, tmp_path
    ) -> None:
        rng_a, rng_b = random.Random(11), random.Random(12)
        a = [rng_a.randint(-1000, 1000) for _ in range(4096)]
        b = [rng_b.randint(-1000, 1000) for _ in range(4096)]
        rc = self._run_main(probe_module, monkeypatch, tmp_path, (a, b))
        assert rc == 0
        prom = (tmp_path / "textfiles" / "hapax_private_broadcast_echo.prom").read_text()
        assert "hapax_private_broadcast_echo_collect_ts" in prom, (
            "clean tick skipped the textfile — the gauge must be written "
            "EVERY tick or Prometheus staleness detection lies"
        )

    def test_ntfy_fires_only_on_third_consecutive_leak_tick(
        self, probe_module, monkeypatch, tmp_path
    ) -> None:
        random.seed(5)
        leak = [random.randint(-1000, 1000) for _ in range(4096)]
        calls: list[float] = []
        monkeypatch.setattr(
            probe_module,
            "post_ntfy_alert",
            lambda base, topic, corr, thr: (calls.append(corr) or (True, None)),
        )
        rcs = []
        for _ in range(3):
            rcs.append(
                self._run_main(
                    probe_module,
                    monkeypatch,
                    tmp_path,
                    (leak, leak[:]),
                    extra_args=("--ntfy-topic", "test-topic"),
                )
            )
        assert rcs == [2, 2, 2], "every leak tick exits 2 regardless of ntfy gating"
        assert len(calls) == 1, (
            f"ntfy posted {len(calls)}x over 3 breach ticks; the gating must "
            f"hold it to exactly one (the 3rd tick)"
        )


class TestStatePersistence:
    def test_missing_state_file_loads_fresh(self, probe_module, tmp_path) -> None:
        state = probe_module.load_state(tmp_path / "absent.json")
        assert state["streak"] == 0 and state["episode_start"] is None

    def test_corrupt_state_file_loads_fresh(self, probe_module, tmp_path) -> None:
        p = tmp_path / "state.json"
        p.write_text("{not json")
        state = probe_module.load_state(p)
        assert state["streak"] == 0

    def test_roundtrip(self, probe_module, tmp_path) -> None:
        p = tmp_path / "state.json"
        probe_module.save_state(p, {"streak": 2, "episode_start": 5.0, "last_ntfy": None})
        assert probe_module.load_state(p)["streak"] == 2
