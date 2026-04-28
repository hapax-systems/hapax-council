"""Guarded Tavily client with cache, budget accounting, and ledger writes."""

from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import logging
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml

log = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "tavily.yaml"


class TavilyConfigError(RuntimeError):
    """Raised when Tavily config is present but unsafe or unparsable."""


@dataclass(frozen=True)
class TavilyOperationConfig:
    enabled: bool
    daily_budget_units: int
    estimated_cost_units: int


@dataclass(frozen=True)
class TavilyStatePaths:
    cache_path: Path
    budget_path: Path
    ledger_path: Path
    lock_path: Path


@dataclass(frozen=True)
class TavilyConfig:
    base_url: str = "https://api.tavily.com"
    timeout_s: float = 15.0
    cache_ttl_s: int = 86_400
    global_daily_cap_units: int = 100
    max_concurrent_requests: int = 1
    default_max_results: int = 5
    state: TavilyStatePaths = field(
        default_factory=lambda: TavilyStatePaths(
            cache_path=Path("~/.cache/hapax/tavily/cache.json").expanduser(),
            budget_path=Path("~/.cache/hapax/tavily/budget.json").expanduser(),
            ledger_path=Path("~/.cache/hapax/tavily/ledger.jsonl").expanduser(),
            lock_path=Path("~/.cache/hapax/tavily/state.lock").expanduser(),
        )
    )
    operations: dict[str, TavilyOperationConfig] = field(
        default_factory=lambda: {
            "search": TavilyOperationConfig(True, 80, 1),
            "extract": TavilyOperationConfig(False, 0, 1),
            "crawl": TavilyOperationConfig(False, 0, 1),
            "map": TavilyOperationConfig(False, 0, 1),
            "research": TavilyOperationConfig(False, 0, 2),
        }
    )
    caller_daily_budgets: dict[str, int] = field(
        default_factory=lambda: {
            "agents.scout": 60,
            "agents.demo_pipeline.research": 10,
            "default": 20,
        }
    )

    @classmethod
    def load(cls, path: Path | str | None = None) -> TavilyConfig:
        config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
        if not config_path.exists():
            return cls()
        try:
            raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise TavilyConfigError(f"invalid Tavily config YAML at {config_path}: {exc}") from exc
        except OSError as exc:
            raise TavilyConfigError(f"cannot read Tavily config at {config_path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise TavilyConfigError(
                f"invalid Tavily config at {config_path}: top-level map required"
            )
        return cls.from_mapping(raw, source=config_path)

    @classmethod
    def from_mapping(cls, raw: dict[str, Any], *, source: Path | None = None) -> TavilyConfig:
        defaults = cls()
        state_raw = raw.get("state", {}) or {}
        if not isinstance(state_raw, dict):
            raise TavilyConfigError(_config_msg(source, "state must be a map"))

        state = TavilyStatePaths(
            cache_path=_path_value(
                state_raw.get("cache_path"),
                defaults.state.cache_path,
                source,
                "state.cache_path",
            ),
            budget_path=_path_value(
                state_raw.get("budget_path"),
                defaults.state.budget_path,
                source,
                "state.budget_path",
            ),
            ledger_path=_path_value(
                state_raw.get("ledger_path"),
                defaults.state.ledger_path,
                source,
                "state.ledger_path",
            ),
            lock_path=_path_value(
                state_raw.get("lock_path"),
                defaults.state.lock_path,
                source,
                "state.lock_path",
            ),
        )

        operations_raw = raw.get("operations", {}) or {}
        if not isinstance(operations_raw, dict):
            raise TavilyConfigError(_config_msg(source, "operations must be a map"))
        operations = dict(defaults.operations)
        for name, value in operations_raw.items():
            if not isinstance(value, dict):
                raise TavilyConfigError(_config_msg(source, f"operation {name!r} must be a map"))
            default_operation = operations.get(str(name), defaults.operations["search"])
            operations[str(name)] = TavilyOperationConfig(
                enabled=_bool_value(
                    value.get("enabled"),
                    default_operation.enabled,
                    source,
                    f"operations.{name}.enabled",
                ),
                daily_budget_units=_int_value(
                    value.get("daily_budget_units"),
                    default_operation.daily_budget_units,
                    source,
                    f"operations.{name}.daily_budget_units",
                    min_value=0,
                ),
                estimated_cost_units=_int_value(
                    value.get("estimated_cost_units"),
                    default_operation.estimated_cost_units,
                    source,
                    f"operations.{name}.estimated_cost_units",
                    min_value=1,
                ),
            )

        caller_raw = raw.get("caller_daily_budgets", {}) or {}
        if not isinstance(caller_raw, dict):
            raise TavilyConfigError(_config_msg(source, "caller_daily_budgets must be a map"))
        caller_daily_budgets = dict(defaults.caller_daily_budgets)
        for caller, budget in caller_raw.items():
            caller_daily_budgets[str(caller)] = _int_value(
                budget,
                caller_daily_budgets.get(str(caller), caller_daily_budgets["default"]),
                source,
                f"caller_daily_budgets.{caller}",
                min_value=0,
            )

        return cls(
            base_url=str(raw.get("base_url", defaults.base_url)).rstrip("/"),
            timeout_s=_float_value(
                raw.get("timeout_s"),
                defaults.timeout_s,
                source,
                "timeout_s",
                min_value=0.1,
            ),
            cache_ttl_s=_int_value(
                raw.get("cache_ttl_s"),
                defaults.cache_ttl_s,
                source,
                "cache_ttl_s",
                min_value=0,
            ),
            global_daily_cap_units=_int_value(
                raw.get("global_daily_cap_units"),
                defaults.global_daily_cap_units,
                source,
                "global_daily_cap_units",
                min_value=0,
            ),
            max_concurrent_requests=_int_value(
                raw.get("max_concurrent_requests"),
                defaults.max_concurrent_requests,
                source,
                "max_concurrent_requests",
                min_value=1,
            ),
            default_max_results=_int_value(
                raw.get("default_max_results"),
                defaults.default_max_results,
                source,
                "default_max_results",
                min_value=1,
            ),
            state=state,
            operations=operations,
            caller_daily_budgets=caller_daily_budgets,
        )


