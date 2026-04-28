"""Shared Tavily REST client with Hapax budget, cache, and egress guardrails."""

from __future__ import annotations

import fcntl
import hashlib
import ipaddress
import json
import math
import os
import re
import subprocess
import time
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

API_BASE_URL = "https://api.tavily.com"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "tavily.yaml"
DEFAULT_STATE_DIR = Path("~/.cache/hapax/tavily").expanduser()
DEFAULT_CACHE_DIR = DEFAULT_STATE_DIR / "cache"
DEFAULT_LEDGER_PATH = DEFAULT_STATE_DIR / "usage.jsonl"
DEFAULT_LOCK_DIR = DEFAULT_STATE_DIR / "locks"
PASS_ENTRIES = ("tavily/api-key", "api/tavily")

SearchDepth = Literal["basic", "advanced", "fast", "ultra-fast"]
SearchTopic = Literal["general", "news", "finance"]
SearchTimeRange = Literal["day", "week", "month", "year", "d", "w", "m", "y"]
ExtractDepth = Literal["basic", "advanced"]
ResearchModel = Literal["mini", "pro", "auto"]
ExtractFormat = Literal["markdown", "text"]


class TavilyConfigError(RuntimeError):
    """Tavily is not configured well enough to make a request."""


class TavilyPolicyViolation(ValueError):
    """A query or extraction request violates Hapax egress policy."""


class TavilyBudgetExceeded(RuntimeError):
    """A Tavily request would exceed the configured credit budget."""


class TavilyRequestError(RuntimeError):
    """Tavily returned an error or could not be reached."""


class TavilyUsage(BaseModel):
    """Credit usage returned or inferred for one Tavily request."""

    credits: float = 0
    endpoint: str = ""
    cache_hit: bool = False
    estimated_credits: float = 0
    actual_credits: float = 0


class TavilySearchResult(BaseModel):
    """A normalized Tavily search result."""

    title: str = ""
    url: str = ""
    content: str = ""
    score: float | None = None
    raw_content: str | None = None
    published_date: str | None = None


class TavilySearchRequest(BaseModel):
    """Request body for Tavily `/search`."""

    model_config = ConfigDict(extra="allow")

    query: str
    lane: str = "interactive_coding"
    max_results: int = Field(default=5, ge=1, le=20)
    search_depth: SearchDepth = "basic"
    topic: SearchTopic = "general"
    time_range: SearchTimeRange | None = None
    start_date: str | None = None
    end_date: str | None = None
    chunks_per_source: int | None = Field(default=None, ge=1, le=3)
    include_answer: bool = False
    include_raw_content: bool = False
    include_images: bool = False
    include_image_descriptions: bool = False
    include_favicon: bool = False
    include_domains: list[str] | None = None
    exclude_domains: list[str] | None = None
    country: str | None = None
    exact_match: bool = False
    auto_parameters: bool = False
    safe_search: bool = False
    include_usage: bool = True
    project_id: str | None = None
    allow_private: bool = False
    allow_public_bibliographic_people: bool = False
    p0: bool = False


