"""Local trace readers for the existing quota/spend ledger. No provider calls.

Only allowlisted numeric and categorical fields leave the readers. Prompts,
responses, account identifiers and credential stores are never projected.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from bisect import bisect_right
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from shared.quota_spend_ledger import PAID_CAPACITY_POOLS, QuotaMeasurement, QuotaSpendLedger
from shared.quota_wall import CLAUDE_HEADLESS_ROLES

MEASUREMENT_TTL = timedelta(hours=1)
# These are known capacities without a registry declaration, not invented routes.
UNDECLARED_FAMILIES = ("grok", "muse", "qwencloud", "fugu", "aperture")
FAMILY_ALIASES = {"glmcp": "glm", "local_tool": "local"}
SECRETISH = re.compile(r"(?i)(bearer\s|sk-[\w-]+|(?:api[_-]?key|secret|password)\s*[:=])")
ISO_TIME = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)")
# Claude CLI window name -> (capacity id, window). The weekly window is the pacing quantity.
CLAUDE_WINDOWS = {
    "seven_day": ("claude.subscription.weekly", "10080m"),
    "five_hour": ("claude.subscription.five_hour", "300m"),
}
# A file untouched for longer than the longest window cannot hold an open window's reading.
CLAUDE_WINDOW_HORIZON = timedelta(days=8)
SERVED_STATUSES = frozenset({"allowed", "allowed_warning"})
# Hours in the window a wall's own evidence names. A window full at the refusal ends no later
# than the refusal plus its length, whether rolling, calendar or first-use, so a wall with no
# reset binds at most that long. This bounds the wall and invents no reset. A wall whose
# evidence names no window gets no bound: it binds until its reset or a witnessed serve.
WINDOW_HOURS = {"seven_day": 168, "weekly": 168, "five_hour": 5, "session": 5}
# Claude enumerates its own subscription windows (rate_limit_event.unifiedWindows: five_hour and
# seven_day only), so any Claude wall binds at most its longest window, including one whose
# evidence names no window or states a later reset. The eight-day source horizon relies on it:
# no Claude wall in a file untouched for longer can still be live.
CLAUDE_LONGEST_WINDOW_HOURS = WINDOW_HOURS["seven_day"]
# Burn pairs: closer than the minimum the rate is noise; beyond the maximum it is history.
BURN_MIN_SPAN = timedelta(minutes=20)
BURN_MAX_SPAN = timedelta(hours=6)
# An optional bracketed alias suffix, as in the 1M-context `claude-opus-5[1m]`.
CLAUDE_MODEL = re.compile(r"\Aclaude-[a-z0-9.-]+(?:\[[a-z0-9]+\])?\Z")
KIMI_RESPONSE = re.compile(
    rf"({ISO_TIME.pattern})\s+[A-Z]+\s+llm response\s.*?\boutputTokens=(\d+)\b"
)


class TraceReadError(ValueError):
    """An existing source could not be read; messages contain no source contents."""


def instant(value: Any) -> datetime | None:
    try:
        if isinstance(value, (float, int)) and not isinstance(value, bool):
            return datetime.fromtimestamp(value, UTC)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo is not None else None
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if not isinstance(value, bool) and math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def source_ref(path: Path, kind: str) -> str:
    # Hash paths because CLI session paths can encode private working directories.
    digest = hashlib.sha256(str(path).encode()).hexdigest()[:16]
    return f"local-trace:{kind}:{digest}"


def json_lines(path: Path, *, contains: bytes | None = None):
    try:
        with path.open("rb") as stream:
            for line in stream:
                if not line.strip() or (contains is not None and contains not in line):
                    continue
                try:
                    value = json.loads(line)
                except ValueError:
                    # A live writer's unfinished last line has no newline yet; any other
                    # malformed line is corruption.
                    if not line.endswith(b"\n"):
                        return
                    raise
                if not isinstance(value, dict):
                    raise ValueError("object required")
                yield value
    except (OSError, ValueError) as exc:
        raise TraceReadError(f"corrupt_or_unreadable_source:{source_ref(path, 'jsonl')}") from exc


def json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
        if not isinstance(value, dict):
            raise ValueError("object required")
        return value
    except (OSError, ValueError) as exc:
        raise TraceReadError(f"corrupt_or_unreadable_source:{source_ref(path, 'json')}") from exc


def measurement(capacity_id: str, *, reason: str = "no_local_quota_quantity", **fields):
    return QuotaMeasurement(capacity_id=capacity_id, reason_code=reason, **fields)


def evidence(capacity_id: str, *, at: datetime, reset=None, **fields) -> QuotaMeasurement:
    fresh_until = min(at + MEASUREMENT_TTL, reset) if reset else at + MEASUREMENT_TTL
    return QuotaMeasurement(
        capacity_id=capacity_id,
        observed_at=at,
        resets_at=reset,
        measurement_fresh_until=fresh_until,
        **fields,
    )


def burn_rows(readings: list[QuotaMeasurement]) -> list[QuotaMeasurement]:
    """Percent of a window used per hour, derived from two readings of that same window.

    The newest reading is paired with the oldest one of the same capacity and the same reset
    between BURN_MAX_SPAN and BURN_MIN_SPAN before it: a reset between readings makes their
    difference meaningless, a short pair is noise, and a falling pair is not a burn. This is the
    pool's burn; it is the seat's own only on a pool the seat has to itself.
    """
    windows = defaultdict(list)
    for row in readings:
        if row.label == "observed" and row.unit == "percent_used" and row.resets_at:
            windows[row.capacity_id].append(row)
    rows = []
    for capacity_id, series in sorted(windows.items()):
        newest = max(series, key=lambda row: row.observed_at)
        earlier = [
            row
            for row in series
            if row.resets_at == newest.resets_at
            and newest.observed_at - BURN_MAX_SPAN <= row.observed_at
            and row.observed_at <= newest.observed_at - BURN_MIN_SPAN
        ]
        if not earlier:
            continue
        oldest = min(earlier, key=lambda row: row.observed_at)
        if newest.quantity < oldest.quantity:
            continue
        hours = (newest.observed_at - oldest.observed_at).total_seconds() / 3600
        rows.append(
            evidence(
                f"{capacity_id}.burn",
                at=newest.observed_at,
                reset=newest.resets_at,
                quantity=round((newest.quantity - oldest.quantity) / hours, 6),
                unit="percent_used_per_hour",
                window=f"[{oldest.observed_at.isoformat()},{newest.observed_at.isoformat()}]",
                label="derived",
                source=newest.source,
                details={
                    "from_percent": oldest.quantity,
                    "to_percent": newest.quantity,
                    "hours": round(hours, 4),
                    "from_source": oldest.source,
                },
            )
        )
    return rows


def read_codex_token_count(
    sessions_root: Path, *, now: datetime | None = None
) -> list[QuotaMeasurement]:
    """Select by event time across all rollouts; mtime never supplies freshness.

    An event dated after ``now`` (clock skew) is ignored rather than shadowing current limits.
    """
    samples = []
    window_samples = []
    local_usage_times = []
    latest = None
    for path in sorted(sessions_root.glob("**/rollout-*.jsonl")):
        previous_total = 0.0
        for event in json_lines(path, contains=b'"token_count"'):
            payload = event.get("payload") or {}
            if not isinstance(payload, dict) or payload.get("type") != "token_count":
                continue
            at = instant(event.get("timestamp"))
            if at is None or (now is not None and at > now):
                continue
            info = payload.get("info") or {}
            total = number((info.get("total_token_usage") or {}).get("total_tokens"))
            if total is not None:
                if total != previous_total:
                    local_usage_times.append(at)
                previous_total = total
            elif info:
                # Unaccountable local activity prevents an unattributed claim.
                local_usage_times.append(at)
            limits = payload.get("rate_limits") or {}
            primary = limits.get("primary") or {}
            used = number(primary.get("used_percent"))
            if used is None or used < 0 or limits.get("limit_id") not in {None, "codex"}:
                continue
            # Retain only the credit series for attribution. Holding every
            # provider payload makes a full-history scan exceed the timer's
            # memory ceiling; only the newest payload supplies current limits.
            samples.append((at, str(path), number((limits.get("credits") or {}).get("balance"))))
            # Primary-window readings as bare numbers, for the burn between two of them.
            window_samples.append(
                (at, used, primary.get("resets_at"), number(primary.get("window_minutes")), path)
            )
            if latest is None or at >= latest[0]:
                latest = (at, str(path), limits)
    if not samples:
        return [measurement("codex.subscription.weekly", reason="no_token_count_event")]
    samples.sort(key=lambda row: (row[0], row[1]))
    at, path_text, limits = latest
    path = Path(path_text)
    rows = []
    for name in ("primary", "secondary"):
        data = limits.get(name) or {}
        used = number(data.get("used_percent"))
        if used is None:
            continue
        minutes = number(data.get("window_minutes"))
        suffix = "weekly" if minutes == 10080 else name
        rows.append(
            evidence(
                f"codex.subscription.{suffix}",
                at=at,
                reset=instant(data.get("resets_at")),
                quantity=used,
                unit="percent_used",
                window=f"{minutes:g}m" if minutes else None,
                label="observed",
                source=source_ref(path, "codex_rollout_token_count"),
            )
        )
    balance = number((limits.get("credits") or {}).get("balance"))
    if balance is not None:
        rows.append(
            evidence(
                "codex.credits.balance",
                at=at,
                quantity=balance,
                unit="credits",
                window="balance_at_event",
                label="observed",
                source=source_ref(path, "codex_rollout_token_count"),
            )
        )
    local_usage_times.sort()
    for left, right in zip(samples, samples[1:], strict=False):
        old = left[2]
        new = right[2]
        activity = bisect_right(local_usage_times, right[0]) - bisect_right(
            local_usage_times, left[0]
        )
        if (
            old is not None
            and new is not None
            and new < old
            and right[0] > left[0]
            and activity == 0
        ):
            rows.append(
                evidence(
                    "codex.credits.unattributed_consumption",
                    at=right[0],
                    quantity=old - new,
                    unit="credits",
                    label="derived",
                    window=f"[{left[0].isoformat()},{right[0].isoformat()}]",
                    source=source_ref(Path(right[1]), "codex_balance_difference"),
                    reason_code="balance_drop_without_local_usage",
                    details={"previous_balance": old, "balance": new},
                )
            )
    newest_at, _, newest_reset, minutes, _ = max(window_samples, key=lambda row: row[0])
    in_window = [row for row in window_samples if row[2:4] == (newest_reset, minutes)]
    rows.extend(
        burn_rows(
            [
                evidence(
                    f"codex.subscription.{'weekly' if minutes == 10080 else 'primary'}",
                    at=sample_at,
                    reset=instant(reset),
                    quantity=used,
                    unit="percent_used",
                    label="observed",
                    source=source_ref(sample_path, "codex_rollout_token_count"),
                )
                for sample_at, used, reset, _, sample_path in in_window
                if newest_at - BURN_MAX_SPAN <= sample_at
            ]
        )
    )
    return rows


def receipt_fields(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_bytes())
        if not isinstance(value, dict):
            raise ValueError("object required")
        return value
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise TraceReadError(f"corrupt_or_unreadable_source:{source_ref(path, 'receipt')}") from exc


def claude_wall_receipt(path: Path, data: dict[str, Any]) -> bool:
    """Claude's by its route or provider; a lane receipt without either, by its role."""
    route, provider = str(data.get("route_id") or ""), str(data.get("provider") or "")
    if route or provider:
        return route.startswith("claude.") or provider.startswith("anthropic-claude")
    return path.name.startswith("claude") or data.get("role") in CLAUDE_HEADLESS_ROLES


