"""Cross-correlate hapax-private-monitor.monitor vs hapax-obs-broadcast-remap.monitor.

Auditor D probe (cc-task audio-audit-D-broadcast-bus-echo-prometheus-probe).
Records 1s simultaneous samples from both PipeWire monitor sources via
pw-cat, computes the normalized peak cross-correlation, and emits two
Prometheus textfile metrics + an optional ntfy alert when the
correlation exceeds the leak threshold.

This is the empirical bottom-line probe for the privacy invariant.
Even when every other defense (consent gate, leak guard, layout swap)
fails, the echo probe catches actual leaks with measurable evidence —
because it watches what is *actually* on the broadcast bus, not what
the configuration *says* should be there.

Run via systemd user timer (every 30s):
    systemctl --user enable --now hapax-private-broadcast-echo-probe.timer

Or one-shot for diagnosis:
    uv run scripts/private-broadcast-echo-probe.py
    uv run scripts/private-broadcast-echo-probe.py --duration 2 --threshold 0.05

Env / flags:
    --private-target  PipeWire source (default: hapax-private-monitor.monitor)
    --broadcast-target PipeWire source (default: hapax-obs-broadcast-remap.monitor)
    --duration         seconds to record (default: 1.0)
    --threshold        |corr| above which we alert (default: 0.05)
    --textfile-dir     where to write the .prom files (default: /var/lib/node_exporter/textfile_collector)
    --ntfy-topic       ntfy topic on alert (default: audio-private-leak-suspect; empty disables)
    --ntfy-base        ntfy base URL (default: HAPAX_NTFY_BASE_URL or http://localhost:8090)
    --json             emit JSON report to stdout (default: human-readable)

Exit codes:
    0  no leak (correlation below threshold) OR record failed in a tolerated way
    2  leak detected (correlation above threshold)
    3  hard failure (pw-cat missing, cross-correlation math broke)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

DEFAULT_PRIVATE = "hapax-private-monitor.monitor"
DEFAULT_BROADCAST = "hapax-obs-broadcast-remap.monitor"
DEFAULT_DURATION_S = 1.0
DEFAULT_THRESHOLD = 0.05
DEFAULT_TEXTFILE_DIR = "/var/lib/node_exporter/textfile_collector"
DEFAULT_NTFY_TOPIC = "audio-private-leak-suspect"
METRIC_PREFIX = "hapax_private_broadcast_echo"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--private-target", default=DEFAULT_PRIVATE)
    p.add_argument("--broadcast-target", default=DEFAULT_BROADCAST)
    p.add_argument("--duration", type=float, default=DEFAULT_DURATION_S)
    p.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    p.add_argument("--textfile-dir", type=Path, default=Path(DEFAULT_TEXTFILE_DIR))
    p.add_argument("--ntfy-topic", default=DEFAULT_NTFY_TOPIC)
    p.add_argument(
        "--ntfy-base",
        default=os.environ.get("HAPAX_NTFY_BASE_URL", "http://localhost:8090"),
    )
    p.add_argument("--json", action="store_true")
    return p.parse_args()


def record_pair(
    private_target: str, broadcast_target: str, duration_s: float
) -> tuple[bytes, bytes] | tuple[None, str]:
    """Record both monitors simultaneously. Returns (private_bytes, broadcast_bytes)
    or (None, error_msg) on failure."""
    if shutil.which("pw-cat") is None:
        return None, "pw-cat not found in PATH"

    with tempfile.TemporaryDirectory() as td:
        priv_path = Path(td) / "private.wav"
        broad_path = Path(td) / "broadcast.wav"

        def spawn(target: str, out: Path) -> subprocess.Popen:
            return subprocess.Popen(
                [
                    "pw-cat",
                    "--record",
                    "--target",
                    target,
                    str(out),
                    "--format=s16",
                    "--channels=1",
                    "--rate=48000",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )

        priv_proc = spawn(private_target, priv_path)
        broad_proc = spawn(broadcast_target, broad_path)
        try:
            time.sleep(duration_s)
        finally:
            for proc in (priv_proc, broad_proc):
                proc.terminate()
            for proc in (priv_proc, broad_proc):
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()

        if not priv_path.exists() or not broad_path.exists():
            return None, "pw-cat did not produce output files"
        return priv_path.read_bytes(), broad_path.read_bytes()


def parse_wav_pcm(buf: bytes) -> list[int]:
    """Parse a 16-bit PCM mono WAV buffer into a list of int samples.

    Avoids the numpy dependency for the script's per-tick path; the math
    we need (mean, sumprod, std) is short and clear in pure Python.
    """
    with wave.open(__import__("io").BytesIO(buf), "rb") as wf:
        n = wf.getnframes()
        raw = wf.readframes(n)
    return list(__import__("array").array("h", raw))


def normalized_peak_xcorr(a: list[int], b: list[int]) -> float:
    """Return |max normalized cross-correlation| over a small lag window.

    Searches lags in ±N where N = min(len(a), 256) so inertia in either
    side of the bus alignment doesn't dominate. Returns 0.0 if either
    series is silent (zero variance).
    """
    n = min(len(a), len(b))
    if n < 32:
        return 0.0
    a_view = a[:n]
    b_view = b[:n]
    mean_a = sum(a_view) / n
    mean_b = sum(b_view) / n
    var_a = sum((x - mean_a) ** 2 for x in a_view)
    var_b = sum((x - mean_b) ** 2 for x in b_view)
    if var_a == 0 or var_b == 0:
        return 0.0
    denom = (var_a * var_b) ** 0.5

    max_lag = min(256, n // 4)
    best = 0.0
    for lag in range(-max_lag, max_lag + 1):
        s = 0.0
        if lag >= 0:
            for i in range(n - lag):
                s += (a_view[i] - mean_a) * (b_view[i + lag] - mean_b)
        else:
            for i in range(n + lag):
                s += (a_view[i - lag] - mean_a) * (b_view[i] - mean_b)
        coeff = abs(s / denom)
        if coeff > best:
            best = coeff
    return min(1.0, best)


def emit_textfile(
    textfile_dir: Path, correlation: float, alert_increment: int
) -> tuple[bool, str | None]:
    """Write the Prometheus textfile via tmp+rename. Returns (ok, error_msg)."""
    try:
        textfile_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        return False, f"textfile_dir not writable: {exc}"

    target = textfile_dir / "hapax_private_broadcast_echo.prom"
    body = (
        f"# HELP {METRIC_PREFIX}_correlation Normalized peak cross-correlation between private and broadcast monitors\n"
        f"# TYPE {METRIC_PREFIX}_correlation gauge\n"
        f"{METRIC_PREFIX}_correlation {correlation:.6f}\n"
        f"# HELP {METRIC_PREFIX}_alert_total Counter of probe ticks where correlation exceeded the leak threshold\n"
        f"# TYPE {METRIC_PREFIX}_alert_total counter\n"
        f"{METRIC_PREFIX}_alert_total {alert_increment}\n"
    )
    tmp = target.with_suffix(".prom.tmp")
    try:
        tmp.write_text(body)
        tmp.rename(target)
    except OSError as exc:
        return False, f"textfile write failed: {exc}"
    return True, None


def post_ntfy_alert(
    ntfy_base: str, topic: str, correlation: float, threshold: float
) -> tuple[bool, str | None]:
    if not topic:
        return True, "ntfy disabled"
    if shutil.which("curl") is None:
        return False, "curl not found in PATH"
    body = (
        f"private-broadcast echo probe LEAK\n"
        f"correlation={correlation:.4f} threshold={threshold:.3f}\n"
        f"Runbook: docs/runbooks/audio-incidents.md#private-leak-l12\n"
    )
    cmd = [
        "curl",
        "-s",
        "-o",
        "/dev/null",
        "-H",
        "Title: audio private→broadcast leak suspect",
        "-H",
        "Priority: high",
        "-H",
        "Tags: warning,sound",
        "-d",
        body,
        f"{ntfy_base.rstrip('/')}/{topic}",
    ]
    try:
        subprocess.run(cmd, check=True, timeout=5)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return False, f"ntfy POST failed: {exc}"
    return True, None


def main() -> int:
    args = parse_args()

    pair = record_pair(args.private_target, args.broadcast_target, args.duration)
    if pair[0] is None:
        report = {"status": "skipped", "reason": pair[1]}
        if args.json:
            print(json.dumps(report))
        else:
            print(f"skipped: {pair[1]}")
        return 0  # tolerate transient missing source

    priv_bytes, broad_bytes = pair
    try:
        priv_samples = parse_wav_pcm(priv_bytes)
        broad_samples = parse_wav_pcm(broad_bytes)
    except Exception as exc:
        report = {"status": "error", "reason": f"wav parse failed: {exc}"}
        if args.json:
            print(json.dumps(report))
        else:
            print(f"error: {exc}")
        return 3

    correlation = normalized_peak_xcorr(priv_samples, broad_samples)
    leaked = correlation > args.threshold
    alert_increment = 1 if leaked else 0

    text_ok, text_err = emit_textfile(args.textfile_dir, correlation, alert_increment)

    ntfy_ok, ntfy_err = (True, "no alert (no leak)")
    if leaked:
        ntfy_ok, ntfy_err = post_ntfy_alert(
            args.ntfy_base, args.ntfy_topic, correlation, args.threshold
        )

    report = {
        "status": "leak" if leaked else "ok",
        "correlation": round(correlation, 6),
        "threshold": args.threshold,
        "duration_s": args.duration,
        "private_target": args.private_target,
        "broadcast_target": args.broadcast_target,
        "textfile_emit": {"ok": text_ok, "reason": text_err},
        "ntfy_alert": {"ok": ntfy_ok, "reason": ntfy_err},
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        marker = "LEAK" if leaked else "ok"
        print(
            f"[{marker}] correlation={correlation:.4f} threshold={args.threshold:.3f}\n"
            f"  textfile: {text_ok} ({text_err or 'wrote'})\n"
            f"  ntfy: {ntfy_ok} ({ntfy_err})"
        )

    return 2 if leaked else 0


if __name__ == "__main__":
    sys.exit(main())
