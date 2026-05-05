"""H5 Phase 2 A/B telemetry recorder.

Samples the live software OBS path and the secondary L-12 AUX10/AUX11 tap,
writes JSONL evidence, and publishes Prometheus textfile gauges. It is
observe-only: no PipeWire module loading, no service restarts, and no graph
mutation happen here.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from agents.audio_health.m1_dimensions import compute_lufs_s
from shared.notify import send_notification

log = logging.getLogger(__name__)

DEFAULT_STATE_ROOT = Path.home() / "hapax-state" / "audio-ab"
DEFAULT_SOFTWARE_DEVICE = "hapax-broadcast-normalized.monitor"
DEFAULT_L12_DEVICE = "hapax-obs-broadcast-mainmix-tap.monitor"
DEFAULT_SAMPLE_RATE = 48000
DEFAULT_CHANNELS = 2
DEFAULT_CAPTURE_DURATION_S = 0.2
DEFAULT_INTERVAL_S = 0.2
DEFAULT_DELTA_ALERT_DB = 1.0
DEFAULT_DELTA_SUSTAIN_S = 30.0
DEFAULT_ALERT_COOLDOWN_S = 300.0


class CaptureError(RuntimeError):
    """Raised when parecord cannot produce a bounded PCM window."""


@dataclass(frozen=True)
class RecorderConfig:
    """Runtime configuration for the A/B recorder."""

    state_root: Path = DEFAULT_STATE_ROOT
    software_device: str = DEFAULT_SOFTWARE_DEVICE
    l12_device: str = DEFAULT_L12_DEVICE
    sample_rate: int = DEFAULT_SAMPLE_RATE
    channels: int = DEFAULT_CHANNELS
    capture_duration_s: float = DEFAULT_CAPTURE_DURATION_S
    interval_s: float = DEFAULT_INTERVAL_S
    parecord_path: str = "parecord"
    timeout_extra_s: float = 4.0
    delta_alert_db: float = DEFAULT_DELTA_ALERT_DB
    delta_sustain_s: float = DEFAULT_DELTA_SUSTAIN_S
    alert_cooldown_s: float = DEFAULT_ALERT_COOLDOWN_S
    enable_ntfy: bool = True
    run_once: bool = False
    textfile_collector_dir: Path | None = None

    @property
    def today_jsonl_path(self) -> Path:
        date = datetime.now(UTC).strftime("%Y-%m-%d")
        return self.state_root / f"{date}.jsonl"

    @classmethod
    def from_env(cls) -> RecorderConfig:
        def _path(key: str) -> Path | None:
            raw = os.environ.get(key)
            return Path(raw).expanduser() if raw else None

        def _float(key: str, default: float) -> float:
            raw = os.environ.get(key)
            if raw is None or raw == "":
                return default
            try:
                return float(raw)
            except ValueError:
                log.warning("%s=%r is not a float; using %s", key, raw, default)
                return default

        def _int(key: str, default: int) -> int:
            raw = os.environ.get(key)
            if raw is None or raw == "":
                return default
            try:
                return int(raw)
            except ValueError:
                log.warning("%s=%r is not an int; using %s", key, raw, default)
                return default

        def _bool(key: str, default: bool) -> bool:
            raw = os.environ.get(key)
            if raw is None:
                return default
            return raw.strip().lower() not in {"", "0", "false", "no", "off"}

        return cls(
            state_root=_path("HAPAX_AUDIO_AB_STATE_ROOT") or DEFAULT_STATE_ROOT,
            software_device=os.environ.get(
                "HAPAX_AUDIO_AB_SOFTWARE_DEVICE",
                DEFAULT_SOFTWARE_DEVICE,
            ),
            l12_device=os.environ.get("HAPAX_AUDIO_AB_L12_DEVICE", DEFAULT_L12_DEVICE),
            sample_rate=_int("HAPAX_AUDIO_AB_SAMPLE_RATE", DEFAULT_SAMPLE_RATE),
            channels=_int("HAPAX_AUDIO_AB_CHANNELS", DEFAULT_CHANNELS),
            capture_duration_s=_float(
                "HAPAX_AUDIO_AB_CAPTURE_DURATION_S",
                DEFAULT_CAPTURE_DURATION_S,
            ),
            interval_s=_float("HAPAX_AUDIO_AB_INTERVAL_S", DEFAULT_INTERVAL_S),
            parecord_path=os.environ.get("HAPAX_AUDIO_AB_PARECORD", "parecord"),
            delta_alert_db=_float("HAPAX_AUDIO_AB_DELTA_ALERT_DB", DEFAULT_DELTA_ALERT_DB),
            delta_sustain_s=_float(
                "HAPAX_AUDIO_AB_DELTA_SUSTAIN_S",
                DEFAULT_DELTA_SUSTAIN_S,
            ),
            alert_cooldown_s=_float(
                "HAPAX_AUDIO_AB_ALERT_COOLDOWN_S",
                DEFAULT_ALERT_COOLDOWN_S,
            ),
            enable_ntfy=_bool("HAPAX_AUDIO_AB_ENABLE_NTFY", True),
            run_once=_bool("HAPAX_AUDIO_AB_RUN_ONCE", False),
            textfile_collector_dir=_path("HAPAX_AUDIO_AB_TEXTFILE_COLLECTOR_DIR"),
        )


@dataclass(frozen=True)
class AudioMetrics:
    """One PCM window's measurements."""

    lufs_i: float
    rms_dbfs: float
    peak_dbfs: float
    crest_factor: float
    zero_crossing_rate: float
    sample_count: int

    def to_payload(self) -> dict[str, float | int]:
        return {
            "lufs_i": self.lufs_i,
            "rms_dbfs": self.rms_dbfs,
            "peak_dbfs": self.peak_dbfs,
            "crest_factor": self.crest_factor,
            "zero_crossing_rate": self.zero_crossing_rate,
            "sample_count": self.sample_count,
        }