def read_receipt_measurements(receipts: Path, family: str) -> list[QuotaMeasurement]:
    patterns = {
        # Headless lanes name their wall receipt by role (`beta-quota-wall.yaml`).
        "claude": ("*quota-wall*.yaml",),
        "glm": ("*glm*quota-wall*.yaml", "*glmcp-quota-admission*.yaml"),
        "agy": ("*agy-quota-admission*.yaml", "*agy*quota-wall*.yaml"),
    }
    rows = []
    latest_admission = None
    for path in sorted({p for pattern in patterns[family] for p in receipts.glob(pattern)}):
        data = receipt_fields(path)
        if family == "claude" and not claude_wall_receipt(path, data):
            continue
        at = instant(data.get("observed_at") or data.get("detected_at"))
        if at is None:
            continue
        # PAYG admissions cannot measure the subscription allowance.
        if data.get("capacity_pool") == "api_paid_spend" or data.get("payg_fallback") is True:
            continue
        used = number(data.get("used_percent"))
        if used is not None:
            rows.append(
                evidence(
                    f"{family}.subscription.receipt",
                    at=at,
                    quantity=used,
                    unit="percent_used",
                    window=str(data.get("window_minutes", "unknown")),
                    label="observed",
                    reset=instant(data.get("resets_at")),
                    source=source_ref(path, "quota_receipt"),
                )
            )
        elif (
            data.get("status") in {"quota_blocked", "quota_exhausted"} or "quota-wall" in path.name
        ):
            rows.append(
                evidence(
                    f"{family}.subscription.wall",
                    at=at,
                    label="wall-signal",
                    unit="refusal",
                    reset=instant(data.get("resets_at")),
                    source=source_ref(path, "quota_wall_receipt"),
                    reason_code="provider_refusal_without_fraction",
                    details={
                        "binds_at_most_hours": WINDOW_HOURS.get(
                            str(data.get("rate_limit_type")),
                            CLAUDE_LONGEST_WINDOW_HOURS if family == "claude" else None,
                        )
                    },
                )
            )
        elif data.get("status") == "quota_available":
            if latest_admission is None or at > latest_admission[0]:
                latest_admission = (at, path)
    if latest_admission:
        at, path = latest_admission
        rows.append(
            measurement(
                f"{family}.subscription.admission_basis",
                reason="admission_witness_has_no_quantity",
                source=source_ref(path, "admission_receipt"),
                observed_at=at,
                details={"basis": "supported_tool_witness_not_a_quota_fraction"},
            )
        )
    return rows