@dataclass(frozen=True)
class TavilyResult:
    operation: str
    status: str
    results: list[dict[str, Any]] = field(default_factory=list)
    answer: str = ""
    error_class: str = ""
    cache_hit: bool = False
    query_hash: str = ""
    latency_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.status in {"ok", "cache_hit"}


class TavilyClient:
    """Shared Tavily HTTP surface.

    All network calls go through cache, payload guard, daily budget, key
    resolution, local concurrency, and ledger recording in that order.
    """

    def __init__(
        self,
        config: TavilyConfig | None = None,
        *,
        opener: Callable[..., Any] = urlopen,
        sleep: Callable[[float], None] = time.sleep,
        key_loader: Callable[[], str] | None = None,
    ) -> None:
        self.config = config or TavilyConfig.load()
        self._opener = opener
        self._sleep = sleep
        self._key_loader = key_loader or _load_api_key
        self._thread_lock = threading.Lock()
        self._http_semaphore = threading.BoundedSemaphore(self.config.max_concurrent_requests)

    @classmethod
    def from_config(cls, path: Path | str | None = None) -> TavilyClient:
        return cls(config=TavilyConfig.load(path))

    def search(
        self,
        query: str,
        *,
        caller: str,
        max_results: int | None = None,
        search_depth: str = "basic",
        include_answer: bool = False,
    ) -> TavilyResult:
        payload = {
            "query": query,
            "max_results": max_results or self.config.default_max_results,
            "search_depth": search_depth,
            "include_answer": include_answer,
        }
        return self._request("search", payload, caller=caller)

    def _request(self, operation: str, payload: dict[str, Any], *, caller: str) -> TavilyResult:
        start = time.monotonic()
        query_hash = _payload_hash(operation, payload)
        guard_reason = _guard_payload(payload)
        if guard_reason:
            result = TavilyResult(
                operation=operation,
                status="guard_denied",
                error_class=guard_reason,
                query_hash=query_hash,
            )
            self._write_ledger(caller, payload, result, _cost_for(self.config, operation), start)
            return result

        op_config = self.config.operations.get(operation)
        if op_config is None or not op_config.enabled:
            result = TavilyResult(
                operation=operation,
                status="disabled",
                error_class="operation_disabled",
                query_hash=query_hash,
            )
            self._write_ledger(caller, payload, result, 0, start)
            return result

        with self._state_lock():
            cached = self._cache_get(query_hash)
            if cached is not None:
                result = TavilyResult(
                    operation=operation,
                    status="cache_hit",
                    results=cached.get("results", []),
                    answer=cached.get("answer", ""),
                    cache_hit=True,
                    query_hash=query_hash,
                )
                self._append_ledger_locked(caller, payload, result, 0, start)
                return result

        api_key = self._key_loader()
        if not api_key:
            result = TavilyResult(
                operation=operation,
                status="no_key",
                error_class="missing_api_key",
                query_hash=query_hash,
            )
            self._write_ledger(caller, payload, result, 0, start)
            return result

        with self._state_lock():
            cost = op_config.estimated_cost_units
            denial = self._try_acquire_budget(operation, caller, cost)
            if denial:
                result = TavilyResult(
                    operation=operation,
                    status="over_budget",
                    error_class=denial,
                    query_hash=query_hash,
                )
                self._append_ledger_locked(caller, payload, result, cost, start)
                return result

        result = self._dispatch(operation, payload, api_key=api_key, query_hash=query_hash)
        with self._state_lock():
            if result.ok:
                self._cache_put(query_hash, result)
            self._append_ledger_locked(
                caller, payload, result, op_config.estimated_cost_units, start
            )
        return result

    def _dispatch(
        self,
        operation: str,
        payload: dict[str, Any],
        *,
        api_key: str,
        query_hash: str,
    ) -> TavilyResult:
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        req = Request(
            f"{self.config.base_url}/{operation}",
            data=encoded,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        started = time.monotonic()
        last_error = ""
        for attempt in range(3):
            acquired = self._http_semaphore.acquire(timeout=self.config.timeout_s)
            if not acquired:
                return TavilyResult(
                    operation=operation,
                    status="error",
                    error_class="concurrency_timeout",
                    query_hash=query_hash,
                    latency_ms=_elapsed_ms(started),
                )
            try:
                with self._opener(req, timeout=self.config.timeout_s) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                return TavilyResult(
                    operation=operation,
                    status="ok",
                    results=[
                        {
                            "title": item.get("title", ""),
                            "url": item.get("url", ""),
                            "content": item.get("content", ""),
                        }
                        for item in data.get("results", [])
                        if isinstance(item, dict)
                    ],
                    answer=str(data.get("answer", "") or ""),
                    query_hash=query_hash,
                    latency_ms=_elapsed_ms(started),
                )
            except HTTPError as exc:
                last_error = f"http_{exc.code}"
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    break
                self._sleep(0.25 * (2**attempt))
            except TimeoutError:
                last_error = "timeout"
                if attempt == 2:
                    break
                self._sleep(0.25 * (2**attempt))
            except (URLError, json.JSONDecodeError) as exc:
                last_error = type(exc).__name__
                break
            finally:
                self._http_semaphore.release()

        log.warning("Tavily %s failed: %s", operation, last_error)
        return TavilyResult(
            operation=operation,
            status="error",
            error_class=last_error or "request_failed",
            query_hash=query_hash,
            latency_ms=_elapsed_ms(started),
        )

    @contextmanager
    def _state_lock(self):
        self.config.state.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._thread_lock:
            with self.config.state.lock_path.open("a+") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _cache_get(self, query_hash: str) -> dict[str, Any] | None:
        payload = _read_json(self.config.state.cache_path, {"entries": {}})
        entry = payload.get("entries", {}).get(query_hash)
        if not isinstance(entry, dict):
            return None
        created_at = float(entry.get("created_at", 0.0))
        if time.time() - created_at > self.config.cache_ttl_s:
            return None
        response = entry.get("response", {})
        return response if isinstance(response, dict) else None

    def _cache_put(self, query_hash: str, result: TavilyResult) -> None:
        payload = _read_json(self.config.state.cache_path, {"entries": {}})
        entries = payload.setdefault("entries", {})
        entries[query_hash] = {
            "created_at": time.time(),
            "response": {
                "results": result.results,
                "answer": result.answer,
            },
        }
        _write_json_atomic(self.config.state.cache_path, payload)

    def _try_acquire_budget(self, operation: str, caller: str, cost: int) -> str:
        today = dt.datetime.now(dt.UTC).date().isoformat()
        state = _read_json(
            self.config.state.budget_path,
            {
                "day_utc": today,
                "global_used": 0,
                "operation_used": {},
                "caller_used": {},
            },
        )
        if state.get("day_utc") != today:
            state = {
                "day_utc": today,
                "global_used": 0,
                "operation_used": {},
                "caller_used": {},
            }

        operation_used = state.setdefault("operation_used", {})
        caller_used = state.setdefault("caller_used", {})
        op_budget = self.config.operations[operation].daily_budget_units
        caller_budget = self.config.caller_daily_budgets.get(
            caller,
            self.config.caller_daily_budgets.get("default", 0),
        )
        if int(state.get("global_used", 0)) + cost > self.config.global_daily_cap_units:
            return "global_daily_cap_exhausted"
        if int(operation_used.get(operation, 0)) + cost > op_budget:
            return "operation_daily_budget_exhausted"
        if int(caller_used.get(caller, 0)) + cost > caller_budget:
            return "caller_daily_budget_exhausted"

        state["global_used"] = int(state.get("global_used", 0)) + cost
        operation_used[operation] = int(operation_used.get(operation, 0)) + cost
        caller_used[caller] = int(caller_used.get(caller, 0)) + cost
        _write_json_atomic(self.config.state.budget_path, state)
        return ""

    def _write_ledger(
        self,
        caller: str,
        payload: dict[str, Any],
        result: TavilyResult,
        cost: int,
        start: float,
    ) -> None:
        with self._state_lock():
            self._append_ledger_locked(caller, payload, result, cost, start)

    def _append_ledger_locked(
        self,
        caller: str,
        payload: dict[str, Any],
        result: TavilyResult,
        cost: int,
        start: float,
    ) -> None:
        self.config.state.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": dt.datetime.now(dt.UTC).isoformat(),
            "caller": caller,
            "operation": result.operation,
            "query_hash": result.query_hash,
            "cache_hit": result.cache_hit,
            "estimated_cost_units": cost,
            "result_count": len(result.results),
            "status": result.status,
            "latency_ms": result.latency_ms or _elapsed_ms(start),
            "error_class": result.error_class,
            "max_results": payload.get("max_results"),
        }
        with self.config.state.ledger_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, sort_keys=True) + "\n")