@dataclass(frozen=True)
class CaptureResult:
    """Capture result for one side of the A/B pair."""

    path: str
    device: str
    captured_at: float
    duration_s: float
    metrics: AudioMetrics | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.metrics is not None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "path": self.path,
            "device": self.device,
            "captured_at": _iso_from_epoch(self.captured_at),
            "duration_s": self.duration_s,
            "ok": self.ok,
            "error": self.error,
        }
        if self.metrics is not None:
            payload.update(self.metrics.to_payload())
        return payload


class DriftDetector:
    """Sustained LUFS-delta detector with cooldown."""

    def __init__(
        self,
        *,
        threshold_db: float = DEFAULT_DELTA_ALERT_DB,
        sustain_s: float = DEFAULT_DELTA_SUSTAIN_S,
        cooldown_s: float = DEFAULT_ALERT_COOLDOWN_S,
    ) -> None:
        self.threshold_db = threshold_db
        self.sustain_s = sustain_s
        self.cooldown_s = cooldown_s
        self._breach_start_at: float | None = None
        self._last_alert_at = -math.inf

    def observe(self, delta_lufs_i: float | None, *, now: float | None = None) -> bool:
        ts = time.time() if now is None else now
        if delta_lufs_i is None or abs(delta_lufs_i) <= self.threshold_db:
            self._breach_start_at = None
            return False

        if self._breach_start_at is None:
            self._breach_start_at = ts
        if ts - self._breach_start_at < self.sustain_s:
            return False
        if ts - self._last_alert_at < self.cooldown_s:
            return False
        self._last_alert_at = ts
        return True


def _iso_from_epoch(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).isoformat().replace("+00:00", "Z")


def _dbfs(value: float) -> float:
    if value <= 0.0:
        return -120.0
    return max(-120.0, 20.0 * math.log10(value))