def claude_rate_limit_windows(info: Any) -> dict[str, tuple[float, datetime]]:
    """Subscription windows reported in one Claude CLI ``rate_limit_info``, as percent used.

    Reads ``unifiedWindows.{five_hour,seven_day}`` and the older single-window form, where
    ``rateLimitType`` names the window its own ``utilization`` describes. A window needs a
    numeric, non-negative utilization and a reset; anything else is absent, never zero.
    """
    if not isinstance(info, dict):
        return {}
    candidates = {}
    if info.get("rateLimitType") in CLAUDE_WINDOWS:
        candidates[info["rateLimitType"]] = info
    unified = info.get("unifiedWindows")
    if isinstance(unified, dict):
        candidates.update((name, unified[name]) for name in CLAUDE_WINDOWS if name in unified)
    windows = {}
    for name, window in candidates.items():
        utilization = window.get("utilization") if isinstance(window, dict) else None
        reset = instant(window.get("resetsAt")) if isinstance(window, dict) else None
        if (
            isinstance(utilization, bool)
            or not isinstance(utilization, (int, float))
            or not math.isfinite(utilization)
            or utilization < 0
            or reset is None
        ):
            continue
        windows[name] = (round(utilization * 100, 6), reset)
    return windows


def claude_window_rows(
    windows, *, at: datetime, source: str, details: dict[str, Any] | None = None
) -> list[QuotaMeasurement]:
    # A reading taken at or after its own reset describes a window that has closed.
    return [
        evidence(
            CLAUDE_WINDOWS[name][0],
            at=at,
            reset=reset,
            quantity=used,
            unit="percent_used",
            window=CLAUDE_WINDOWS[name][1],
            label="observed",
            source=source,
            details=details or {},
        )
        for name, (used, reset) in windows.items()
        if at < reset
    ]


def recently_changed(path: Path, *, now: datetime) -> bool:
    """A scan filter only; a file's mtime never dates the evidence inside it."""
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC) >= now - CLAUDE_WINDOW_HORIZON
    except OSError:
        return False


