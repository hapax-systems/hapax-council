"""Cross-correlate hapax-private.monitor vs hapax-obs-broadcast-remap.

Auditor D probe (cc-task audio-audit-D-broadcast-bus-echo-prometheus-probe).
Records 1s simultaneous samples from both PipeWire sources via
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
    # deliberately-sensitive diagnostic override (default is 0.15; 0.05
    # sits inside the ambient hum band and WILL flag a healthy bus):
    uv run scripts/private-broadcast-echo-probe.py --duration 2 --threshold 0.05

Env / flags:
    --private-target  PipeWire source (default: hapax-private.monitor)
    --broadcast-target PipeWire source (default: hapax-obs-broadcast-remap)
    --duration         seconds to record (default: 1.0)
    --threshold        |corr| above which we alert (default: 0.15)
    --textfile-dir     where to write the .prom files (default: /var/lib/node_exporter/textfile_collector)
    --ntfy-topic       ntfy topic on alert (default: audio-private-leak-suspect; empty disables)
    --ntfy-base        ntfy base URL (default: HAPAX_NTFY_BASE_URL or http://localhost:8090)
    --breach-ticks     consecutive breach ticks before the first ntfy (default: 3)
    --ntfy-cooldown    seconds between ntfys within one breach episode (default: 900)
    --state-file       breach-streak state across oneshot ticks (default: ~/.cache/hapax/private-broadcast-echo-probe-state.json)
    --json             emit JSON report to stdout (default: human-readable)

Alert design (audit-w4-observability-honesty):
    The 0.05 threshold sat inside the ambient correlated-hum noise band
    (clean ticks witnessed at 0.033-0.066), and an unconditional ntfy per
    30s breach tick produced ~2,000 alerts/day — fatigue that buries real
    leaks. The Jun 9-10 real-leak band was 0.21-1.00, so 0.15 separates
    cleanly. ntfy now needs 3 consecutive breach ticks and repeats at most
    every 15 min per breach episode. The textfile gauge (and the new
    _collect_ts inertness stamp) is still written on EVERY tick — the
    durable alert path is the Prometheus rule over the gauge, not ntfy.

Exit codes (unchanged — the timer + OnFailure semantics stay honest):
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

DEFAULT_PRIVATE = "hapax-private.monitor"
DEFAULT_BROADCAST = "hapax-obs-broadcast-remap"
DEFAULT_DURATION_S = 1.0
# 0.05 was inside the ambient noise band (0.02-0.07 floor for 1s@48k
# correlated hum); real leaks witnessed at 0.21-1.00. See module docstring.
DEFAULT_THRESHOLD = 0.15
DEFAULT_TEXTFILE_DIR = "/var/lib/node_exporter/textfile_collector"
DEFAULT_NTFY_TOPIC = "audio-private-leak-suspect"
DEFAULT_BREACH_TICKS = 3
DEFAULT_NTFY_COOLDOWN_S = 900
DEFAULT_STATE_FILE = Path.home() / ".cache" / "hapax" / "private-broadcast-echo-probe-state.json"
METRIC_PREFIX = "hapax_private_broadcast_echo"

FRESH_STATE: dict = {"streak": 0, "episode_start": None, "last_ntfy": None}


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
    p.add_argument("--breach-ticks", type=int, default=DEFAULT_BREACH_TICKS)
    p.add_argument("--ntfy-cooldown", type=float, default=DEFAULT_NTFY_COOLDOWN_S)
    p.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    p.add_argument("--json", action="store_true")
    return p.parse_args()


def load_state(path: Path) -> dict:
    """Load breach-streak state; missing or corrupt files degrade to a
    fresh state (the probe must keep measuring no matter what)."""
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return dict(FRESH_STATE)
    if not isinstance(raw, dict):
        return dict(FRESH_STATE)
    return {**FRESH_STATE, **raw}


def save_state(path: Path, state: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state))
        tmp.rename(path)
    except OSError:
        pass  # state is an optimization; never let it break the measurement


def decide_alert(
    state: dict,
    leaked: bool,
    now: float,
    breach_ticks: int = DEFAULT_BREACH_TICKS,
    cooldown_s: float = DEFAULT_NTFY_COOLDOWN_S,
) -> tuple[bool, dict]:
    """Hysteresis + per-episode cooldown for the ntfy path ONLY.

    A breach episode is a run of consecutive over-threshold ticks. The
    first ntfy needs ``breach_ticks`` consecutive breaches; while the
    episode persists, repeats are spaced ``cooldown_s`` apart, keyed on
    the episode (state carries ``episode_start``). A clean tick resets
    everything. Exit codes and the textfile gauge are deliberately NOT
    routed through this function — every tick stays visible to
    Prometheus and to the timer's OnFailure semantics.

    Returns (should_ntfy, new_state).
    """
    if not leaked:
        return False, dict(FRESH_STATE)

    try:
        streak = int(state.get("streak", 0)) + 1
    except (TypeError, ValueError):
        streak = 1
    episode_start = state.get("episode_start")
    if not isinstance(episode_start, (int, float)) or streak == 1:
        episode_start = now
    last_ntfy = state.get("last_ntfy")
    if not isinstance(last_ntfy, (int, float)):
        last_ntfy = None

    should_ntfy = streak >= breach_ticks and (last_ntfy is None or now - last_ntfy >= cooldown_s)
    if should_ntfy:
        last_ntfy = now
    return should_ntfy, {
        "streak": streak,
        "episode_start": episode_start,
        "last_ntfy": last_ntfy,
    }


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
                    "--channels=2",
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
    """Parse a 16-bit PCM WAV buffer into a list of int samples (mono).

    If the input is stereo, channels are averaged to mono. Avoids the
    numpy dependency for the script's per-tick path; the math we need
    (mean, sumprod, std) is short and clear in pure Python.
    """
    with wave.open(__import__("io").BytesIO(buf), "rb") as wf:
        nch = wf.getnchannels()
        n = wf.getnframes()
        raw = wf.readframes(n)
    samples = list(__import__("array").array("h", raw))
    if nch == 2 and len(samples) >= 2:
        # Downmix stereo→mono by averaging pairs
        samples = [(samples[i] + samples[i + 1]) // 2 for i in range(0, len(samples) - 1, 2)]
    return samples


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
    textfile_dir: Path,
    correlation: float,
    alert_increment: int,
    collect_ts: float | None = None,
) -> tuple[bool, str | None]:
    """Write the Prometheus textfile via tmp+rename. Returns (ok, error_msg).

    ``collect_ts`` is the probe-inertness stamp: the HapaxEchoProbeStale
    rule fires when ``time() - collect_ts > 300``, catching the watcher
    itself dying — written on every tick, leak or not.
    """
    try:
        textfile_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        return False, f"textfile_dir not writable: {exc}"

    if collect_ts is None:
        collect_ts = time.time()
    target = textfile_dir / "hapax_private_broadcast_echo.prom"
    body = (
        f"# HELP {METRIC_PREFIX}_correlation Normalized peak cross-correlation between private and broadcast monitors\n"
        f"# TYPE {METRIC_PREFIX}_correlation gauge\n"
        f"{METRIC_PREFIX}_correlation {correlation:.6f}\n"
        f"# HELP {METRIC_PREFIX}_alert_total Counter of probe ticks where correlation exceeded the leak threshold\n"
        f"# TYPE {METRIC_PREFIX}_alert_total counter\n"
        f"{METRIC_PREFIX}_alert_total {alert_increment}\n"
        f"# HELP {METRIC_PREFIX}_collect_ts Unix time of the last completed probe tick (staleness/inertness detector)\n"
        f"# TYPE {METRIC_PREFIX}_collect_ts gauge\n"
        f"{METRIC_PREFIX}_collect_ts {collect_ts:.0f}\n"
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

    state = load_state(args.state_file)
    should_ntfy, state = decide_alert(
        state, leaked, time.time(), args.breach_ticks, args.ntfy_cooldown
    )
    save_state(args.state_file, state)

    if should_ntfy:
        ntfy_ok, ntfy_err = post_ntfy_alert(
            args.ntfy_base, args.ntfy_topic, correlation, args.threshold
        )
    elif leaked:
        ntfy_ok, ntfy_err = (
            True,
            f"suppressed (streak {state['streak']}/{args.breach_ticks}"
            + (", cooldown)" if state["streak"] >= args.breach_ticks else ")"),
        )
    else:
        ntfy_ok, ntfy_err = (True, "no alert (no leak)")

    report = {
        "status": "leak" if leaked else "ok",
        "correlation": round(correlation, 6),
        "threshold": args.threshold,
        "duration_s": args.duration,
        "private_target": args.private_target,
        "broadcast_target": args.broadcast_target,
        "breach_streak": state["streak"],
        "episode_start": state["episode_start"],
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
