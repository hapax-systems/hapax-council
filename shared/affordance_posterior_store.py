"""Locked persistence and update protocol for affordance learning state."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from shared.affordance import ActivationState

log = logging.getLogger("affordance_posterior_store")

POSTERIOR_UPDATE_LOCK_TIMEOUT_ENV = "HAPAX_AFFORDANCE_POSTERIOR_UPDATE_LOCK_TIMEOUT_S"
POSTERIOR_OWNER_DRAIN_LOCK_TIMEOUT_ENV = "HAPAX_AFFORDANCE_POSTERIOR_OWNER_DRAIN_LOCK_TIMEOUT_S"
POSTERIOR_UPDATE_LOG_MAX_BYTES_ENV = "HAPAX_AFFORDANCE_POSTERIOR_UPDATE_LOG_MAX_BYTES"
POSTERIOR_UPDATE_LOCK_TIMEOUT_DEFAULT_S = 0.0
POSTERIOR_OWNER_DRAIN_LOCK_TIMEOUT_DEFAULT_S = 1.0
POSTERIOR_UPDATE_LOG_MAX_BYTES_DEFAULT = 5 * 1024 * 1024
OUTCOME_CONTEXT_ASSOCIATION_SUCCESS_DELTA = 0.1
OUTCOME_CONTEXT_ASSOCIATION_FAILURE_DELTA = -0.05


class PosteriorLockError(RuntimeError):
    """Raised when the posterior store cannot acquire its exclusive lock."""


def posterior_update_log_path(path: Path) -> Path:
    """Return the sidecar JSONL used by read-only clients to queue updates."""

    return path.with_name(f"{path.stem}-updates.jsonl")


@contextmanager
def posterior_file_lock(
    path: Path,
    *,
    blocking: bool = False,
    timeout_s: float | None = None,
) -> Iterator[None]:
    """Hold an exclusive advisory lock for ``path`` using a persistent sidecar file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f"{path.name}.lock")
    fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
    acquired = False
    try:
        if blocking and timeout_s is None:
            fcntl.flock(fd, fcntl.LOCK_EX)
        else:
            deadline = None if timeout_s is None else time.monotonic() + timeout_s
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError as exc:
                    if not blocking or (deadline is not None and time.monotonic() >= deadline):
                        raise PosteriorLockError(
                            f"posterior lock held: {lock_path}; next action: retry or confirm "
                            "the affordance posterior owner is draining normally"
                        ) from exc
                    time.sleep(0.01)
        acquired = True
        yield
    finally:
        if acquired:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def load_posterior_state(
    path: Path,
) -> tuple[dict[str, ActivationState], dict[tuple[str, str], float]] | None:
    """Load activation and association maps from the persisted posterior file."""

    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None

    activations: dict[str, ActivationState] = {}
    raw_activations = data.get("activations", {})
    if isinstance(raw_activations, dict):
        for name, state_dict in raw_activations.items():
            if not isinstance(name, str) or not isinstance(state_dict, dict):
                continue
            try:
                activations[name] = ActivationState(**state_dict)
            except Exception:
                log.warning("Skipping malformed affordance posterior state for %s", name)
                continue

    associations: dict[tuple[str, str], float] = {}
    raw_associations = data.get("associations", {})
    if isinstance(raw_associations, dict):
        for key_str, strength in raw_associations.items():
            if not isinstance(key_str, str):
                continue
            cue, sep, capability = key_str.partition("|")
            if not sep:
                continue
            try:
                associations[(cue, capability)] = float(strength)
            except (TypeError, ValueError):
                continue

    return activations, associations


def write_posterior_state(
    path: Path,
    activations: dict[str, ActivationState],
    associations: dict[tuple[str, str], float],
    *,
    blocking: bool = False,
    before_write: Callable[[], None] | None = None,
) -> None:
    """Write posterior state under an exclusive file lock."""

    with posterior_file_lock(path, blocking=blocking):
        if before_write is not None:
            before_write()
        _write_posterior_state_unlocked(path, activations, associations)


def write_posterior_state_draining_updates(
    path: Path,
    activations: dict[str, ActivationState],
    associations: dict[tuple[str, str], float],
    apply_updates: Callable[[list[dict[str, Any]]], int],
    *,
    blocking: bool = False,
) -> int:
    """Apply queued reader updates and write state under posterior + journal locks."""

    update_path = posterior_update_log_path(path)
    timeout_s = _float_env(
        POSTERIOR_OWNER_DRAIN_LOCK_TIMEOUT_ENV,
        POSTERIOR_OWNER_DRAIN_LOCK_TIMEOUT_DEFAULT_S,
    )
    with posterior_file_lock(update_path, blocking=True, timeout_s=timeout_s):
        with posterior_file_lock(path, blocking=blocking):
            events = _read_posterior_update_events(update_path)
            applied = apply_updates(events)
            _write_posterior_state_unlocked(path, activations, associations)
            if events:
                # Safe because reader appends and owner drains share this journal lock.
                update_path.write_text("", encoding="utf-8")
            return applied