def read_claude_stream_windows(stream_root: Path, *, now: datetime) -> list[QuotaMeasurement]:
    """Windows and refusals from ``rate_limit_event`` records in Claude CLI stream-json output.

    The event carries no clock, so each kind is dated on its safe side. A reading takes the
    newest dated record written before it (early: it can only look older). A refusal takes the
    first dated record written after it, or the file mtime, clamped to ``now`` (late: it can only
    look newer, so an older reading never lifts it); its early bound is kept as ``earliest_at``.
    A reading with nothing dated before it is not evidence. Only a session whose init names an
    Anthropic model without an API key witnesses the subscription: gateways speak the same wire
    format. A line that does not parse is not evidence (a live stream can end mid-line).
    """
    rows = []
    for path in sorted(stream_root.glob("*/output.jsonl")):
        if not recently_changed(path, now=now):
            continue
        subscription_sessions = set()
        dated = None
        pending = []  # refusals waiting for the next dated record
        source = source_ref(path, "claude_stream_rate_limit_event")
        try:
            with path.open("rb") as stream:
                for line in stream:
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(record, dict):
                        continue
                    at = instant(record.get("timestamp")) if "timestamp" in record else None
                    if at is not None:
                        rows.extend(stream_wall(*wall, at=at, now=now) for wall in pending)
                        pending = []
                        if dated is None or at > dated:
                            dated = at
                    session = record.get("session_id")
                    if record.get("type") == "system" and record.get("subtype") == "init":
                        if (
                            CLAUDE_MODEL.fullmatch(str(record.get("model")))
                            and record.get("apiKeySource") == "none"
                        ):
                            subscription_sessions.add(session)
                        continue
                    if record.get("type") != "rate_limit_event" or session not in (
                        subscription_sessions
                    ):
                        continue
                    info = record.get("rate_limit_info")
                    if not isinstance(info, dict) or (dated is not None and dated > now):
                        continue
                    if info.get("status") == "rejected":
                        pending.append((info, dated, source))
                    if dated is not None:
                        rows.extend(
                            claude_window_rows(
                                claude_rate_limit_windows(info),
                                at=dated,
                                source=source,
                                details=request_details(info),
                            )
                        )
            if pending:
                mtime = datetime.fromtimestamp(path.stat().st_mtime, UTC)
                rows.extend(stream_wall(*wall, at=mtime, now=now) for wall in pending)
        except OSError as exc:
            raise TraceReadError(
                f"corrupt_or_unreadable_source:{source_ref(path, 'claude_stream')}"
            ) from exc
    return rows


def overage_state(info: dict) -> bool | None:
    """True, False, or None when the event does not say. Recorded events carry a JSON boolean
    (423/423 local samples ``false``); an explicit false-y value, numeric or string, is False;
    any other present value is True (fail closed)."""
    value = info.get("isUsingOverage")
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return not (isinstance(value, str) and value.strip().lower() in {"false", "0", "0.0"})


def harness_window_hours(text: str) -> int:
    """Five hours for a "session limit" notice; any other Claude notice, "weekly limit" included,
    binds at most Claude's longest window."""
    if "session limit" in text.lower():
        return WINDOW_HOURS["session"]
    return CLAUDE_LONGEST_WINDOW_HOURS


def request_details(info: dict) -> dict[str, Any]:
    """Whether the subscription itself served the request the reading came with.

    ``subscription_served`` needs both an allowed status and an explicit non-overage flag:
    absent is "not established", never a serve.
    """
    status = info.get("status") if isinstance(info.get("status"), str) else None
    overage = overage_state(info)
    return {
        "status": status,
        "using_overage": int(overage is True),
        "subscription_served": int(status in SERVED_STATUSES and overage is False),
    }


def stream_wall(info: dict, earliest, source: str, *, at: datetime, now: datetime):
    """A refusal dated late: the later bound clamped to ``now``, the early bound kept beside it."""
    limit = info.get("rateLimitType")
    return evidence(
        "claude.subscription.rate_limit_rejected",
        at=min(max(at, earliest) if earliest else at, now),
        label="wall-signal",
        unit="refusal",
        reset=instant(info.get("resetsAt")),
        window=CLAUDE_WINDOWS.get(limit, (None, None))[1],
        source=source,
        reason_code="provider_rate_limit_rejected",
        details={
            "rate_limit_type": limit if isinstance(limit, str) else None,
            "earliest_at": earliest.isoformat() if earliest else None,
            "binds_at_most_hours": WINDOW_HOURS.get(limit, CLAUDE_LONGEST_WINDOW_HOURS)
            if isinstance(limit, str)
            else CLAUDE_LONGEST_WINDOW_HOURS,
        },
    )


def read_claude_probe_receipts(receipts: Path, *, now: datetime) -> list[QuotaMeasurement]:
    """Windows the account-live probe kept on its admission receipt.

    Only a receipt from the probe itself carries numbers: the subscription observation on the
    subscription auth surface, with the scrubbed-environment disclosure. An operator attestation
    or a passive serve never does, and a receipt without window keys remains an admission bit.
    """
    rows = []
    for path in sorted(receipts.glob("*claude-subscription-quota-admission*.yaml")):
        try:
            if not recently_changed(path, now=now) or b"_used_percent" not in path.read_bytes():
                continue
        except OSError:
            continue
        data = receipt_fields(path)
        at = instant(data.get("observed_at"))
        if (
            data.get("schema") != "hapax.claude_quota_admission.v1"
            or data.get("status") != "quota_available"
            or data.get("auth_surface") != "subscription"
            or data.get("observation") != "subscription_quota_headroom_observed"
            or not data.get("probe_environment_scrubbed")
            or at is None
            or at > now
        ):
            continue
        windows = {}
        for name in CLAUDE_WINDOWS:
            used = number(data.get(f"{name}_used_percent"))
            reset = instant(data.get(f"{name}_resets_at"))
            if used is not None and used >= 0 and reset is not None:
                windows[name] = (used, reset)
        source = source_ref(path, "claude_probe_admission_receipt")
        # The probe mints only for a request the subscription served (no refusal, no overage).
        # Witnessed at mint time by the probe (explicit allowed status, explicit non-overage);
        # a receipt without the field carries the numbers but never lifts a wall.
        served = {"subscription_served": int(data.get("subscription_served") is True)}
        rows.extend(claude_window_rows(windows, at=at, source=source, details=served))
    return rows