def _config_msg(source: Path | None, message: str) -> str:
    prefix = f"invalid Tavily config at {source}: " if source else "invalid Tavily config: "
    return prefix + message


def _path_value(value: Any, default: Path, source: Path | None, key: str) -> Path:
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise TavilyConfigError(_config_msg(source, f"{key} must be a non-empty path string"))
    return Path(value).expanduser()


def _int_value(
    value: Any,
    default: int,
    source: Path | None,
    key: str,
    *,
    min_value: int,
) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise TavilyConfigError(_config_msg(source, f"{key} must be an integer")) from exc
    if parsed < min_value:
        raise TavilyConfigError(_config_msg(source, f"{key} must be >= {min_value}"))
    return parsed


def _float_value(
    value: Any,
    default: float,
    source: Path | None,
    key: str,
    *,
    min_value: float,
) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise TavilyConfigError(_config_msg(source, f"{key} must be a number")) from exc
    if parsed < min_value:
        raise TavilyConfigError(_config_msg(source, f"{key} must be >= {min_value}"))
    return parsed


def _bool_value(value: Any, default: bool, source: Path | None, key: str) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise TavilyConfigError(_config_msg(source, f"{key} must be a boolean"))


def _payload_hash(operation: str, payload: dict[str, Any]) -> str:
    normalized = json.dumps(
        {"operation": operation, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _cost_for(config: TavilyConfig, operation: str) -> int:
    op_config = config.operations.get(operation)
    return op_config.estimated_cost_units if op_config else 0


_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:api[_-]?key|password|passwd|token|secret)\s*[=:]", re.IGNORECASE),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\bTAVILY_API_KEY\b"),
]

_LOCAL_PATH_PATTERNS = [
    re.compile(r"(^|\s)(?:/home|/etc|/var|/tmp|/mnt|/run|/dev|~)/"),
    re.compile(r"\b(?:Documents/Personal|20-projects|\.ssh|\.gnupg|pass show)\b"),
]

_WORK_CONTEXT_PATTERNS = [
    re.compile(r"\b(?:confidential|proprietary|employer|corporate|work account)\b", re.IGNORECASE),
]


def _guard_payload(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, sort_keys=True)
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            return "secret_like_payload"
    for pattern in _LOCAL_PATH_PATTERNS:
        if pattern.search(text):
            return "local_path_payload"
    for pattern in _WORK_CONTEXT_PATTERNS:
        if pattern.search(text):
            return "work_context_payload"
    return ""


def _load_api_key() -> str:
    env_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if env_key:
        return env_key
    try:
        result = subprocess.run(
            ["pass", "show", "api/tavily"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(default)
    return data if isinstance(data, dict) else dict(default)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
