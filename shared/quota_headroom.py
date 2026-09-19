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

MEASUREMENT_TTL = timedelta(hours=1)
# These are known capacities without a registry declaration, not invented routes.
UNDECLARED_FAMILIES = ("grok", "muse", "qwencloud", "fugu", "aperture")
FAMILY_ALIASES = {"glmcp": "glm", "local_tool": "local"}
SECRETISH = re.compile(r"(?i)(bearer\s|sk-[\w-]+|(?:api[_-]?key|secret|password)\s*[:=])")
ISO_TIME = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)")


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
                value = json.loads(line)
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


def read_codex_token_count(sessions_root: Path) -> list[QuotaMeasurement]:
    """Select by event time across all rollouts; mtime never supplies freshness."""
    samples = []
    local_usage_times = []
    latest = None
    for path in sorted(sessions_root.glob("**/rollout-*.jsonl")):
        previous_total = 0.0
        for event in json_lines(path, contains=b'"token_count"'):
            payload = event.get("payload") or {}
            if not isinstance(payload, dict) or payload.get("type") != "token_count":
                continue
            at = instant(event.get("timestamp"))
            if at is None:
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
    return rows


def receipt_fields(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_bytes())
        if not isinstance(value, dict):
            raise ValueError("object required")
        return value
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise TraceReadError(f"corrupt_or_unreadable_source:{source_ref(path, 'receipt')}") from exc


def read_receipt_measurements(receipts: Path, family: str) -> list[QuotaMeasurement]:
    patterns = {
        "claude": ("claude*quota-wall.yaml",),
        "glm": ("*glm*quota-wall*.yaml", "*glmcp-quota-admission*.yaml"),
        "agy": ("*agy-quota-admission*.yaml", "*agy*quota-wall*.yaml"),
    }
    rows = []
    latest_admission = None
    for path in sorted({p for pattern in patterns[family] for p in receipts.glob(pattern)}):
        data = receipt_fields(path)
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


def read_claude_wall_and_spend(receipts_dir: Path, transcript_roots: Path, *, now: datetime):
    rows = [measurement("claude.subscription.weekly", reason="no_mechanical_weekly_fraction")]
    walls = read_receipt_measurements(receipts_dir, "claude")
    messages: dict[str, tuple[datetime, dict[str, float]]] = {}
    token_fields = (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    )
    for path in sorted(transcript_roots.glob("**/*.jsonl")):
        for event in json_lines(path):
            at = instant(event.get("timestamp"))
            msg = event.get("message") or {}
            if not isinstance(msg, dict) or at is None or at > now:
                continue
            if event.get("isApiErrorMessage") or event.get("type") == "system":
                content = msg.get("content", event.get("content", ""))
                text = json.dumps(content)
                if re.search(
                    r"(?i)(usage limit|weekly limit|hit your limit|quota.exhausted)", text
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
        walls.append(max(harness, key=lambda row: row.observed_at))
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
    global_path = kimi_sessions_root.parent / "logs/kimi-code.log"
    paths = sorted(kimi_sessions_root.glob("**/logs/kimi-code.log"))
    for path in [*paths, *([global_path] if global_path.exists() else [])]:
        file_hits = 0
        try:
            with path.open(encoding="utf-8") as stream:
                for line in stream:
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
    details = {"files_with_hit": files_with_hit, "hit_count": hits, "global_log_hits": global_hits}
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
            )
        ]
    return [
        measurement(
            "kimi.subscription.weekly",
            reason="no_timestamped_weekly_403_or_fraction",
            source="local-trace:kimi_session_logs_http_403",
            details=details,
        )
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
    result = {
        "codex": read_codex_token_count(home / ".codex/sessions"),
        "claude": read_claude_wall_and_spend(receipts, home / ".claude/projects", now=now),
        "kimi": read_kimi_403_signal(home / ".kimi-code/sessions"),
    }
    for family in ("glm", "agy"):
        rows = read_receipt_measurements(receipts, family)
        result[family] = rows or [
            measurement(f"{family}.subscription", reason="no_quantity_bearing_receipt")
        ]
    for family in (*UNDECLARED_FAMILIES, "vibe"):
        result[family] = read_other_family(home, family)
    return result


def freeze_predicate(rows: list[QuotaMeasurement], *, now: datetime) -> dict[str, Any]:
    frozen = [
        row
        for row in rows
        if row.resets_at
        and row.observed_at
        and row.observed_at <= now < row.resets_at
        and (
            row.label == "wall-signal"
            or (row.label == "observed" and row.unit == "percent_used" and row.quantity >= 100)
        )
    ]
    return {
        "schema": "hapax.freeze-predicate.v1",
        "active": bool(frozen),
        "families": sorted({row.capacity_id.split(".")[0] for row in frozen}),
        "until": min(row.resets_at for row in frozen).isoformat().replace("+00:00", "Z")
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
    from shared.platform_capability_registry import check_route_freshness

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
        if any(check_route_freshness(r, now=now).ok for r in budget_eligible):
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
        if any(
            r.label == "wall-signal" and (r.resets_at is None or now < r.resets_at)
            for r in measures
        ):
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
