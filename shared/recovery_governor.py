"""shared/recovery_governor.py — control-theory stability gate for the recovery loop.

Every recovery substrate (the idle/rate-limit watchdogs, the lane reaper, the
coordinator's converge loop, and any future level-triggered reconciler) routes
its respawn/kill/converge actions through one shared ``RecoveryGovernor`` so the
closed recovery loop is provably contractive (loop-gain ``G < 1``) rather than
the metastable retry-storm that starved the coordinator to death at load 30
(Bronson, *Metastable failures in distributed systems*, HotOS 2021).

This is the Kubernetes ``client-go`` ``DefaultControllerRateLimiter`` pattern —
per-item exponential backoff MAX'd with a global token bucket — *plus* two terms
the cloud limiter lacks because we run on a fixed 16-core box, not elastic cloud:

  1. **The #3850 PSI throttle** (``shared.sdlc_pressure_gate.admission_state``)
     used as a proportional negative-feedback term: the more load recovery
     creates, the less recovery is permitted (``open`` → ``paced`` → ``closed``).
  2. **An in-flight concurrency cap**: the token bucket bounds the *rate* of
     relaunches but not their *concurrency*; each relaunch is ~1.5 cores for
     60-180s, so a rate-only cap still permits ~18 concurrent relaunches (~27
     cores) — the exact load that killed the coordinator. The semaphore bounds it.

Three composable limiters; a recovery action is permitted iff **all** admit, so
the worst-case forward gain is the *product* of sub-unity factors → ``G ≪ 1``.

NEVER-FREEZE: the governor can throttle recovery to *slow* but never *halt* it.
If it cannot read PSI it fails to a **tightened** bucket (not the open-mode rate
— see ``RecoveryParams.degraded_*``); if ``/dev/shm`` is unwritable it fails to
*permit*; a critical-reserve token + ``MAX_ATTEMPTS → auto-mint-escape`` guarantee
safety recovery never fully stops. Every fail-open event is counted, ledgered and
ntfy'd (rate-limited) so a silently-broken governor is *visible*, not a silent
revert to the unthrottled load-30 surface.

CLI (for the bash respawn floors), exit ``0`` permit / ``75`` backoff / ``2``
closed::
    python3 -m shared.recovery_governor --permit lane:beta
    python3 -m shared.recovery_governor --record lane:beta ok|fail
    python3 -m shared.recovery_governor --permit-batch lane:beta lane:gamma ...
    python3 -m shared.recovery_governor --state
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path

# ── States (mirror sdlc_pressure_gate) ───────────────────────────────────────

PERMIT, BACKOFF, CLOSED = 0, 75, 2  # CLI exit codes

OFF_ENV = "HAPAX_RECOVERY_GOVERNOR_OFF"
MODE_ENV = "HAPAX_RECOVERY_GOVERNOR_MODE"  # "shadow" (default) | "enforce"


def _governor_off() -> bool:
    return os.environ.get(OFF_ENV, "").strip().lower() in ("1", "true", "yes")


def _iso_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _psi_readable(path: str = "/proc/pressure/cpu") -> bool:
    try:
        Path(path).read_text()
        return True
    except OSError:
        return False


def _live_admission():
    from shared.sdlc_pressure_gate import admission_state

    return admission_state()


def _default_notify(title: str, message: str, **kw) -> None:
    from shared.notify import send_notification

    send_notification(title, message, **kw)


# ── MF5: interim critical-target predicate (signals that exist on main today) ──

_PID_DIR = Path(f"/run/user/{os.getuid()}/hapax-claude")
_ACTIVE_TASK_FMT = str(Path.home() / ".cache" / "hapax" / "cc-active-task-{role}")
_TASKS_ACTIVE = Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"


def _coordinator_alive() -> bool:
    """Liveness of hapax-coordinator.service — the same ``systemctl is-active``
    signal the rest of the fleet uses. Fails *alive* (so a check error never
    classifies the coordinator dead and storms recovery)."""
    import shutil
    import subprocess

    systemctl = shutil.which("systemctl")
    if not systemctl:
        return True
    try:
        proc = subprocess.run(
            [systemctl, "--user", "is-active", "hapax-coordinator.service"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return proc.stdout.strip() == "active"
    except (subprocess.SubprocessError, OSError):
        return True


def _lane_pid_alive(role: str) -> bool:
    """``kill -0`` liveness of a lane via its pidfile (the rate-limit-watchdog
    signal). Missing/dead pidfile → not alive."""
    try:
        pid = int((_PID_DIR / f"{role}.pid").read_text().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def _lane_task_priority(role: str) -> str:
    """Priority of the cc-task a lane currently holds (frontmatter ``priority:``),
    read from the active-task pointer + note. '' when unknown."""
    try:
        task_id = Path(_ACTIVE_TASK_FMT.format(role=role)).read_text().strip()
    except OSError:
        return ""
    if not task_id:
        return ""
    for note in _TASKS_ACTIVE.glob(f"{task_id}*.md"):
        try:
            text = note.read_text(encoding="utf-8")
        except OSError:
            continue
        import re

        m = re.search(r"^priority:\s*(\S+)", text, re.MULTILINE)
        if m:
            return m.group(1).strip().strip("\"'").lower()
    return ""


def _interim_critical_predicate(
    target_id: str,
    *,
    coordinator_alive_fn=_coordinator_alive,
    pid_alive_fn=_lane_pid_alive,
    priority_fn=_lane_task_priority,
) -> bool:
    """A *machine-checkable* critical predicate built only from signals that
    exist on ``origin/main`` today (no LaneState ``stalled``/``dead`` distinction
    yet): a DEAD coordinator, or a DEAD lane holding a P0/P1 task. A live lane is
    never critical — recovering a heartbeating lane is the storm we prevent."""
    kind, _, rest = target_id.partition(":")
    if target_id == "coordinator" or kind == "coordinator" or rest == "coordinator":
        return not coordinator_alive_fn()
    if kind == "lane":
        role = rest
        if priority_fn(role) in ("p0", "p1") and not pid_alive_fn(role):
            return True
    return False


# ── Escalation: mint a bounded escape cc-task (NO-STALL, idempotent) ──────────


def _mint_escalation_task(target_id: str, detail: str, *, tasks_dir: Path | None = None) -> Path:
    """Write a ``recovery-escalation`` cc-task via the sanctioned bootstrap path
    so a target stuck at MAX_ATTEMPTS hands off to a human-visible escape rather
    than retrying forever. One deterministic file per target → idempotent."""
    import re

    tasks_dir = tasks_dir or _TASKS_ACTIVE
    tasks_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", target_id.lower()).strip("-") or "target"
    path = tasks_dir / f"recovery-escalation-{slug}.md"
    body = (
        "---\n"
        "type: cc-task\n"
        f"task_id: recovery-escalation-{slug}\n"
        f'title: "Recovery escalation: {target_id} exhausted automatic recovery"\n'
        "status: offered\n"
        "assigned_to: unassigned\n"
        "priority: p1\n"
        "kind: bug\n"
        "tags: [cc-task, recovery-escalation, sdlc, auto-minted]\n"
        f"created_at: {_iso_now()}\n"
        "---\n\n"
        f"# Recovery escalation: `{target_id}`\n\n"
        "The shared RecoveryGovernor stopped issuing automatic recovery for this "
        "target after it reached MAX_ATTEMPTS (the AIMD ceiling), to avoid a "
        "retry-storm. A human (or a higher-order reconciler) must inspect it.\n\n"
        f"- **Target:** `{target_id}`\n"
        f"- **Detail:** {detail}\n"
        f"- **Minted:** {_iso_now()}\n"
    )
    path.write_text(body, encoding="utf-8")
    return path


# ── Tabulated parameters (design § Concrete parameters) ──────────────────────


@dataclass(frozen=True)
class RecoveryParams:
    """All governor knobs in one overridable dataclass (design table)."""

    base_s: float = 30.0  # AIMD BASE — one tick of the slow loops
    multiplier: float = 2.0  # AIMD ×2 per attempt → 30/60/120/240/480s
    cap_s: float = 1800.0  # AIMD CAP (30min) — matches reaper cadence
    max_attempts: int = 5  # bounded; then escalate, never infinite
    bucket_rate: float = 0.1  # 1 action / 10s — fleet-wide load-injection cap
    bucket_burst: int = 3  # absorbs a small genuine wave without serializing
    critical_reserve: int = 1  # dead-coordinator/P0-lane recovery never starves
    max_concurrent_relaunch: int = 3  # MF2 — bound CONCURRENCY, not just rate
    inflight_ttl_s: float = 300.0  # stale in-flight entries expire (lost record)
    # MF1 — PSI-unreadable degraded bucket: TIGHTER than open, safe standalone.
    degraded_rate: float = 1.0 / 30.0  # 1 action / 30s
    degraded_burst: int = 1
    # Coordinator per-tick converge ceiling (open/paced/closed[+1 critical]).
    tick_cap_open: int = 6
    tick_cap_paced: int = 2
    tick_cap_closed: int = 0
    # Internal flags set by params_for_state; not user-tuned.
    suspend_noncritical: bool = False


def aimd_backoff_delay(attempt: int, params: RecoveryParams) -> float:
    """Nominal (un-jittered) AIMD delay for ``attempt`` — ``BASE·mult^attempt``
    clamped to ``CAP``. Multiplicative increase = the AIMD *decrease* of recovery
    rate; this is the metastable-breaker for a target that keeps looking stale."""
    nominal = params.base_s * (params.multiplier ** max(0, attempt))
    return min(nominal, params.cap_s)


def params_for_state(state: str, base: RecoveryParams) -> RecoveryParams:
    """Apply the PSI throttle to the params (proof step 2, the negative-feedback
    term). ``paced`` halves the bucket rate AND doubles the AIMD base (the
    proportional band); ``closed`` suspends non-critical recovery (the integral
    cutout); ``degraded`` (PSI unreadable, MF1) tightens the bucket below open."""
    if state == "paced":
        return replace(base, base_s=base.base_s * 2.0, bucket_rate=base.bucket_rate * 0.5)
    if state == "closed":
        return replace(base, suspend_noncritical=True)
    if state == "degraded":
        return replace(base, bucket_rate=base.degraded_rate, bucket_burst=base.degraded_burst)
    return base  # open


def converge_action_cap(
    state: str, params: RecoveryParams | None = None, *, critical_pending: bool = False
) -> int:
    """Per-tick ceiling on converge (recovery/dispatch) actions a controller may
    take, by PSI state: ``open`` → fleet-width, ``paced`` → 2, ``closed`` → 0
    (plus the critical reserve if a critical target is pending). The coordinator
    applies this so the controller itself can never become the load-injecting
    storm it exists to prevent — #3850's L4 intent, mapped to the 6-lane fleet."""
    params = params or RecoveryParams()
    if state == "closed":
        return params.critical_reserve if critical_pending else params.tick_cap_closed
    if state == "paced":
        return params.tick_cap_paced
    return params.tick_cap_open


