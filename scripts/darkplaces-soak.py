#!/usr/bin/env python3
"""DarkPlaces/Screwm renderer soak runner + gate-promotion CLI.

The 2026-05-23 AMD data-fabric sync-flood host hard-reset made the DarkPlaces GL
renderer attended-only (docs/audits/2026-05-23-screwm-quake-runtime-reset-
containment.md). This CLI is the live half of the 1-hour crash-free soak gate;
all PASS/FAIL and promote DECISIONS are delegated to the tested core in
shared/darkplaces_soak.py.

Subcommands:
  monitor     Run the per-second soak evaluation loop against a live renderer,
              write a fingerprinted receipt, and (on fault) kill the renderer.
              Exit 0 = PASS, 2 = FAIL, other = harness error.
  promote     Create ~/.config/hapax/enable-darkplaces-runtime ONLY if a fresh
              PASS receipt matches the current hardware fingerprint. Fail-closed.
  fingerprint Print the current hardware fingerprint (nvidia name|driver|pci).

This script never launches the renderer itself — scripts/darkplaces-soak.sh does
that under the runtime guard (HAPAX_DARKPLACES_RUNTIME_ACK=1) so containment is
intact if the soak aborts.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.darkplaces_soak import (  # noqa: E402
    SoakCriteria,
    SoakEvaluator,
    SoakObservation,
    SoakReceipt,
    hardware_fingerprint,
    is_hardware_risk_line,
    promote_decision,
    read_receipt,
    write_receipt,
)

DEFAULT_GATE_FILE = Path.home() / ".config" / "hapax" / "enable-darkplaces-runtime"
DEFAULT_RUNS_ROOT = Path.home() / "hapax-state" / "hardware-validation"


# --- live system probes (best-effort I/O glue; decisions live in the core) ---


def _boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return ""


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return True  # not tracked -> don't synthesise a crash fault
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _nvidia_gpu_info(index: int) -> dict[str, str]:
    """name, driver_version, pci.bus_id, memory.used (MiB), temperature.gpu (C)."""
    fields = ["name", "driver_version", "pci.bus_id", "memory.used", "temperature.gpu"]
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "-i",
                str(index),
                f"--query-gpu={','.join(fields)}",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return {}
    parts = [p.strip() for p in out.split(",")]
    if len(parts) != len(fields):
        return {}
    return dict(zip(fields, parts, strict=True))


def _current_fingerprint(index: int) -> tuple[str, dict[str, str]]:
    info = _nvidia_gpu_info(index)
    fp = hardware_fingerprint(
        info.get("name", ""), info.get("driver_version", ""), info.get("pci.bus_id", "")
    )
    return fp, info


def _gl_renderer_from_log(launch_log: Path) -> str:
    try:
        for line in launch_log.read_text(errors="replace").splitlines():
            if "GL_RENDERER" in line:
                _, _, rhs = line.partition("GL_RENDERER")
                return rhs.lstrip(" :=\t").strip()
    except OSError:
        pass
    return ""


def _frame_age_s(device: str) -> float:
    """Best-effort frame-staleness for a v4l2 output device.

    A reliable per-frame sequence is renderer/driver specific; absent a usable
    signal we return 0.0 (liveness is then carried by renderer/feeder PID checks).
    The attended bring-up wires a real frame-progress signal here.
    """
    return 0.0


def _read_new_kernel_risk_lines(path: Path, offset: int) -> tuple[list[str], int]:
    """Return (new hardware-risk lines since offset, new offset)."""
    try:
        size = path.stat().st_size
    except OSError:
        return [], offset
    if size <= offset:
        return [], size
    risk: list[str] = []
    try:
        with path.open("r", errors="replace") as fh:
            fh.seek(offset)
            for line in fh:
                if is_hardware_risk_line(line):
                    risk.append(line.strip())
    except OSError:
        return [], offset
    return risk, size


def _kill(pid: int | None) -> None:
    if not pid:
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


# --- subcommands ---


def cmd_monitor(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    launch_log = Path(args.launch_log) if args.launch_log else run_dir / "darkplaces-launch.log"
    kernel_log = Path(args.kernel_log) if args.kernel_log else run_dir / "kernel-follow.log"

    expected = args.expected_gl_renderer
    if not expected and not args.skip_gl_assert:
        info = _nvidia_gpu_info(args.gpu_index)
        expected = info.get("name", "")

    crit = SoakCriteria(
        soak_duration_s=float(args.duration_s),
        expected_gl_renderer="" if args.skip_gl_assert else expected,
        max_frame_age_s=float(args.max_frame_age_s),
        temp_fail_c=float(args.temp_fail_c),
        vram_limit_mib=args.vram_limit_mib,
    )
    started_wall = time.time()
    started = time.monotonic()
    ev = SoakEvaluator(criteria=crit, started_at=started)
    fp, info = _current_fingerprint(args.gpu_index)
    # Skip kernel lines that pre-date launch.
    try:
        kernel_offset = kernel_log.stat().st_size
    except OSError:
        kernel_offset = 0

    print(
        f"[soak] start: duration={crit.soak_duration_s:.0f}s expected_gl={expected!r} "
        f"gpu_index={args.gpu_index} fp={fp[:12]}",
        flush=True,
    )

    def _write(status: str, reasons: list[str], end_marker: bool) -> Path:
        rec = SoakReceipt(
            status=status,
            fingerprint=fp,
            boot_id=_boot_id(),
            gl_renderer=_gl_renderer_from_log(launch_log) or expected,
            driver_version=info.get("driver_version", ""),
            pci_bus_id=info.get("pci.bus_id", ""),
            started_at=started_wall,
            ended_at=time.time(),
            soak_duration_s=crit.soak_duration_s,
            reasons=reasons,
            end_marker=end_marker,
        )
        return write_receipt(run_dir, rec)

    while True:
        now = time.monotonic()
        t = now - started
        risk_lines, kernel_offset = _read_new_kernel_risk_lines(kernel_log, kernel_offset)
        gpu = _nvidia_gpu_info(args.gpu_index)
        try:
            vram = int(gpu.get("memory.used", "0") or 0)
        except ValueError:
            vram = 0
        try:
            temp = float(gpu.get("temperature.gpu", "0") or 0)
        except ValueError:
            temp = 0.0
        obs = SoakObservation(
            t=t,
            renderer_alive=_pid_alive(args.renderer_pid),
            feeder_alive=_pid_alive(args.feeder_pid),
            gl_renderer=_gl_renderer_from_log(launch_log),
            frame_age_s=_frame_age_s(args.video_device),
            vram_used_mib=vram,
            gpu_temp_c=temp,
            kernel_risk_lines=risk_lines,
        )
        ev.record(obs)
        status, reasons = ev.verdict(now=time.monotonic())
        if status == "fail":
            # Fastest mitigation for the sync-flood class: get GL off the GPU now.
            _kill(args.renderer_pid)
            _kill(args.feeder_pid)
            path = _write("fail", reasons, end_marker=True)
            print(
                f"[soak] FAIL after {t:.0f}s: {reasons[0] if reasons else '?'} (receipt {path})",
                flush=True,
            )
            return 2
        if status == "pass":
            path = _write("pass", [], end_marker=True)
            print(
                f"[soak] PASS: {crit.soak_duration_s:.0f}s crash-free (receipt {path})", flush=True
            )
            return 0
        time.sleep(float(args.poll_s))


def _latest_receipt(runs_root: Path) -> Path | None:
    candidates = sorted(runs_root.glob("*/receipt.json"), key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def cmd_promote(args: argparse.Namespace) -> int:
    runs_root = Path(args.runs_root)
    receipt_path = Path(args.receipt) if args.receipt else _latest_receipt(runs_root)
    receipt = read_receipt(receipt_path) if receipt_path and receipt_path.exists() else None
    current_fp, _ = _current_fingerprint(args.gpu_index)
    ok, reason = promote_decision(
        receipt, current_fingerprint=current_fp, now=time.time(), max_age_s=float(args.max_age_s)
    )
    if not ok:
        print(f"[promote] REFUSED: {reason}", file=sys.stderr)
        if receipt_path:
            print(f"[promote] receipt: {receipt_path}", file=sys.stderr)
        return 1
    gate = Path(args.gate_file)
    gate.parent.mkdir(parents=True, exist_ok=True)
    gate.touch()
    print(f"[promote] OK: {reason}; created gate {gate} (renderer cleared for ATTENDED runtime)")
    print(
        "[promote] NOTE: unattended boot-enable still requires a repeat/overnight pass AND "
        "the 2026-05-23 reset cause understood (audit hard rule)."
    )
    return 0


def cmd_fingerprint(args: argparse.Namespace) -> int:
    fp, info = _current_fingerprint(args.gpu_index)
    print(fp)
    print(
        f"  name={info.get('name', '')!r} driver={info.get('driver_version', '')} "
        f"pci={info.get('pci.bus_id', '')}",
        file=sys.stderr,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="darkplaces-soak", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("monitor", help="run the soak evaluation loop")
    m.add_argument("--run-dir", required=True)
    m.add_argument("--duration-s", default=3600.0, type=float)
    m.add_argument("--gpu-index", default=1, type=int)
    m.add_argument("--expected-gl-renderer", default="")
    m.add_argument("--skip-gl-assert", action="store_true")
    m.add_argument("--renderer-pid", default=None, type=int)
    m.add_argument("--feeder-pid", default=None, type=int)
    m.add_argument("--launch-log", default="")
    m.add_argument("--kernel-log", default="")
    m.add_argument("--video-device", default="/dev/video52")
    m.add_argument("--vram-limit-mib", default=None, type=int)
    m.add_argument("--temp-fail-c", default=90.0, type=float)
    m.add_argument("--max-frame-age-s", default=5.0, type=float)
    m.add_argument("--poll-s", default=1.0, type=float)
    m.set_defaults(func=cmd_monitor)

    pr = sub.add_parser("promote", help="create the gate file iff a fresh matching PASS exists")
    pr.add_argument("--gpu-index", default=1, type=int)
    pr.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT))
    pr.add_argument("--receipt", default="")
    pr.add_argument("--gate-file", default=str(DEFAULT_GATE_FILE))
    pr.add_argument("--max-age-s", default=86400.0, type=float)
    pr.set_defaults(func=cmd_promote)

    fp = sub.add_parser("fingerprint", help="print the current hardware fingerprint")
    fp.add_argument("--gpu-index", default=1, type=int)
    fp.set_defaults(func=cmd_fingerprint)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
