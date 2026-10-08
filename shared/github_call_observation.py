"""Observe existing GitHub calls in stderr/journald; never read credentials or store events.

A CLI invocation is not an HTTP request count: gh may paginate, retry or discover a
repository. Only captured response headers count as observed responses. This is
bounded attribution, not an estate-wide meter or evidence of calls outside these adapters.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

SCHEMA = "hapax.github-call-observation.v1"
LOG_PREFIX = "github_call_observation "
READING_MAX_AGE_SECONDS = 60
CALLERS = frozenset(
    {
        "cc-pr-autoqueue.py",
        "cc-pr-merge-watcher.py",
        "cc-pr-review-dispatch.py",
        "hapax-pr-admission",
        "hapax-merge-queue-lineage",
        "github_pr_status.py",
        "cc-pr-release",
        "unknown",
    }
)
_RESOURCES = frozenset({"core", "graphql", "search", "code_search", "integration_manifest"})
_IDENTITY = re.compile(r"github_user_id:[0-9]{1,20}\Z")
_HEADER_SPLIT = re.compile(r"\r?\n\r?\n")


def _number(value: Any) -> int | None:
    text = str(value)
    return int(text) if re.fullmatch(r"[0-9]{1,20}", text) else None


def _caller() -> str:
    name = Path(sys.argv[0]).name if sys.argv else "unknown"
    return name if name in CALLERS else "unknown"


def _emit(event: dict[str, Any]) -> None:
    # Only locally constructed allowlisted fields reach this sink. No command, URL,
    # query, arbitrary header, response body, stderr or environment value is logged.
    try:
        print(LOG_PREFIX + json.dumps(event, sort_keys=True), file=sys.stderr)
    except (OSError, ValueError):
        # A broken/closed observation sink cannot turn received rate headers into
        # a transport failure (and hence unknown headroom). Coverage remains a
        # lower bound; do not retry the request or create an alternative store.
        pass


def _event(kind: str, transport: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "observed_at_epoch": time.time(),
        "caller": _caller(),
        "execution_context": "systemd"
        if re.fullmatch(r"[a-f0-9]{32}", os.environ.get("INVOCATION_ID", ""))
        else "manual_or_unknown",
        "kind": kind,
        "transport": transport,
        "pool": None,
        "command_started": False,
        "http_responses_observed": 0,
        "request_count_exact": False,
        "auth_identity": None,
        "auth_identity_source": "unobserved",
        "readings": [],
    }


def observe_cache_hit() -> None:
    """A rollup hit is no call and supplies no new pool/headroom observation."""
    _emit(_event("cache_hit", "rest"))


def _response_observation(stdout: str, *, rate_probe: bool, ok: bool) -> tuple[str, list[dict]]:
    """Read only numeric rate fields; preserve the body for the existing caller."""
    parts = _HEADER_SPLIT.split(stdout, maxsplit=1)
    if len(parts) != 2 or not re.match(r"HTTP/\S+ [0-9]{3}(?:\s|$)", parts[0]):
        return stdout, []
    head, body = parts
    headers = {}
    for line in head.splitlines()[1:]:
        key, _, value = line.partition(":")
        headers[key.strip().lower()] = value.strip()
    readings = []
    resource = headers.get("x-ratelimit-resource")
    remaining = _number(headers.get("x-ratelimit-remaining"))
    if resource in _RESOURCES and remaining is not None:
        readings.append(
            {
                "resource": resource,
                "remaining": remaining,
                "limit": _number(headers.get("x-ratelimit-limit")),
                "reset_epoch": _number(headers.get("x-ratelimit-reset")),
                "used": _number(headers.get("x-ratelimit-used")),
                "source": "header",
            }
        )
    if rate_probe and ok:
        try:
            payload = json.loads(body)
        except (ValueError, TypeError):
            payload = None
        resources = payload.get("resources") if isinstance(payload, dict) else None
        for name in ("core", "graphql"):
            entry = resources.get(name) if isinstance(resources, dict) else None
            if not isinstance(entry, dict) or _number(entry.get("remaining")) is None:
                continue
            readings.append(
                {
                    "resource": name,
                    "remaining": _number(entry.get("remaining")),
                    "limit": _number(entry.get("limit")),
                    "reset_epoch": _number(entry.get("reset")),
                    "used": _number(entry.get("used")),
                    "source": "body",
                }
            )
    return body, readings


def run_gh_observed(
    runner: Any,
    cmd: list[str],
    *,
    repo_root: Path,
    timeout: int = 60,
) -> subprocess.CompletedProcess:
    """Run an existing call once, observing headers for unfiltered single-page APIs.

    The injected --include affects only output formatting. Explicit header consumers
    retain their raw output. Paginated/filtered commands and gh's higher-level commands
    remain unchanged and their internal request count is explicitly unobserved.
    """
    api = cmd[:2] == ["gh", "api"]
    graphql = api and len(cmd) > 2 and cmd[2] == "graphql"
    event = _event("command", "graphql" if graphql else "rest" if api else "cli")
    excluded = {"--paginate", "--slurp", "--jq", "-q", "--template", "-t", "--cache", "--silent"}
    filtered = any(
        arg.split("=", 1)[0] in excluded or arg.startswith(("-q", "-t")) for arg in cmd[2:]
    )
    explicit = "-i" in cmd or "--include" in cmd
    inject = api and not filtered and not explicit
    actual = [*cmd, "--include"] if inject else cmd
    try:
        proc = runner(
            actual, cwd=str(repo_root), capture_output=True, text=True, check=False, timeout=timeout
        )
    except OSError:
        event["outcome"] = "launch_failed"
        _emit(event)
        raise
    except subprocess.TimeoutExpired:
        event.update(command_started=True, outcome="timeout")
        _emit(event)
        raise
    event.update(command_started=True, outcome="success" if proc.returncode == 0 else "failed")
    event["observed_at_epoch"] = time.time()
    stdout = proc.stdout or ""
    body, readings = (
        _response_observation(
            stdout,
            rate_probe=api and "rate_limit" in cmd,
            ok=proc.returncode == 0,
        )
        if api and not filtered and (inject or explicit)
        else (stdout, [])
    )
    if body != stdout:
        event["http_responses_observed"] = 1
    event["readings"] = readings
    event["pool"] = next((r["resource"] for r in readings if r["source"] == "header"), None)
    # This identity is observed only in this transport's error response. Successful
    # requests do not identify the account; never guess from repo owner or environment.
    if proc.returncode != 0:
        match = re.search(r"API rate limit exceeded for user ID ([0-9]{1,20})\.", body)
        if match:
            event.update(
                auth_identity=f"github_user_id:{match[1]}", auth_identity_source="error_body"
            )
    _emit(event)
    return subprocess.CompletedProcess(
        cmd, proc.returncode, body if inject else proc.stdout, proc.stderr
    )


def reading_validity(*, observed_at: float, reset_epoch: int | None, now: float) -> dict[str, Any]:
    """An observation expires at its reset or after 60 seconds; reading it never renews it.

    This is diagnostic validity only, not a new admission floor or cached routing input.
    """
    until = (
        min(observed_at + READING_MAX_AGE_SECONDS, reset_epoch) if reset_epoch is not None else None
    )
    freshness = (
        "unknown" if until is None or now < observed_at else "fresh" if now < until else "stale"
    )
    return {
        "observed_at_epoch": observed_at,
        "valid_until_epoch": until,
        "freshness": freshness,
        "recheck": "python scripts/github_pr_status.py rate",
    }


def summarize_log(
    lines: Iterable[str], *, since: float, until: float, now: float
) -> dict[str, Any]:
    """Summarize a finite existing log/journal JSON interval, without a new event store.

    Group unknown identities separately from observed ones. Header and body values
    retain separate provenance; no subtraction across callers is called their spend.
    """
    groups: dict[tuple, dict] = {}
    ignored = 0
    for line in lines:
        try:
            outer = json.loads(line)
        except ValueError:
            outer = None
        message = outer.get("MESSAGE", "") if isinstance(outer, dict) else line
        try:
            event = json.loads(message.split(LOG_PREFIX, 1)[1])
            observed = event["observed_at_epoch"]
            caller, transport, identity = (
                event["caller"],
                event["transport"],
                event["auth_identity"],
            )
            context = event.get("execution_context", "manual_or_unknown")
            pool = event.get("pool")
            if (
                event["schema"] != SCHEMA
                or caller not in CALLERS
                or transport not in {"rest", "graphql", "cli"}
                or context not in {"systemd", "manual_or_unknown"}
                or (pool is not None and pool not in _RESOURCES)
                or not isinstance(event.get("readings"), list)
                or (identity is not None and not _IDENTITY.fullmatch(identity))
                or not since <= observed < until
            ):
                raise ValueError
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            ignored += 1
            continue
        key = (caller, transport, pool, identity, context)
        row = groups.setdefault(
            key,
            {
                "caller": caller,
                "transport": transport,
                "pool": pool,
                "auth_identity": identity,
                "execution_context": context,
                "commands_started": 0,
                "http_responses_observed": 0,
                "cache_hits": 0,
                "launch_failures": 0,
                "latest_readings": {},
            },
        )
        row["commands_started"] += event.get("command_started") is True
        row["http_responses_observed"] += event.get("http_responses_observed") == 1
        row["cache_hits"] += event.get("kind") == "cache_hit"
        row["launch_failures"] += event.get("outcome") == "launch_failed"
        for reading in event.get("readings", []):
            if not isinstance(reading, dict):
                continue
            resource, source = reading.get("resource"), reading.get("source")
            if (
                not isinstance(resource, str)
                or not isinstance(source, str)
                or resource not in _RESOURCES
                or source not in {"header", "body"}
            ):
                continue
            rkey = (resource, source)
            previous = row["latest_readings"].get(rkey)
            if previous and previous["validity"]["observed_at_epoch"] > observed:
                continue
            row["latest_readings"][rkey] = {
                "resource": resource,
                "source": source,
                **{
                    field: _number(reading.get(field))
                    for field in ("remaining", "limit", "used", "reset_epoch")
                },
                "validity": reading_validity(
                    observed_at=observed, reset_epoch=_number(reading.get("reset_epoch")), now=now
                ),
            }
    callers = sorted(
        groups.values(),
        key=lambda row: (-row["http_responses_observed"], -row["commands_started"], row["caller"]),
    )
    for row in callers:
        row["latest_readings"] = list(row["latest_readings"].values())
    return {
        "since_epoch": since,
        "until_epoch": until,
        "generated_at_epoch": now,
        "coverage": "instrumented_calls_only",
        "observation_state": "observed" if callers else "unobserved",
        "request_count_exact": False,
        "ignored_lines": ignored,
        "callers": callers,
        "note": "Confirmed responses are a lower bound. CLI-internal calls, other adapters, hosts and uncaptured manual stderr remain unobserved; pool deltas are not caller spend.",
    }