# ── Token bucket (pure) ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class BucketState:
    tokens: float
    updated: float


def bucket_take(
    state: BucketState, now: float, *, rate: float, burst: int, n: int = 1
) -> tuple[bool, BucketState]:
    """Take ``n`` tokens from a leaky bucket refilling at ``rate``/s up to
    ``burst``. Bounds fleet-wide recovery to ``burst`` immediate then ``rate``/s,
    *independent of how many targets look stale* — the clamp that breaks the
    metastable sustaining effect (proof step 1)."""
    elapsed = max(0.0, now - state.updated)
    tokens = min(float(burst), state.tokens + elapsed * rate)
    if tokens >= n:
        return True, BucketState(tokens - n, now)
    return False, BucketState(tokens, now)


# ── Grant + per-target backoff entry ─────────────────────────────────────────


@dataclass(frozen=True)
class RecoveryGrant:
    """The verdict the governor returns for one recovery action."""

    permitted: bool
    reason: str
    target_id: str
    state: str = "open"
    attempt: int = 0
    critical: bool = False
    shadow: bool = False


@dataclass(frozen=True)
class BackoffEntry:
    next_eligible: float
    attempt: int
    last_outcome: str


def _default_state_dir() -> Path:
    """``/dev/shm`` (crash-survivable, any loop reconstructs it) with a
    ``~/.cache`` fallback — mirrors ``sdlc_pressure_gate.default_state_path``."""
    base = Path("/dev/shm/hapax/recovery")
    try:
        base.mkdir(parents=True, exist_ok=True)
        return base
    except OSError:
        fallback = Path.home() / ".cache" / "hapax" / "recovery"
        try:
            fallback.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return fallback


