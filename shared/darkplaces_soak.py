"""Renderer suitability soak gate for the DarkPlaces/Screwm visual substrate.

After the 2026-05-23 AMD data-fabric sync-flood host hard-reset, the DarkPlaces
GL renderer is attended-only (docs/audits/2026-05-23-screwm-quake-runtime-reset-
containment.md). This module is the *testable core* of the 1-hour crash-free soak
that must PASS before the renderer may be promoted behind the persistent
``~/.config/hapax/enable-darkplaces-runtime`` gate.

The orchestrator (``scripts/darkplaces-soak.sh``) launches the renderer under a
single-command ``HAPAX_DARKPLACES_RUNTIME_ACK=1`` (so containment stays intact if
the soak aborts) and feeds per-second :class:`SoakObservation` samples to a
:class:`SoakEvaluator`. The evaluator fails CLOSED on the first hardware-risk
signal — a single data-fabric/Xid line is an instant FAIL, no tolerance — and
returns PASS only after the full soak duration with zero faults.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

# The instant-FAIL hardware-risk subset — kept identical to the exit-2 check in
# scripts/darkplaces-attended-smoke.sh so the soak and the smoke agree on what
# counts as a host-reset-class signal.
_HARDWARE_RISK_RE = re.compile(
    r"data fabric|sync flood|NVRM: Xid|GPU has fallen off|hardware error|fatal",
    re.IGNORECASE,
)


def is_hardware_risk_line(line: str) -> bool:
    """True if a kernel log line is a host-reset-class hardware-risk signal."""
    return bool(_HARDWARE_RISK_RE.search(line))


@dataclass
class SoakCriteria:
    """Pass/fail thresholds for a renderer soak run."""

    soak_duration_s: float = 3600.0
    expected_gl_renderer: str = ""
    max_frame_age_s: float = 5.0
    temp_fail_c: float = 90.0
    vram_limit_mib: int | None = None


@dataclass
class SoakObservation:
    """One per-second sample of renderer + GPU health during a soak."""

    t: float
    renderer_alive: bool
    feeder_alive: bool
    gl_renderer: str
    frame_age_s: float
    vram_used_mib: int
    gpu_temp_c: float
    kernel_risk_lines: list[str] = field(default_factory=list)


@dataclass
class SoakEvaluator:
    """Accumulate observations and produce a terminal PASS/FAIL verdict.

    Fail-closed: any fault recorded is permanent. ``verdict`` returns ``"fail"``
    the moment a fault exists, ``"pass"`` only once the soak duration is reached
    with zero faults, and ``"running"`` otherwise.
    """

    criteria: SoakCriteria
    started_at: float
    faults: list[str] = field(default_factory=list)

    def record(self, obs: SoakObservation) -> None:
        c = self.criteria
        tag = f"t={obs.t:.0f}s"
        for line in obs.kernel_risk_lines:
            self.faults.append(f"hardware-risk kernel line at {tag}: {line.strip()}")
        if not obs.renderer_alive:
            self.faults.append(f"renderer process not alive at {tag}")
        if not obs.feeder_alive:
            self.faults.append(f"feeder (Xorg/Xvfb) not alive at {tag}")
        if c.expected_gl_renderer and c.expected_gl_renderer not in obs.gl_renderer:
            self.faults.append(
                f"GL_RENDERER mismatch at {tag}: observed {obs.gl_renderer!r}, "
                f"expected substring {c.expected_gl_renderer!r} (GPU re-selection)"
            )
        if obs.frame_age_s > c.max_frame_age_s:
            self.faults.append(
                f"frame production stalled at {tag}: frame age {obs.frame_age_s:.1f}s "
                f"> max {c.max_frame_age_s:.1f}s"
            )
        if obs.gpu_temp_c >= c.temp_fail_c:
            self.faults.append(
                f"GPU temperature over threshold at {tag}: "
                f"{obs.gpu_temp_c:.0f}C >= {c.temp_fail_c:.0f}C"
            )
        if c.vram_limit_mib is not None and obs.vram_used_mib > c.vram_limit_mib:
            self.faults.append(
                f"VRAM over limit at {tag}: {obs.vram_used_mib} MiB > {c.vram_limit_mib} MiB"
            )

    def verdict(self, now: float) -> tuple[str, list[str]]:
        if self.faults:
            return "fail", list(self.faults)
        if now - self.started_at >= self.criteria.soak_duration_s:
            return "pass", []
        return "running", []


def hardware_fingerprint(gl_renderer: str, driver_version: str, pci_bus_id: str) -> str:
    """Stable identity of the GPU the soak passed under.

    Deliberately EXCLUDES boot-id: a clean reboot does not invalidate a hardware
    suitability pass, but a GPU swap, GL re-selection, or driver upgrade MUST.
    """
    norm = "|".join(part.strip() for part in (gl_renderer, driver_version, pci_bus_id))
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


@dataclass
class SoakReceipt:
    """Signed-by-evidence record of a soak run, written to the run dir.

    A PASS receipt authorizes :func:`promote_decision` to create the persistent
    ``enable-darkplaces-runtime`` gate — but only while fresh and matching the
    current hardware fingerprint. ``end_marker`` is written last; its absence
    means the soak was killed mid-write (e.g. a host reset) and the pass cannot
    be trusted.
    """

    status: str
    fingerprint: str
    boot_id: str
    gl_renderer: str
    driver_version: str
    pci_bus_id: str
    started_at: float
    ended_at: float
    soak_duration_s: float
    reasons: list[str] = field(default_factory=list)
    end_marker: bool = False


def write_receipt(run_dir: Path, receipt: SoakReceipt) -> Path:
    """Atomically write ``receipt.json`` into ``run_dir`` and return its path."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "receipt.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(receipt), indent=2))
    tmp.rename(path)
    return path


def read_receipt(path: Path) -> SoakReceipt:
    """Load a :class:`SoakReceipt` from a ``receipt.json`` path."""
    data = json.loads(Path(path).read_text())
    return SoakReceipt(**data)


def promote_decision(
    receipt: SoakReceipt | None,
    current_fingerprint: str,
    now: float,
    max_age_s: float,
) -> tuple[bool, str]:
    """Decide whether a soak receipt authorizes creating the persistent gate.

    Fail-closed: refuse on a missing/FAIL/incomplete/mismatched/stale receipt.
    """
    if receipt is None:
        return False, "no PASS receipt found — run the soak first"
    if receipt.status != "pass":
        return False, f"receipt status is {receipt.status!r}, not 'pass' — re-run the soak"
    if not receipt.end_marker:
        return False, (
            "receipt has no END marker — soak was incomplete "
            "(possible mid-write host reset); re-run the soak"
        )
    if receipt.fingerprint != current_fingerprint:
        return False, "hardware/driver fingerprint changed since the pass — re-run the soak"
    age = now - receipt.ended_at
    if age > max_age_s:
        return (
            False,
            f"PASS receipt is stale (age {age:.0f}s > max {max_age_s:.0f}s) — re-run the soak",
        )
    return True, "fresh matching PASS receipt"
