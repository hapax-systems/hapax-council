"""shared/sdlc_pressure_gate.py — L3 PSI-feedback admission gate for the SDLC fleet.

The fleet (Claude/Codex/Gemini/Vibe lanes + their git/pytest/cargo grandchildren)
runs in ``hapax-sdlc.slice`` at ``CPUWeight=idle``. That elastic baseline yields
to every non-idle peer but always *completes*. This module adds **burst control**
on top of it: under sustained CPU pressure it tells dispatchers and respawn floors
to QUEUE — pace (slow) or pause (block-and-wait) — never DROP. It slows the fleet;
it never degrades it (no skipped agents / tests / research, just serialized waves).

Three load-bearing signals (a model-profile router is a red herring for CPU):
  - ``/proc/pressure/cpu`` ``some avg10``  — the responsive burst signal
  - ``/proc/loadavg`` load-per-core        — sustained saturation
  - ``hapax-team-load`` classify (opt-in)  — team-vs-operational accounting +
    fortress tightening (reused verbatim, so going fortress auto-hard-paces)

States ``open`` < ``paced`` < ``closed``. Hysteresis (separate enter/exit
thresholds) plus a per-state min-dwell stop it flapping between states.

CLI (for the bash respawn floors): ``python3 -m shared.sdlc_pressure_gate --state``
prints the word and exits 0/1/2 for open/paced/closed.
"""

from __future__ import annotations

import functools
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

SDLC_SLICE = "hapax-sdlc.slice"
_DETECT = "\x00detect"  # sentinel: auto-detect systemd-run on PATH

STATES: tuple[str, ...] = ("open", "paced", "closed")
_SEVERITY: dict[str, int] = {"open": 0, "paced": 1, "closed": 2}

# Per-state minimum dwell (seconds) before the gate may RELAX. Escalation is
# always immediate — we tighten fast, loosen slow.
MIN_DWELL_S: dict[str, float] = {"open": 0.0, "paced": 15.0, "closed": 20.0}


@dataclass(frozen=True)
class PsiReading:
    some_avg10: float
    some_avg60: float


@dataclass(frozen=True)
class PressureReading:
    psi_some_avg10: float
    psi_some_avg60: float
    load_per_core: float
    working_mode: str
    team_level: str | None = None


@dataclass(frozen=True)
class GateState:
    state: str
    since: float


@dataclass(frozen=True)
class AdmissionDecision:
    state: str
    reasons: list[str] = field(default_factory=list)
    reading: PressureReading | None = None
    dwell_remaining_s: float = 0.0
    changed: bool = False


# ── Thresholds ───────────────────────────────────────────────────────────────
# Each signal carries (paced_enter, paced_exit, closed_enter, closed_exit).
# enter > exit gives the hysteresis band. Research/rnd mirror hapax-team-load's
# load bands (yellow 1.5 / red 3.0); fortress tightens both, so the operator
# going fortress auto-hard-paces the fleet with zero extra plumbing.
_THRESHOLDS: dict[str, dict[str, tuple[float, float, float, float]]] = {
    "research": {
        "psi": (35.0, 20.0, 65.0, 45.0),
        "load": (1.5, 1.2, 3.0, 2.5),
    },
    "fortress": {
        "psi": (20.0, 12.0, 40.0, 28.0),
        "load": (1.0, 0.8, 2.0, 1.6),
    },
}


def thresholds(mode: str) -> dict[str, tuple[float, float, float, float]]:
    """Threshold table for ``mode`` (fortress tightens; rnd aliases research)."""
    return _THRESHOLDS.get(mode, _THRESHOLDS["research"])


# ── Pure signal parsing ──────────────────────────────────────────────────────


