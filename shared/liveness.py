"""shared/liveness.py — the unified liveness + recovery substrate.

The entire SDLC reform wave has been fixing instances of ONE class: a
long-running operation enters an intermediate state, has no liveness signal, no
staleness watchdog, and no automatic recovery, so it sits wedged until a human
intervenes (deploy froze silently #3840; armed PRs stranded #3849; output-stalled
lanes #3852; …). Each was patched with its own bespoke loop, state files and
bound. This module is the shared contract so the *next* stuck-state surface gets
liveness by **registering**, not by writing yet another watchdog.

Three composable parts (design: docs/superpowers/specs/
2026-06-03-liveness-recovery-substrate-design.md):

1. **Heartbeat** — an op writes ``<op_id>.beat`` (``{op_id, ts, token, meta}``)
   to a canonical dir. ``ts`` is the last-progress time; ``token`` is a *monotonic
   progress token* that separates *stalled* (silent AND token unmoved) from
   *legitimately long-quiet* (token advanced ⇒ progressing — never recover it).
2. **Registry** — an op declares a :class:`LivenessSpec` (``op_id``,
   ``recovery_cmd`` argv, ``max_quiet_s`` or measured tau, optional ``lineage``).
   It carries **no bound** — every limit is the shared governor's.
3. **Watchdog** — :meth:`LivenessWatchdog.scan` reads every registered op's beat,
   classifies it, and for a confirmed stall routes the recovery through the shared
   :class:`~shared.recovery_governor.RecoveryGovernor` (the one bounding +
   pressure-gate + escalation engine), executes the declared ``recovery_cmd``,
   records the outcome, and ledgers a ``recovery-action`` ``CoordEvent``.

NEVER-FREEZE: the substrate can only *slow* recovery (via the governor), never
halt it; a progressing op (token advancing) is never recovered.

CLI::
    python -m shared.liveness --beat lane:epsilon:progress --token 4213
    python -m shared.liveness --scan        # the unified watchdog tick (timer)
    python -m shared.liveness --list
"""

from __future__ import annotations

import dataclasses
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# ── verdict statuses ──────────────────────────────────────────────────────────

ALIVE = "alive"  # progress token advanced since last scan → never recover
QUIET = "quiet"  # token unchanged but within max_quiet → within budget
STALLED = "stalled"  # token unchanged AND quiet past threshold → recover
MISSING = "missing"  # no heartbeat (never-started / torn down)

AUTHORITY_CASE = "CASE-SDLC-REFORM-001"


def _liveness_root() -> Path:
    return Path.home() / ".cache" / "hapax" / "liveness"


def _default_beat_dir() -> Path:
    return _liveness_root() / "beats"


def _default_registry_dir() -> Path:
    return _liveness_root() / "registry"


def _default_scan_state_path() -> Path:
    return _liveness_root() / "scan-state.json"


def _sanitize(op_id: str) -> str:
    """A filename-safe slug for an ``op_id`` (``lane:epsilon:progress`` →
    ``lane_epsilon_progress``). Collapses any non ``[A-Za-z0-9._-]`` run so a
    ``/`` in an op_id can never traverse out of the beat/registry dir."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", op_id).strip("_") or "op"


def _iso_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


# ── 1. Heartbeat ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Heartbeat:
    """One progress signal emitted by an operation."""

    op_id: str
    ts: float
    token: str
    meta: dict = field(default_factory=dict)


def emit_heartbeat(
    op_id: str,
    token: str | int,
    *,
    ts: float | None = None,
    meta: dict | None = None,
    beat_dir: Path | None = None,
) -> Path:
    """Write ``op_id``'s heartbeat atomically. ``token`` is coerced to ``str`` so
    a caller may pass a line count / byte offset / sequence directly."""
    beat_dir = Path(beat_dir) if beat_dir is not None else _default_beat_dir()
    ts = time.time() if ts is None else ts
    path = beat_dir / f"{_sanitize(op_id)}.beat"
    payload = {"op_id": op_id, "ts": float(ts), "token": str(token), "meta": meta or {}}
    _atomic_write(path, json.dumps(payload))
    return path


def read_heartbeat(op_id: str, *, beat_dir: Path | None = None) -> Heartbeat | None:
    """Read ``op_id``'s heartbeat, or ``None`` if absent/corrupt."""
    beat_dir = Path(beat_dir) if beat_dir is not None else _default_beat_dir()
    path = beat_dir / f"{_sanitize(op_id)}.beat"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        return Heartbeat(
            op_id=str(data["op_id"]),
            ts=float(data["ts"]),
            token=str(data["token"]),
            meta=dict(data.get("meta") or {}),
        )
    except (KeyError, TypeError, ValueError):
        return None