class TavilyExtractRequest(BaseModel):
    """Request body for Tavily `/extract`."""

    model_config = ConfigDict(extra="allow")

    urls: list[str]
    lane: str = "interactive_coding"
    extract_depth: ExtractDepth = "basic"
    format: ExtractFormat = "markdown"
    query: str | None = None
    include_images: bool = False
    include_favicon: bool = False
    include_usage: bool = True
    project_id: str | None = None
    allow_private: bool = False
    p0: bool = False

    @field_validator("urls")
    @classmethod
    def _require_urls(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("urls must not be empty")
        return value


class TavilyMapRequest(BaseModel):
    """Request body for Tavily `/map`."""

    model_config = ConfigDict(extra="allow")

    url: str
    lane: str = "knowledge_ingest"
    instructions: str | None = None
    max_depth: int = Field(default=1, ge=1, le=5)
    max_breadth: int = Field(default=20, ge=1, le=500)
    limit: int = Field(default=50, ge=1)
    allow_external: bool = True
    select_domains: list[str] | None = None
    select_paths: list[str] | None = None
    include_usage: bool = True
    project_id: str | None = None
    allow_private: bool = False
    p0: bool = False


class TavilyCrawlRequest(BaseModel):
    """Request body for Tavily `/crawl`."""

    model_config = ConfigDict(extra="allow")

    url: str
    lane: str = "knowledge_ingest"
    instructions: str | None = None
    max_depth: int = Field(default=1, ge=1, le=5)
    max_breadth: int = Field(default=20, ge=1, le=500)
    limit: int = Field(default=50, ge=1)
    extract_depth: ExtractDepth = "basic"
    format: ExtractFormat = "markdown"
    include_images: bool = False
    include_favicon: bool = False
    allow_external: bool = True
    select_domains: list[str] | None = None
    select_paths: list[str] | None = None
    include_usage: bool = True
    project_id: str | None = None
    allow_private: bool = False
    p0: bool = False


class TavilyResearchRequest(BaseModel):
    """Request body for Tavily `/research`."""

    model_config = ConfigDict(extra="allow")

    query: str
    lane: str = "research_reports"
    model: ResearchModel = "mini"
    include_usage: bool = True
    project_id: str | None = None
    allow_private: bool = False
    allow_public_bibliographic_people: bool = False
    p0: bool = False


class TavilySearchResponse(BaseModel):
    """Normalized response for Tavily `/search`."""

    query: str = ""
    answer: str | None = None
    results: list[TavilySearchResult] = Field(default_factory=list)
    images: list[Any] = Field(default_factory=list)
    response_time: float | None = None
    usage: TavilyUsage = Field(default_factory=TavilyUsage)
    raw: dict[str, Any] = Field(default_factory=dict)


class TavilyRawResponse(BaseModel):
    """Generic normalized response for non-search Tavily endpoints."""

    endpoint: str
    data: dict[str, Any] = Field(default_factory=dict)
    usage: TavilyUsage = Field(default_factory=TavilyUsage)


class TavilyAccountUsage(BaseModel):
    """Usage fields returned by Tavily for an API key or whole account."""

    usage: float = 0
    limit: float = 0
    search_usage: float = 0
    extract_usage: float = 0
    crawl_usage: float = 0
    map_usage: float = 0
    research_usage: float = 0
    current_plan: str | None = None
    plan_usage: float = 0
    plan_limit: float = 0
    paygo_usage: float = 0
    paygo_limit: float = 0


class TavilyUsageResponse(BaseModel):
    """Normalized response for Tavily `/usage`."""

    key: TavilyAccountUsage = Field(default_factory=TavilyAccountUsage)
    account: TavilyAccountUsage = Field(default_factory=TavilyAccountUsage)
    raw: dict[str, Any] = Field(default_factory=dict)


def pass_first_line(name: str) -> str:
    """Return the first line from pass, or an empty string."""
    try:
        result = subprocess.run(
            ["pass", "show", name],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.splitlines()[0].strip() if result.stdout.splitlines() else ""


def load_tavily_api_key(env: Mapping[str, str] | None = None) -> str:
    """Load Tavily API key from env, then expected pass entries."""
    env = env or os.environ
    value = env.get("TAVILY_API_KEY", "").strip()
    if value:
        return value
    for entry in PASS_ENTRIES:
        value = pass_first_line(entry)
        if value:
            return value
    return ""


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise TavilyConfigError(f"Tavily config must be a mapping: {path}")
    return data


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _month_prefix(ts: datetime) -> str:
    return ts.strftime("%Y-%m")


def _day_prefix(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d")


def _json_default(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=_json_default)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _expand_config_path(value: Any, default: Path) -> Path:
    if not value:
        return default
    return Path(str(value)).expanduser()


def _float_config(config: Mapping[str, Any], key: str, default: float) -> float:
    try:
        return float(config.get(key, default))
    except (TypeError, ValueError) as exc:
        raise TavilyConfigError(f"Tavily config {key} must be numeric") from exc


def _int_config(config: Mapping[str, Any], key: str, default: int) -> int:
    try:
        return int(config.get(key, default))
    except (TypeError, ValueError) as exc:
        raise TavilyConfigError(f"Tavily config {key} must be an integer") from exc


@contextmanager
def _exclusive_file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _host(value: str) -> str:
    parsed = urlparse(value)
    return parsed.netloc.lower()


_REDACTED_TEXT_KEYS = {"query", "input", "instructions"}


def _redacted_payload(endpoint: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {"endpoint": endpoint}
    for key, value in payload.items():
        if key in _REDACTED_TEXT_KEYS and isinstance(value, str):
            redacted[f"{key}_hash"] = _stable_hash(value)
        elif key == "urls" and isinstance(value, list):
            redacted["url_hosts"] = sorted({_host(str(url)) for url in value})
        elif key == "url" and isinstance(value, str):
            redacted["url_host"] = _host(value)
        elif key not in {"api_key", *_REDACTED_TEXT_KEYS}:
            redacted[key] = value
    return redacted


_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_TOKEN_RE = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|"
    r"eyJ[A-Za-z0-9_-]{40,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,})"
)
_PRIVATE_MARKERS = (
    "internal only",
    "confidential",
    "nda",
    "proprietary",
    "private email",
    "raw transcript",
    "meeting transcript",
    "slack transcript",
    "from:",
    "subject:",
)
_BIBLIOGRAPHIC_MARKERS = (
    "orcid",
    "datacite",
    "doi",
    "publication",
    "paper",
    "arxiv",
    "scholar",
    "citation",
)


def validate_public_web_text(
    text: str,
    *,
    allow_private: bool = False,
    allow_public_bibliographic_people: bool = False,
) -> None:
    """Reject private/corporate/operator data before web egress."""
    if allow_private:
        return
    lower = text.lower()
    if _TOKEN_RE.search(text):
        raise TavilyPolicyViolation("query appears to contain a credential or bearer token")
    if _EMAIL_RE.search(text):
        if not (
            allow_public_bibliographic_people
            and any(marker in lower for marker in _BIBLIOGRAPHIC_MARKERS)
        ):
            raise TavilyPolicyViolation("query appears to contain an email address")
    if any(marker in lower for marker in _PRIVATE_MARKERS):
        raise TavilyPolicyViolation("query appears to contain private or corporate content")


def validate_public_web_url(url: str, *, allow_private: bool = False) -> None:
    """Reject local/private URLs before handing them to Tavily URL endpoints."""
    if allow_private:
        return

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise TavilyPolicyViolation("url must be a public http(s) URL")
    if parsed.username or parsed.password:
        raise TavilyPolicyViolation("url must not contain credentials")

    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise TavilyPolicyViolation("url must have a public host")
    if host == "localhost" or host.endswith(".local"):
        raise TavilyPolicyViolation("url host is local-only")
    if "." not in host and ":" not in host:
        raise TavilyPolicyViolation("url host must be publicly resolvable")

    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise TavilyPolicyViolation("url host is not public")


class TavilyClient:
    """Small REST client for Tavily with Hapax accounting and policy checks."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        config_path: Path | None = None,
        cache_dir: Path | None = None,
        ledger_path: Path | None = None,
        lock_dir: Path | None = None,
        http_client: httpx.Client | None = None,
        now: Callable[[], datetime] = _utc_now,
        base_url: str | None = None,
    ) -> None:
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self.config = _load_yaml(self.config_path)
        self.api_key = (api_key if api_key is not None else load_tavily_api_key()).strip()
        state_config = self.config.get("state", {}) if isinstance(self.config, Mapping) else {}
        if not isinstance(state_config, Mapping):
            raise TavilyConfigError("Tavily config state must be a mapping")
        self.cache_dir = cache_dir or _expand_config_path(
            state_config.get("cache_dir"), DEFAULT_CACHE_DIR
        )
        self.ledger_path = ledger_path or _expand_config_path(
            state_config.get("ledger_path"), DEFAULT_LEDGER_PATH
        )
        self.lock_dir = lock_dir or _expand_config_path(
            state_config.get("lock_dir"), DEFAULT_LOCK_DIR
        )
        self.http_client = http_client or httpx.Client(
            timeout=_float_config(self.config, "timeout_s", 30.0)
        )
        self.now = now
        self.base_url = (base_url or str(self.config.get("base_url") or API_BASE_URL)).rstrip("/")
        self.max_concurrent_requests = max(
            1, _int_config(self.config, "max_concurrent_requests", 4)
        )
        self.reservation_ttl_s = max(1, _int_config(self.config, "reservation_ttl_s", 900))

    def search(self, request: TavilySearchRequest) -> TavilySearchResponse:
        payload = request.model_dump(
            exclude={
                "lane",
                "project_id",
                "allow_private",
                "p0",
                "allow_public_bibliographic_people",
            },
            exclude_none=True,
        )
        if request.safe_search:
            if request.search_depth in {"fast", "ultra-fast"}:
                raise TavilyPolicyViolation(
                    "Tavily safe_search is not supported for fast or ultra-fast search"
                )
        else:
            payload.pop("safe_search", None)
        validate_public_web_text(
            request.query,
            allow_private=request.allow_private,
            allow_public_bibliographic_people=self._allow_public_bibliographic_people(
                request.allow_public_bibliographic_people
            ),
        )
        data, usage = self._request(
            "search",
            payload,
            lane=request.lane,
            project_id=request.project_id,
            estimate=self._estimate_search(request),
            p0=request.p0,
        )
        results = [TavilySearchResult.model_validate(item) for item in data.get("results", [])]
        return TavilySearchResponse(
            query=str(data.get("query", request.query)),
            answer=data.get("answer"),
            results=results,
            images=data.get("images") or [],
            response_time=data.get("response_time"),
            usage=usage,
            raw=data,
        )

    def extract(self, request: TavilyExtractRequest) -> TavilyRawResponse:
        for url in request.urls:
            validate_public_web_url(url, allow_private=request.allow_private)
        if request.query:
            validate_public_web_text(request.query, allow_private=request.allow_private)
        payload = request.model_dump(
            exclude={"lane", "project_id", "allow_private", "p0"},
            exclude_none=True,
        )
        data, usage = self._request(
            "extract",
            payload,
            lane=request.lane,
            project_id=request.project_id,
            estimate=self._estimate_extract(request),
            p0=request.p0,
        )
        return TavilyRawResponse(endpoint="extract", data=data, usage=usage)

    def map(self, request: TavilyMapRequest) -> TavilyRawResponse:
        validate_public_web_url(request.url, allow_private=request.allow_private)
        if request.instructions:
            validate_public_web_text(request.instructions, allow_private=request.allow_private)
        payload = request.model_dump(
            exclude={"lane", "project_id", "allow_private", "p0"},
            exclude_none=True,
        )
        data, usage = self._request(
            "map",
            payload,
            lane=request.lane,
            project_id=request.project_id,
            estimate=self._estimate_map(request),
            p0=request.p0,
        )
        return TavilyRawResponse(endpoint="map", data=data, usage=usage)

    def crawl(self, request: TavilyCrawlRequest) -> TavilyRawResponse:
        validate_public_web_url(request.url, allow_private=request.allow_private)
        if request.instructions:
            validate_public_web_text(request.instructions, allow_private=request.allow_private)
        payload = request.model_dump(
            exclude={"lane", "project_id", "allow_private", "p0"},
            exclude_none=True,
        )
        data, usage = self._request(
            "crawl",
            payload,
            lane=request.lane,
            project_id=request.project_id,
            estimate=self._estimate_crawl(request),
            p0=request.p0,
        )
        return TavilyRawResponse(endpoint="crawl", data=data, usage=usage)

    def create_research(self, request: TavilyResearchRequest) -> TavilyRawResponse:
        validate_public_web_text(
            request.query,
            allow_private=request.allow_private,
            allow_public_bibliographic_people=self._allow_public_bibliographic_people(
                request.allow_public_bibliographic_people
            ),
        )
        payload = request.model_dump(
            exclude={
                "lane",
                "project_id",
                "allow_private",
                "p0",
                "allow_public_bibliographic_people",
            },
            exclude_none=True,
        )
        payload["input"] = payload.pop("query")
        data, usage = self._request(
            "research",
            payload,
            lane=request.lane,
            project_id=request.project_id,
            estimate=self._estimate_research(request),
            p0=request.p0,
            cacheable=False,
        )
        return TavilyRawResponse(endpoint="research", data=data, usage=usage)

    def _allow_public_bibliographic_people(self, request_value: bool) -> bool:
        if request_value:
            return True
        guardrails = self.config.get("guardrails", {}) if isinstance(self.config, Mapping) else {}
        if not isinstance(guardrails, Mapping):
            return False
        return bool(guardrails.get("allow_public_bibliographic_people", False))

    def get_research(self, request_id: str) -> TavilyRawResponse:
        if not request_id:
            raise ValueError("request_id is required")
        data, usage = self._request(
            f"research/{request_id}",
            {},
            lane="research_reports",
            project_id=None,
            estimate=0,
            p0=True,
            method="GET",
            cacheable=False,
        )
        return TavilyRawResponse(endpoint="research", data=data, usage=usage)

    def research(
        self,
        request: TavilyResearchRequest,
        *,
        poll: bool = True,
        timeout_s: float = 120.0,
        poll_interval_s: float = 3.0,
    ) -> TavilyRawResponse:
        result = self.create_research(request)
        if not poll:
            return result
        request_id = str(
            result.data.get("request_id")
            or result.data.get("id")
            or result.data.get("task_id")
            or ""
        )
        if not request_id:
            return result
        deadline = time.monotonic() + timeout_s
        latest = result
        while time.monotonic() < deadline:
            latest = self.get_research(request_id)
            status = str(latest.data.get("status") or "").lower()
            if status in {"completed", "failed"}:
                return latest
            time.sleep(max(0.1, poll_interval_s))
        return latest

    def usage(self, *, project_id: str | None = None) -> TavilyUsageResponse:
        """Return Tavily's account/key usage view without writing local ledger rows."""
        if not self.api_key:
            raise TavilyConfigError("TAVILY_API_KEY is not set and no pass entry was found")
        try:
            response = self.http_client.get(
                f"{self.base_url}/usage",
                headers=self._headers(project_id or "hapax-usage"),
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            raise TavilyRequestError(
                f"Tavily usage failed with HTTP {exc.response.status_code}"
            ) from exc
        except (httpx.RequestError, ValueError) as exc:
            raise TavilyRequestError(f"Tavily usage request failed: {exc}") from exc
        return TavilyUsageResponse(
            key=TavilyAccountUsage.model_validate(data.get("key") or {}),
            account=TavilyAccountUsage.model_validate(data.get("account") or {}),
            raw=data if isinstance(data, dict) else {},
        )

    def _request(
        self,
        endpoint: str,
        payload: dict[str, Any],
        *,
        lane: str,
        project_id: str | None,
        estimate: float,
        p0: bool,
        method: Literal["GET", "POST"] = "POST",
        cacheable: bool = True,
    ) -> tuple[dict[str, Any], TavilyUsage]:
        if not self.api_key:
            raise TavilyConfigError("TAVILY_API_KEY is not set and no pass entry was found")
        self._configured_lane_cap(lane)

        project = project_id or f"hapax-{lane}"
        cache_key = _stable_hash({"endpoint": endpoint, "payload": payload, "project_id": project})
        request_id = _stable_hash(
            {
                "cache_key": cache_key,
                "endpoint": endpoint,
                "pid": os.getpid(),
                "started_ns": time.time_ns(),
            }
        )
        if cacheable:
            with self._cache_lock(endpoint, cache_key):
                cached = self._read_cache(endpoint, cache_key, lane=lane)
                if cached is not None:
                    usage = TavilyUsage(
                        endpoint=endpoint,
                        cache_hit=True,
                        estimated_credits=estimate,
                        actual_credits=0,
                    )
                    self._record_usage(
                        endpoint,
                        lane,
                        project,
                        payload,
                        cache_key,
                        usage,
                        status="cache_hit",
                    )
                    return cached, usage
                data, usage = self._request_uncached(
                    endpoint,
                    payload,
                    lane=lane,
                    project=project,
                    estimate=estimate,
                    p0=p0,
                    method=method,
                    cache_key=cache_key,
                    request_id=request_id,
                )
                self._write_cache(endpoint, cache_key, data)
                return data, usage

        return self._request_uncached(
            endpoint,
            payload,
            lane=lane,
            project=project,
            estimate=estimate,
            p0=p0,
            method=method,
            cache_key=cache_key,
            request_id=request_id,
        )

    def _request_uncached(
        self,
        endpoint: str,
        payload: dict[str, Any],
        *,
        lane: str,
        project: str,
        estimate: float,
        p0: bool,
        method: Literal["GET", "POST"],
        cache_key: str,
        request_id: str,
    ) -> tuple[dict[str, Any], TavilyUsage]:
        with self._ledger_lock():
            try:
                self._check_budget(lane, estimate, p0=p0)
            except TavilyBudgetExceeded:
                usage = TavilyUsage(
                    endpoint=endpoint,
                    cache_hit=False,
                    estimated_credits=estimate,
                    actual_credits=0,
                )
                self._record_usage(
                    endpoint,
                    lane,
                    project,
                    payload,
                    cache_key,
                    usage,
                    status="budget_denied",
                    request_id=request_id,
                    lock=False,
                )
                raise
            reserved = TavilyUsage(
                endpoint=endpoint,
                cache_hit=False,
                estimated_credits=estimate,
                actual_credits=0,
            )
            self._record_usage(
                endpoint,
                lane,
                project,
                payload,
                cache_key,
                reserved,
                status="reserved",
                request_id=request_id,
                lock=False,
            )

        attempts = 0
        max_attempts = _int_config(self.config, "max_retries", 2) + 1
        started = time.monotonic()
        while True:
            attempts += 1
            if method == "GET":
                request_call = self.http_client.get
                request_kwargs = {"headers": self._headers(project)}
            else:
                request_call = self.http_client.post
                request_kwargs = {"json": payload, "headers": self._headers(project)}
            try:
                with self._concurrency_slot():
                    response = request_call(f"{self.base_url}/{endpoint}", **request_kwargs)
                    response.raise_for_status()
                    data = response.json()
                break
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if (status == 429 or 500 <= status <= 599) and attempts < max_attempts:
                    retry_after = exc.response.headers.get("retry-after")
                    delay = self._retry_delay(attempts, retry_after)
                    time.sleep(delay)
                    continue
                self._record_failed(
                    endpoint,
                    lane,
                    project,
                    payload,
                    cache_key,
                    estimate,
                    status,
                    request_id=request_id,
                    latency_ms=(time.monotonic() - started) * 1000,
                )
                raise TavilyRequestError(f"Tavily {endpoint} failed with HTTP {status}") from exc
            except httpx.RequestError as exc:
                if attempts < max_attempts:
                    time.sleep(self._retry_delay(attempts, None))
                    continue
                self._record_failed(
                    endpoint,
                    lane,
                    project,
                    payload,
                    cache_key,
                    estimate,
                    "request_error",
                    request_id=request_id,
                    latency_ms=(time.monotonic() - started) * 1000,
                )
                raise TavilyRequestError(f"Tavily {endpoint} request failed: {exc}") from exc
            except ValueError as exc:
                self._record_failed(
                    endpoint,
                    lane,
                    project,
                    payload,
                    cache_key,
                    estimate,
                    "request_error",
                    request_id=request_id,
                    latency_ms=(time.monotonic() - started) * 1000,
                )
                raise TavilyRequestError(f"Tavily {endpoint} request failed: {exc}") from exc

        usage = self._usage_from_response(endpoint, data, estimate)
        self._record_usage(
            endpoint,
            lane,
            project,
            payload,
            cache_key,
            usage,
            status="ok",
            request_id=request_id,
            latency_ms=(time.monotonic() - started) * 1000,
            result_count=self._result_count(data),
        )
        return data, usage

    def _headers(self, project_id: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-Project-ID": project_id,
        }

    def _usage_from_response(
        self, endpoint: str, data: Mapping[str, Any], estimate: float
    ) -> TavilyUsage:
        raw = data.get("usage") if isinstance(data, Mapping) else None
        credits = 0.0
        if isinstance(raw, Mapping):
            credits = float(raw.get("credits") or raw.get("total_credits") or 0)
        return TavilyUsage(
            credits=credits,
            endpoint=endpoint,
            cache_hit=False,
            estimated_credits=estimate,
            actual_credits=credits if credits else estimate,
        )

    def _estimate_search(self, request: TavilySearchRequest) -> float:
        return 2 if request.search_depth == "advanced" or request.auto_parameters else 1

    def _estimate_extract(self, request: TavilyExtractRequest) -> float:
        per_batch = 2 if request.extract_depth == "advanced" else 1
        return per_batch * max(1, math.ceil(len(request.urls) / 5))

    def _estimate_map(self, request: TavilyMapRequest) -> float:
        per_ten_pages = 2 if request.instructions else 1
        return per_ten_pages * max(1, math.ceil(request.limit / 10))

    def _estimate_crawl(self, request: TavilyCrawlRequest) -> float:
        map_per_ten_pages = 2 if request.instructions else 1
        extract_per_five_pages = 2 if request.extract_depth == "advanced" else 1
        mapping = map_per_ten_pages * max(1, math.ceil(request.limit / 10))
        extraction = extract_per_five_pages * max(1, math.ceil(request.limit / 5))
        return mapping + extraction

    def _estimate_research(self, request: TavilyResearchRequest) -> float:
        if request.model == "pro" and not request.p0:
            raise TavilyBudgetExceeded("Tavily pro research requires p0=True")
        if request.model == "auto" and not request.p0:
            raise TavilyBudgetExceeded("Tavily auto research requires p0=True")
        return 250 if request.model in {"pro", "auto"} else 110

    def _retry_delay(self, attempts: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                pass
        base = _float_config(self.config, "retry_base_delay_s", 2.0)
        ceiling = _float_config(self.config, "retry_max_delay_s", 10.0)
        return min(base * attempts, ceiling)

    @staticmethod
    def _result_count(data: Mapping[str, Any]) -> int:
        results = data.get("results") if isinstance(data, Mapping) else None
        return len(results) if isinstance(results, list) else 0

    def _read_cache(
        self, endpoint: str, cache_key: str, *, lane: str | None = None
    ) -> dict[str, Any] | None:
        path = self._cache_path(endpoint, cache_key)
        if not path.is_file():
            return None
        try:
            record = json.loads(path.read_text())
            cached_at = datetime.fromisoformat(record["cached_at"])
            ttl = self._cache_ttl(endpoint, lane=lane)
            if ttl > 0 and (self.now() - cached_at).total_seconds() > ttl:
                return None
            data = record.get("data")
            return data if isinstance(data, dict) else None
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None

    def _write_cache(self, endpoint: str, cache_key: str, data: Mapping[str, Any]) -> None:
        path = self._cache_path(endpoint, cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"cached_at": self.now().isoformat(), "data": data}
        path.write_text(json.dumps(record, sort_keys=True))

    def _cache_path(self, endpoint: str, cache_key: str) -> Path:
        return self.cache_dir / endpoint.replace("/", "_") / f"{cache_key}.json"

    def _cache_ttl(self, endpoint: str, *, lane: str | None = None) -> int:
        endpoint_key = endpoint.split("/", 1)[0]
        if lane:
            lane_ttls = self.config.get("lane_cache_ttl_s", {})
            lane_ttl = lane_ttls.get(lane, {}) if isinstance(lane_ttls, Mapping) else {}
            if isinstance(lane_ttl, Mapping) and endpoint_key in lane_ttl:
                return int(lane_ttl.get(endpoint_key, 0) or 0)
        defaults = self.config.get("defaults", {}) if isinstance(self.config, Mapping) else {}
        ttl = defaults.get("cache_ttl_s", {}) if isinstance(defaults, Mapping) else {}
        if not isinstance(ttl, Mapping):
            return 0
        return int(ttl.get(endpoint_key, 0) or 0)

    def _check_budget(self, lane: str, estimate: float, *, p0: bool) -> None:
        now = self.now()
        month = _month_prefix(now)
        day = _day_prefix(now)
        totals = self._ledger_totals(month=month, day=day)

        monthly_credits = _float_config(self.config, "monthly_credits", 150000)
        reserve = _float_config(self.config, "monthly_reserve_credits", 30000)
        normal_monthly_cap = max(0.0, monthly_credits - reserve)
        daily_cap_key = "daily_p0_credits" if p0 else "daily_nominal_credits"
        daily_cap = _float_config(self.config, daily_cap_key, 4000 if not p0 else 10000)
        lanes = self.config.get("lanes", {}) or {}
        lane_cap = self._configured_lane_cap(lane, lanes=lanes)
        if estimate <= 0:
            return

        if totals["month"] + estimate > normal_monthly_cap and not p0:
            raise TavilyBudgetExceeded("monthly Tavily reserve would be exceeded")
        if totals["day"] + estimate > daily_cap:
            raise TavilyBudgetExceeded(
                f"daily Tavily cap for {'p0' if p0 else 'normal'} use exceeded"
            )
        if totals["lanes"].get(lane, 0.0) + estimate > lane_cap:
            raise TavilyBudgetExceeded(f"Tavily lane budget exceeded: {lane}")

    def _configured_lane_cap(self, lane: str, *, lanes: Mapping[str, Any] | None = None) -> float:
        if lanes is None:
            lanes = self.config.get("lanes", {}) or {}
        if not isinstance(lanes, Mapping):
            raise TavilyConfigError("Tavily config lanes must be a mapping")
        if lane not in lanes:
            raise TavilyConfigError(f"Tavily lane is not configured: {lane}")
        try:
            return float(lanes[lane])
        except (TypeError, ValueError) as exc:
            raise TavilyConfigError(f"Tavily lane budget must be numeric: {lane}") from exc

    def _ledger_totals(self, *, month: str, day: str) -> dict[str, Any]:
        totals: dict[str, Any] = {"month": 0.0, "day": 0.0, "lanes": {}}
        if not self.ledger_path.is_file():
            return totals
        now = self.now()
        latest_by_request: dict[str, dict[str, Any]] = {}
        legacy_records: list[dict[str, Any]] = []
        try:
            lines = self.ledger_path.read_text().splitlines()
        except OSError:
            return totals
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            request_id = str(record.get("request_id") or "")
            if request_id:
                existing = latest_by_request.get(request_id)
                if existing is None or str(record.get("timestamp", "")) >= str(
                    existing.get("timestamp", "")
                ):
                    latest_by_request[request_id] = record
            else:
                legacy_records.append(record)
        for record in [*legacy_records, *latest_by_request.values()]:
            self._add_record_to_totals(totals, record, month=month, day=day, now=now)
        return totals

    def _add_record_to_totals(
        self,
        totals: dict[str, Any],
        record: Mapping[str, Any],
        *,
        month: str,
        day: str,
        now: datetime,
    ) -> None:
        status = str(record.get("status") or "")
        if status in {"cache_hit", "budget_denied"}:
            return
        if status == "reserved":
            try:
                reserved_at = datetime.fromisoformat(str(record.get("timestamp", "")))
            except ValueError:
                return
            if (now - reserved_at).total_seconds() > self.reservation_ttl_s:
                return
            credits = float(record.get("estimated_credits") or 0)
        elif status == "ok":
            credits = float(record.get("actual_credits") or record.get("estimated_credits") or 0)
        elif "request_id" in record:
            return
        else:
            credits = float(record.get("actual_credits") or 0)
        if credits <= 0:
            return
        ts = str(record.get("timestamp", ""))
        lane = str(record.get("lane") or "")
        if ts.startswith(month):
            totals["month"] += credits
            if lane:
                totals["lanes"][lane] = totals["lanes"].get(lane, 0.0) + credits
        if ts.startswith(day):
            totals["day"] += credits

    def _record_failed(
        self,
        endpoint: str,
        lane: str,
        project_id: str,
        payload: Mapping[str, Any],
        request_hash: str,
        estimate: float,
        status: str | int,
        *,
        request_id: str | None = None,
        latency_ms: float | None = None,
    ) -> None:
        usage = TavilyUsage(
            endpoint=endpoint,
            cache_hit=False,
            estimated_credits=estimate,
            actual_credits=0,
        )
        self._record_usage(
            endpoint,
            lane,
            project_id,
            payload,
            request_hash,
            usage,
            status=str(status),
            request_id=request_id,
            latency_ms=latency_ms,
        )

    def _record_usage(
        self,
        endpoint: str,
        lane: str,
        project_id: str,
        payload: Mapping[str, Any],
        request_hash: str,
        usage: TavilyUsage,
        *,
        status: str,
        request_id: str | None = None,
        latency_ms: float | None = None,
        result_count: int | None = None,
        lock: bool = True,
    ) -> None:
        record = {
            "timestamp": self.now().isoformat(),
            "endpoint": endpoint,
            "operation": endpoint.split("/", 1)[0],
            "lane": lane,
            "caller": project_id,
            "project_id": project_id,
            "request_hash": request_hash,
            "request": _redacted_payload(endpoint, payload),
            "status": status,
            "cache_hit": usage.cache_hit,
            "estimated_credits": usage.estimated_credits,
            "actual_credits": usage.actual_credits,
            "pid": os.getpid(),
        }
        if request_id:
            record["request_id"] = request_id
        if latency_ms is not None:
            record["latency_ms"] = round(latency_ms, 3)
        if result_count is not None:
            record["result_count"] = result_count
        if lock:
            with self._ledger_lock():
                self._append_usage_record(record)
        else:
            self._append_usage_record(record)

    def _append_usage_record(self, record: Mapping[str, Any]) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")

    @contextmanager
    def _ledger_lock(self):
        with _exclusive_file_lock(self.lock_dir / "ledger.lock"):
            yield

    @contextmanager
    def _cache_lock(self, endpoint: str, cache_key: str):
        safe_endpoint = endpoint.replace("/", "_")
        with _exclusive_file_lock(self.lock_dir / "cache" / f"{safe_endpoint}-{cache_key}.lock"):
            yield

    @contextmanager
    def _concurrency_slot(self):
        slot_dir = self.lock_dir / "concurrency"
        slot_dir.mkdir(parents=True, exist_ok=True)
        fd = -1
        try:
            for index in range(self.max_concurrent_requests):
                slot_path = slot_dir / f"slot.{index}"
                fd = os.open(str(slot_path), os.O_CREAT | os.O_RDWR, 0o600)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    yield
                    return
                except BlockingIOError:
                    os.close(fd)
                    fd = -1

            slot_path = slot_dir / "slot.0"
            fd = os.open(str(slot_path), os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            if fd >= 0:
                os.close(fd)