def read_claude_wall_and_spend(
    receipts_dir: Path, transcript_roots: Path, *, now: datetime, stream_root: Path | None = None
):
    readings = read_claude_probe_receipts(receipts_dir, now=now)
    if stream_root is not None:
        readings.extend(read_claude_stream_windows(stream_root, now=now))
    newest: dict[tuple[str, str | None], QuotaMeasurement] = {}
    for row in readings:
        key = (row.capacity_id, row.window)
        if key not in newest or row.observed_at > newest[key].observed_at:
            newest[key] = row
    weekly = newest.pop(("claude.subscription.weekly", "10080m"), None)
    rows = [
        weekly
        or measurement("claude.subscription.weekly", reason="no_claude_rate_limit_window_observed")
    ]
    rows.extend(sorted(newest.values(), key=lambda row: (row.capacity_id, row.window or "")))
    rows.extend(burn_rows(readings))
    walls = read_receipt_measurements(receipts_dir, "claude")
    messages: dict[str, tuple[datetime, dict[str, float]]] = {}
    token_fields = (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    )
    for path in sorted(transcript_roots.glob("**/*.jsonl")):
        # Every spend window ends at most a week back; an older file holds nothing in one.
        if not recently_changed(path, now=now):
            continue
        for event in json_lines(path):
            at = instant(event.get("timestamp"))
            msg = event.get("message") or {}
            if not isinstance(msg, dict) or at is None or at > now:
                continue
            if event.get("isApiErrorMessage") or event.get("type") == "system":
                content = msg.get("content", event.get("content", ""))
                text = json.dumps(content)
                if re.search(
                    r"(?i)(usage limit|weekly limit|session limit|hit your limit|quota.exhausted)",
                    text,
                ):
                    reset_match = ISO_TIME.search(text)
                    walls.append(
                        evidence(
                            "claude.subscription.harness_wall",
                            at=at,
                            label="wall-signal",
                            unit="refusal",
                            reset=instant(reset_match[0]) if reset_match else None,
                            source=source_ref(path, "claude_harness_limit_notice"),
                            reason_code="harness_limit_notice",
                            # Recorded wording: "You've hit your weekly limit · resets …" and
                            # "You've hit your session limit · resets …" (five-hour).
                            details={"binds_at_most_hours": harness_window_hours(text)},
                        )
                    )
            usage = msg.get("usage")
            msg_id = msg.get("id")
            if msg.get("role") != "assistant" or not msg_id or not isinstance(usage, dict):
                continue
            values = {k: max(0.0, number(usage.get(k)) or 0.0) for k in token_fields}
            previous = messages.get(msg_id)
            if previous:
                at = min(at, previous[0])
                values = {k: max(previous[1][k], values[k]) for k in token_fields}
            messages[msg_id] = (at, values)
    # Retain the latest harness wall and each receipt wall, not every duplicated notice.
    harness = [row for row in walls if row.capacity_id.endswith("harness_wall")]
    walls = [row for row in walls if not row.capacity_id.endswith("harness_wall")]
    if harness:
        # The newest notice, and the newest notice for each reset still ahead: a later notice
        # with a nearer reset must not hide an earlier wall that binds longer.
        newest = max(harness, key=lambda row: row.observed_at)
        live = {}
        for row in sorted(harness, key=lambda row: row.observed_at):
            if row.resets_at is not None and row.resets_at > now:
                live[row.resets_at] = row
        walls.extend([newest, *(row for row in live.values() if row is not newest)])
    rows.extend(walls)
    windows = {
        "5h": (now - timedelta(hours=5), now),
        "day": (now.replace(hour=0, minute=0, second=0, microsecond=0), now),
        "weekly": (now - timedelta(days=7), now),
    }
    resets = [row.resets_at for row in walls if row.resets_at is not None]
    if resets:
        end = max(resets)
        while end <= now:
            end += timedelta(days=7)
        while end - timedelta(days=7) > now:
            end -= timedelta(days=7)
        windows["weekly"] = (end - timedelta(days=7), end)
    for name, (start, end) in windows.items():
        entries = [(at, values) for at, values in messages.values() if start <= at < end]
        if not entries:
            rows.append(
                measurement(
                    f"claude.spend.{name}",
                    reason="no_message_ids_in_window" if messages else "no_message_ids",
                )
            )
            continue
        rows.append(
            evidence(
                f"claude.spend.{name}",
                at=max(at for at, _ in entries),
                quantity=sum(sum(values.values()) for _, values in entries),
                unit="tokens",
                label="derived",
                window=f"[{start.isoformat()},{end.isoformat()})",
                source="local-trace:claude_transcript_usage_deduplicated",
                details={
                    "message_id_count": len(entries),
                    "window_basis": "receipt_reset"
                    if name == "weekly" and resets
                    else "rolling_or_utc_day",
                },
            )
        )
    return rows