def _decode_s16le(raw: bytes, *, channels: int) -> np.ndarray:
    samples = np.frombuffer(raw, dtype=np.int16)
    if samples.size == 0:
        return np.zeros((0, channels), dtype=np.float64)
    truncated = (samples.size // channels) * channels
    if truncated == 0:
        return np.zeros((0, channels), dtype=np.float64)
    reshaped = samples[:truncated].reshape(-1, channels)
    return reshaped.astype(np.float64) / 32768.0


def _zero_crossing_rate(mono: np.ndarray) -> float:
    if mono.size <= 1:
        return 0.0
    signs = np.signbit(mono)
    crossings = int(np.count_nonzero(np.diff(signs)))
    return crossings / (mono.size - 1)


def _integrated_lufs(samples: np.ndarray, *, sample_rate: int) -> float:
    if samples.size == 0:
        return -120.0
    if samples.ndim == 1:
        channels = samples.reshape(-1, 1)
    else:
        channels = samples
    powers: list[float] = []
    for idx in range(channels.shape[1]):
        channel_lufs = compute_lufs_s(channels[:, idx], sample_rate=sample_rate)
        powers.append(10.0 ** ((channel_lufs + 0.691) / 10.0))
    summed = float(sum(powers))
    if summed <= 0.0:
        return -120.0
    return max(-120.0, -0.691 + 10.0 * math.log10(summed))


def measure_samples(samples: np.ndarray, *, sample_rate: int = DEFAULT_SAMPLE_RATE) -> AudioMetrics:
    """Measure a mono or interleaved stereo float array normalized to [-1, 1]."""

    if samples.ndim == 1:
        matrix = samples.reshape(-1, 1)
    elif samples.ndim == 2:
        matrix = samples
    else:
        raise ValueError(f"measure_samples expects 1D or 2D samples, got ndim={samples.ndim}")

    if matrix.size == 0:
        return AudioMetrics(
            lufs_i=-120.0,
            rms_dbfs=-120.0,
            peak_dbfs=-120.0,
            crest_factor=0.0,
            zero_crossing_rate=0.0,
            sample_count=0,
        )

    abs_samples = np.abs(matrix)
    peak = float(abs_samples.max())
    rms = float(np.sqrt(np.mean(np.square(matrix))))
    crest = (peak / rms) if rms > 0.0 else 0.0
    mono = matrix.mean(axis=1)
    return AudioMetrics(
        lufs_i=_integrated_lufs(matrix, sample_rate=sample_rate),
        rms_dbfs=_dbfs(rms),
        peak_dbfs=_dbfs(peak),
        crest_factor=crest,
        zero_crossing_rate=_zero_crossing_rate(mono),
        sample_count=int(matrix.shape[0]),
    )


def _capture_parecord(device: str, config: RecorderConfig) -> bytes:
    if shutil.which(config.parecord_path) is None:
        raise CaptureError(f"parecord binary not found at {config.parecord_path!r}")

    cmd = [
        config.parecord_path,
        f"--device={device}",
        "--raw",
        f"--rate={config.sample_rate}",
        f"--channels={config.channels}",
        "--format=s16le",
        f"--latency-msec={max(1, int(config.capture_duration_s * 1000))}",
    ]
    target_bytes = int(config.capture_duration_s * config.sample_rate * config.channels * 2)
    deadline = time.monotonic() + config.capture_duration_s
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except (FileNotFoundError, OSError) as exc:
        raise CaptureError(f"parecord spawn failed for {device!r}: {exc}") from exc

    captured = bytearray()
    try:
        assert proc.stdout is not None
        while len(captured) < target_bytes:
            now = time.monotonic()
            if now > deadline + config.timeout_extra_s:
                break
            chunk = proc.stdout.read(min(4096, max(1, target_bytes - len(captured))))
            if not chunk:
                if now >= deadline:
                    break
                time.sleep(0.01)
                continue
            captured.extend(chunk)
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
        except OSError:
            pass

    if not captured:
        stderr_tail = ""
        if proc.stderr is not None:
            try:
                stderr_tail = proc.stderr.read().decode("utf-8", errors="replace")[-500:]
            except OSError:
                stderr_tail = ""
        raise CaptureError(f"parecord captured 0 bytes from {device!r}: {stderr_tail!r}")
    return bytes(captured)


def capture_device(path: str, device: str, config: RecorderConfig) -> CaptureResult:
    started = time.time()
    try:
        raw = _capture_parecord(device, config)
        samples = _decode_s16le(raw, channels=config.channels)
        metrics = measure_samples(samples, sample_rate=config.sample_rate)
        duration = samples.shape[0] / config.sample_rate if config.sample_rate else 0.0
        return CaptureResult(
            path=path,
            device=device,
            captured_at=started,
            duration_s=float(duration),
            metrics=metrics,
        )
    except Exception as exc:
        log.debug("capture failed for %s (%s): %s", path, device, exc)
        return CaptureResult(
            path=path,
            device=device,
            captured_at=started,
            duration_s=0.0,
            error=str(exc),
        )


def capture_pair(
    config: RecorderConfig,
    *,
    capture_fn: Callable[[str, str, RecorderConfig], CaptureResult] = capture_device,
) -> tuple[CaptureResult, CaptureResult]:
    with ThreadPoolExecutor(max_workers=2) as pool:
        software_future = pool.submit(
            capture_fn,
            "software",
            config.software_device,
            config,
        )
        l12_future = pool.submit(capture_fn, "l12-mainmix", config.l12_device, config)
        return software_future.result(), l12_future.result()


def build_pair_record(
    software: CaptureResult,
    l12: CaptureResult,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    ts = time.time() if now is None else now
    delta = None
    if software.metrics is not None and l12.metrics is not None:
        delta = software.metrics.lufs_i - l12.metrics.lufs_i
    return {
        "schema_version": 1,
        "captured_at": _iso_from_epoch(ts),
        "timestamp": ts,
        "software": software.to_payload(),
        "l12_mainmix": l12.to_payload(),
        "delta_lufs_i": delta,
        "abs_delta_lufs_i": abs(delta) if delta is not None else None,
        "rtmp_egress_unchanged": True,
    }


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def emit_metrics(record: dict[str, Any], config: RecorderConfig) -> None:
    try:
        from shared.recovery_counter_textfile import DEFAULT_COLLECTOR_DIR, write_gauge
    except Exception:
        return

    collector_dir = config.textfile_collector_dir or DEFAULT_COLLECTOR_DIR
    file_basename = "hapax_audio_ab.prom"
    for key, label in (("software", "software"), ("l12_mainmix", "l12-mainmix")):
        side = record.get(key)
        if not isinstance(side, dict):
            continue
        device = str(side.get("device", "unknown"))
        ok_value = 1.0 if side.get("ok") is True else 0.0
        write_gauge(
            metric_name="hapax_audio_ab_sample_ok",
            labels={"path": label, "source": device},
            help_text="1 if the latest audio A/B capture for this path succeeded.",
            value=ok_value,
            collector_dir=collector_dir,
            file_basename=file_basename,
        )
        for field, metric_name, help_text in (
            ("lufs_i", "hapax_audio_ab_lufs_i", "Integrated loudness by A/B path."),
            ("rms_dbfs", "hapax_audio_ab_rms_dbfs", "RMS dBFS by A/B path."),
            ("crest_factor", "hapax_audio_ab_crest_factor", "Crest factor by A/B path."),
        ):
            value = side.get(field)
            if isinstance(value, int | float):
                write_gauge(
                    metric_name=metric_name,
                    labels={"path": label, "source": device},
                    help_text=help_text,
                    value=float(value),
                    collector_dir=collector_dir,
                    file_basename=file_basename,
                )
    delta = record.get("delta_lufs_i")
    if isinstance(delta, int | float):
        write_gauge(
            metric_name="hapax_audio_ab_delta_lufs",
            labels={"pair": "software_minus_l12"},
            help_text="LUFS-I delta between software egress and L-12 secondary tap.",
            value=float(delta),
            collector_dir=collector_dir,
            file_basename=file_basename,
        )


def _notify_drift(record: dict[str, Any], *, notify_fn: Callable[..., bool]) -> None:
    delta = record.get("delta_lufs_i")
    if not isinstance(delta, int | float):
        return
    message = (
        f"Software vs L-12 mainmix LUFS-I drift sustained: delta={delta:.2f} dB. "
        "RTMP path remains the software source."
    )
    try:
        notify_fn(
            "Audio A/B drift",
            message,
            priority="high",
            tags=["warning", "microphone"],
        )
    except Exception:
        log.debug("audio A/B ntfy dispatch failed", exc_info=True)


def run_once(
    config: RecorderConfig | None = None,
    *,
    drift: DriftDetector | None = None,
    capture_fn: Callable[[str, str, RecorderConfig], CaptureResult] = capture_device,
    notify_fn: Callable[..., bool] = send_notification,
) -> dict[str, Any]:
    cfg = config or RecorderConfig.from_env()
    software, l12 = capture_pair(cfg, capture_fn=capture_fn)
    now = time.time()
    record = build_pair_record(software, l12, now=now)
    append_jsonl(cfg.today_jsonl_path, record)
    emit_metrics(record, cfg)
    detector = drift or DriftDetector(
        threshold_db=cfg.delta_alert_db,
        sustain_s=cfg.delta_sustain_s,
        cooldown_s=cfg.alert_cooldown_s,
    )
    delta = record.get("delta_lufs_i")
    if cfg.enable_ntfy and detector.observe(
        delta if isinstance(delta, int | float) else None, now=now
    ):
        _notify_drift(record, notify_fn=notify_fn)
    return record


def _sd_notify(message: str) -> None:
    notify_socket = os.environ.get("NOTIFY_SOCKET")
    if not notify_socket:
        return
    address: str | bytes = notify_socket
    if notify_socket.startswith("@"):
        address = "\0" + notify_socket[1:]
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        sock.connect(address)
        sock.sendall(message.encode("utf-8"))
    except OSError:
        log.debug("sd_notify failed for %r", message, exc_info=True)
    finally:
        sock.close()


def run_daemon(config: RecorderConfig | None = None) -> None:
    cfg = config or RecorderConfig.from_env()
    drift = DriftDetector(
        threshold_db=cfg.delta_alert_db,
        sustain_s=cfg.delta_sustain_s,
        cooldown_s=cfg.alert_cooldown_s,
    )
    shutdown = False

    def _stop(_signum: int, _frame: object) -> None:
        nonlocal shutdown
        shutdown = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    _sd_notify("READY=1")
    log.info(
        "audio A/B recorder started software=%s l12=%s interval=%.3fs capture=%.3fs",
        cfg.software_device,
        cfg.l12_device,
        cfg.interval_s,
        cfg.capture_duration_s,
    )

    while not shutdown:
        started = time.monotonic()
        try:
            run_once(cfg, drift=drift)
            _sd_notify("WATCHDOG=1")
        except Exception:
            log.warning("audio A/B recorder tick failed", exc_info=True)
        if cfg.run_once:
            break
        elapsed = time.monotonic() - started
        time.sleep(max(0.01, cfg.interval_s - elapsed))


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="capture one A/B sample and exit")
    parser.add_argument(
        "--no-ntfy", action="store_true", help="disable sustained drift ntfy alerts"
    )
    parser.add_argument("--state-root", type=Path, help="override ~/hapax-state/audio-ab")
    parser.add_argument("--software-device", help="software path parecord device")
    parser.add_argument("--l12-device", help="L-12 secondary tap parecord device")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    cfg = RecorderConfig.from_env()
    if args.state_root is not None:
        cfg = replace(cfg, state_root=args.state_root.expanduser())
    if args.software_device:
        cfg = replace(cfg, software_device=args.software_device)
    if args.l12_device:
        cfg = replace(cfg, l12_device=args.l12_device)
    if args.no_ntfy:
        cfg = replace(cfg, enable_ntfy=False)
    if args.once:
        cfg = replace(cfg, run_once=True)
    run_daemon(cfg)


if __name__ == "__main__":
    main()