def _full_jitter(delay: float) -> float:
    """AWS decorrelated 'full jitter' — ``U(0, delay)``. Provably breaks
    synchronized herds; expected delay still doubles per attempt."""
    import random

    return random.uniform(0.0, delay)


class RecoveryGovernor:
    """Stateful façade over the pure limiters. All collaborators are injectable
    so the whole decision path is deterministic under test and fail-open in prod."""

    def __init__(
        self,
        *,
        params: RecoveryParams | None = None,
        state_dir: Path | None = None,
        now_fn=time.time,
        admission_fn=None,
        psi_readable_fn=None,
        jitter_fn=_full_jitter,
        critical_validator_fn=None,
        notify_fn=None,
        mint_fn=None,
        shielded_fn=None,
        mode: str | None = None,
    ) -> None:
        self._params = params or RecoveryParams()
        self._dir = state_dir if state_dir is not None else _default_state_dir()
        self._now_fn = now_fn
        self._admission_fn = admission_fn
        self._psi_readable_fn = psi_readable_fn or _psi_readable
        self._jitter_fn = jitter_fn
        self._critical_validator_fn = critical_validator_fn or self._default_critical
        self._notify_fn = notify_fn if notify_fn is not None else _default_notify
        self._mint_fn = mint_fn if mint_fn is not None else _mint_escalation_task
        self._shielded_fn = shielded_fn if shielded_fn is not None else coordinator_shielded
        self._mode = (mode or os.environ.get(MODE_ENV, "shadow")).strip().lower()

    # ── paths ────────────────────────────────────────────────────────────────
    @property
    def _backoff_path(self) -> Path:
        return self._dir / "backoff.json"

    @property
    def _bucket_path(self) -> Path:
        return self._dir / "bucket.json"

    @property
    def _critical_path(self) -> Path:
        return self._dir / "critical_bucket.json"

    @property
    def _inflight_path(self) -> Path:
        return self._dir / "inflight.json"

    # ── admission / mode ──────────────────────────────────────────────────────
    def _resolve_state(self) -> tuple[str, bool]:
        """(state, psi_readable). PSI-unreadable → 'degraded' (MF1), NOT 'open' —
        and a fail-open observability event is recorded so it is never silent."""
        try:
            readable = bool(self._psi_readable_fn())
        except Exception:
            readable = False
        if not readable:
            self._record_failopen("psi-unreadable", "/proc/pressure/cpu not readable")
            return "degraded", False
        try:
            fn = self._admission_fn or _live_admission
            return str(fn().state), True
        except Exception as exc:  # PSI parse / gate error → degraded, observable
            self._record_failopen("psi-error", repr(exc))
            return "degraded", False

    def state(self) -> str:
        return self._resolve_state()[0]

    def effective_mode(self) -> str:
        """'enforce' only when the operator asked for it AND the coordinator is
        shielded (CPUWeight raised) — otherwise 'shadow' (non-binding, not
        stalled). MF4: the #3850 dependency is a runtime precondition, not a hope."""
        if self._mode != "enforce":
            return "shadow"
        try:
            return "enforce" if self._shielded_fn() else "shadow"
        except Exception:
            return "shadow"

    # ── critical predicate (MF5) ──────────────────────────────────────────────
    def _is_critical(self, target_id: str, requested: bool) -> bool:
        if not requested:
            return False
        try:
            return bool(self._critical_validator_fn(target_id))
        except Exception:
            return False

    def _default_critical(self, target_id: str) -> bool:
        return _interim_critical_predicate(target_id)

    # ── permit ────────────────────────────────────────────────────────────────
    def permit(
        self, target_id: str, *, critical: bool = False, now: float | None = None
    ) -> RecoveryGrant:
        if _governor_off():
            return RecoveryGrant(True, "governor-off", target_id, "open")
        try:
            return self._permit_inner(target_id, critical, now)
        except Exception as exc:  # NEVER a deny-sink: any error → permit + observe
            self._record_failopen("governor-error", f"{target_id}: {exc!r}")
            return RecoveryGrant(True, "fail-open:governor-error", target_id, "open")

    def _permit_inner(self, target_id: str, critical: bool, now: float | None) -> RecoveryGrant:
        now = self._now_fn() if now is None else now
        state, _ = self._resolve_state()
        params = params_for_state(state, self._params)
        is_crit = self._is_critical(target_id, critical)
        shadow = self.effective_mode() == "shadow"
        entry = self.backoff_entry(target_id)  # default (0, 0, "") when never failed

        def grant(permitted: bool, reason: str) -> RecoveryGrant:
            return RecoveryGrant(
                permitted,
                reason,
                target_id,
                state,
                attempt=entry.attempt,
                critical=is_crit,
                shadow=shadow,
            )

        # Escalated targets are severed from the loop (proof step 3).
        if entry.attempt >= self._params.max_attempts and not is_crit:
            return grant(False, f"escalated:attempt={entry.attempt}")

        # 'closed' suspends non-critical recovery (the integral cutout).
        if params.suspend_noncritical and not is_crit:
            return grant(False, "closed:suspended-noncritical")

        if is_crit:
            ok = self._take_critical(now)
            return grant(ok, "critical-reserve" if ok else "critical-reserve-exhausted")

        # Per-target AIMD backoff.
        if now < entry.next_eligible:
            return grant(False, f"backoff:attempt={entry.attempt}")

        # MF2: in-flight concurrency cap (bucket bounds rate, not concurrency).
        if len(self._active_inflight(now)) >= params.max_concurrent_relaunch:
            return grant(False, "concurrency-cap")

        # Global token bucket (the herd cap).
        bucket = self._load_bucket(self._bucket_path)
        ok, bucket = bucket_take(bucket, now, rate=params.bucket_rate, burst=params.bucket_burst)
        self._store_bucket(self._bucket_path, bucket)
        if not ok:
            return grant(False, "bucket-empty")

        self._mark_inflight(target_id, now)
        return grant(True, "permitted")

    def permit_batch(self, targets, *, now: float | None = None) -> list[RecoveryGrant]:
        """MF3: admit a whole tick's candidate set in ONE call (one PSI read, one
        state load) — bounds permit-call frequency to 1/loop/tick instead of N."""
        now = self._now_fn() if now is None else now
        return [self.permit(t, now=now) for t in targets]

    # ── record outcome → AIMD reset/increment, free in-flight ─────────────────
    def record_outcome(self, target_id: str, success: bool, *, now: float | None = None) -> None:
        now = self._now_fn() if now is None else now
        self._clear_inflight(target_id, now)
        backoff = self._load_backoff()
        entry = backoff.get(target_id) or BackoffEntry(0.0, 0, "")
        if success:
            backoff[target_id] = BackoffEntry(now, 0, "ok")  # reset-on-success
        else:
            old_attempt = entry.attempt
            new_attempt = old_attempt + 1
            state, _ = self._resolve_state()
            params = params_for_state(state, self._params)
            delay = self._jitter_fn(aimd_backoff_delay(old_attempt, params))
            outcome = "fail"
            if new_attempt >= self._params.max_attempts and old_attempt < self._params.max_attempts:
                self._escalate(target_id, new_attempt)
                outcome = "escalated"
            backoff[target_id] = BackoffEntry(now + delay, new_attempt, outcome)
        self._store_backoff(backoff)

    def backoff_entry(self, target_id: str) -> BackoffEntry:
        return self._load_backoff().get(target_id) or BackoffEntry(0.0, 0, "")

    # ── escalation (bounded, automatic — NO-STALL) ────────────────────────────
    def _escalate(self, target_id: str, attempt: int) -> None:
        detail = f"target={target_id} reached MAX_ATTEMPTS={self._params.max_attempts}"
        try:
            self._mint_fn(target_id, detail)
        except Exception as exc:
            self._record_failopen("escalation-mint-failed", f"{target_id}: {exc!r}")
        try:
            self._notify_fn(
                "Recovery escalation",
                f"{target_id}: {self._params.max_attempts} recovery attempts failed — minted escape task",
                priority="high",
                tags=["warning"],
            )
        except Exception:
            pass

    # ── token buckets ─────────────────────────────────────────────────────────
    def _take_critical(self, now: float) -> bool:
        bucket = self._load_bucket(self._critical_path, burst=self._params.critical_reserve)
        ok, bucket = bucket_take(
            bucket, now, rate=self._params.bucket_rate, burst=self._params.critical_reserve
        )
        self._store_bucket(self._critical_path, bucket)
        return ok

    def _load_bucket(self, path: Path, *, burst: int | None = None) -> BucketState:
        burst = self._params.bucket_burst if burst is None else burst
        try:
            data = json.loads(path.read_text())
            return BucketState(float(data["tokens"]), float(data["updated"]))
        except (OSError, ValueError, KeyError, TypeError):
            return BucketState(float(burst), 0.0)  # fail-open: a full bucket

    def _store_bucket(self, path: Path, state: BucketState) -> None:
        self._atomic_write(path, json.dumps({"tokens": state.tokens, "updated": state.updated}))

    # ── per-target backoff store ──────────────────────────────────────────────
    def _load_backoff(self) -> dict[str, BackoffEntry]:
        try:
            data = json.loads(self._backoff_path.read_text())
        except (OSError, ValueError):
            return {}
        out: dict[str, BackoffEntry] = {}
        for target, raw in (data or {}).items():
            try:
                out[target] = BackoffEntry(float(raw[0]), int(raw[1]), str(raw[2]))
            except (ValueError, IndexError, TypeError):
                continue
        return out

    def _store_backoff(self, backoff: dict[str, BackoffEntry]) -> None:
        payload = {t: [e.next_eligible, e.attempt, e.last_outcome] for t, e in backoff.items()}
        self._atomic_write(self._backoff_path, json.dumps(payload))

    # ── in-flight set (MF2) ───────────────────────────────────────────────────
    def _active_inflight(self, now: float) -> dict[str, float]:
        try:
            data = json.loads(self._inflight_path.read_text())
        except (OSError, ValueError):
            return {}
        ttl = self._params.inflight_ttl_s
        return {t: float(ts) for t, ts in (data or {}).items() if now - float(ts) < ttl}

    def _mark_inflight(self, target_id: str, now: float) -> None:
        active = self._active_inflight(now)
        active[target_id] = now
        self._atomic_write(self._inflight_path, json.dumps(active))

    def _clear_inflight(self, target_id: str, now: float) -> None:
        active = self._active_inflight(now)
        if active.pop(target_id, None) is not None:
            self._atomic_write(self._inflight_path, json.dumps(active))

    # ── fail-open observability (MF6) ─────────────────────────────────────────
    def _record_failopen(self, kind: str, detail: str) -> None:
        rec = {"kind": kind, "detail": detail[:240], "ts": _iso_now()}
        wrote = self._append_failopen(rec)
        if not wrote:
            # shm unwritable too — fall back to ~/.cache so the event is not lost.
            self._append_failopen(rec, fallback=True)
        try:
            self._notify_fn(
                "Recovery governor fail-open",
                f"{kind}: {detail[:160]}",
                priority="high",
                tags=["warning"],
            )
        except Exception:
            pass

    def _append_failopen(self, rec: dict, *, fallback: bool = False) -> bool:
        target_dir = (Path.home() / ".cache" / "hapax" / "recovery") if fallback else self._dir
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            # jsonl-rotation: exempt(dual-path writer; both failopen paths are registry targets)
            with (target_dir / "failopen.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
            self._bump_counter(target_dir / "counters.json", "failopen")
            return True
        except OSError:
            return False

    def _bump_counter(self, path: Path, key: str) -> None:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            data = {}
        data[key] = int(data.get(key, 0)) + 1
        try:
            self._atomic_write(path, json.dumps(data))
        except OSError:
            pass

    def failopen_count(self) -> int:
        for d in (self._dir, Path.home() / ".cache" / "hapax" / "recovery"):
            try:
                return int(json.loads((d / "counters.json").read_text()).get("failopen", 0))
            except (OSError, ValueError):
                continue
        return 0

    # ── atomic write (tmp-rename, like sdlc_pressure_gate._store_state) ────────
    def _atomic_write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)