# ── 2. Registry ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LivenessSpec:
    """An operation's liveness declaration.

    No ``max_attempts``/backoff knobs live here — bounding is entirely the shared
    :class:`RecoveryGovernor`'s, so a surface can never drift its own bound from
    the fleet's. ``recovery_cmd`` is an argv (not an in-process callable) because
    the surfaces are independent processes/timers.
    """

    op_id: str
    recovery_cmd: list[str]
    max_quiet_s: float | None = None  # None ⇒ measured tau via dispatch_service_time
    lineage: str | None = None  # tau lookup + governor target grouping
    critical: bool = False  # routes to the governor critical reserve
    recover_when_missing: bool = False
    description: str = ""


def register(spec: LivenessSpec, *, registry_dir: Path | None = None) -> Path:
    """Persist ``spec`` to the registry (one JSON per op_id; idempotent)."""
    registry_dir = Path(registry_dir) if registry_dir is not None else _default_registry_dir()
    path = registry_dir / f"{_sanitize(spec.op_id)}.json"
    _atomic_write(path, json.dumps(dataclasses.asdict(spec)))
    return path


def load_registry(*, registry_dir: Path | None = None) -> list[LivenessSpec]:
    """Load every registered :class:`LivenessSpec` (sorted by op_id), skipping any
    corrupt/unparseable entry rather than failing the whole scan."""
    registry_dir = Path(registry_dir) if registry_dir is not None else _default_registry_dir()
    if not registry_dir.exists():
        return []
    known = {f.name for f in dataclasses.fields(LivenessSpec)}
    out: list[LivenessSpec] = []
    for entry in sorted(registry_dir.glob("*.json")):
        try:
            data = json.loads(entry.read_text(encoding="utf-8"))
            out.append(LivenessSpec(**{k: v for k, v in data.items() if k in known}))
        except (OSError, ValueError, TypeError):
            continue
    return out


# ── 3. Classification (pure: progress-token, not wall-clock) ─────────────────


@dataclass(frozen=True)
class LivenessVerdict:
    op_id: str
    status: str
    quiet_s: float
    threshold_s: float
    token: str | None


def classify(
    spec: LivenessSpec,
    heartbeat: Heartbeat | None,
    *,
    prev_token: str | None,
    now: float,
    threshold_s: float,
) -> LivenessVerdict:
    """Stalled-vs-quiet-vs-alive, deciding on the *progress token* first.

    A token that advanced since the previous scan means the op did work between
    scans → ``alive``, regardless of how long its beat looks quiet (the Gittins
    move: rank by silence-against-hazard, never raw wall-clock). On the first scan
    (no ``prev_token``) only the beat age is available, so a beat already stale
    past ``threshold_s`` is ``stalled``.
    """
    if heartbeat is None:
        return LivenessVerdict(spec.op_id, MISSING, 0.0, threshold_s, None)
    advanced = prev_token is not None and heartbeat.token != prev_token
    quiet_s = now - heartbeat.ts
    if advanced:
        status = ALIVE
    elif quiet_s <= threshold_s:
        status = QUIET
    else:
        status = STALLED
    return LivenessVerdict(spec.op_id, status, quiet_s, threshold_s, heartbeat.token)


# ── default collaborators (prod; tests inject) ───────────────────────────────


def _default_exec(cmd: list[str], *, timeout_s: float = 120.0) -> bool:
    """Run a recovery argv; True iff it exits 0. Bounded by a timeout; any
    failure is False (the governor then counts it as a failed attempt)."""
    try:
        return subprocess.run(cmd, timeout=timeout_s).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _default_tau(lineage: str | None) -> float:
    """Measured per-lineage progress-timeout from ``dispatch_service_time``. Falls
    back to the 1800s floor (the safe, less-aggressive bound) if the fold fails."""
    try:
        from shared.dispatch_service_time import load_service_time_distribution, tau_for_lineage

        return tau_for_lineage(load_service_time_distribution(), lineage or "")
    except Exception:
        return 1800.0


def _default_ledger(event: dict) -> None:
    """Append a ``recovery-action`` :class:`CoordEvent` to the coord ledger
    (daemon writer, fail-open spool). Best-effort: a ledger failure must never
    break recovery, so any error falls back to a local JSONL."""
    try:
        from shared.coord_event_log import CoordEvent, CoordEventLog, CoordWriter

        ev = CoordEvent(
            event_id=event["event_id"],
            timestamp=event["ts"],
            event_type=event.get("event_type", "recovery-action"),
            actor=event["op_id"],
            subject=str(event.get("lineage") or event["op_id"]),
            authority_case=AUTHORITY_CASE,
            payload=event,
        )
        CoordEventLog().append(ev, writer=CoordWriter.daemon("hapax-liveness"), fail_open=True)
    except Exception:
        try:
            path = _liveness_root() / "recovery-ledger.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event) + "\n")
        except OSError:
            pass


# ── Watchdog (the one scan that replaces N bespoke loops) ────────────────────


@dataclass(frozen=True)
class ScanResult:
    op_id: str
    status: str
    recovered: bool
    permit_reason: str
    quiet_s: float


