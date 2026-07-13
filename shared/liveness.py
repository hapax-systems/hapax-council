"""Support-only liveness observation and protected-action HOLD projection.

Heartbeat and registry data are evidence. They never authorize recovery. A
registry entry may name a frozen symbolic adapter descriptor, but it cannot
carry executable argv, a callable, or an execution lease. ``scan`` is
read-only: candidates that would require an effect are represented with the
shared :class:`~shared.execution_admission.ProtectedActionHold` contract.
"""

from __future__ import annotations

import dataclasses
import json
import math
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from shared.execution_admission import (
    PROTECTED_ACTION_HOLD_SCHEMA,
    ProtectedActionHold,
    build_protected_action_hold,
    content_address,
)

ALIVE = "alive"
QUIET = "quiet"
STALLED = "stalled"
MISSING = "missing"
INDETERMINATE = "indeterminate"

SUPPORT_ONLY = "support_only"
HELD_NOT_ADMITTED = "held_not_admitted"
EFFECT_HOLD_REASON = "execution_authority_admission_lease_absent"

_ADAPTER_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
_ACTION_KIND_RE = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9_-]*)+$")


def _liveness_root() -> Path:
    return Path.home() / ".cache" / "hapax" / "liveness"


def _default_beat_dir() -> Path:
    return _liveness_root() / "beats"


def _default_registry_dir() -> Path:
    return _liveness_root() / "registry"