# ── Bounded-recovery kill helper (NEVER a process-group kill) ─────────────────


def safe_kill(pid: int, sig: int, *, kill_fn=None) -> None:
    """Kill EXACTLY one PID. Rejects a process-group id (``pid <= 0``) at the type
    boundary — the process-group kill idiom (a negative PID) is the exit-144
    cascade that the reaper's group-free ``tmux kill-session`` deliberately
    avoids. There is no process-group kill anywhere in this module (grep-clean, by
    acceptance criterion). ``os.kill`` is resolved at call time so a monkeypatch
    (and test injection) is honoured."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise ValueError(
            f"safe_kill refuses non-positive pid {pid!r} (process-group kill rejected)"
        )
    (kill_fn or os.kill)(pid, sig)


# ── MF4: coordinator-shielded runtime precondition for enforcement ───────────


def _systemctl_cpuweight() -> str:
    import shutil
    import subprocess

    systemctl = shutil.which("systemctl")
    if not systemctl:
        return ""
    try:
        proc = subprocess.run(
            [systemctl, "--user", "show", "hapax-coordinator.service", "-p", "CPUWeight"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return proc.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def coordinator_shielded(*, min_weight: int = 1000, show_fn=_systemctl_cpuweight) -> bool:
    """True iff the coordinator's ``CPUWeight`` is raised (≥ ``min_weight``, well
    above the systemd default of 100). The enforcement flip is gated on this so
    the throttling controller is never itself inside the throttled, starvable
    slice unshielded — MF4 turns the #3850 dependency into a runtime check."""
    import re

    m = re.search(r"CPUWeight=(\d+)", show_fn() or "")
    return bool(m) and int(m.group(1)) >= min_weight


