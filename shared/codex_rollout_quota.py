"""Read Codex's own entitlement-limit observations off disk.

Codex CLI records the provider's subscription limits into its session rollouts — ``limit_id:
"codex"`` with a primary window carrying ``used_percent`` / ``window_minutes`` / ``resets_at``,
plus a credits balance. That is a real headroom magnitude for the SUBSCRIPTION (not an API key),
and reading it calls no provider and spends nothing.

This exists because the estate long recorded codex quota as unobservable
(``local:codex:quota-probe:unobservable``; CASE-CAPACITY-ROUTING-001 R2, "use receipts and manual
refresh until observable"). That stopped being true upstream and nothing was watching for the exit
condition. Two consumers need the same reading — ``scripts/hapax-codex-quota-admission`` and
``scripts/hapax-platform-capability-receipts`` — so it lives here once rather than being
hand-synced twice. The estate has already paid for hand-synced duplicates drifting.

Two hazards are handled here, not by callers:

* **Content.** Rollouts hold the operator's prompts and the model's output. Only ``timestamp`` and
  ``payload.rate_limits`` are lifted out; nothing else is read, returned, or logged.
* **Size.** Rollouts reach gigabytes (one was 1.19GB in the 2026-08-09 OOM). Files are never read
  whole — reading is a bounded seek to the tail.

The same files also record WHICH MODEL and WHICH REASONING EFFORT a session actually ran under, and
``latest_model_observation`` lifts those. That is here for a routing reason, not a quota one.

On 2026-08-10 a lane was found to have run its entire life on a non-frontier model. It was not a bad
judgement call: ``scripts/hapax-codex`` carried ``model="gpt-5.5"`` and
``model_reasoning_effort="xhigh"`` as literals inside its argument array, with no flag and no
environment override, so every codex lane got them and no decision was ever taken. The operator's
standing rule — that a non-frontier choice needs a stated reason — was not merely unenforced but
UNREPRESENTABLE, because there was no decision point to attach a reason to.

Recording the model OBSERVED per session, rather than trusting what a launcher declares, does two
things. It satisfies the subject law that a measurement's subject is the tuple including M, so
results taken inside a session are attributable to one. And it accumulates the routing history the
spinal calculi will need: nothing today records which model ran which task-class at what outcome, so
a routing calculus going live would have nothing to calibrate against.

The read shape differs from the quota one, and the difference is measured rather than assumed. The
model is declared near the START of a rollout, but the opening lines are enormous: in a 13.2MB
sample ``"model"`` appeared nowhere in the first 64KB and nowhere in the last 512KB, yet its first
occurrence was line 5, ending at byte 76,335. So this is a bounded read of the first few LINES —
neither the first N bytes nor the tail.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_SESSIONS_DIR = Path(
    os.environ.get("HAPAX_CODEX_SESSIONS_DIR", str(Path.home() / ".codex" / "sessions"))
)
ROLLOUT_GLOB = "rollout-*.jsonl"
#: Newest-by-mtime rollouts to inspect before giving up. A session that has not spoken to the
#: provider recently carries no fresh snapshot, and scanning the whole history is unbounded.
ROLLOUT_SCAN_LIMIT = 12
#: Never read a rollout whole; seek back this far from the end.
ROLLOUT_TAIL_BYTES = 512 * 1024
#: Older than this and the observation is no longer "account-live".
DEFAULT_MAX_OBSERVATION_AGE_SECONDS = 3600
#: used_percent at or above this is a wall, not headroom. Callers must fail closed on it.
EXHAUSTED_USED_PERCENT = 100.0


class RolloutQuotaUnavailable(ValueError):
    """No fresh, usable limit observation exists. The message names the next action.

    Subclasses ValueError so callers that already fail closed on bad input keep doing so without
    a second except-clause — an unavailable observation is the same class of outcome as an invalid
    one: write nothing, hold the route.
    """


@dataclass(frozen=True)
class RolloutObservation:
    """Numeric limit facts only. Carries no session id, no path, no prompt or model content."""

    observed_at: datetime
    used_percent: float
    window_minutes: int

    @property
    def remaining_percent(self) -> float:
        return round(100.0 - self.used_percent, 4)


def _parse_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(microsecond=0)


def _rate_limits_from_line(line: str) -> tuple[datetime, dict] | None:
    """Return (timestamp, rate_limits) for a rollout line carrying one, else None."""
    if "rate_limits" not in line:
        return None
    try:
        record = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None
    limits = payload.get("rate_limits")
    if not isinstance(limits, dict):
        return None
    observed_at = _parse_utc(str(record.get("timestamp") or ""))
    if observed_at is None:
        return None
    return observed_at, limits


#: Lines to read from the head when observing the model. The model is declared early but the
#: opening lines are huge — measured 2026-08-10: line 5 of a 13.2MB rollout ended at byte 76,335,
#: and "model" appeared in neither the first 64KB nor the last 512KB. Read LINES, cap the bytes.
ROLLOUT_HEAD_LINES = 12
ROLLOUT_HEAD_MAX_BYTES = 2 * 1024 * 1024

#: Model observation gets its OWN staleness bound, and a far longer one than quota.
#:
#: Quota is perishable — a reading an hour old may be wrong about headroom right now, so the
#: 3600s bound is correct there. Which model served a session is not perishable: a session from
#: yesterday ran on the model it ran on, permanently. Reusing the quota bound made the production
#: receipt report `observed-model:unobservable` whenever no codex session had run in the last hour,
#: which is most of the time, and would have made the routing history it exists to accumulate
#: mostly empty.
#:
#: Still bounded rather than unlimited: the receipt attributes a capability "as recently
#: exercised", and a month-old session says little about what a lane launched today would get.
DEFAULT_MAX_MODEL_OBSERVATION_AGE_SECONDS = 7 * 24 * 3600


@dataclass(frozen=True)
class ModelObservation:
    """What a session ACTUALLY ran under. Identifiers only — no prompt or output content."""

    observed_at: datetime
    model: str
    reasoning_effort: str | None


def _head_lines(
    path: Path,
    *,
    max_lines: int = ROLLOUT_HEAD_LINES,
    max_bytes: int = ROLLOUT_HEAD_MAX_BYTES,
) -> list[str]:
    """First ``max_lines`` lines, abandoning the read at ``max_bytes``.

    Both bounds are load-bearing. A rollout's opening lines carry the full system prompt, so a
    line count alone does not bound the read; a byte cap alone does not reach the model, which
    sits past 64KB. Whichever trips first wins, and a truncated final line is discarded rather
    than parsed.
    """
    out: list[str] = []
    consumed = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                consumed += len(line)
                if consumed > max_bytes:
                    break
                out.append(line)
                if len(out) >= max_lines:
                    break
    except OSError:
        return []
    return out


def latest_model_observation(
    sessions_dir: Path | None = None,
    *,
    now: datetime,
    max_age_seconds: int = DEFAULT_MAX_MODEL_OBSERVATION_AGE_SECONDS,
) -> ModelObservation:
    """The model and reasoning effort the newest usable codex session actually ran under.

    Observed, never declared: a launcher's configured value is what it INTENDED, and the estate has
    now been bitten once by trusting an intention that nobody ever chose. Raises
    ``RolloutQuotaUnavailable`` with an actionable message when no fresh observation exists, so a
    caller can never mistake silence for a frontier model.
    """
    sessions_dir = sessions_dir or DEFAULT_SESSIONS_DIR
    if not sessions_dir.is_dir():
        raise RolloutQuotaUnavailable(
            f"no codex sessions directory at {sessions_dir}; run a codex session, or point "
            "HAPAX_CODEX_SESSIONS_DIR at one"
        )
    rollouts = sorted(
        sessions_dir.rglob(ROLLOUT_GLOB),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )[:ROLLOUT_SCAN_LIMIT]
    if not rollouts:
        raise RolloutQuotaUnavailable(f"no codex rollouts under {sessions_dir}")

    for path in rollouts:
        observed_at = _parse_utc_from_rollout_name(path.name)
        model: str | None = None
        effort: str | None = None
        for line in _head_lines(path):
            # Substring-match on the bare words, NOT on '"effort"'. The field is usually
            # "reasoning_effort", where the character before `effort` is an underscore, so a
            # quoted probe silently skipped every line carrying it — the prefilter discarded the
            # exact line it existed to find.
            if "model" not in line and "effort" not in line:
                continue
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            model = model or _first_str(record, "model")
            effort = (
                effort or _first_str(record, "reasoning_effort") or _first_str(record, "effort")
            )
            if observed_at is None:
                observed_at = _parse_utc(str(record.get("timestamp") or ""))
            # Do NOT stop at the model. Measured 2026-08-10: the model is declared on line 5 and
            # the reasoning effort on line 6, so breaking as soon as a model appeared returned
            # effort=None on every real rollout. Read the whole bounded window unless both are in
            # hand — effort is half the routing decision and dropping it silently would leave the
            # observation looking complete while missing the axis the operator actually raised.
            if model and effort:
                break
        if not model:
            continue
        if observed_at is None:
            try:
                observed_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            except OSError:
                continue
        age = (now - observed_at).total_seconds()
        if age < 0 or age > max_age_seconds:
            continue
        return ModelObservation(observed_at=observed_at, model=model, reasoning_effort=effort)

    raise RolloutQuotaUnavailable(
        f"no codex session under {sessions_dir} recorded a model within {max_age_seconds}s; "
        "run a codex session so the CLI writes a fresh rollout"
    )


def _first_str(record: object, key: str) -> str | None:
    """Depth-first search for the first string value under ``key``.

    The model appears at varying depths across rollout record shapes, and pinning one path would
    make this brittle against a CLI upgrade — which is the failure mode this function exists to
    detect.
    """
    if isinstance(record, dict):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        for nested in record.values():
            found = _first_str(nested, key)
            if found:
                return found
    elif isinstance(record, list):
        for item in record:
            found = _first_str(item, key)
            if found:
                return found
    return None


def _parse_utc_from_rollout_name(name: str) -> datetime | None:
    """Rollout filenames lead with an ISO-ish timestamp; cheaper than parsing a huge first line."""
    stem = name.removeprefix("rollout-")
    candidate = stem[:19].replace("_", "-")
    parts = candidate.split("T")
    if len(parts) != 2:
        return None
    try:
        return datetime.fromisoformat(f"{parts[0]}T{parts[1].replace('-', ':')}").replace(
            tzinfo=UTC
        )
    except ValueError:
        return None


def _tail_lines(path: Path, *, tail_bytes: int = ROLLOUT_TAIL_BYTES) -> list[str]:
    """Read at most tail_bytes from the end of path; return complete lines, oldest first."""
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - tail_bytes))
        blob = handle.read()
    lines = blob.decode("utf-8", errors="replace").splitlines()
    # The first line is probably cut in half by the seek, so drop it unless we read from byte 0.
    if size > tail_bytes and lines:
        lines = lines[1:]
    return lines


def latest_rollout_observation(
    sessions_dir: Path | None = None,
    *,
    now: datetime,
    max_age_seconds: int = DEFAULT_MAX_OBSERVATION_AGE_SECONDS,
) -> RolloutObservation:
    """Return the newest account-live limit observation Codex has already written to disk.

    Raises RolloutQuotaUnavailable, with an actionable message, when no fresh usable observation
    exists — including when the window is exhausted, which is a wall rather than headroom.
    """

    sessions_dir = sessions_dir or DEFAULT_SESSIONS_DIR
    if not sessions_dir.is_dir():
        raise RolloutQuotaUnavailable(
            f"no codex sessions directory at {sessions_dir}; run a codex session, or point "
            "HAPAX_CODEX_SESSIONS_DIR at one"
        )
    rollouts = sorted(
        sessions_dir.rglob(ROLLOUT_GLOB),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )[:ROLLOUT_SCAN_LIMIT]
    if not rollouts:
        raise RolloutQuotaUnavailable(f"no codex rollouts under {sessions_dir}")

    best: tuple[datetime, dict] | None = None
    for path in rollouts:
        try:
            lines = _tail_lines(path)
        except OSError:
            continue
        for line in reversed(lines):
            found = _rate_limits_from_line(line)
            if found is not None:
                if best is None or found[0] > best[0]:
                    best = found
                break
        if best is not None:
            break

    if best is None:
        raise RolloutQuotaUnavailable(
            f"no rate_limits snapshot in the newest {len(rollouts)} codex rollout(s); "
            "run a codex session so the CLI records a fresh limit observation"
        )

    observed_at, limits = best
    age = (now - observed_at).total_seconds()
    if age < 0:
        raise RolloutQuotaUnavailable("codex limit observation is timestamped in the future")
    if age > max_age_seconds:
        raise RolloutQuotaUnavailable(
            f"newest codex limit observation is {int(age)}s old (max {max_age_seconds}s); "
            "run a codex session so the CLI records a fresh limit observation"
        )

    primary = limits.get("primary")
    if not isinstance(primary, dict):
        raise RolloutQuotaUnavailable("codex limit observation carries no primary window")
    try:
        used_percent = float(primary["used_percent"])
        window_minutes = int(primary["window_minutes"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RolloutQuotaUnavailable(
            "codex primary window lacks usable used_percent/window_minutes"
        ) from exc
    if not 0.0 <= used_percent <= 1000.0 or window_minutes <= 0:
        raise RolloutQuotaUnavailable("codex primary window values are out of range")
    if used_percent >= EXHAUSTED_USED_PERCENT:
        raise RolloutQuotaUnavailable(
            f"codex primary window is exhausted (used_percent={used_percent}); that is a quota "
            "wall, not headroom — wait for the window to reset rather than admitting"
        )
    # _parse_utc already normalised to whole-second UTC.
    return RolloutObservation(
        observed_at=observed_at,
        used_percent=used_percent,
        window_minutes=window_minutes,
    )