def read_kimi_403_signal(kimi_sessions_root: Path) -> list[QuotaMeasurement]:
    files_with_hit = hits = global_hits = 0
    timestamps = []
    # The newest served response is the post-wall provider observation a wall waits for.
    last_response = None
    global_path = kimi_sessions_root.parent / "logs/kimi-code.log"
    paths = sorted(kimi_sessions_root.glob("**/logs/kimi-code.log"))
    for path in [*paths, *([global_path] if global_path.exists() else [])]:
        file_hits = 0
        try:
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    served = KIMI_RESPONSE.match(line) if "llm response" in line else None
                    served_at = instant(served[1]) if served and path != global_path else None
                    if served_at and int(served[2]) > 0:
                        if last_response is None or served_at > last_response[0]:
                            last_response = (served_at, int(served[2]))
                    if "403" not in line or not re.search(r"(?i)(weekly|7-day).*usage limit", line):
                        continue
                    file_hits += 1
                    match = ISO_TIME.match(line)
                    if match and path != global_path:
                        timestamps.append(instant(match[0]))
        except (OSError, UnicodeError) as exc:
            raise TraceReadError(
                f"corrupt_or_unreadable_source:{source_ref(path, 'kimi_log')}"
            ) from exc
        if path == global_path:
            global_hits = file_hits
        else:
            hits += file_hits
            files_with_hit += bool(file_hits)
    # Only a "weekly (7-day)" 403 is a wall here; recorded wording: "Your quota will reset when
    # the current 7-day window ends", so the wall binds at most a week.
    details = {
        "files_with_hit": files_with_hit,
        "hit_count": hits,
        "global_log_hits": global_hits,
        "binds_at_most_hours": WINDOW_HOURS["weekly"],
    }
    responses = []
    if last_response is not None:
        responses.append(
            evidence(
                "kimi.usage.last_response",
                at=last_response[0],
                quantity=last_response[1],
                unit="tokens",
                window="last_response",
                label="observed",
                source="local-trace:kimi_session_logs_llm_response",
            )
        )
    if timestamps:
        details["first_seen_at"] = min(timestamps).isoformat()
        return [
            evidence(
                "kimi.subscription.wall",
                at=max(timestamps),
                label="wall-signal",
                unit="refusal",
                source="local-trace:kimi_session_logs_http_403",
                details=details,
                reason_code="weekly_403_without_mechanical_reset",
            ),
            *responses,
        ]
    return [
        measurement(
            "kimi.subscription.weekly",
            reason="no_timestamped_weekly_403_or_fraction",
            source="local-trace:kimi_session_logs_http_403",
            details=details,
        ),
        *responses,
    ]


def read_other_family(home: Path, family: str) -> list[QuotaMeasurement]:
    """Inspect bounded known telemetry surfaces, never login/config or chat content."""
    if family in {"fugu", "aperture"}:
        return [
            measurement(
                f"{family}.capacity",
                reason="no_existing_local_usage_capture"
                if family == "fugu"
                else "no_reachable_local_resource_capture",
            )
        ]
    roots = {
        "grok": (".grok/sessions", "**/events.jsonl"),
        "muse": (".local/share/muse", "**/session.jsonl"),
        "vibe": (".vibe/logs/session", "**/meta.json"),
        "qwencloud": (".qwencloud/logs", "**/*.jsonl"),
    }
    root, pattern = roots[family]
    paths = sorted((home / root).glob(pattern))
    rows = []
    usage_rows = []
    for path in paths:
        events = json_lines(path) if path.suffix == ".jsonl" else [json_object(path)]
        for event in events:
            if family == "muse" and event.get("payload_type") == "runtime.session":
                model_event = (event.get("payload") or {}).get("event") or {}
                # Muse's journal records microseconds since epoch, not seconds.
                micros = number(event.get("recorded_at"))
                usage_at = instant(micros / 1_000_000) if micros is not None else None
                if model_event.get("kind") == "model_completed" and usage_at is not None:
                    usage = model_event.get("usage") or {}
                    for field in ("input_tokens", "output_tokens"):
                        value = number(usage.get(field))
                        if value is not None:
                            usage_rows.append(
                                evidence(
                                    f"muse.usage.{field}",
                                    at=usage_at,
                                    quantity=value,
                                    unit="tokens",
                                    window="last_model_completion",
                                    label="observed",
                                    source=source_ref(path, "muse_model_completed_usage"),
                                )
                            )
            if family == "vibe":
                stats = event.get("stats") or {}
                usage_at = instant(event.get("end_time"))
                if usage_at is not None:
                    for field, unit in (
                        ("session_total_llm_tokens", "tokens"),
                        ("session_cost", "USD"),
                    ):
                        value = number(stats.get(field))
                        if value is not None:
                            usage_rows.append(
                                evidence(
                                    f"vibe.usage.{field}",
                                    at=usage_at,
                                    quantity=value,
                                    unit=unit,
                                    window="completed_session",
                                    label="derived",
                                    source=source_ref(path, "vibe_session_stats"),
                                )
                            )
            at = instant(
                event.get("timestamp")
                or event.get("ts")
                or event.get("observed_at")
                or event.get("recorded_at")
            )
            # No recursive search: user/tool text must never masquerade as provider telemetry.
            limits = event.get("rate_limits")
            if at is not None and isinstance(limits, dict):
                used = number(limits.get("used_percent"))
                if used is not None:
                    rows.append(
                        evidence(
                            f"{family}.subscription.usage",
                            at=at,
                            quantity=used,
                            unit="percent_used",
                            window=str(limits.get("window_minutes", "unknown")),
                            reset=instant(limits.get("resets_at")),
                            label="observed",
                            source=source_ref(path, f"{family}_provider_usage"),
                        )
                    )
            if at is not None and event.get("type") in {"quota_exhausted", "rate_limit_exceeded"}:
                rows.append(
                    evidence(
                        f"{family}.subscription.wall",
                        at=at,
                        label="wall-signal",
                        unit="refusal",
                        reset=instant(event.get("resets_at")),
                        source=source_ref(path, f"{family}_limit_event"),
                        reason_code="provider_limit_event_without_fraction",
                    )
                )
    if rows:
        rows = [max(rows, key=lambda row: row.observed_at)]
    else:
        rows = [
            measurement(
                f"{family}.capacity",
                reason="no_provider_quantity_in_local_traces"
                if paths
                else "local_usage_source_absent",
                source=f"local-trace:{family}_usage_scan",
                details={"files_scanned": len(paths)},
            )
        ]
    if family == "vibe":
        path = home / ".vibe/whoami_cache.json"
        if path.exists():
            cache = json_object(path)
            # Keyed by account hash; project only the plan type, never the key or identifiers.
            plans = {
                entry.get("payload", {}).get("plan_type")
                for entry in cache.values()
                if isinstance(entry, dict)
            }
            rows[0] = rows[0].model_copy(
                update={
                    "details": {
                        **rows[0].details,
                        "plan_type": "api" if "api" in plans else "unknown",
                    }
                }
            )
    for capacity_id in sorted({row.capacity_id for row in usage_rows}):
        rows.append(
            max(
                (row for row in usage_rows if row.capacity_id == capacity_id),
                key=lambda row: row.observed_at,
            )
        )
    return rows