def parse_psi_some(text: str) -> PsiReading:
    """Parse the ``some`` line of ``/proc/pressure/cpu``."""
    avg10 = avg60 = 0.0
    for line in text.splitlines():
        if not line.startswith("some"):
            continue
        m10 = re.search(r"avg10=([0-9.]+)", line)
        m60 = re.search(r"avg60=([0-9.]+)", line)
        if m10:
            avg10 = float(m10.group(1))
        if m60:
            avg60 = float(m60.group(1))
        break
    return PsiReading(some_avg10=avg10, some_avg60=avg60)


def read_psi(path: str | os.PathLike[str] = "/proc/pressure/cpu") -> PsiReading:
    try:
        return parse_psi_some(Path(path).read_text())
    except OSError:
        return PsiReading(0.0, 0.0)


def read_load_per_core(path: str | os.PathLike[str] = "/proc/loadavg") -> float:
    try:
        load_1 = float(Path(path).read_text().split()[0])
        return load_1 / max(os.cpu_count() or 1, 1)
    except (OSError, ValueError, IndexError):
        return 0.0


def read_working_mode() -> str:
    try:
        return (Path.home() / ".cache" / "hapax" / "working-mode").read_text().strip() or "research"
    except OSError:
        return "research"


def read_team_level(repo_root: Path | None = None, timeout_s: float = 4.0) -> str | None:
    """Best-effort team-load classification (reuses scripts/hapax-team-load).

    Returns the classifier level (green/yellow/red/ops-distress) or ``None`` if
    team-load is unavailable/slow — the gate never blocks on this opt-in signal.
    """
    root = repo_root or Path(__file__).resolve().parents[1]
    script = root / "scripts" / "hapax-team-load"
    if not script.is_file():
        return None
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--json", "--no-color"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if proc.returncode not in (0, 1, 2):
            return None
        return str(json.loads(proc.stdout).get("status")) or None
    except (subprocess.SubprocessError, OSError, ValueError):
        return None


# ── Pure decision ────────────────────────────────────────────────────────────


def _team_severity(level: str | None) -> int:
    if level in ("red", "ops-distress"):
        return _SEVERITY["closed"]
    if level == "yellow":
        return _SEVERITY["paced"]
    return _SEVERITY["open"]


def _signal_severity(
    value: float, band: tuple[float, float, float, float], *, by_enter: bool
) -> int:
    """Severity a single numeric signal demands, via ENTER or EXIT thresholds."""
    paced_enter, paced_exit, closed_enter, closed_exit = band
    closed_t, paced_t = (closed_enter, paced_enter) if by_enter else (closed_exit, paced_exit)
    if value >= closed_t:
        return _SEVERITY["closed"]
    if value >= paced_t:
        return _SEVERITY["paced"]
    return _SEVERITY["open"]


def decide(reading: PressureReading, prev: GateState | None, now: float) -> GateState:
    """Pure hysteresis + min-dwell state machine. No IO.

    - ``demand_enter``: the worst state any signal pushes UP to (enter thresholds).
    - ``demand_hold``:  the worst state any signal still HOLDS (exit thresholds).
    Escalate to ``demand_enter`` immediately; relax to ``demand_hold`` only once
    the prior state's min-dwell has elapsed. Between exit and enter we hold.
    """
    band = thresholds(reading.working_mode)
    prev_state = prev.state if prev is not None else "open"
    prev_since = prev.since if prev is not None else now

    demand_enter = max(
        _signal_severity(reading.psi_some_avg10, band["psi"], by_enter=True),
        _signal_severity(reading.load_per_core, band["load"], by_enter=True),
        _team_severity(reading.team_level),
    )
    demand_hold = max(
        _signal_severity(reading.psi_some_avg10, band["psi"], by_enter=False),
        _signal_severity(reading.load_per_core, band["load"], by_enter=False),
        _team_severity(reading.team_level),
    )
    prev_sev = _SEVERITY[prev_state]

    if demand_enter > prev_sev:  # escalate — immediate, ignore dwell
        return GateState(STATES[demand_enter], now)

    dwell_ok = (now - prev_since) >= MIN_DWELL_S[prev_state]
    if demand_hold < prev_sev and dwell_ok:  # relax — only after min-dwell
        return GateState(STATES[demand_hold], now)

    return GateState(prev_state, prev_since)  # hold (band or dwell)


