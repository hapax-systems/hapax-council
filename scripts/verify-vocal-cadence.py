#!/usr/bin/env python3
"""Verify Hapax produces broadcast vocal output at the target 30-90s cadence.

Sibling to the destination + cadence work shipped in PR #2466
(``cc-task: livestream-vocal-as-fuck-amp``). The bias path widens
``classify_destination`` to route ``endogenous.narrative_drive``
impingements to LIVESTREAM under an active broadcast-eligible
programme; the cadence tune drops the impingement-bus floor to 30 s
and the drive's tau to 60 s. Nothing in production validates that the
end-to-end chain — narrative_drive emission → classify LIVESTREAM →
``resolve_playback_decision`` ALLOW → broadcast TTS — actually fires;
silent failures at any gate look identical to "Hapax is being quiet."

This harness samples the chain over a configurable window and produces
both an operator-facing plaintext report ("cadence ok / silent /
blocked at gate X") and a JSON line suitable for trending against the
30-90 s SLO.

The harness is read-only against production state files; it never
mutates the impingement bus, the programme store, or any audio
runtime. Add a ``--force-emit`` mode in a follow-up PR if the natural
drive cadence is too slow for development.

Usage::

    uv run python scripts/verify-vocal-cadence.py
    uv run python scripts/verify-vocal-cadence.py --window-s 600
    uv run python scripts/verify-vocal-cadence.py --json-only
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

DEFAULT_IMPINGEMENTS_PATH = Path("/dev/shm/hapax-dmn/impingements.jsonl")
DEFAULT_AUDIO_SAFE_PATH = Path("/dev/shm/hapax-broadcast/audio-safe-for-broadcast.json")
DEFAULT_WINDOW_S = 600.0  # 10-minute sample window
DEFAULT_PROMETHEUS_URL = "http://127.0.0.1:9484/metrics"  # hapax-daimonion exporter
SLO_MIN_PER_MIN = 0.6  # ~1 emission per 90s
SLO_MAX_PER_MIN = 2.5  # ~1 emission per 24s upper bound
DAIMONION_UNIT = "hapax-daimonion.service"
BIAS_ENV = "HAPAX_DAIMONION_BROADCAST_BIAS_ENABLED"


# Exit codes — the operator should be able to read intent from the code
# alone without parsing the report.
EXIT_OK = 0
EXIT_NO_DAIMONION = 10
EXIT_NO_PROGRAMME = 11
EXIT_PROGRAMME_INELIGIBLE = 12
EXIT_AUDIO_UNSAFE = 13
EXIT_BIAS_DISABLED = 14
EXIT_SILENT = 20
EXIT_OUT_OF_BAND = 21
EXIT_TOOLING_ERROR = 30


@dataclasses.dataclass(frozen=True)
class GateStatus:
    """Outcome of a single pre-check gate."""

    name: str
    ok: bool
    detail: str
    exit_code: int = EXIT_OK


@dataclasses.dataclass(frozen=True)
class Emission:
    """One narrative_drive impingement observed in the window."""

    timestamp: float
    strength: float
    programme_role: str | None
    stimmung_stance: str | None


@dataclasses.dataclass(frozen=True)
class CadenceReport:
    """Full sampler output."""

    window_start: float
    window_end: float
    window_s: float
    gates: tuple[GateStatus, ...]
    emissions: tuple[Emission, ...]
    longest_silence_s: float
    emissions_per_min: float
    pressure_p10: float | None
    pressure_p50: float | None
    pressure_p90: float | None
    in_slo: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "window_start": self.window_start,
            "window_end": self.window_end,
            "window_s": self.window_s,
            "gates": [{"name": g.name, "ok": g.ok, "detail": g.detail} for g in self.gates],
            "emissions_count": len(self.emissions),
            "emissions_per_min": round(self.emissions_per_min, 3),
            "longest_silence_s": round(self.longest_silence_s, 1),
            "pressure_p10": self.pressure_p10,
            "pressure_p50": self.pressure_p50,
            "pressure_p90": self.pressure_p90,
            "in_slo": self.in_slo,
            "slo_min_per_min": SLO_MIN_PER_MIN,
            "slo_max_per_min": SLO_MAX_PER_MIN,
        }


def check_daimonion_running() -> GateStatus:
    """Verify hapax-daimonion.service is active under the user manager.

    `systemctl --user is-active <unit>` exits 0 when active; non-zero
    otherwise. We treat the absence of `systemctl` (e.g. on a CI
    container without systemd) as a tooling error rather than a
    daemon-down failure — the harness is for live runtime.
    """
    if shutil.which("systemctl") is None:
        return GateStatus(
            name="daimonion_running",
            ok=False,
            detail="systemctl not on PATH; cannot verify",
            exit_code=EXIT_TOOLING_ERROR,
        )
    result = subprocess.run(
        ["systemctl", "--user", "is-active", DAIMONION_UNIT],
        capture_output=True,
        text=True,
        check=False,
    )
    state = result.stdout.strip() or "unknown"
    if result.returncode == 0:
        return GateStatus(
            name="daimonion_running",
            ok=True,
            detail=f"unit {DAIMONION_UNIT} state={state}",
        )
    return GateStatus(
        name="daimonion_running",
        ok=False,
        detail=f"unit {DAIMONION_UNIT} state={state} (not active)",
        exit_code=EXIT_NO_DAIMONION,
    )


def check_programme_active() -> GateStatus:
    """Verify an ACTIVE programme with broadcast-eligible role exists.

    Reads through the canonical store rather than re-implementing
    role-eligibility — uses the same private set the production
    classifier consults so this harness stays consistent with whatever
    the destination_channel module decides on the next utterance.
    """
    try:
        from agents.hapax_daimonion.cpal.destination_channel import (
            _BROADCAST_ELIGIBLE_ROLES,
        )
        from shared.programme_store import default_store
    except ImportError as exc:
        return GateStatus(
            name="programme_active",
            ok=False,
            detail=f"import failed: {exc}",
            exit_code=EXIT_TOOLING_ERROR,
        )
    try:
        prog = default_store().active_programme()
    except Exception as exc:  # pragma: no cover — depends on filesystem state
        return GateStatus(
            name="programme_active",
            ok=False,
            detail=f"programme store read failed: {exc}",
            exit_code=EXIT_TOOLING_ERROR,
        )
    if prog is None:
        return GateStatus(
            name="programme_active",
            ok=False,
            detail="no programme has status=ACTIVE",
            exit_code=EXIT_NO_PROGRAMME,
        )
    role = getattr(prog.role, "value", str(prog.role))
    if role not in _BROADCAST_ELIGIBLE_ROLES:
        return GateStatus(
            name="programme_active",
            ok=False,
            detail=(
                f"active programme role={role!r} is not broadcast-eligible "
                f"(allowed: {sorted(_BROADCAST_ELIGIBLE_ROLES)})"
            ),
            exit_code=EXIT_PROGRAMME_INELIGIBLE,
        )
    return GateStatus(
        name="programme_active",
        ok=True,
        detail=f"programme={prog.programme_id} role={role}",
    )


def check_audio_safe(path: Path = DEFAULT_AUDIO_SAFE_PATH) -> GateStatus:
    """Verify the canonical audio_safe_for_broadcast state is fresh + safe."""
    try:
        from shared.broadcast_audio_health import (
            DEFAULT_STATE_PATH,
            read_broadcast_audio_health_state,
        )
    except ImportError as exc:
        return GateStatus(
            name="audio_safe",
            ok=False,
            detail=f"import failed: {exc}",
            exit_code=EXIT_TOOLING_ERROR,
        )
    state_path = path if path.exists() else DEFAULT_STATE_PATH
    health = read_broadcast_audio_health_state(state_path)
    if not health.safe:
        codes = [getattr(r, "code", "unknown") for r in health.blocking_reasons]
        return GateStatus(
            name="audio_safe",
            ok=False,
            detail=f"audio_safe=False status={health.status} blockers={codes}",
            exit_code=EXIT_AUDIO_UNSAFE,
        )
    return GateStatus(
        name="audio_safe",
        ok=True,
        detail=f"safe=True status={health.status} freshness_s={health.freshness_s}",
    )


def check_bias_flag() -> GateStatus:
    """Verify HAPAX_DAIMONION_BROADCAST_BIAS_ENABLED is not explicitly off.

    Default is on (unset, empty, or "1"); only the literal "0" disables.
    Mirrors `_is_broadcast_bias_enabled` exactly so this harness reflects
    what the classifier sees on the next call.
    """
    raw = os.environ.get(BIAS_ENV)
    if raw is None or raw.strip() != "0":
        return GateStatus(
            name="bias_enabled",
            ok=True,
            detail=f"{BIAS_ENV}={raw!r} (active)",
        )
    return GateStatus(
        name="bias_enabled",
        ok=False,
        detail=f"{BIAS_ENV}={raw!r} disables the bias path",
        exit_code=EXIT_BIAS_DISABLED,
    )


def collect_emissions(
    impingements_path: Path,
    *,
    window_start: float,
    window_end: float,
) -> tuple[Emission, ...]:
    """Return endogenous.narrative_drive emissions in the window.

    The bus file is append-only JSONL written by
    ``narrative_drive._emit_drive_impingement``. A missing file means the
    bus has never been written this session — equivalent to zero
    emissions. Malformed lines are skipped silently because the bus is
    the daimonion's authoritative log; the harness never owns repair.
    """
    if not impingements_path.exists():
        return ()
    out: list[Emission] = []
    with impingements_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                imp = json.loads(line)
            except json.JSONDecodeError:
                continue
            if imp.get("source") != "endogenous.narrative_drive":
                continue
            ts = imp.get("timestamp")
            if not isinstance(ts, (int, float)):
                continue
            if not (window_start <= float(ts) <= window_end):
                continue
            content = imp.get("content") or {}
            out.append(
                Emission(
                    timestamp=float(ts),
                    strength=float(imp.get("strength") or 0.0),
                    programme_role=content.get("programme_role"),
                    stimmung_stance=content.get("stimmung_stance"),
                )
            )
    return tuple(out)


def longest_silence(
    emissions: Iterable[Emission],
    *,
    window_start: float,
    window_end: float,
) -> float:
    """Largest gap between consecutive emissions, including window edges."""
    timestamps = sorted(e.timestamp for e in emissions)
    if not timestamps:
        return window_end - window_start
    gaps = [timestamps[0] - window_start]
    for prev, curr in zip(timestamps, timestamps[1:], strict=False):
        gaps.append(curr - prev)
    gaps.append(window_end - timestamps[-1])
    return max(gaps)


def percentile(values: list[float], p: float) -> float | None:
    """Linear-interpolation percentile; ``None`` on empty input.

    With a single sample, all percentiles collapse to that sample —
    ``statistics.quantiles`` requires n ≥ 2, so handle the small-N case
    explicitly rather than masking the StatisticsError.
    """
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    return float(statistics.quantiles(values, n=100)[max(0, min(98, int(p) - 1))])


def in_slo(emissions_per_min: float) -> bool:
    return SLO_MIN_PER_MIN <= emissions_per_min <= SLO_MAX_PER_MIN


def build_report(
    *,
    window_s: float,
    impingements_path: Path,
    audio_safe_path: Path,
    skip_pre_checks: bool = False,
) -> CadenceReport:
    """Run gates, sample emissions, return the structured report."""
    if skip_pre_checks:
        gates: tuple[GateStatus, ...] = ()
    else:
        gates = (
            check_daimonion_running(),
            check_programme_active(),
            check_audio_safe(audio_safe_path),
            check_bias_flag(),
        )
    window_end = time.time()
    window_start = window_end - window_s
    emissions = collect_emissions(
        impingements_path,
        window_start=window_start,
        window_end=window_end,
    )
    pressures = [e.strength for e in emissions]
    epm = (len(emissions) / window_s) * 60.0 if window_s > 0 else 0.0
    return CadenceReport(
        window_start=window_start,
        window_end=window_end,
        window_s=window_s,
        gates=gates,
        emissions=emissions,
        longest_silence_s=longest_silence(
            emissions, window_start=window_start, window_end=window_end
        ),
        emissions_per_min=epm,
        pressure_p10=percentile(pressures, 10),
        pressure_p50=percentile(pressures, 50),
        pressure_p90=percentile(pressures, 90),
        in_slo=in_slo(epm),
    )


def render_text(report: CadenceReport) -> str:
    """Operator-facing plaintext summary."""
    lines: list[str] = []
    lines.append("=== Vocal cadence verification ===")
    lines.append(
        f"window: {report.window_s:.0f}s "
        f"({time.strftime('%H:%M:%S', time.localtime(report.window_start))} → "
        f"{time.strftime('%H:%M:%S', time.localtime(report.window_end))})"
    )
    lines.append("")
    if report.gates:
        lines.append("Pre-checks:")
        for g in report.gates:
            mark = "OK " if g.ok else "FAIL"
            lines.append(f"  [{mark}] {g.name}: {g.detail}")
        lines.append("")
    lines.append(f"Emissions: {len(report.emissions)}")
    lines.append(f"  per minute: {report.emissions_per_min:.2f}")
    lines.append(
        f"  SLO band: [{SLO_MIN_PER_MIN:.2f}, {SLO_MAX_PER_MIN:.2f}] "
        f"({'in band' if report.in_slo else 'OUT OF BAND'})"
    )
    lines.append(f"  longest silence: {report.longest_silence_s:.1f}s")
    if report.pressure_p50 is not None:
        lines.append(
            f"  pressure p10/p50/p90: "
            f"{report.pressure_p10:.3f} / "
            f"{report.pressure_p50:.3f} / "
            f"{report.pressure_p90:.3f}"
        )
    return "\n".join(lines)


def select_exit_code(report: CadenceReport) -> int:
    """Pick a single non-zero code from the first failing gate, else SLO."""
    for g in report.gates:
        if not g.ok:
            return g.exit_code
    if not report.emissions:
        return EXIT_SILENT
    if not report.in_slo:
        return EXIT_OUT_OF_BAND
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--window-s",
        type=float,
        default=DEFAULT_WINDOW_S,
        help="sample window length in seconds (default 600)",
    )
    parser.add_argument(
        "--impingements-path",
        type=Path,
        default=DEFAULT_IMPINGEMENTS_PATH,
        help=f"impingements.jsonl path (default {DEFAULT_IMPINGEMENTS_PATH})",
    )
    parser.add_argument(
        "--audio-safe-path",
        type=Path,
        default=DEFAULT_AUDIO_SAFE_PATH,
        help=f"audio-safe-for-broadcast.json path (default {DEFAULT_AUDIO_SAFE_PATH})",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="emit JSON only (one line, suitable for piping to jq / Loki / Grafana)",
    )
    parser.add_argument(
        "--skip-pre-checks",
        action="store_true",
        help="skip gates and only sample (useful for offline analysis of recorded bus)",
    )
    args = parser.parse_args(argv)

    report = build_report(
        window_s=args.window_s,
        impingements_path=args.impingements_path,
        audio_safe_path=args.audio_safe_path,
        skip_pre_checks=args.skip_pre_checks,
    )

    if args.json_only:
        print(json.dumps(report.to_json()))
    else:
        print(render_text(report))
        print()
        print(json.dumps(report.to_json()))

    return select_exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