def _ledger_shadow(governor: RecoveryGovernor, grant: RecoveryGrant) -> None:
    """Append the would-be grant to the shadow-compare ledger (Phase 2 evidence:
    would-permit vs actual, before the enforcement flip)."""
    rec = {
        "target": grant.target_id,
        "would_permit": grant.permitted,
        "reason": grant.reason,
        "state": grant.state,
        "ts": _iso_now(),
    }
    try:
        governor._dir.mkdir(parents=True, exist_ok=True)
        with (governor._dir / "shadow-compare.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def _grant_exit_code(grant: RecoveryGrant) -> int:
    if grant.permitted:
        return PERMIT
    if grant.reason.startswith("closed"):
        return CLOSED
    return BACKOFF  # backoff / concurrency / bucket / escalated


# ── CLI (bash respawn floors) ────────────────────────────────────────────────


def main(argv: list[str] | None = None, *, governor: RecoveryGovernor | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    gov = governor if governor is not None else RecoveryGovernor()

    if "--state" in argv:
        state = gov.state()
        print(state)
        return {"open": 0, "paced": 1, "closed": 2, "degraded": 1}.get(state, 0)

    if "--stats" in argv:  # MF6: the governor's own health is observable
        print(
            json.dumps(
                {
                    "state": gov.state(),
                    "effective_mode": gov.effective_mode(),
                    "failopen_count": gov.failopen_count(),
                }
            )
        )
        return 0

    if "--kill" in argv:  # sanctioned bounded kill for recovery sites (pgid-safe)
        i = argv.index("--kill")
        pid = int(argv[i + 1])
        sig = int(argv[argv.index("--signal") + 1]) if "--signal" in argv else signal.SIGTERM
        safe_kill(pid, sig)
        return 0

    if "--record" in argv:
        i = argv.index("--record")
        target, outcome = argv[i + 1], argv[i + 2]
        gov.record_outcome(target, success=(outcome.strip().lower() == "ok"))
        return 0

    if "--permit-batch" in argv:
        i = argv.index("--permit-batch")
        targets = [a for a in argv[i + 1 :] if not a.startswith("-")]
        for grant in gov.permit_batch(targets):
            if grant.shadow:
                _ledger_shadow(gov, grant)
            if grant.permitted or grant.shadow:
                print(grant.target_id)
        return 0

    if "--permit" in argv:
        i = argv.index("--permit")
        target = argv[i + 1]
        grant = gov.permit(target, critical=("--critical" in argv))
        if grant.shadow:  # non-binding: ledger the would-be grant, act as today
            _ledger_shadow(gov, grant)
            return PERMIT
        return _grant_exit_code(grant)

    print("usage: recovery_governor --permit|--record|--permit-batch|--state ...", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