def _sanitize(op_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", op_id).strip("_") or "op"


def _atomic_write(path: Path, text: str) -> None:
    """Persist explicit support-plane input; operational scans never call this."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _finite_number(value: object, label: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or (nonnegative and number < 0):
        raise ValueError(f"{label} must be finite" + (" and nonnegative" if nonnegative else ""))
    return number


def _nonblank(value: object, label: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{label} must be a nonblank canonical string")
    return value


@dataclass(frozen=True)
class Heartbeat:
    """One untrusted support-plane progress observation."""

    op_id: str
    ts: float
    token: str
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        _nonblank(self.op_id, "op_id")
        object.__setattr__(self, "ts", _finite_number(self.ts, "heartbeat timestamp"))
        if type(self.token) is not str:
            raise TypeError("heartbeat token must be a string")
        if type(self.meta) is not dict:
            raise TypeError("heartbeat meta must be an exact dictionary")


def emit_heartbeat(
    op_id: str,
    token: str | int,
    *,
    ts: float | None = None,
    meta: dict | None = None,
    beat_dir: Path | None = None,
) -> Path:
    """Atomically persist an explicit support observation, never authority."""
    observed_at = time.time() if ts is None else ts
    heartbeat = Heartbeat(
        op_id=_nonblank(op_id, "op_id"),
        ts=_finite_number(observed_at, "heartbeat timestamp"),
        token=str(token),
        meta={} if meta is None else meta,
    )
    root = Path(beat_dir) if beat_dir is not None else _default_beat_dir()
    path = root / f"{_sanitize(heartbeat.op_id)}.beat"
    _atomic_write(
        path,
        json.dumps(dataclasses.asdict(heartbeat), allow_nan=False, sort_keys=True),
    )
    return path


def read_heartbeat(op_id: str, *, beat_dir: Path | None = None) -> Heartbeat | None:
    """Read an exact heartbeat for ``op_id``; hostile or corrupt data is absent."""
    expected_op_id = _nonblank(op_id, "op_id")
    root = Path(beat_dir) if beat_dir is not None else _default_beat_dir()
    path = root / f"{_sanitize(expected_op_id)}.beat"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if type(data) is not dict or set(data) != {"meta", "op_id", "token", "ts"}:
            return None
        heartbeat = Heartbeat(
            op_id=data["op_id"],
            ts=data["ts"],
            token=data["token"],
            meta=data["meta"],
        )
    except (OSError, TypeError, ValueError):
        return None
    return heartbeat if heartbeat.op_id == expected_op_id else None


@dataclass(frozen=True)
class EffectAdapterDescriptor:
    """Immutable symbolic adapter identity; it is not executable or authorizing."""

    adapter_id: str
    action_kind: str
    target_id: str
    version: int = 1

    def __post_init__(self) -> None:
        adapter_id = _nonblank(self.adapter_id, "adapter_id")
        action_kind = _nonblank(self.action_kind, "action_kind")
        _nonblank(self.target_id, "target_id")
        if not _ADAPTER_ID_RE.fullmatch(adapter_id):
            raise ValueError("adapter_id is not canonical")
        if not _ACTION_KIND_RE.fullmatch(action_kind):
            raise ValueError("action_kind is not canonical")
        if type(self.version) is not int or self.version != 1:
            raise ValueError("only adapter descriptor version 1 is supported")


@dataclass(frozen=True)
class LivenessSpec:
    """A support observation declaration with an optional symbolic effect adapter."""

    op_id: str
    adapter: EffectAdapterDescriptor | None = None
    max_quiet_s: float | None = None
    lineage: str | None = None
    recover_when_missing: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        _nonblank(self.op_id, "op_id")
        if self.adapter is not None and type(self.adapter) is not EffectAdapterDescriptor:
            raise TypeError("adapter must be an exact EffectAdapterDescriptor")
        if self.max_quiet_s is not None:
            object.__setattr__(
                self,
                "max_quiet_s",
                _finite_number(self.max_quiet_s, "max_quiet_s", nonnegative=True),
            )
        if self.lineage is not None:
            _nonblank(self.lineage, "lineage")
        if type(self.recover_when_missing) is not bool:
            raise TypeError("liveness flags must be exact booleans")
        if type(self.description) is not str:
            raise TypeError("description must be a string")


def register(spec: LivenessSpec, *, registry_dir: Path | None = None) -> Path:
    """Persist an explicit support declaration containing no executable material."""
    if type(spec) is not LivenessSpec:
        raise TypeError("spec must be an exact LivenessSpec")
    root = Path(registry_dir) if registry_dir is not None else _default_registry_dir()
    path = root / f"{_sanitize(spec.op_id)}.json"
    _atomic_write(path, json.dumps(dataclasses.asdict(spec), allow_nan=False, sort_keys=True))
    return path


def _decode_spec(data: object) -> LivenessSpec:
    if type(data) is not dict:
        raise TypeError("registry entry must be an exact dictionary")
    known = {item.name for item in dataclasses.fields(LivenessSpec)}
    if not set(data).issubset(known) or "op_id" not in data:
        raise ValueError("registry entry contains unknown or legacy fields")
    values = dict(data)
    adapter_data = values.get("adapter")
    if adapter_data is not None:
        adapter_fields = {item.name for item in dataclasses.fields(EffectAdapterDescriptor)}
        if type(adapter_data) is not dict or set(adapter_data) != adapter_fields:
            raise ValueError("adapter descriptor must contain its exact fields")
        values["adapter"] = EffectAdapterDescriptor(**adapter_data)
    return LivenessSpec(**values)


def load_registry(*, registry_dir: Path | None = None) -> list[LivenessSpec]:
    """Read valid symbolic declarations, rejecting legacy executable entries."""
    root = Path(registry_dir) if registry_dir is not None else _default_registry_dir()
    if not root.exists():
        return []
    result: list[LivenessSpec] = []
    for entry in sorted(root.glob("*.json")):
        try:
            result.append(_decode_spec(json.loads(entry.read_text(encoding="utf-8"))))
        except (OSError, TypeError, ValueError):
            continue
    return result


@dataclass(frozen=True)
class LivenessVerdict:
    op_id: str
    status: str
    quiet_s: float
    threshold_s: float
    token: str | None
    reason: str


def classify(
    spec: LivenessSpec,
    heartbeat: Heartbeat | None,
    *,
    prev_token: str | None,
    now: float,
    threshold_s: float,
) -> LivenessVerdict:
    """Classify support evidence without converting it into action authority."""
    current_time = _finite_number(now, "now")
    threshold = _finite_number(threshold_s, "threshold_s", nonnegative=True)
    if heartbeat is None:
        return LivenessVerdict(spec.op_id, MISSING, 0.0, threshold, None, "heartbeat_missing")
    if type(heartbeat) is not Heartbeat or heartbeat.op_id != spec.op_id:
        return LivenessVerdict(
            spec.op_id,
            INDETERMINATE,
            0.0,
            threshold,
            None,
            "heartbeat_identity_invalid",
        )
    if heartbeat.ts > current_time:
        return LivenessVerdict(
            spec.op_id,
            INDETERMINATE,
            0.0,
            threshold,
            heartbeat.token,
            "heartbeat_from_future",
        )
    quiet_s = current_time - heartbeat.ts
    if prev_token is not None and heartbeat.token != str(prev_token):
        status, reason = ALIVE, "progress_token_advanced"
    elif quiet_s <= threshold:
        status, reason = QUIET, "within_quiet_threshold"
    else:
        status, reason = STALLED, "quiet_threshold_exceeded"
    return LivenessVerdict(spec.op_id, status, quiet_s, threshold, heartbeat.token, reason)


def _default_tau(lineage: str | None) -> float:
    """Read measured service time only as support; invalid values use a safe floor."""
    try:
        from shared.dispatch_service_time import load_service_time_distribution, tau_for_lineage

        value = tau_for_lineage(load_service_time_distribution(), lineage or "")
        return _finite_number(value, "measured tau", nonnegative=True)
    except Exception:
        return 1800.0


def _hold_for_candidate(
    spec: LivenessSpec,
    verdict: LivenessVerdict,
    *,
    checked_at: float,
) -> ProtectedActionHold:
    assert spec.adapter is not None
    observation = {
        "adapter": dataclasses.asdict(spec.adapter),
        "op_id": spec.op_id,
        "quiet_s": verdict.quiet_s,
        "reason": verdict.reason,
        "status": verdict.status,
        "threshold_s": verdict.threshold_s,
        "token": verdict.token,
    }
    reasons = {
        "execution_admission_absent",
        "execution_authority_absent",
        "execution_lease_absent",
    }
    if verdict.status == INDETERMINATE:
        reasons.add(verdict.reason)
    return build_protected_action_hold(
        raw_invocation=content_address(f"liveness-observation:{spec.op_id}", observation),
        operation=spec.adapter.action_kind,
        ingress_surface="shared.liveness.LivenessWatchdog.scan",
        ingress_module=content_address(
            "python:shared.liveness",
            {"contract": "gate0a-support-only", "module": "shared.liveness"},
        ),
        admission_module=content_address(
            "python:shared.execution_admission",
            {"schema": PROTECTED_ACTION_HOLD_SCHEMA},
        ),
        checked_at=datetime.fromtimestamp(checked_at, UTC),
        reason_codes=tuple(sorted(reasons)),
    )


@dataclass(frozen=True)
class ScanResult:
    op_id: str
    status: str
    recovered: bool
    permit_reason: str
    quiet_s: float
    effect_state: str
    hold: ProtectedActionHold | None


class LivenessWatchdog:
    """Read-only observer. No collaborator can inject authority or execution."""

    def __init__(
        self,
        *,
        registry_dir: Path | None = None,
        beat_dir: Path | None = None,
        now_fn=time.time,
        tau_fn=None,
    ) -> None:
        self._registry_dir = (
            Path(registry_dir) if registry_dir is not None else _default_registry_dir()
        )
        self._beat_dir = Path(beat_dir) if beat_dir is not None else _default_beat_dir()
        self._now_fn = now_fn
        self._tau_fn = tau_fn or _default_tau

    def scan(self, *, previous_tokens: dict[str, str] | None = None) -> list[ScanResult]:
        """Return support verdicts and generic HOLDs without writing or acting."""
        if previous_tokens is not None and type(previous_tokens) is not dict:
            raise TypeError("previous_tokens must be an exact dictionary")
        previous = {} if previous_tokens is None else dict(previous_tokens)
        if any(type(key) is not str or type(value) is not str for key, value in previous.items()):
            raise TypeError("previous_tokens must map exact strings to exact strings")
        now = _finite_number(self._now_fn(), "now")
        results: list[ScanResult] = []
        for spec in load_registry(registry_dir=self._registry_dir):
            heartbeat = read_heartbeat(spec.op_id, beat_dir=self._beat_dir)
            try:
                threshold = (
                    spec.max_quiet_s
                    if spec.max_quiet_s is not None
                    else _finite_number(
                        self._tau_fn(spec.lineage),
                        "measured tau",
                        nonnegative=True,
                    )
                )
                verdict = classify(
                    spec,
                    heartbeat,
                    prev_token=previous.get(spec.op_id),
                    now=now,
                    threshold_s=threshold,
                )
            except (TypeError, ValueError):
                verdict = LivenessVerdict(
                    spec.op_id,
                    INDETERMINATE,
                    0.0,
                    0.0,
                    None if heartbeat is None else heartbeat.token,
                    "liveness_threshold_invalid",
                )
            candidate = spec.adapter is not None and (
                verdict.status in {STALLED, INDETERMINATE}
                or (verdict.status == MISSING and spec.recover_when_missing)
            )
            hold = _hold_for_candidate(spec, verdict, checked_at=now) if candidate else None
            results.append(
                ScanResult(
                    op_id=spec.op_id,
                    status=verdict.status,
                    recovered=False,
                    permit_reason=EFFECT_HOLD_REASON if candidate else verdict.reason,
                    quiet_s=verdict.quiet_s,
                    effect_state=HELD_NOT_ADMITTED if candidate else SUPPORT_ONLY,
                    hold=hold,
                )
            )
        return results


def _format_adapter(adapter: EffectAdapterDescriptor | None) -> str:
    if adapter is None:
        return "observation-only"
    return f"{adapter.adapter_id}:{adapter.action_kind}:{adapter.target_id}"


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
            threshold = "tau" if spec.max_quiet_s is None else f"{spec.max_quiet_s:.0f}s"
            print(f"{spec.op_id}\t{threshold}\t{_format_adapter(spec.adapter)}\tsupport-only")
        return 0
    if "--scan" in argv:
        held = 0
        for result in LivenessWatchdog().scan():
            if result.hold is not None:
                held += 1
                print(result.hold.model_dump_json(by_alias=True))
            else:
                print(
                    f"OBSERVE status={result.status} op_id={result.op_id} "
                    f"effect_state={result.effect_state} reason={result.permit_reason}"
                )
        print(f"# liveness scan: effects=0 held={held} support_only=true")
        return 0
    print("usage: liveness --beat <op_id> --token <t> | --scan | --list", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