def collect_measurements(
    home: Path, receipts: Path, *, now: datetime
) -> dict[str, list[QuotaMeasurement]]:
    """One reading per family. A family whose source is unreadable becomes ``unobserved`` with a
    typed reason; it never stops the other families or the admission ledger around them."""
    readers = {
        "codex": lambda: read_codex_token_count(home / ".codex/sessions", now=now),
        "claude": lambda: read_claude_wall_and_spend(
            receipts,
            home / ".claude/projects",
            now=now,
            stream_root=home / ".cache/hapax/claude-headless",
        ),
        "kimi": lambda: read_kimi_403_signal(home / ".kimi-code/sessions"),
    }
    for family in ("glm", "agy"):
        readers[family] = lambda family=family: (
            read_receipt_measurements(receipts, family)
            or [measurement(f"{family}.subscription", reason="no_quantity_bearing_receipt")]
        )
    for family in (*UNDECLARED_FAMILIES, "vibe"):
        readers[family] = lambda family=family: read_other_family(home, family)
    result = {}
    for family, read in readers.items():
        try:
            result[family] = read()
        except TraceReadError as exc:
            result[family] = [
                measurement(
                    f"{family}.capacity",
                    reason="corrupt_or_unreadable_source",
                    details={"source": str(exc).partition(":")[2]},
                )
            ]
        except Exception as exc:  # noqa: BLE001 - the family boundary: nothing crosses it
            # Anything else a reader raises also stays inside its family; only the type is kept.
            result[family] = [
                measurement(
                    f"{family}.capacity",
                    reason="reader_error",
                    details={"error": type(exc).__name__},
                )
            ]
    return result


def served_by_the_subscription(row: QuotaMeasurement) -> bool:
    """True only for a reading that says the subscription itself served its request.

    Positive evidence, never absence of it: a refused or overage reading says no, and a row
    from a source that cannot tell (a served Kimi response may be booster-paid; derived spend
    may be another provider) does not say yes.
    """
    return row.details.get("subscription_served") == 1


def wall_is_live(wall: QuotaMeasurement, rows, *, now: datetime) -> bool:
    """A wall binds until its reset or a newer provider observation of the same family.

    A wall's next act asks for a post-wall provider observation; this is that check. Only
    ``observed`` rows from a request the subscription served count (transcript-derived spend can
    come from another provider speaking the same wire format; a refusal or an overage serve says
    the window is spent). A served request of any window means no window was binding, so a wall
    that names no window lifts on it; a wall scoped to one window needs a reading of that window.
    """
    if wall.label != "wall-signal" or wall.observed_at is None:
        return False
    if wall.resets_at is not None and now >= wall.resets_at:
        return False
    family = wall.capacity_id.split(".", 1)[0]
    # The bound caps a stated reset too: a window full at the refusal ends by refusal + length.
    bound = wall.details.get("binds_at_most_hours")
    if isinstance(bound, int) and now >= wall.observed_at + timedelta(hours=bound):
        return False
    return not any(
        row.label == "observed"
        and served_by_the_subscription(row)
        and row.capacity_id.split(".", 1)[0] == family
        and row.observed_at is not None
        and wall.observed_at < row.observed_at <= now
        and (wall.window is None or row.window == wall.window)
        for row in rows
    )


def freeze_predicate(rows: list[QuotaMeasurement], *, now: datetime) -> dict[str, Any]:
    frozen = [
        row
        for row in rows
        if row.resets_at
        and row.observed_at
        and row.observed_at <= now < row.resets_at
        and (
            (row.label == "wall-signal" and wall_is_live(row, rows, now=now))
            or (row.label == "observed" and row.unit == "percent_used" and row.quantity >= 100)
        )
    ]
    return {
        "schema": "hapax.freeze-predicate.v1",
        "active": bool(frozen),
        "families": sorted({row.capacity_id.split(".")[0] for row in frozen}),
        "until": min(row.resets_at for row in frozen if row.resets_at is not None)
        .isoformat()
        .replace("+00:00", "Z")
        if frozen
        else None,
        "source": "quota-spend-ledger:local-measurements",
    }


