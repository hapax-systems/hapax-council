"""Tests for the DarkPlaces/Screwm renderer suitability soak gate.

The renderer is attended-only after the 2026-05-23 AMD data-fabric sync-flood
host hard-reset (docs/audits/2026-05-23-screwm-quake-runtime-reset-containment.md).
shared/darkplaces_soak.py is the testable core of the 1-hour crash-free soak that
must PASS before the renderer may be promoted behind the persistent
enable-darkplaces-runtime gate. The load-bearing invariant: fail CLOSED on the
first hardware-risk signal.
"""

from __future__ import annotations

from dataclasses import replace

from shared.darkplaces_soak import (
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


def _ok_obs(t: float, gl_renderer: str) -> SoakObservation:
    return SoakObservation(
        t=t,
        renderer_alive=True,
        feeder_alive=True,
        gl_renderer=gl_renderer,
        frame_age_s=0.1,
        vram_used_mib=2000,
        gpu_temp_c=60.0,
        kernel_risk_lines=[],
    )


def test_single_hardware_risk_line_is_instant_fail() -> None:
    """A single data-fabric/Xid kernel line FAILS immediately — no tolerance,
    regardless of how far the soak is from its duration (this is the exact
    fault class that hard-reset the host on 2026-05-23)."""
    gpu = "NVIDIA GeForce RTX 5060 Ti"
    crit = SoakCriteria(soak_duration_s=3600.0, expected_gl_renderer=gpu)
    ev = SoakEvaluator(criteria=crit, started_at=0.0)

    # Healthy first sample, nowhere near the 1h duration -> still running.
    ev.record(_ok_obs(t=1.0, gl_renderer=gpu))
    assert ev.verdict(now=1.0)[0] == "running"

    # A single data-fabric sync-flood kernel line at t=2s -> instant FAIL,
    # even though the renderer is alive and 2s << 3600s.
    ev.record(
        SoakObservation(
            t=2.0,
            renderer_alive=True,
            feeder_alive=True,
            gl_renderer=gpu,
            frame_age_s=0.1,
            vram_used_mib=2000,
            gpu_temp_c=60.0,
            kernel_risk_lines=[
                "x86/amd: Previous system reset reason [0x08000800]: "
                "an uncorrected error caused a data fabric sync flood event"
            ],
        )
    )
    status, reasons = ev.verdict(now=2.0)
    assert status == "fail"
    assert any("data fabric" in r for r in reasons)


def test_renderer_crash_is_fail() -> None:
    gpu = "NVIDIA GeForce RTX 5060 Ti"
    crit = SoakCriteria(soak_duration_s=10.0, expected_gl_renderer=gpu)
    ev = SoakEvaluator(criteria=crit, started_at=0.0)
    ev.record(_ok_obs(1.0, gpu))
    ev.record(replace(_ok_obs(2.0, gpu), renderer_alive=False))
    status, reasons = ev.verdict(now=2.0)
    assert status == "fail"
    assert any("renderer" in r.lower() for r in reasons)


def test_feeder_crash_is_fail() -> None:
    gpu = "NVIDIA GeForce RTX 5060 Ti"
    crit = SoakCriteria(soak_duration_s=10.0, expected_gl_renderer=gpu)
    ev = SoakEvaluator(criteria=crit, started_at=0.0)
    ev.record(replace(_ok_obs(1.0, gpu), feeder_alive=False))
    status, reasons = ev.verdict(now=1.0)
    assert status == "fail"
    assert any("feeder" in r.lower() for r in reasons)


def test_gpu_reselection_is_fail() -> None:
    """A mid-run GL_RENDERER change == silent GPU re-selection (the 5090-vs-5060Ti
    hazard from the audit) -> FAIL."""
    gpu = "NVIDIA GeForce RTX 5060 Ti"
    crit = SoakCriteria(soak_duration_s=10.0, expected_gl_renderer=gpu)
    ev = SoakEvaluator(criteria=crit, started_at=0.0)
    ev.record(_ok_obs(1.0, gpu))
    ev.record(replace(_ok_obs(2.0, gpu), gl_renderer="NVIDIA GeForce RTX 5090"))
    status, reasons = ev.verdict(now=2.0)
    assert status == "fail"
    assert any("GL_RENDERER" in r or "renderer" in r.lower() for r in reasons)


def test_empty_expected_renderer_skips_gl_assertion() -> None:
    """When no expected renderer is configured, a differing GL_RENDERER is not a
    fault (assertion intentionally skipped)."""
    crit = SoakCriteria(soak_duration_s=10.0, expected_gl_renderer="")
    ev = SoakEvaluator(criteria=crit, started_at=0.0)
    ev.record(replace(_ok_obs(1.0, ""), gl_renderer="anything at all"))
    assert ev.verdict(now=1.0)[0] == "running"


def test_frame_stall_is_fail() -> None:
    gpu = "NVIDIA GeForce RTX 5060 Ti"
    crit = SoakCriteria(soak_duration_s=10.0, expected_gl_renderer=gpu, max_frame_age_s=5.0)
    ev = SoakEvaluator(criteria=crit, started_at=0.0)
    ev.record(replace(_ok_obs(6.0, gpu), frame_age_s=6.0))
    status, reasons = ev.verdict(now=6.0)
    assert status == "fail"
    assert any("frame" in r.lower() for r in reasons)


def test_thermal_over_threshold_is_fail() -> None:
    gpu = "NVIDIA GeForce RTX 5060 Ti"
    crit = SoakCriteria(soak_duration_s=10.0, expected_gl_renderer=gpu, temp_fail_c=90.0)
    ev = SoakEvaluator(criteria=crit, started_at=0.0)
    ev.record(replace(_ok_obs(1.0, gpu), gpu_temp_c=95.0))
    status, reasons = ev.verdict(now=1.0)
    assert status == "fail"
    assert any("temp" in r.lower() for r in reasons)


def test_vram_over_limit_is_fail() -> None:
    gpu = "NVIDIA GeForce RTX 5060 Ti"
    crit = SoakCriteria(soak_duration_s=10.0, expected_gl_renderer=gpu, vram_limit_mib=4000)
    ev = SoakEvaluator(criteria=crit, started_at=0.0)
    ev.record(replace(_ok_obs(1.0, gpu), vram_used_mib=5000))
    status, reasons = ev.verdict(now=1.0)
    assert status == "fail"
    assert any("vram" in r.lower() for r in reasons)


def test_clean_full_duration_is_pass() -> None:
    """No faults for the whole duration -> PASS once the duration is reached."""
    gpu = "NVIDIA GeForce RTX 5060 Ti"
    crit = SoakCriteria(soak_duration_s=10.0, expected_gl_renderer=gpu)
    ev = SoakEvaluator(criteria=crit, started_at=0.0)
    for t in range(1, 11):
        ev.record(_ok_obs(float(t), gpu))
    assert ev.verdict(now=9.0)[0] == "running"
    assert ev.verdict(now=10.0)[0] == "pass"


# --- fingerprint + receipt + promote decision (the gate-creation safety chain) ---


def test_is_hardware_risk_line_matches_the_failfast_subset() -> None:
    """The instant-FAIL classifier matches the same hardware-risk subset the
    attended-smoke harness exits 2 on — data fabric / Xid / GPU-fallen-off /
    hardware error / fatal — and ignores benign kernel chatter."""
    assert is_hardware_risk_line(
        "x86/amd: Previous system reset reason [0x08000800]: data fabric sync flood event"
    )
    assert is_hardware_risk_line("NVRM: Xid (PCI:0000:05:00): 79, GPU has fallen off the bus")
    assert is_hardware_risk_line("kernel: HARDWARE ERROR something")  # case-insensitive
    assert not is_hardware_risk_line("usb 1-1: new high-speed USB device number 5")
    assert not is_hardware_risk_line("audit: BPF prog loaded")


def test_fingerprint_is_deterministic_and_driver_sensitive() -> None:
    r, p = "NVIDIA GeForce RTX 5060 Ti/PCIe/SSE2", "00000000:05:00.0"
    fp1 = hardware_fingerprint(r, "580.95.05", p)
    fp2 = hardware_fingerprint(r, "580.95.05", p)
    fp3 = hardware_fingerprint(r, "590.00.00", p)
    assert fp1 == fp2
    assert fp1 != fp3  # a driver change must invalidate a prior pass


def _pass_receipt(
    fp: str, ended_at: float, *, end_marker: bool = True, status: str = "pass"
) -> SoakReceipt:
    return SoakReceipt(
        status=status,
        fingerprint=fp,
        boot_id="boot-abc",
        gl_renderer="NVIDIA GeForce RTX 5060 Ti",
        driver_version="580.95.05",
        pci_bus_id="00000000:05:00.0",
        started_at=ended_at - 3600.0,
        ended_at=ended_at,
        soak_duration_s=3600.0,
        reasons=[],
        end_marker=end_marker,
    )


def test_receipt_round_trip(tmp_path) -> None:
    fp = hardware_fingerprint("r", "d", "p")
    rec = _pass_receipt(fp, ended_at=1000.0)
    path = write_receipt(tmp_path, rec)
    assert read_receipt(path) == rec


def test_promote_allows_fresh_matching_pass() -> None:
    fp = hardware_fingerprint("r", "d", "p")
    rec = _pass_receipt(fp, ended_at=1000.0)
    ok, _ = promote_decision(rec, current_fingerprint=fp, now=1060.0, max_age_s=86400.0)
    assert ok is True


def test_promote_refuses_without_receipt() -> None:
    ok, reason = promote_decision(None, current_fingerprint="fp", now=0.0, max_age_s=86400.0)
    assert ok is False
    assert "receipt" in reason.lower()


def test_promote_refuses_fail_receipt() -> None:
    fp = hardware_fingerprint("r", "d", "p")
    rec = _pass_receipt(fp, ended_at=1000.0, status="fail")
    ok, reason = promote_decision(rec, current_fingerprint=fp, now=1060.0, max_age_s=86400.0)
    assert ok is False
    assert "pass" in reason.lower() or "fail" in reason.lower()


def test_promote_refuses_without_end_marker() -> None:
    """A receipt without an END marker means the soak may have been killed
    mid-write (e.g. a host reset) -> refuse."""
    fp = hardware_fingerprint("r", "d", "p")
    rec = _pass_receipt(fp, ended_at=1000.0, end_marker=False)
    ok, reason = promote_decision(rec, current_fingerprint=fp, now=1060.0, max_age_s=86400.0)
    assert ok is False
    assert "end" in reason.lower() or "incomplete" in reason.lower()


def test_promote_refuses_fingerprint_mismatch() -> None:
    fp = hardware_fingerprint("r", "d", "p")
    other = hardware_fingerprint("r", "d2", "p")
    rec = _pass_receipt(fp, ended_at=1000.0)
    ok, reason = promote_decision(rec, current_fingerprint=other, now=1060.0, max_age_s=86400.0)
    assert ok is False
    assert "fingerprint" in reason.lower() or "hardware" in reason.lower()


def test_promote_refuses_stale_pass() -> None:
    fp = hardware_fingerprint("r", "d", "p")
    rec = _pass_receipt(fp, ended_at=1000.0)
    ok, reason = promote_decision(
        rec, current_fingerprint=fp, now=1000.0 + 100_000, max_age_s=86400.0
    )
    assert ok is False
    assert "stale" in reason.lower() or "age" in reason.lower() or "old" in reason.lower()
