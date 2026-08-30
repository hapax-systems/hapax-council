#!/usr/bin/env python3
"""GitHub PR/status helpers that spread routine polling across both rate pools.

REST/``core`` and GraphQL are **separate** quotas. Polling everything through one of
them drains it while the other idles — measured 2026-08-29 at ``core`` 0/5000 with
``graphql`` 4660/5000 — so ``list_open_pr_statuses`` measures both and picks the
roomier pool *before* spending the call. Ties and unknown headroom resolve to REST,
which is the post-#4436 default, so traffic only ever diverts away from a pool
measured to be in trouble.

Some operations still have no REST replacement (native merge-queue metadata, the
dequeue mutation) and remain GraphQL regardless.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_REPO = "hapax-systems/hapax-council"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "hapax" / "pr-status"
DEFAULT_CACHE_TTL_SECONDS = 60
DEFAULT_GRAPHQL_MIN_REMAINING = 500
# Floor for the REST (`core`) pool, which had no guard at all before this change. Applied by
# `rest_pool_blocked`, which is the single place this floor is evaluated; `choose_transport`
# delegates its REST test there rather than keeping a second copy — see the note on
# `rest_pool_blocked` for why there is no separate `rest_backoff`. Same value as the GraphQL
# floor because both pools carry the same 5,000/hr limit today; the two are independent
# constants so a future divergence in limits does not require rediscovering this one.
#
# OPERATIONAL KILLSWITCH: ``HAPAX_GITHUB_REST_MIN_REMAINING=0`` disables the REST floor, so
# nothing is ever refused for measured exhaustion and the fleet behaves exactly as it did
# before this change. This gate now sits on every fleet scan, so it needs a documented way off
# that does not require a deploy — a guard whose only escape is editing source is one an
# operator cannot use at 3am. The GraphQL floor has the same escape via
# ``HAPAX_GITHUB_GRAPHQL_MIN_REMAINING=0``.
DEFAULT_REST_MIN_REMAINING = 500
REST_MIN_REMAINING_ENV = "HAPAX_GITHUB_REST_MIN_REMAINING"
GRAPHQL_MIN_REMAINING_ENV = "HAPAX_GITHUB_GRAPHQL_MIN_REMAINING"
DEFAULT_GRAPHQL_BACKOFF_MAX_SLEEP_SECONDS = 0
DEFAULT_TIMEOUT_SECONDS = 60
STATUS_CACHE_SCHEMA_VERSION = 2
GRAPHQL_BACKOFF_RC = 75
REST_INDETERMINATE_CHECK_NAME = "github-rest-status-indeterminate"
DEFAULT_REVIEW_DECISION_REST_LIMIT = 5000

_SAFE_CACHE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class GraphQLBackoff:
    remaining: int
    reset_epoch: int | None
    reason: str

    @property
    def reset_in_seconds(self) -> int | None:
        if self.reset_epoch is None:
            return None
        return max(0, self.reset_epoch - int(time.time()))


@dataclass(frozen=True)
class RatePool:
    """Measured headroom for one GitHub rate-limit pool.

    ``source`` records provenance, because the two available sources have been observed to
    disagree. Measured 2026-08-29: ``gh api rate_limit`` reported ``core: 4996/5000
    remaining`` at the same moment a real call returned ``403`` with
    ``X-Ratelimit-Remaining: 0``, ``Used: 5000``, ``Resource: core``. Response headers are
    what actually govern a call, so a body-sourced figure is weaker evidence and says so
    rather than being silently treated as equivalent.
    """

    resource: str
    remaining: int
    limit: int
    reset_epoch: int | None
    source: str  # "header" (authoritative) | "body" (weaker)

    @property
    def fraction(self) -> float:
        """Headroom as a share of the pool's own limit.

        Routing compares fractions, not raw counts, so the decision stays correct if the
        two pools are ever given different limits.
        """
        if self.limit <= 0:
            return 0.0
        return max(0.0, min(1.0, self.remaining / self.limit))

    @property
    def reset_in_seconds(self) -> int | None:
        if self.reset_epoch is None:
            return None
        return max(0, self.reset_epoch - int(time.time()))


@dataclass(frozen=True)
class RateSnapshot:
    """Both pools from a single probe, so a routing decision costs one call, not two."""

    core: RatePool | None
    graphql: RatePool | None


@dataclass(frozen=True)
class ListingRoute:
    """One cycle's transport decision, returned rather than reconstructed.

    An earlier revision let callers infer the cycle's transport by scanning the returned rows
    for ``transport == "graphql"``. That worked only because every GraphQL row happens to be
    stamped, and it silently degraded to REST for an empty listing — so the "chosen before the
    call" predicate held *by coincidence of data rather than by construction*. The decision is
    the chooser's output; it belongs in the return value.

    ``rest_blocked`` is the part that changes behaviour rather than merely recording it. When
    REST is measured below its floor it is **not an eligible fallback**: falling back to a pool
    known to be empty attempts more after a failure than before it, which is the failure-paths-
    narrow rule, and it recreates exactly the failure-triggered routing this change replaced.
    """

    transport: str  # "rest" | "graphql"
    rest_blocked: bool
    reason: str

    @property
    def rest_available(self) -> bool:
        """Whether REST may be used at all — as a primary path or as a fallback."""
        return not self.rest_blocked


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _rest_floor() -> int:
    """The REST floor in effect, honouring the operational override."""
    return max(0, _env_int(REST_MIN_REMAINING_ENV, DEFAULT_REST_MIN_REMAINING))


def _graphql_floor() -> int:
    """The GraphQL floor in effect, honouring the operational override."""
    return max(0, _env_int(GRAPHQL_MIN_REMAINING_ENV, DEFAULT_GRAPHQL_MIN_REMAINING))


def _runner_uses_real_gh(runner: Any) -> bool:
    return runner is subprocess.run


def _run(
    runner: Any,
    cmd: list[str],
    *,
    repo_root: Path,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess:
    return runner(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _json_from_proc(proc: subprocess.CompletedProcess) -> Any | None:
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout or "null")
    except json.JSONDecodeError:
        return None


def _upper_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text.upper() if text else None


def _cache_key(repo: str, ref: str) -> Path:
    repo_part = _SAFE_CACHE_RE.sub("_", repo)
    ref_part = _SAFE_CACHE_RE.sub("_", ref)
    return DEFAULT_CACHE_DIR / repo_part / f"{ref_part}.json"


def _cache_ttl_seconds() -> int:
    return max(0, _env_int("HAPAX_GITHUB_PR_STATUS_CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS))


def _read_cached_rollup(repo: str, ref: str) -> list[dict[str, Any]] | None:
    ttl = _cache_ttl_seconds()
    if ttl <= 0:
        return None
    path = _cache_key(repo, ref)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    fetched_at = payload.get("fetched_at")
    if not isinstance(fetched_at, (int, float)):
        return None
    if time.time() - float(fetched_at) > ttl:
        return None
    if (
        payload.get("schema_version") != STATUS_CACHE_SCHEMA_VERSION
        or payload.get("complete") is not True
    ):
        return None
    rollup = payload.get("statusCheckRollup")
    return rollup if isinstance(rollup, list) else None


def _write_cached_rollup(repo: str, ref: str, rollup: list[dict[str, Any]]) -> None:
    ttl = _cache_ttl_seconds()
    if ttl <= 0:
        return
    path = _cache_key(repo, ref)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "fetched_at": time.time(),
                    "schema_version": STATUS_CACHE_SCHEMA_VERSION,
                    "complete": True,
                    "repo": repo,
                    "ref": ref,
                    "statusCheckRollup": rollup,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
    except OSError:
        return


def _rest_get_json(
    path: str,
    *,
    repo_root: Path,
    runner: Any,
    fields: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> Any | None:
    cmd = [
        "gh",
        "api",
        "--method",
        "GET",
        "-H",
        "Accept: application/vnd.github+json",
        path,
    ]
    for key, value in (fields or {}).items():
        cmd.extend(["-f", f"{key}={value}"])
    proc = _run(runner, cmd, repo_root=repo_root, timeout=timeout)
    return _json_from_proc(proc)


def _rest_get_json_pages_or_none(
    path: str,
    *,
    repo_root: Path,
    runner: Any,
    fields: dict[str, str] | None = None,
    limit: int = 100,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> list[Any] | None:
    if limit <= 0:
        return []
    out: list[Any] = []
    page = 1
    while len(out) < limit:
        per_page = min(100, limit - len(out))
        page_fields = dict(fields or {})
        page_fields.update({"per_page": str(per_page), "page": str(page)})
        payload = _rest_get_json(
            path,
            repo_root=repo_root,
            runner=runner,
            fields=page_fields,
            timeout=timeout,
        )
        if not isinstance(payload, list):
            return None
        if not payload:
            break
        out.extend(payload)
        if len(payload) < per_page:
            break
        page += 1
    return out


def _rest_get_json_pages(
    path: str,
    *,
    repo_root: Path,
    runner: Any,
    fields: dict[str, str] | None = None,
    limit: int = 100,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> list[Any]:
    return (
        _rest_get_json_pages_or_none(
            path,
            repo_root=repo_root,
            runner=runner,
            fields=fields,
            limit=limit,
            timeout=timeout,
        )
        or []
    )


def _rest_get_json_object_array_pages_or_none(
    path: str,
    *,
    array_key: str,
    total_key: str | None = None,
    repo_root: Path,
    runner: Any,
    fields: dict[str, str] | None = None,
    limit: int = 5000,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> list[Any] | None:
    if limit <= 0:
        return []
    out: list[Any] = []
    page = 1
    while len(out) < limit:
        per_page = min(100, limit - len(out))
        page_fields = dict(fields or {})
        page_fields.update({"per_page": str(per_page), "page": str(page)})
        payload = _rest_get_json(
            path,
            repo_root=repo_root,
            runner=runner,
            fields=page_fields,
            timeout=timeout,
        )
        if not isinstance(payload, dict):
            return None
        raw_items = payload.get(array_key)
        if not isinstance(raw_items, list):
            return None
        out.extend(raw_items)
        total_count = payload.get(total_key) if total_key else None
        if isinstance(total_count, int):
            if total_count > limit:
                return None
            if len(out) >= total_count:
                break
        if not raw_items or len(raw_items) < per_page:
            break
        page += 1
    return out


def _indeterminate_rollup(reason: str) -> list[dict[str, Any]]:
    return [
        {
            "name": REST_INDETERMINATE_CHECK_NAME,
            "status": "PENDING",
            "conclusion": None,
            "details": reason,
        }
    ]


def _check_run_to_rollup(item: dict[str, Any]) -> dict[str, Any]:
    app = item.get("app") if isinstance(item.get("app"), dict) else {}
    return {
        "name": item.get("name") or item.get("external_id") or "unnamed-check",
        "status": _upper_or_none(item.get("status")),
        "conclusion": _upper_or_none(item.get("conclusion")),
        "started_at": item.get("started_at"),
        "completed_at": item.get("completed_at"),
        "app": {"name": app.get("name")} if app else {},
    }


def _status_to_rollup(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "context": item.get("context") or "unnamed-status",
        "state": _upper_or_none(item.get("state")),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
    }


def fetch_status_check_rollup_rest(
    ref: str,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path,
    runner: Any = subprocess.run,
    use_cache: bool | None = None,
) -> list[dict[str, Any]]:
    """Return a GraphQL-like ``statusCheckRollup`` using REST check/status APIs."""

    if not ref:
        return []
    if use_cache is None:
        use_cache = _runner_uses_real_gh(runner)
    if use_cache:
        cached = _read_cached_rollup(repo, ref)
        if cached is not None:
            return cached

    raw_runs = _rest_get_json_object_array_pages_or_none(
        f"repos/{repo}/commits/{ref}/check-runs",
        array_key="check_runs",
        total_key="total_count",
        repo_root=repo_root,
        runner=runner,
    )
    if raw_runs is None:
        return _indeterminate_rollup("check_runs_rest_indeterminate")

    raw_statuses = _rest_get_json_object_array_pages_or_none(
        f"repos/{repo}/commits/{ref}/status",
        array_key="statuses",
        total_key="total_count",
        repo_root=repo_root,
        runner=runner,
    )
    if raw_statuses is None:
        return _indeterminate_rollup("combined_status_rest_indeterminate")

    rollup: list[dict[str, Any]] = []
    rollup.extend(_check_run_to_rollup(item) for item in raw_runs if isinstance(item, dict))
    rollup.extend(_status_to_rollup(item) for item in raw_statuses if isinstance(item, dict))

    if use_cache and rollup:
        _write_cached_rollup(repo, ref, rollup)
    return rollup


def get_pull_rest(
    pr_number: int | str,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path,
    runner: Any = subprocess.run,
) -> dict[str, Any] | None:
    payload = _rest_get_json(
        f"repos/{repo}/pulls/{pr_number}",
        repo_root=repo_root,
        runner=runner,
    )
    return payload if isinstance(payload, dict) else None


def rest_merge_state_status(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return "UNKNOWN"
    raw = str(payload.get("mergeable_state") or "").strip().upper()
    if raw:
        return raw
    mergeable = payload.get("mergeable")
    if mergeable is True:
        return "CLEAN"
    if mergeable is False:
        return "DIRTY"
    return "UNKNOWN"


def rest_pull_state(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    state = str(payload.get("state") or "").lower()
    if state == "open":
        return "OPEN"
    if state == "closed":
        if payload.get("merged") or payload.get("merged_at"):
            return "MERGED"
        return "CLOSED"
    return None


def list_pulls_for_branch_rest(
    branch: str,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path,
    runner: Any = subprocess.run,
    state: str = "all",
    limit: int = 1,
    fail_on_indeterminate: bool = False,
) -> list[dict[str, Any]]:
    owner = repo.split("/", 1)[0]
    head = branch if ":" in branch else f"{owner}:{branch}"
    if fail_on_indeterminate:
        payload = _rest_get_json_pages_or_none(
            f"repos/{repo}/pulls",
            repo_root=repo_root,
            runner=runner,
            fields={"head": head, "state": state, "per_page": str(limit)},
            limit=limit,
        )
        if payload is None:
            raise subprocess.SubprocessError(f"REST pull list indeterminate for {repo} head={head}")
    else:
        payload = _rest_get_json_pages(
            f"repos/{repo}/pulls",
            repo_root=repo_root,
            runner=runner,
            fields={"head": head, "state": state, "per_page": str(limit)},
            limit=limit,
        )
    return [item for item in payload if isinstance(item, dict)]


def list_pulls_rest(
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path,
    runner: Any = subprocess.run,
    state: str = "open",
    limit: int = 100,
    sort: str | None = None,
    direction: str | None = None,
    fail_on_indeterminate: bool = False,
) -> list[dict[str, Any]]:
    fields = {"state": state, "per_page": str(limit)}
    if sort:
        fields["sort"] = sort
    if direction:
        fields["direction"] = direction
    if fail_on_indeterminate:
        payload = _rest_get_json_pages_or_none(
            f"repos/{repo}/pulls",
            repo_root=repo_root,
            runner=runner,
            fields=fields,
            limit=limit,
        )
        if payload is None:
            raise subprocess.SubprocessError(f"REST pull list indeterminate for {repo}")
    else:
        payload = _rest_get_json_pages(
            f"repos/{repo}/pulls",
            repo_root=repo_root,
            runner=runner,
            fields=fields,
            limit=limit,
        )
    return [item for item in payload if isinstance(item, dict)]


def list_pull_files_rest(
    pr_number: int | str,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path,
    runner: Any = subprocess.run,
    limit: int = 3000,
) -> list[dict[str, Any]]:
    payload = _rest_get_json_pages(
        f"repos/{repo}/pulls/{pr_number}/files",
        repo_root=repo_root,
        runner=runner,
        limit=limit,
    )
    return [item for item in payload if isinstance(item, dict)]


def review_decision_rest(
    pr_number: int | str,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path,
    runner: Any = subprocess.run,
    limit: int = DEFAULT_REVIEW_DECISION_REST_LIMIT,
) -> str | None:
    payload = _rest_get_json_pages_or_none(
        f"repos/{repo}/pulls/{pr_number}/reviews",
        repo_root=repo_root,
        runner=runner,
        limit=limit,
    )
    if payload is None or len(payload) >= limit:
        return "REVIEW_REQUIRED"
    latest_by_reviewer: dict[str, str] = {}
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            continue
        state = _upper_or_none(item.get("state"))
        if not state or state == "COMMENTED":
            continue
        user = item.get("user") if isinstance(item.get("user"), dict) else {}
        reviewer = str(user.get("login") or item.get("user_login") or f"review-{index}")
        latest_by_reviewer[reviewer] = state
    states = set(latest_by_reviewer.values())
    if not states:
        return None
    if "CHANGES_REQUESTED" in states:
        return "CHANGES_REQUESTED"
    if "APPROVED" in states:
        return "APPROVED"
    return "REVIEW_REQUIRED"


def _files_payload_from_rest(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in files:
        filename = item.get("filename") or item.get("path")
        if filename:
            out.append({"path": str(filename)})
    return out


def _pull_status_row_from_rest(
    item: dict[str, Any],
    *,
    repo: str,
    repo_root: Path,
    runner: Any,
    include_files: bool = False,
    include_review_decision: bool = False,
    include_status: bool = True,
    hydrate_pull: bool = False,
) -> dict[str, Any]:
    number = item.get("number")
    should_hydrate = hydrate_pull or include_files or include_review_decision
    detail = (
        (get_pull_rest(number, repo=repo, repo_root=repo_root, runner=runner) if number else None)
        if should_hydrate
        else None
    )
    pull = detail if isinstance(detail, dict) else item
    head = pull.get("head") if isinstance(pull.get("head"), dict) else {}
    sha = str(head.get("sha") or "")
    head_ref = str(head.get("ref") or "")
    status_ref = sha or head_ref
    files = (
        list_pull_files_rest(number, repo=repo, repo_root=repo_root, runner=runner)
        if (include_files and number)
        else []
    )
    try:
        changed_files = (
            int(pull["changed_files"]) if pull.get("changed_files") is not None else None
        )
    except (TypeError, ValueError):
        changed_files = None
    if changed_files is None and files:
        changed_files = len(files)
    labels = pull.get("labels") if isinstance(pull.get("labels"), list) else []
    return {
        "number": number,
        "id": pull.get("node_id") or pull.get("id"),
        "state": rest_pull_state(pull),
        "title": pull.get("title") or "",
        "body": pull.get("body") or "",
        "url": pull.get("html_url") or pull.get("url"),
        "updatedAt": pull.get("updated_at"),
        "mergedAt": pull.get("merged_at"),
        "headRefName": head_ref,
        "headRefOid": sha,
        "changedFiles": changed_files,
        "files": _files_payload_from_rest(files) if include_files else None,
        "isDraft": bool(pull.get("draft")),
        "labels": labels,
        "reviewDecision": review_decision_rest(
            number,
            repo=repo,
            repo_root=repo_root,
            runner=runner,
        )
        if include_review_decision and number
        else None,
        "autoMergeRequest": pull.get("auto_merge"),
        "mergeStateStatus": rest_merge_state_status(pull),
        "statusCheckRollup": fetch_status_check_rollup_rest(
            status_ref,
            repo=repo,
            repo_root=repo_root,
            runner=runner,
        )
        if include_status and status_ref
        else [],
        "transport": "rest",
    }


def rest_pool_blocked(
    snapshot: RateSnapshot,
    *,
    min_remaining: int | None = None,
) -> str | None:
    """Return a reason when a REST-only path must not spend, else ``None``.

    **This is deliberately not ``choose_transport(...) != "rest"``.** That question is
    "which pool should new work prefer", and it answers "graphql" whenever GraphQL has
    proportionally more headroom — including when REST is entirely healthy. Refusing on
    that answer would halt every REST caller on a mere *preference*: three reviewers
    independently caught exactly that regression in an earlier revision, where a healthy
    REST pool with a roomier GraphQL pool stopped all three fleet timers.

    A REST-only function has no GraphQL alternative to route to, so the only question that
    matters to it is whether REST itself is spendable. Preference is irrelevant here.

    **It is nonetheless the same policy, evaluated once.** An earlier revision reimplemented
    the floor here alongside `choose_transport`'s own copy, so the two could disagree —
    core=400 with a chooser floor of 300 selects REST while a guard defaulting to 500 blocks
    it. That is the two-mitigations-per-hazard smell this change removed `rest_backoff` for,
    reintroduced in a different shape. `choose_transport` now delegates its REST test here,
    so there is exactly one place the floor is applied.
    """
    floor = _rest_floor() if min_remaining is None else max(0, min_remaining)
    core = snapshot.core
    if core is None:
        return None  # unknown headroom is not exhaustion; fail open
    if core.remaining >= floor:
        return None
    return f"github_rest_below_floor:{core.remaining}<{floor}"


class PrListingUnavailable(RuntimeError):
    """The open-PR listing could not be obtained. **"We did not look", never "nothing found".**

    Both subclasses mean a caller must skip its cycle rather than act on an empty list. That
    distinction is the whole point: an empty result that reads as "no PRs need attention"
    silently deadlocks the merge pipeline, which is exactly how the pre-#4436 implementation
    failed when GitHub 504'd its bulk query.
    """

    def __init__(self, reason: str, reset_epoch: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.reset_epoch = reset_epoch

    @property
    def reset_in_seconds(self) -> int | None:
        if self.reset_epoch is None:
            return None
        return max(0, self.reset_epoch - int(time.time()))


def listing_unavailable_detail(exc: PrListingUnavailable) -> str:
    """A log suffix that names what actually happened, and what to do about it.

    The three fleet handlers each wrote ``"(quota, not auth; resets in %ss)"``. That is true
    of exhaustion and false of a failed listing, which can be auth, malformed output, or a
    504 — and it printed a null reset with no recovery action. Reason codes must name the
    state they are actually in; one shared formatter keeps the three from drifting apart
    again.
    """
    if isinstance(exc, RestPoolExhausted):
        # "Next action: none" was wrong: a pool that stays empty across cycles is a spend
        # problem, not weather, and the operator is the only one who can look into what is
        # burning it. The routine case still needs nothing done, so say both.
        return (
            # `reset_in_seconds` is None when no reset epoch was carried, and an f-string
            # renders that as the literal "Nones" — a nonsense duration in the one message an
            # operator actually reads.
            f" (quota, not auth; {f'resets in {exc.reset_in_seconds}s' if exc.reset_in_seconds is not None else 'reset time unknown'}). "
            "Next action: none if this clears on the next cycle. If both pools stay below "
            "their floors across several resets, something is spending them — check "
            "`github_pr_status.py rate` and the fleet timer cadences."
        )
    return (
        " (listing failed; cause not classified — this is NOT the measured-exhaustion case, "
        "but the call itself may still have hit a limit). Next action: run `gh auth status` "
        "and `gh pr list --repo <repo> --state open --limit 1`; a repeated 504 means the "
        "query is too large, a 403/429 means a pool this probe does not measure, and an auth "
        "error means the token needs attention."
    )


class RestListingFailed(PrListingUnavailable):
    """The REST listing did not come back. Symmetric with ``GraphQLListingFailed``.

    Without this the two transports failed differently for the same event: GraphQL raised,
    REST returned ``[]``. An empty list reads downstream as "no PRs need attention", so the
    fleet path demands a determinate listing and converts an indeterminate one into a refusal.
    Direct callers of ``list_open_pr_statuses_rest`` keep the older, laxer contract.
    """


class GraphQLListingFailed(PrListingUnavailable):
    """``gh pr list`` failed or returned something that is not a list of PRs.

    Distinct from exhaustion: the pool had headroom and the call still did not produce
    rows. Falling back to REST here would *widen* the failure path — attempting more after
    a failure than before it — so this refuses instead, and the caller skips the cycle.
    """


class RestPoolExhausted(PrListingUnavailable):
    """The REST pool has no headroom, measured before spending a call.

    Carries the reset time so a caller can report *when*, not merely *that*. This is a
    quota condition and never an auth one — `gh auth status` reports an exhausted pool as
    "the token is invalid", which sends people to re-authenticate for nothing.
    """

    def __init__(self, reason: str, reset_epoch: int | None) -> None:
        super().__init__(reason, reset_epoch)


def list_open_pr_statuses_rest(
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path,
    runner: Any = subprocess.run,
    limit: int = 100,
    include_files: bool = False,
    include_review_decision: bool = False,
    include_status: bool = True,
    hydrate_pull: bool = False,
    fail_on_indeterminate: bool = False,
    respect_rate_pools: bool = True,
) -> list[dict[str, Any]]:
    # The operational guard. This is the entry point all three fleet timers use
    # (cc-pr-autoqueue, cc-pr-merge-watcher, cc-pr-review-dispatch), and one call here
    # fans out into a listing plus a per-PR hydration — so a single cheap probe protects
    # many requests.
    #
    # Refusing early is strictly better than proceeding: when `core` is measurably at
    # zero, those requests are guaranteed 403s. Spending them produces the same failure
    # more slowly, having burned the rate limit further and reported nothing useful about
    # why. `RestPoolExhausted` names the pool and the reset.
    #
    # Fails OPEN by construction: `choose_transport` returns "rest" whenever headroom is
    # unknown, so a probe failure, a network hiccup, or an old `gh` never blocks polling.
    # Only a *measured* empty pool refuses.
    if respect_rate_pools:
        snapshot = rate_snapshot(repo_root=repo_root, runner=runner)
        blocked = rest_pool_blocked(snapshot)
        if blocked is not None:
            raise RestPoolExhausted(blocked, snapshot.core.reset_epoch if snapshot.core else None)

    payload = list_pulls_rest(
        repo=repo,
        repo_root=repo_root,
        runner=runner,
        state="open",
        limit=limit,
        fail_on_indeterminate=fail_on_indeterminate,
    )

    out: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        out.append(
            _pull_status_row_from_rest(
                item,
                repo=repo,
                repo_root=repo_root,
                runner=runner,
                include_files=include_files,
                include_review_decision=include_review_decision,
                include_status=include_status,
                hydrate_pull=hydrate_pull or include_files or include_review_decision,
            )
        )
    return out


#: Fields the bulk ``gh pr list --json`` query requests.
#:
#: ``statusCheckRollup`` is deliberately absent, and this is not an oversight: it is the
#: check-runs-per-PR field, and requesting it for the whole open-PR backlog makes the
#: aggregate GraphQL response large enough that GitHub returns HTTP 504 — empirically
#: deterministic at ~30 open PRs, per the pre-#4436 implementation this restores. That
#: version then swallowed the 504 as an empty list and silently deadlocked the merge
#: pipeline. It is fetched per-PR below instead, which always serves.
_GRAPHQL_PR_LIST_FIELDS = (
    "number",
    "id",
    "state",
    "title",
    "body",
    "url",
    "updatedAt",
    "mergedAt",
    "headRefName",
    "headRefOid",
    "changedFiles",
    "files",
    "isDraft",
    "labels",
    "reviewDecision",
    "autoMergeRequest",
    "mergeStateStatus",
)


def _status_check_rollup_graphql(
    number: Any,
    *,
    repo: str,
    repo_root: Path,
    runner: Any,
) -> list[dict[str, Any]]:
    """One PR's rollup via a light ``gh pr view``. Fail-closed: unfetchable becomes ``[]``.

    An empty rollup reads downstream as "checks unknown / not green", so a failure here
    cannot cause a merge that the checks would have prevented.
    """
    if not number:
        return []
    payload = _json_from_proc(
        _run(
            runner,
            ["gh", "pr", "view", str(number), "--repo", repo, "--json", "statusCheckRollup"],
            repo_root=repo_root,
        )
    )
    rollup = payload.get("statusCheckRollup") if isinstance(payload, dict) else None
    return rollup if isinstance(rollup, list) else []


def list_open_pr_statuses_graphql(
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path,
    runner: Any = subprocess.run,
    limit: int = 100,
    include_files: bool = False,
    include_review_decision: bool = False,
    include_status: bool = True,
) -> list[dict[str, Any]]:
    """The GraphQL half of the balancer: the same rows, off the other rate pool.

    This is a restoration, not a new transport. `gh pr list --json` is GraphQL-backed and
    is what the three fleet timers used until #4436 moved polling to REST; the row shape
    every consumer reads is *this* shape, and `_pull_status_row_from_rest` is the adapter
    written to imitate it. So the direction of risk runs opposite to the obvious guess —
    the REST path is the translation, and it is the one already covered by tests.

    `test_the_two_transports_agree_on_row_shape` pins the two against each other so a
    divergence is a failing test rather than a field that silently reads ``None`` in the
    autoqueue's merge decision.
    """
    # `_run` can raise (a timeout, or gh missing), and a raised exception is outside the
    # refusal contract this function documents: callers catch `PrListingUnavailable`, so an
    # escaping TimeoutExpired would crash the timer rather than skip its cycle. Same shape as
    # the probe's fail-open path — normalise at the boundary rather than at each caller.
    try:
        proc = _run(
            runner,
            [
                "gh",
                "pr",
                "list",
                "--repo",
                repo,
                "--state",
                "open",
                "--limit",
                str(limit),
                "--json",
                ",".join(_GRAPHQL_PR_LIST_FIELDS),
            ],
            repo_root=repo_root,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise GraphQLListingFailed(f"github_graphql_listing_unavailable:{exc}") from exc
    # Refuse rather than return []. A failed listing and "no open PRs" are the same value and
    # different facts, and the merge pipeline acts on the difference. This is the exact way
    # the pre-#4436 implementation failed: it swallowed GitHub's 504 as an empty list and
    # silently deadlocked. Documenting that hazard three paragraphs up and then reproducing it
    # is what the review caught here.
    if proc.returncode != 0:
        raise GraphQLListingFailed(
            f"github_graphql_listing_failed:rc={proc.returncode}:{(proc.stderr or '').strip()[:200]}"
        )
    raw = _json_from_proc(proc)
    if not isinstance(raw, list):
        raise GraphQLListingFailed(
            f"github_graphql_listing_malformed:expected list, got {type(raw).__name__}"
        )

    out: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        # Skipping a bad row rebuilds the silent-empty failure one level down: a payload of
        # `[null]` parses fine, yields no rows, and reads downstream as "no open PRs" — the
        # exact deadlock `GraphQLListingFailed` was added to prevent. A row we cannot identify
        # is not a PR we can safely omit from a merge decision.
        if not isinstance(item, dict):
            raise GraphQLListingFailed(
                f"github_graphql_listing_malformed:row {index} is {type(item).__name__}, not an object"
            )
        number = item.get("number")
        if number is None:
            raise GraphQLListingFailed(
                f"github_graphql_listing_malformed:row {index} has no `number`"
            )
        files = item.get("files") if isinstance(item.get("files"), list) else []
        changed_files = item.get("changedFiles")
        if changed_files is None and files:
            changed_files = len(files)
        out.append(
            {
                "number": number,
                "id": item.get("id"),
                "state": _upper_or_none(item.get("state")),
                "title": item.get("title") or "",
                "body": item.get("body") or "",
                "url": item.get("url"),
                "updatedAt": item.get("updatedAt"),
                "mergedAt": item.get("mergedAt"),
                "headRefName": str(item.get("headRefName") or ""),
                "headRefOid": str(item.get("headRefOid") or ""),
                "changedFiles": changed_files,
                "files": files if include_files else None,
                "isDraft": bool(item.get("isDraft")),
                "labels": item.get("labels") if isinstance(item.get("labels"), list) else [],
                "reviewDecision": _upper_or_none(item.get("reviewDecision"))
                if include_review_decision
                else None,
                "autoMergeRequest": item.get("autoMergeRequest"),
                "mergeStateStatus": _upper_or_none(item.get("mergeStateStatus")) or "UNKNOWN",
                "statusCheckRollup": _status_check_rollup_graphql(
                    number, repo=repo, repo_root=repo_root, runner=runner
                )
                if include_status
                else [],
                # Provenance, and it is load-bearing rather than decorative. A consumer that
                # re-hydrates each row over REST would spend the very pool the routing exists
                # to spare — one call moved, nothing saved. The tag lets a consumer skip work
                # this transport has already done, and mirrors `RatePool.source`: a value is
                # not usable without knowing where it came from.
                "transport": "graphql",
            }
        )
    return out


def list_open_pr_statuses(
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path,
    runner: Any = subprocess.run,
    limit: int = 100,
    include_files: bool = False,
    include_review_decision: bool = False,
    include_status: bool = True,
) -> tuple[list[dict[str, Any]], ListingRoute]:
    """Choose the transport on measured headroom, **then** make the call.

    This is the operational half of the change, and the reason the helper alone was not
    enough. `choose_transport` was reachable only from the diagnostic CLI, so a REST pool
    measured at zero with GraphQL at 93% headroom made all three fleet timers sit out their
    cycles — better than 403ing, but still a stall, and not the balancing the exit predicate
    promises. Three independent review families said so before this existed.

    ``None`` from `choose_transport` means both pools are measurably below their floors;
    that is the one case where refusing is right, and it raises so callers keep their
    existing skip-the-cycle handling for it.
    """
    snapshot = rate_snapshot(repo_root=repo_root, runner=runner)
    transport, reason = choose_transport(repo_root=repo_root, runner=runner, snapshot=snapshot)
    if transport is None:
        # Carry the reset time. "Both pools are empty" without a *when* tells an operator
        # nothing they can act on, and this is the one path that reaches them as a warning.
        resets = [
            pool.reset_epoch
            for pool in (snapshot.core, snapshot.graphql)
            if pool is not None and pool.reset_epoch is not None
        ]
        raise RestPoolExhausted(reason, min(resets) if resets else None)
    route = ListingRoute(
        transport=transport,
        rest_blocked=rest_pool_blocked(snapshot) is not None,
        reason=reason,
    )
    if transport == "graphql":
        return (
            list_open_pr_statuses_graphql(
                repo=repo,
                repo_root=repo_root,
                runner=runner,
                limit=limit,
                include_files=include_files,
                include_review_decision=include_review_decision,
                include_status=include_status,
            ),
            route,
        )
    # The decision was made above, on a snapshot already taken. Letting the REST helper
    # re-probe would be a *second* rate decision on the same call — a fresh snapshot, taken
    # at a different moment, able to reach a different verdict than the one that routed here.
    # That is the two-mitigations-per-hazard smell this change removed `rest_backoff` for,
    # reappearing one layer down. Direct callers of `list_open_pr_statuses_rest` keep their
    # own guard; this path has already spent its decision.
    try:
        rows = list_open_pr_statuses_rest(
            repo=repo,
            repo_root=repo_root,
            runner=runner,
            limit=limit,
            include_files=include_files,
            include_review_decision=include_review_decision,
            include_status=include_status,
            respect_rate_pools=False,
            # The fleet path demands a determinate listing. Without this the two transports
            # fail differently for the same event — GraphQL raises, REST quietly returns [] —
            # and an empty list is indistinguishable from "no open PRs".
            fail_on_indeterminate=True,
        )
    except subprocess.SubprocessError as exc:
        raise RestListingFailed(f"github_rest_listing_indeterminate:{exc}") from exc
    return (rows, route)


def list_pr_statuses_for_branch_rest(
    branch: str,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path,
    runner: Any = subprocess.run,
    limit: int = 5,
    include_status: bool = True,
    fail_on_indeterminate: bool = False,
) -> list[dict[str, Any]]:
    payload = list_pulls_for_branch_rest(
        branch,
        repo=repo,
        repo_root=repo_root,
        runner=runner,
        state="open",
        limit=limit,
        fail_on_indeterminate=fail_on_indeterminate,
    )
    return [
        _pull_status_row_from_rest(
            item,
            repo=repo,
            repo_root=repo_root,
            runner=runner,
            include_status=include_status,
            hydrate_pull=False,
        )
        for item in payload
        if isinstance(item, dict)
    ]


def get_pr_status_rest(
    pr_number: int | str,
    *,
    repo: str = DEFAULT_REPO,
    repo_root: Path,
    runner: Any = subprocess.run,
    include_status: bool = True,
) -> dict[str, Any] | None:
    pull = get_pull_rest(pr_number, repo=repo, repo_root=repo_root, runner=runner)
    if not isinstance(pull, dict):
        return None
    return _pull_status_row_from_rest(
        pull,
        repo=repo,
        repo_root=repo_root,
        runner=runner,
        include_status=include_status,
        hydrate_pull=True,
    )


#: Header/body separator in an ``gh api -i`` response: a blank line, CRLF or LF.
#:
#: HTTP puts ``\r\n\r\n`` on the wire. ``_run`` passes ``text=True``, whose universal-newline
#: translation rewrites that to ``\n\n`` before we ever see it — measured 2026-08-29:
#: ``text=True`` output contains ``\n\n`` and no ``\r\n\r\n``; ``text=False`` output is the
#: reverse. So a bare ``partition("\n\n")`` does work today, but only because of a decoding
#: side effect nothing in this module states or tests. One caller reading bytes would break
#: it silently: no separator found, body empty, both pools ``None``, and the balancer
#: degenerates to "rest" unconditionally while ``graphql_backoff`` becomes a permanent no-op.
#: Matching both shapes removes the dependency instead of resting on it.
_RATE_SECTION_SPLIT = re.compile(r"\r?\n\r?\n")


def _split_head_body(stdout: str) -> tuple[str, str]:
    parts = _RATE_SECTION_SPLIT.split(stdout, maxsplit=1)
    return (parts[0], parts[1]) if len(parts) == 2 else (stdout, "")


def _parse_rate_headers(stdout: str) -> dict[str, str]:
    """Split ``gh api -i`` output and return lowercased response headers."""
    head, _ = _split_head_body(stdout)
    headers: dict[str, str] = {}
    for line in head.splitlines():
        if ":" in line and not line.startswith("HTTP"):
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()
    return headers


def _pool_from_body(payload: Any, resource: str) -> RatePool | None:
    if not isinstance(payload, dict):
        return None
    resources = payload.get("resources")
    if not isinstance(resources, dict):
        return None
    entry = resources.get(resource)
    if not isinstance(entry, dict):
        return None
    try:
        remaining = int(entry.get("remaining"))
        limit = int(entry.get("limit", 0))
    except (TypeError, ValueError):
        return None
    try:
        reset_epoch: int | None = int(entry.get("reset"))
    except (TypeError, ValueError):
        reset_epoch = None
    return RatePool(
        resource=resource,
        remaining=remaining,
        limit=limit,
        reset_epoch=reset_epoch,
        source="body",
    )


def rate_snapshot(
    *,
    repo_root: Path,
    runner: Any = None,
) -> RateSnapshot:
    """Probe both rate pools with one call.

    ``core`` is taken from the response headers when they are present, because the headers
    are what the API enforces. When the header and body figures disagree the **pessimistic**
    one wins: over-reporting exhaustion costs at most an unnecessary reroute, while
    under-reporting it spends a call into a 403. That asymmetry is the whole reason the
    disagreement matters.

    ``graphql`` has no cheap header source — only an actual GraphQL call returns GraphQL
    headers — so it is body-sourced and labelled as such. Callers that need certainty about
    GraphQL must make the call and read its headers.

    A lookup failure yields ``RateSnapshot(None, None)`` so callers fail open, preserving
    the pre-existing contract: a network or auth hiccup must not be mistaken for confirmed
    exhaustion.
    """
    # Late-bound so the module-level `subprocess.run` stays patchable. A
    # `runner: Any = subprocess.run` default binds at def time, which silently makes a
    # monkeypatched test issue a REAL network call — observed while writing the CLI test
    # for this change.
    runner = runner if runner is not None else subprocess.run
    try:
        proc = _run(runner, ["gh", "api", "-i", "rate_limit"], repo_root=repo_root, timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        # The fail-open promise is three paragraphs up, and a raised exception is the one way
        # to break it: the probe is now on the path of every fleet scan, so a 30-second hang
        # would crash the timer rather than proceed on unknown headroom. A probe that cannot
        # answer means "unknown", which routes to REST exactly as before this change.
        return RateSnapshot(core=None, graphql=None)
    stdout = proc.stdout or ""
    ok = getattr(proc, "returncode", 1) == 0

    # Headers are read even on a NONZERO exit. A 403 carrying `X-Ratelimit-Resource: core`
    # and `X-Ratelimit-Remaining: 0` is GitHub telling us the pool is spent — that is the
    # most direct evidence of exhaustion there is, and an earlier revision threw it away and
    # failed open, then shipped a test codifying the discard. Transport-level rate headers
    # are authoritative regardless of status code.
    #
    # The BODY is only rate data when the call succeeded: a 403's body is an error payload,
    # not a rate_limit document. So headers survive failure; the body does not.
    headers = _parse_rate_headers(stdout)
    payload = None
    if ok:
        _, body = _split_head_body(stdout)
        try:
            payload = json.loads(body or stdout or "null")
        except json.JSONDecodeError:
            payload = None

    core = _pool_from_body(payload, "core")
    graphql = _pool_from_body(payload, "graphql")

    if headers.get("x-ratelimit-resource") == "core":
        try:
            header_remaining = int(headers["x-ratelimit-remaining"])
            header_limit = int(headers.get("x-ratelimit-limit", core.limit if core else 0))
        except (KeyError, TypeError, ValueError):
            # Nothing to unwind: only the ``else`` branch reads the parsed header values,
            # so a parse failure simply leaves ``core`` as the body-derived pool.
            pass
        else:
            try:
                header_reset: int | None = int(headers.get("x-ratelimit-reset"))
            except (TypeError, ValueError):
                header_reset = core.reset_epoch if core else None
            # Pessimistic merge: never claim more headroom than the strictest source.
            # The label must follow the winning figure. Labelling a body-derived number
            # "header" would overstate its evidence in the one case the two disagree —
            # which is the case this merge exists for.
            if core is not None and core.remaining < header_remaining:
                remaining = core.remaining
                remaining_source = "body"
            else:
                remaining = header_remaining
                remaining_source = "header"
            core = RatePool(
                resource="core",
                remaining=remaining,
                limit=header_limit or (core.limit if core else 0),
                reset_epoch=header_reset,
                source=remaining_source,
            )

    return RateSnapshot(core=core, graphql=graphql)


def graphql_backoff(
    *,
    repo_root: Path,
    runner: Any = subprocess.run,
    min_remaining: int | None = None,
) -> GraphQLBackoff | None:
    """Return a backoff decision when GraphQL remaining is below threshold.

    A rate-limit lookup failure returns ``None`` so callers fail open: a network
    or auth hiccup must not be mistaken for confirmed GraphQL exhaustion.
    """

    min_remaining = _graphql_floor() if min_remaining is None else max(0, min_remaining)
    pool = rate_snapshot(repo_root=repo_root, runner=runner).graphql
    if pool is None:
        return None
    if pool.remaining >= min_remaining:
        return None
    return GraphQLBackoff(
        remaining=pool.remaining,
        reset_epoch=pool.reset_epoch,
        reason=f"github_graphql_remaining_below_threshold:{pool.remaining}<{min_remaining}",
    )


# There is deliberately no `rest_backoff()`. A first draft added one as the symmetric twin of
# `graphql_backoff`, and the unused-function gate flagged it — correctly, and for a better
# reason than "no caller": `choose_transport` already applies DEFAULT_REST_MIN_REMAINING to
# the core pool, so a separate REST guard would be a SECOND mitigation for the SAME hazard —
# two guards over one pool that can disagree. The rule is to change the shape rather than
# patch the boundary, so the twin was removed instead of being given a caller or whitelisted.
#
# `graphql_backoff` survives because it has a live consumer with different semantics —
# `run_graphql_rate_aware` sleeps on it — not because symmetry is owed.


def choose_transport(
    *,
    repo_root: Path,
    runner: Any = None,
    snapshot: RateSnapshot | None = None,
    rest_min_remaining: int | None = None,
    graphql_min_remaining: int | None = None,
) -> tuple[str | None, str]:
    """Pick REST or GraphQL by measured headroom, **before** spending the call.

    Returns ``(transport, reason)`` where transport is ``"rest"``, ``"graphql"``, or
    ``None`` when both pools are below their floors.

    This is the difference between balancing and falling back. The three pre-existing
    GraphQL call sites are fallbacks: they fire only after REST fails, and a path that
    engages on failure cannot *prevent* exhaustion — it can only react to it. That is why
    ``core`` reached 0/5000 while ``graphql`` sat at 4660/5000; the shape predicts it.

    Ties and unknowns resolve to REST, preserving post-#4436 behaviour: this function only
    ever diverts traffic away from a pool measured to be in trouble.
    """
    snapshot = snapshot or rate_snapshot(repo_root=repo_root, runner=runner)
    rest_floor = _rest_floor() if rest_min_remaining is None else max(0, rest_min_remaining)
    graphql_floor = (
        _graphql_floor() if graphql_min_remaining is None else max(0, graphql_min_remaining)
    )

    core, graph = snapshot.core, snapshot.graphql
    # One decision point for REST exhaustion: delegate rather than re-derive the floor.
    rest_blocked = rest_pool_blocked(snapshot, min_remaining=rest_floor)
    rest_ok = rest_blocked is None
    graph_known = graph is not None
    graph_ok = graph_known and graph.remaining >= graphql_floor

    if not rest_ok and not graph_ok:
        # Distinguish "both measured low" from "one measured low, the other unmeasured".
        # Collapsing them let a known-low REST pool plus absent GraphQL telemetry report
        # `both_pools_below_floor`, recording an inference as a measurement.
        if not graph_known:
            return None, (
                f"github_rest_below_floor_graphql_unknown:core={core.remaining if core else '?'}"
            )
        detail = f"core={core.remaining if core else '?'} graphql={graph.remaining}"
        return None, f"github_both_pools_below_floor:{detail}"
    if not rest_ok:
        return "graphql", (
            f"github_rest_below_floor:{core.remaining}<{rest_floor}"
            f";graphql_remaining={graph.remaining}"
        )
    if not graph_ok:
        # Same discipline as the both-blocked branch above, which this branch was missing:
        # "measured below the floor" and "never measured" are different states, and a reason
        # code that spells them the same way cannot be reconstructed later. The routing
        # outcome is REST either way; the record of why is not.
        if not graph_known:
            return "rest", "github_graphql_unknown"
        return "rest", f"github_graphql_below_floor:{graph.remaining}<{graphql_floor}"
    # Both healthy: send work to whichever pool has proportionally more room, so the two
    # drain together instead of one hitting zero while the other idles.
    if core is not None and graph.fraction > core.fraction:
        return "graphql", (
            f"github_graphql_has_more_headroom:{graph.fraction:.2f}>{core.fraction:.2f}"
        )
    return "rest", "github_rest_has_headroom"


def run_graphql_rate_aware(
    graphql_args: list[str],
    *,
    repo_root: Path,
    runner: Any = subprocess.run,
    min_remaining: int | None = None,
    max_sleep_seconds: int | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess:
    """Run ``gh api graphql`` only when the GraphQL pool is not exhausted."""

    backoff = graphql_backoff(
        repo_root=repo_root,
        runner=runner,
        min_remaining=min_remaining
        if min_remaining is not None
        else _env_int("HAPAX_GITHUB_GRAPHQL_MIN_REMAINING", DEFAULT_GRAPHQL_MIN_REMAINING),
    )
    if backoff is not None:
        max_sleep = (
            _env_int(
                "HAPAX_GITHUB_GRAPHQL_BACKOFF_MAX_SLEEP_SECONDS",
                DEFAULT_GRAPHQL_BACKOFF_MAX_SLEEP_SECONDS,
            )
            if max_sleep_seconds is None
            else max(0, max_sleep_seconds)
        )
        reset = backoff.reset_in_seconds
        if reset is not None and max_sleep > 0:
            time.sleep(min(reset, max_sleep))
            backoff = graphql_backoff(
                repo_root=repo_root,
                runner=runner,
                min_remaining=min_remaining
                if min_remaining is not None
                else _env_int("HAPAX_GITHUB_GRAPHQL_MIN_REMAINING", DEFAULT_GRAPHQL_MIN_REMAINING),
            )
        if backoff is None:
            return _run(
                runner,
                ["gh", "api", "graphql", *graphql_args],
                repo_root=repo_root,
                timeout=timeout,
            )
        reset = backoff.reset_in_seconds
        retry = f"; retry_after={reset}s" if reset is not None else ""
        return subprocess.CompletedProcess(
            ["gh", "api", "graphql", *graphql_args],
            GRAPHQL_BACKOFF_RC,
            "",
            f"{backoff.reason}{retry}",
        )
    return _run(
        runner,
        ["gh", "api", "graphql", *graphql_args],
        repo_root=repo_root,
        timeout=timeout,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    open_parser = subparsers.add_parser(
        "open-prs",
        help="Emit GraphQL-shaped open PR snapshots fetched through REST/core.",
    )
    open_parser.add_argument("--repo", default=DEFAULT_REPO)
    open_parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    open_parser.add_argument("--head", help="Filter to an open PR head branch.")
    open_parser.add_argument("--limit", type=int, default=100)
    open_parser.add_argument(
        "--no-status",
        action="store_true",
        help="Omit per-PR check/status rollups when only PR identity is needed.",
    )

    rate_parser = subparsers.add_parser(
        "rate",
        help="Report both rate pools and which transport has headroom.",
    )
    rate_parser.add_argument("--repo-root", type=Path, default=Path.cwd())

    args = parser.parse_args(argv)
    if args.command == "rate":
        # The diagnostic that would have made 2026-08-29 instant: `gh auth status` said the
        # token was invalid (it was not — the pool was empty) and `gh api rate_limit`
        # reported core headroom that a real call contradicted. This prints what actually
        # governs, per pool, with provenance.
        snapshot = rate_snapshot(repo_root=args.repo_root)
        transport, reason = choose_transport(repo_root=args.repo_root, snapshot=snapshot)
        payload = {
            "core": asdict(snapshot.core) if snapshot.core else None,
            "graphql": asdict(snapshot.graphql) if snapshot.graphql else None,
            "transport": transport,
            "reason": reason,
        }
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        # Exit non-zero when neither pool is spendable, so a caller can branch on it
        # without parsing the payload.
        return 0 if transport else GRAPHQL_BACKOFF_RC
    if args.command == "open-prs":
        include_status = not args.no_status
        if args.head:
            rows = list_pr_statuses_for_branch_rest(
                args.head,
                repo=args.repo,
                repo_root=args.repo_root,
                limit=args.limit,
                include_status=include_status,
                fail_on_indeterminate=True,
            )
        else:
            # Deliberately NOT routed through `list_open_pr_statuses`. This diagnostic asks
            # for `fail_on_indeterminate=True`, which is REST-specific strictness about
            # incomplete check evidence and has no GraphQL analogue — routing it would drop
            # that strictness silently on half its runs. It is also a hand-run command, so it
            # is not the traffic the balancer exists to spread.
            rows = list_open_pr_statuses_rest(
                repo=args.repo,
                repo_root=args.repo_root,
                limit=args.limit,
                include_status=include_status,
                fail_on_indeterminate=True,
            )
        json.dump(rows, sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