class LivenessWatchdog:
    """Scans every registered op once per tick and drives bounded recovery.

    All collaborators are injectable so the decision path is deterministic under
    test and fail-open in prod. ``governor`` is the shared RecoveryGovernor — the
    watchdog owns *when/whether* to recover; the governor owns *how-bounded*
    (AIMD backoff, token bucket, concurrency cap, PSI throttle, escalation).
    """

    def __init__(
        self,
        *,
        governor,
        registry_dir: Path | None = None,
        beat_dir: Path | None = None,
        scan_state_path: Path | None = None,
        now_fn=time.time,
        exec_fn=None,
        ledger_fn=None,
        tau_fn=None,
    ) -> None:
        self._governor = governor
        self._registry_dir = (
            Path(registry_dir) if registry_dir is not None else _default_registry_dir()
        )
        self._beat_dir = Path(beat_dir) if beat_dir is not None else _default_beat_dir()
        self._scan_state_path = (
            Path(scan_state_path) if scan_state_path is not None else _default_scan_state_path()
        )
        self._now_fn = now_fn
        self._exec_fn = exec_fn or _default_exec
        self._ledger_fn = ledger_fn or _default_ledger
        self._tau_fn = tau_fn or _default_tau

    def scan(self) -> list[ScanResult]:
        specs = load_registry(registry_dir=self._registry_dir)
        prev = self._load_scan_state()
        now = self._now_fn()
        new_tokens: dict[str, str] = {}
        results: list[ScanResult] = []

        for spec in specs:
            hb = read_heartbeat(spec.op_id, beat_dir=self._beat_dir)
            if hb is not None:
                new_tokens[spec.op_id] = hb.token
            threshold = (
                spec.max_quiet_s
                if spec.max_quiet_s is not None
                else float(self._tau_fn(spec.lineage))
            )
            verdict = classify(
                spec, hb, prev_token=prev.get(spec.op_id), now=now, threshold_s=threshold
            )
            recovered, reason = self._maybe_recover(spec, verdict, now)
            results.append(
                ScanResult(spec.op_id, verdict.status, recovered, reason, verdict.quiet_s)
            )

        self._store_scan_state(new_tokens)
        return results

    def _maybe_recover(self, spec: LivenessSpec, verdict: LivenessVerdict, now: float):
        recover = verdict.status == STALLED or (
            verdict.status == MISSING and spec.recover_when_missing
        )
        if not recover:
            return False, ""
        target_id = spec.lineage or spec.op_id
        grant = self._governor.permit(target_id, critical=spec.critical, now=now)
        if not grant.permitted:
            return False, grant.reason
        ok = bool(self._exec_fn(list(spec.recovery_cmd)))
        self._governor.record_outcome(target_id, ok, now=now)
        self._ledger_fn(self._build_event(spec, verdict, ok))
        return ok, grant.reason

    def _build_event(self, spec: LivenessSpec, verdict: LivenessVerdict, ok: bool) -> dict:
        iso = _iso_now()
        return {
            "event_id": f"liveness-recovery-{_sanitize(spec.op_id)}-{iso}-{'ok' if ok else 'fail'}",
            "event_type": "recovery-action",
            "op_id": spec.op_id,
            "lineage": spec.lineage,
            "status": verdict.status,
            "quiet_s": round(verdict.quiet_s, 1),
            "threshold_s": round(verdict.threshold_s, 1),
            "recovery_cmd": list(spec.recovery_cmd),
            "result": "ok" if ok else "fail",
            "ts": iso,
        }

    def _load_scan_state(self) -> dict[str, str]:
        try:
            data = json.loads(self._scan_state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(k): str(v) for k, v in (data or {}).items()}

    def _store_scan_state(self, tokens: dict[str, str]) -> None:
        try:
            _atomic_write(self._scan_state_path, json.dumps(tokens))
        except OSError:
            pass


# ── CLI ───────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    if "--beat" in argv:
        op_id = argv[argv.index("--beat") + 1]
        token = argv[argv.index("--token") + 1] if "--token" in argv else str(int(time.time()))
        meta = json.loads(argv[argv.index("--meta") + 1]) if "--meta" in argv else None
        emit_heartbeat(op_id, token, meta=meta)
        return 0

    if "--list" in argv:
        for spec in load_registry():
            thr = "tau" if spec.max_quiet_s is None else f"{spec.max_quiet_s:.0f}s"
            print(f"{spec.op_id}\t{thr}\t{' '.join(spec.recovery_cmd)}")
        return 0

    if "--scan" in argv:
        from shared.recovery_governor import RecoveryGovernor

        wd = LivenessWatchdog(governor=RecoveryGovernor())
        recovered = 0
        for r in wd.scan():
            if r.recovered:
                recovered += 1
            if r.status in (STALLED, MISSING):
                print(f"{r.status}\t{r.op_id}\tquiet={r.quiet_s:.0f}s\t{r.permit_reason}")
        print(f"# liveness scan: {recovered} recovered")
        return 0

    print("usage: liveness --beat <op_id> --token <t> | --scan | --list", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