def enrich_ledger(
    ledger: QuotaSpendLedger,
    readings: dict[str, list[QuotaMeasurement]],
    *,
    registry: Any,
    now: datetime,
) -> QuotaSpendLedger:
    """Project registry declarations and trace evidence without changing admission."""
    routes = defaultdict(list)
    for route in registry.routes:
        family = FAMILY_ALIASES.get(str(route.platform), str(route.platform))
        routes[family].append(route)
    payload = ledger.model_dump(mode="json")
    payload["schema_version"] = 2
    snapshots = payload["quota_snapshots"]
    represented = set()
    for row in snapshots:
        route = next(
            (r for rs in routes.values() for r in rs if r.route_id == row["route_id"]), None
        )
        family = (
            FAMILY_ALIASES.get(str(route.platform), str(route.platform))
            if route
            else row.get("family", "local")
        )
        if family == "unknown":
            family = "local"
        row["family"] = family
        represented.add(family)
    for family in sorted(set(routes) | set(UNDECLARED_FAMILIES) | set(readings)):
        if family in represented:
            continue
        declared = routes.get(family, [])
        route = declared[0] if declared else None
        snapshots.append(
            {
                "snapshot_id": f"quota-{family}-measurement",
                "captured_at": now.isoformat(),
                "route_id": route.route_id if route else None,
                "provider": family,
                "capacity_pool": str(route.capacity_pool)
                if route
                else ("local_compute" if family == "aperture" else "subscription_quota"),
                "subscription_quota_state": "unknown",
                "evidence_refs": ["scripts/hapax-quota-telemetry-writer"],
                "operator_visible_reason": "Local evidence only; this snapshot grants no admission",
                "admission_compatible": False,
                "family": family,
            }
        )
    all_measurements = []
    for row in snapshots:
        family = row["family"]
        measures = readings.get(
            family, [measurement(f"{family}.capacity", reason="no_local_quantity_reader")]
        )
        # Reports stay separate and never overwrite provider measurements or mint freshness.
        measures = [
            *measures,
            *(r for r in ledger.operator_reports if r.capacity_id.startswith(f"{family}.")),
        ]
        primary = measures[0]
        row.update(primary.model_dump(mode="json"))
        row["measurements"] = [r.model_dump(mode="json") for r in measures[1:]]
        row["quota_snapshot_schema"] = 2
        declared = routes.get(family, [])
        measured = any(
            r.label in {"observed", "derived"} and r.measurement_is_fresh(now) for r in measures
        )
        stage = "declared-measured" if measured else "declared-unmeasured"
        next_act, owner = "Collect a provider quantity from local traces", "source"
        if not declared:
            stage, next_act = "usable-undeclared", "Declare the capability shape in the registry"
        budget_eligible = [
            route
            for route in declared
            if str(route.capacity_pool) not in PAID_CAPACITY_POOLS
            or any(
                route.paid_provider in budget.providers_allowed
                and route.paid_profile in budget.profiles_allowed
                for budget in ledger.active_paid_budgets(now)
            )
        ]
        # Routable from this ledger's own admission: a budget-eligible declared route whose
        # admission snapshot is fresh now. No second, strict receipt-applied registry read: the
        # agentic-trust boundary confines that loader to reporting.
        eligible_ids = {route.route_id for route in budget_eligible}
        if any(
            snapshot.get("admission_compatible", True)
            and snapshot.get("route_id") in eligible_ids
            and snapshot.get("subscription_quota_state") == "fresh"
            and (snapshot.get("fresh_until") is None or instant(snapshot["fresh_until"]) > now)
            for snapshot in snapshots
        ):
            stage, next_act, owner = (
                "routable",
                "Refresh measurements before they expire",
                "runtime",
            )
        if measured and stage != "routable":
            next_act, owner = (
                "Validate the existing route admission and capability evidence",
                "runtime",
            )
        if any(wall_is_live(r, measures, now=now) for r in measures):
            if stage == "routable":
                stage = "declared-measured" if measured else "declared-unmeasured"
            next_act, owner = (
                "Obtain a post-wall provider observation; reset alone grants no admission",
                "runtime",
            )
        if family == "vibe" and primary.details.get("plan_type") == "api":
            stage, next_act, owner = (
                "unusable",
                "Bind Vibe to the Team allowance with vibe --setup",
                "operator",
            )
        elif family == "qwencloud":
            stage, next_act, owner = (
                "unusable",
                "Resolve the terms ruling for a Kimi-harness binding",
                "operator",
            )
        elif family == "aperture":
            stage, next_act, owner = (
                "unusable",
                "Permit appendix-to-aperture runner connectivity",
                "operator",
            )
        elif family == "fugu":
            next_act = "Declare a fugu route with a read-only /v1/usage observation contract"
            owner = "source"
        row.update(stage=stage, next_act=next_act, owner=owner)
        all_measurements.extend(measures)
    payload["freeze"] = freeze_predicate(all_measurements, now=now)
    return QuotaSpendLedger.model_validate(payload)


def operator_report(*, family: str, reset: str, quote: str, at: datetime) -> QuotaMeasurement:
    if (
        not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", family)
        or SECRETISH.search(quote)
        or len(quote) > 500
    ):
        raise ValueError("invalid family or unsafe operator quote")
    parsed_reset = instant(reset)
    return evidence(
        f"{family}.operator.reset",
        at=at,
        reset=parsed_reset,
        label="operator-reported",
        source="operator:entered-report",
        unit="reset_time",
        reason_code=None if parsed_reset else "operator_reset_timezone_unspecified",
        details={"quote": quote, "reset_as_reported": reset},
    )