# ── Live wrapper ─────────────────────────────────────────────────────────────


def default_state_path() -> Path:
    base = Path("/dev/shm/hapax/sdlc-pressure")
    try:
        base.mkdir(parents=True, exist_ok=True)
        return base / "state.json"
    except OSError:
        fallback = Path.home() / ".cache" / "hapax" / "sdlc-pressure"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback / "state.json"


def _load_state(state_path: Path) -> GateState | None:
    try:
        data = json.loads(state_path.read_text())
        state = str(data["state"])
        if state in STATES:
            return GateState(state, float(data.get("since", 0.0)))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def _store_state(state_path: Path, state: GateState) -> None:
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = state_path.with_suffix(state_path.suffix + ".tmp")
        tmp.write_text(json.dumps({"state": state.state, "since": state.since}))
        tmp.replace(state_path)
    except OSError:
        pass


def _reasons(reading: PressureReading, state: str) -> list[str]:
    band = thresholds(reading.working_mode)
    out: list[str] = []
    out.append(f"psi.cpu.some.avg10={reading.psi_some_avg10:.0f}% (mode={reading.working_mode})")
    out.append(f"load/core={reading.load_per_core:.2f}")
    if reading.team_level:
        out.append(f"team-load={reading.team_level}")
    if state == "open":
        out.append("headroom — dispatch freely")
    elif state == "paced":
        out.append(f"paced: throttle dispatch (psi enter {band['psi'][0]:.0f}%)")
    else:
        out.append("closed: block-and-wait — queue, never drop")
    return out


def admission_state(
    now: float | None = None,
    *,
    reading: PressureReading | None = None,
    state_path: Path | None = None,
    fold_team_load: bool = False,
) -> AdmissionDecision:
    """Read pressure, apply hysteresis+dwell against persisted state, return a decision."""
    if os.environ.get("HAPAX_SDLC_PRESSURE_GATE_OFF", "").strip().lower() in ("1", "true", "yes"):
        return AdmissionDecision(
            state="open", reasons=["gate disabled via HAPAX_SDLC_PRESSURE_GATE_OFF"]
        )

    now = time.time() if now is None else now
    path = state_path if state_path is not None else default_state_path()

    if reading is None:
        psi = read_psi()
        team = read_team_level() if fold_team_load else None
        reading = PressureReading(
            psi_some_avg10=psi.some_avg10,
            psi_some_avg60=psi.some_avg60,
            load_per_core=read_load_per_core(),
            working_mode=read_working_mode(),
            team_level=team,
        )

    prev = _load_state(path)
    new = decide(reading, prev, now)
    _store_state(path, new)

    dwell_remaining = max(0.0, MIN_DWELL_S[new.state] - (now - new.since))
    changed = prev is None or prev.state != new.state
    return AdmissionDecision(
        state=new.state,
        reasons=_reasons(reading, new.state),
        reading=reading,
        dwell_remaining_s=dwell_remaining,
        changed=changed,
    )


# ── Wave governor ────────────────────────────────────────────────────────────


def run_in_waves(
    items: Iterable[object],
    wave_size: int,
    *,
    is_open: Callable[[], bool],
    sleep: Callable[[float], None],
    poll_interval: float = 2.0,
    max_wait_s: float | None = None,
) -> Iterator[list[object]]:
    """Yield ``items`` in waves of ``wave_size``, waiting before each wave while
    admission is closed. Every item is eventually yielded — queued, never dropped
    (even if ``max_wait_s`` is hit, the wave still proceeds). This is the Workflow
    fan-out governor: spawn N, await reopen, spawn next — all N still run.
    """
    if wave_size < 1:
        raise ValueError("wave_size must be >= 1")

    def _await_open() -> None:
        waited = 0.0
        while not is_open():
            sleep(poll_interval)
            waited += poll_interval
            if max_wait_s is not None and waited >= max_wait_s:
                return  # never drop — proceed after the cap

    batch: list[object] = []
    for item in items:
        batch.append(item)
        if len(batch) >= wave_size:
            _await_open()
            yield batch
            batch = []
    if batch:
        _await_open()
        yield batch