def _write_posterior_state_unlocked(
    path: Path,
    activations: dict[str, ActivationState],
    associations: dict[tuple[str, str], float],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "activations": {name: state.model_dump() for name, state in activations.items()},
        "associations": {f"{k[0]}|{k[1]}": v for k, v in associations.items()},
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def append_posterior_update(path: Path, event: dict[str, Any]) -> None:
    """Append one read-client update request to the owner-consumed journal."""

    update_path = posterior_update_log_path(path)
    timeout_s = _float_env(
        POSTERIOR_UPDATE_LOCK_TIMEOUT_ENV,
        POSTERIOR_UPDATE_LOCK_TIMEOUT_DEFAULT_S,
    )
    max_bytes = _int_env(
        POSTERIOR_UPDATE_LOG_MAX_BYTES_ENV,
        POSTERIOR_UPDATE_LOG_MAX_BYTES_DEFAULT,
    )
    with posterior_file_lock(update_path, blocking=True, timeout_s=timeout_s):
        update_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"timestamp": time.time(), **event}
        encoded = json.dumps(payload, separators=(",", ":"), default=str) + "\n"
        current_size = update_path.stat().st_size if update_path.exists() else 0
        if current_size + len(encoded.encode("utf-8")) > max_bytes:
            raise PosteriorLockError(
                f"posterior update log exceeds cap: {update_path} > {max_bytes} bytes; "
                "next action: start or repair Reverie so it drains the journal, or raise "
                f"{POSTERIOR_UPDATE_LOG_MAX_BYTES_ENV} after inspecting the file"
            )
        with update_path.open("a", encoding="utf-8") as handle:
            handle.write(encoded)


def _read_posterior_update_events(update_path: Path) -> list[dict[str, Any]]:
    if not update_path.exists():
        return []
    try:
        raw = update_path.read_text(encoding="utf-8")
    except OSError:
        return []
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def apply_posterior_updates(
    activations: dict[str, ActivationState],
    associations: dict[tuple[str, str], float],
    events: list[dict[str, Any]],
) -> int:
    """Apply queued posterior update events using the existing math."""

    applied = 0
    for event in events:
        kind = event.get("kind")
        if kind == "record_outcome":
            capability = event.get("capability_name")
            if not isinstance(capability, str) or not capability:
                continue
            success = bool(event.get("success"))
            state = activations.setdefault(capability, ActivationState())
            if success:
                state.record_success()
                delta = OUTCOME_CONTEXT_ASSOCIATION_SUCCESS_DELTA
            else:
                state.record_failure()
                delta = OUTCOME_CONTEXT_ASSOCIATION_FAILURE_DELTA
            context = event.get("context")
            if isinstance(context, dict):
                for value in context.values():
                    _update_association(
                        associations,
                        str(value),
                        capability,
                        delta,
                    )
            applied += 1
        elif kind == "decay_unused":
            try:
                gamma = float(event.get("gamma", 0.999))
            except (TypeError, ValueError):
                gamma = 0.999
            names = event.get("capability_names")
            if not isinstance(names, list):
                continue
            for capability in names:
                if not isinstance(capability, str) or not capability:
                    continue
                activations.setdefault(capability, ActivationState()).decay_unused(gamma)
            applied += 1
        elif kind == "context_association_delta":
            capability = event.get("capability_name")
            cue = event.get("cue_value")
            if not isinstance(capability, str) or not isinstance(cue, str):
                continue
            try:
                delta = float(event.get("delta", 0.0))
            except (TypeError, ValueError):
                continue
            _update_association(associations, cue, capability, delta)
            applied += 1
        elif kind == "decay_associations":
            try:
                factor = float(event.get("factor", 0.995))
            except (TypeError, ValueError):
                continue
            _decay_associations(associations, factor)
            applied += 1
    return applied


def _update_association(
    associations: dict[tuple[str, str], float],
    cue_value: str,
    capability_name: str,
    delta: float,
) -> None:
    key = (cue_value, capability_name)
    current = associations.get(key, 0.0)
    associations[key] = max(-1.0, min(4.0, current + delta))


def _decay_associations(
    associations: dict[tuple[str, str], float],
    factor: float,
) -> None:
    to_remove = []
    for key, strength in associations.items():
        new_val = strength * factor
        if abs(new_val) < 0.001:
            to_remove.append(key)
        else:
            associations[key] = new_val
    for key in to_remove:
        del associations[key]


def _float_env(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(0.0, value)


def _int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(1, value)