# ── L1 attachment: wrap a lane launch into hapax-sdlc.slice ──────────────────


@functools.cache
def _slice_available_cached(systemd_run: str) -> bool:
    try:
        proc = subprocess.run(
            [systemd_run, "--user", "--scope", "--quiet", f"--slice={SDLC_SLICE}", "--", "true"],
            capture_output=True,
            timeout=10,
        )
        return proc.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def sdlc_slice_available(systemd_run: str | None = None) -> bool:
    """Preflight: can we actually create a scope in hapax-sdlc.slice? Cached."""
    systemd_run = systemd_run or shutil.which("systemd-run")
    if not systemd_run:
        return False
    return _slice_available_cached(systemd_run)


def sdlc_slice_wrap(
    argv: Iterable[str],
    *,
    already_attached: bool | None = None,
    systemd_run: str | None = _DETECT,
    slice_available: bool | None = None,
    setenv: Mapping[str, str] | None = None,
) -> list[str]:
    """Prefix ``argv`` with ``systemd-run --user --scope --slice=hapax-sdlc.slice``
    so the launched lane AND its git/pytest/cargo grandchildren inherit cpu.idle +
    the cpuset fence. No-op (run un-sliced) when already attached, when systemd-run
    is missing, or when the slice can't be created — dispatch must never hard-fail
    on the fence. Pass the keyword args to inject for tests."""
    argv = list(argv)
    if already_attached is None:
        already_attached = os.environ.get("HAPAX_SDLC_SLICE_ATTACHED") == "1"
    if already_attached:
        return argv
    if systemd_run == _DETECT:
        systemd_run = shutil.which("systemd-run")
    if not systemd_run:
        return argv
    if slice_available is None:
        slice_available = sdlc_slice_available(systemd_run)
    if not slice_available:
        return argv
    setenv_args = [f"--setenv={key}={value}" for key, value in sorted((setenv or {}).items())]
    return [
        systemd_run,
        "--user",
        "--scope",
        "--quiet",
        f"--slice={SDLC_SLICE}",
        *setenv_args,
        "--",
        *argv,
    ]


# ── L3 chokepoint: block-and-wait while closed (queue, never drop) ───────────


def wait_until_admitted(
    admission_fn: Callable[[], AdmissionDecision],
    *,
    sleep: Callable[[float], None],
    on_delay: Callable[[AdmissionDecision], None] | None = None,
    poll_interval: float = 5.0,
    max_wait_s: float | None = None,
) -> AdmissionDecision:
    """Block while admission is ``closed``, invoking ``on_delay`` each poll (to
    refresh a DELAYED receipt). Returns once the gate is open/paced — or after
    ``max_wait_s`` so the dispatch is QUEUED then RUN, never dropped."""
    waited = 0.0
    decision = admission_fn()
    while decision.state == "closed":
        if on_delay is not None:
            on_delay(decision)
        sleep(poll_interval)
        waited += poll_interval
        if max_wait_s is not None and waited >= max_wait_s:
            break
        decision = admission_fn()
    return decision


# ── CLI (bash respawn floors) ────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    want_state = "--state" in argv
    decision = admission_state(fold_team_load="--team" in argv)
    if want_state:
        print(decision.state)
    else:
        print(
            json.dumps(
                {
                    "state": decision.state,
                    "reasons": decision.reasons,
                    "dwell_remaining_s": round(decision.dwell_remaining_s, 1),
                    "changed": decision.changed,
                }
            )
        )
    return _SEVERITY[decision.state]


if __name__ == "__main__":
    raise SystemExit(main())
