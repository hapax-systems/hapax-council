"""Entitlement census: what is held, what it holds now, and what is declared, joined into one view.

Architecture, with the estate's nouns removed: a scheduled reconciler joins
(a) **held** -- credential-store names per host, login-file existence and mtime (never content),
    installed harness binaries;
(b) **holds now** -- one allow-listed, spend-free readback per entitlement, vendor caches that carry
    their own fetch time, and declared references that carry an expiry;
(c) **declared** -- the route registry and the quota ledger.
The later slices join these declarations with observations and emit the view.

This is the reconciler the 2026-07-02 supply model designed (section 7, sequence step 4) and never
built. It adds no store: its classifier is ``shared.entitlement_capability``, its deltas are
``shared.capability_surface_delta`` rows, its quantities use the ledger's measurement fields, and its
projection doubles as a capability-surface pack that Reins already knows how to read.

The complete producer pins these safety properties in its integration tests:

* No secret value reaches output. Every rendered artifact is scanned for every credential value this
  run resolved, and for secret-shaped tokens, before anything is written. One hit writes nothing.
* No readback spends. ``READBACKS`` below is the whole allow-list (usage, plan, balance and model-list
  GETs); configuration can only name its ids. The transport has no method or body parameter.
  Claude is never probed: its windows come from the ledger's passive readers.
* A rejected key (401) is ``dead``, never ``held``. A 403 or a redirect proves nothing about the key,
  so it is unobserved: never dead, never live.
* No request follows a redirect, so a credential header never reaches another host.
* One run deadline bounds the whole network phase; past it, nothing more is probed.
* Every declaration carries a cost class; an unknown one is ``unobserved``, never a default.
* A vanished entitlement stays in the view as ``absent`` with its ``last_seen``; an unreachable host
  leaves its rows ``unobserved``, not absent.
* A terms-restricted provider is never probed.
* A vendor cache carries its ``fetched_at`` and goes ``stale`` past a bound; it is never ``live``.
* Remote hosts are read with a declared, non-interactive binding (``ssh -o BatchMode=yes``).
"""

from __future__ import annotations

import json
import math
import re
import shlex
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

REPO_ROOT = Path(__file__).resolve().parents[1]
ENTITLEMENT_CENSUS_CONFIG = REPO_ROOT / "config" / "entitlement-census.json"
DEFAULT_OUTPUT_ROOT = Path.home() / ".cache" / "hapax" / "entitlement-census"
PRODUCER_REF = "scripts/hapax-entitlement-census"
TASK_REF = "entitlement-census-producer-20260924"
VIEW_SCHEMA = "hapax.entitlement_census.view.v1"

#: Mirrors the quota ledger's measurement TTL (A1, #4728): a reading is fresh for an hour or until
#: its window resets, whichever is first.
MEASUREMENT_TTL = timedelta(hours=1)
#: How long a presence observation (a name, a login file, a binary) stands for "held".
PRESENCE_TTL = timedelta(hours=1)
READBACK_TIMEOUT_S = 10.0
#: Explicit, because edge protection rejects urllib's default agent with 403 (Featherless, measured).
USER_AGENT = "hapax-entitlement-census/1 (spend-free readback)"
SERVING_TIMEOUT_S = 5.0
MAX_BODY_BYTES = 1_000_000
ROUTABLE_ROUTE_STATES = frozenset({"active"})
#: Cache names accepted by declarations before the reader implementation arrives in piece 4.
#: Keep these ids aligned with that piece's VENDOR_CACHES reader map.
VENDOR_CACHE_IDS = frozenset({"grok_settings_cache", "vibe_whoami_cache"})


class CensusConfigError(ValueError):
    """The census declaration is invalid; the message names the next action."""


class SecretLeakError(RuntimeError):
    """A rendered artifact contains secret material. Nothing was written."""


class CostClass(StrEnum):
    SUBSCRIPTION = "subscription"
    PREPAID = "prepaid"
    PAYG = "payg"
    FREE = "free"
    LOCAL = "local"
    UNOBSERVED = "unobserved"


class EntitlementKind(StrEnum):
    COGNITION = "cognition"
    GROUNDING = "grounding"
    MODALITY = "modality"
    RESOURCE = "resource"
    LOCAL = "local"


class EvidenceClass(StrEnum):
    LIVE = "live"
    VENDOR_CACHE = "vendor_cache"
    NATIVE_RECORD = "native_record"
    RECORDED = "recorded"
    NAME_ONLY = "name_only"
    NONE = "none"


RecruitmentStage = Literal[
    "unusable", "usable-undeclared", "declared-unmeasured", "declared-measured", "routable"
]


# --- the readback allow-list ----------------------------------------------------------------------


@dataclass(frozen=True)
class ReadbackSpec:
    readback_id: str
    url: str
    auth: Literal["bearer", "raw_authorization", "x_api_key", "xi_api_key", "x_goog_api_key"]
    extractor: str
    extra_headers: tuple[tuple[str, str], ...] = ()


_AUTH_HEADERS: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "bearer": ("Authorization", "Bearer {}"),
        "raw_authorization": ("Authorization", "{}"),
        "x_api_key": ("x-api-key", "{}"),
        "xi_api_key": ("xi-api-key", "{}"),
        "x_goog_api_key": ("x-goog-api-key", "{}"),
    }
)

#: THE allow-list. Every entry is a GET of a usage, plan, balance, identity or model-list endpoint,
#: exactly as measured spend-free by the E0 census (2026-09-24, frame/ENTITLEMENT-CENSUS-R2 section 1).
#: Configuration can name these ids and nothing else; adding an endpoint is a reviewed code change.
READBACKS: Mapping[str, ReadbackSpec] = MappingProxyType(
    {
        spec.readback_id: spec
        for spec in (
            ReadbackSpec(
                "kimi_usages", "https://api.kimi.com/coding/v1/usages", "bearer", "kimi_usages"
            ),
            ReadbackSpec(
                "glm_quota_limit",
                "https://api.z.ai/api/monitor/usage/quota/limit",
                "raw_authorization",
                "glm_quota_limit",
            ),
            ReadbackSpec(
                "sakana_usage", "https://api.sakana.ai/v1/usage", "bearer", "sakana_usage"
            ),
            ReadbackSpec(
                "openrouter_credits",
                "https://openrouter.ai/api/v1/credits",
                "bearer",
                "openrouter_credits",
            ),
            ReadbackSpec(
                "openrouter_key", "https://openrouter.ai/api/v1/key", "bearer", "openrouter_key"
            ),
            ReadbackSpec(
                "featherless_plan",
                "https://api.featherless.ai/v1/plan",
                "bearer",
                "featherless_plan",
            ),
            ReadbackSpec(
                "hf_whoami", "https://huggingface.co/api/whoami-v2", "bearer", "hf_whoami"
            ),
            ReadbackSpec("tavily_usage", "https://api.tavily.com/usage", "bearer", "tavily_usage"),
            ReadbackSpec(
                "firecrawl_credit_usage",
                "https://api.firecrawl.dev/v2/team/credit-usage",
                "bearer",
                "firecrawl_credit_usage",
            ),
            ReadbackSpec(
                "elevenlabs_subscription",
                "https://api.elevenlabs.io/v1/user/subscription",
                "xi_api_key",
                "elevenlabs_subscription",
            ),
            ReadbackSpec(
                "mistral_models", "https://api.mistral.ai/v1/models", "bearer", "status_only"
            ),
            ReadbackSpec(
                "cohere_models",
                "https://api.cohere.com/v1/models?page_size=1",
                "bearer",
                "status_only",
            ),
            ReadbackSpec(
                "verboo_models", "https://code.verboo.ai/router/v1/models", "bearer", "model_list"
            ),
            ReadbackSpec(
                "google_models",
                "https://generativelanguage.googleapis.com/v1beta/models",
                "x_goog_api_key",
                "status_only",
            ),
            ReadbackSpec(
                "anthropic_models",
                "https://api.anthropic.com/v1/models",
                "x_api_key",
                "status_only",
                (("anthropic-version", "2023-06-01"),),
            ),
            ReadbackSpec(
                "openai_models", "https://api.openai.com/v1/models", "bearer", "status_only"
            ),
            ReadbackSpec(
                "llama_models", "https://api.llama.com/v1/models", "bearer", "status_only"
            ),
        )
    }
)


# --- declaration ----------------------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,95}$")
_TARGET_RE = re.compile(r"^(?:[A-Za-z0-9_][A-Za-z0-9._-]*@)?[A-Za-z0-9][A-Za-z0-9.-]*$")
_BASE_URL_RE = re.compile(r"^https?://[A-Za-z0-9][A-Za-z0-9.-]*(?::\d{1,5})?$")


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name} must carry a timezone; next action: write it as ISO-8601 with Z")
    return value.astimezone(UTC)


class ReadbackRef(_Strict):
    readback_id: str
    secret: str | None = Field(validation_alias="credential_name")

    @model_validator(mode="after")
    def _allow_listed(self) -> ReadbackRef:
        if self.readback_id not in READBACKS:
            raise ValueError(
                f"readback {self.readback_id!r} is not in the allow-list; next action: name one of "
                f"{sorted(READBACKS)}, or add a spend-free GET to READBACKS through review"
            )
        if not self.secret:
            raise ValueError(
                f"readback {self.readback_id!r} needs the credential NAME it reads with; next "
                "action: set credential_name to the FileStore name (never a value)"
            )
        return self


class DeclaredReference(_Strict):
    fact: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1)
    recorded_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def _dated(self) -> DeclaredReference:
        _aware(self.recorded_at, "recorded_at")
        _aware(self.expires_at, "expires_at")
        if self.expires_at <= self.recorded_at:
            raise ValueError(
                "a declared reference must expire after it was recorded; next action: set "
                "expires_at later than recorded_at (the fact's own renewal date, or recorded_at + 30 d)"
            )
        return self


class HostBinding(_Strict):
    host_id: str = Field(min_length=1)
    transport: Literal["local", "ssh_batch"]
    target: str | None = None

    @model_validator(mode="after")
    def _target(self) -> HostBinding:
        if self.transport == "ssh_batch":
            if not self.target or not _TARGET_RE.match(self.target):
                raise ValueError(
                    f"host {self.host_id!r}: ssh_batch needs a [user@]host target that cannot be read "
                    "as an ssh option; next action: set target to a plain host name"
                )
        elif self.target is not None:
            raise ValueError(
                f"host {self.host_id!r}: a local binding takes no target; next action: remove "
                "target, or set transport to ssh_batch for a remote host"
            )
        return self


class ServingEndpoint(_Strict):
    endpoint_id: str = Field(pattern=_ID_RE.pattern)
    host_id: str = Field(min_length=1)
    base_url: str
    #: Fixed by code: only a model listing may be read from a serving endpoint.
    models_path: Literal["/v1/models", "/api/tags"]

    @field_validator("base_url")
    @classmethod
    def _bare_origin(cls, value: str) -> str:
        if not _BASE_URL_RE.match(value):
            raise ValueError(
                "base_url must be scheme://host[:port] with no path; next action: drop the path, "
                "and set models_path to /v1/models or /api/tags"
            )
        return value


class HardwareFact(_Strict):
    host_id: str = Field(min_length=1)
    device: str = Field(min_length=1)
    memory_gb: float = Field(ge=0)
    availability: Literal["available", "degraded", "unavailable"]
    until: str | None = None
    #: A substring of the GPU name that a hardware readback must show before this device counts as
    #: enumerated. Without such a readback, a device declared unavailable stays unavailable.
    enumerate_gpu: str | None = None
    source: str = Field(min_length=1)
    recorded_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def _dated(self) -> HardwareFact:
        _aware(self.recorded_at, "recorded_at")
        _aware(self.expires_at, "expires_at")
        return self


class TrialRecord(_Strict):
    model: str = Field(min_length=1)
    stage: Literal["candidate_to_experiment", "candidate_to_deploy", "deployed", "rejected"]
    evidence: str = Field(min_length=1)
    recorded_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def _dated(self) -> TrialRecord:
        _aware(self.recorded_at, "recorded_at")
        _aware(self.expires_at, "expires_at")
        return self


class ScoutBinding(_Strict):
    host_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    components: tuple[str, ...] = ()


class MetalConfig(_Strict):
    scout_report: ScoutBinding | None = None
    hardware: tuple[HardwareFact, ...] = ()
    trial_records: tuple[TrialRecord, ...] = ()


class TrendSources(_Strict):
    """Home-relative bindings the trend face reads. Existing estate records, never a new store."""

    task_rows: str | None = None  # active task-row directory: queued demand
    route_decisions: str | None = None  # dispatch route-decision JSONL: dispatched demand
    wall_witness: str | None = None  # review plane's per-family outage witness


class EntitlementDecl(_Strict):
    entitlement_id: str = Field(pattern=_ID_RE.pattern)
    provider: str = Field(min_length=1)
    kind: EntitlementKind
    cost_class: CostClass  # required: PAYG must never read as subscription by default
    credential_names: tuple[str, ...] = ()
    env_names: tuple[str, ...] = ()
    login_files: tuple[str, ...] = ()
    harness_bins: tuple[str, ...] = ()
    readbacks: tuple[ReadbackRef, ...] = ()
    measurement_prefixes: tuple[str, ...] = ()
    vendor_cache: str | None = None
    declared_refs: tuple[DeclaredReference, ...] = ()
    terms_restricted: bool = False
    registry_platforms: tuple[str, ...] = ()
    registry_route_ids: tuple[str, ...] = ()
    registry_shape_ids: tuple[str, ...] = ()
    expected_shape_class: str | None = None
    ledger_providers: tuple[str, ...] = ()
    notes: str | None = None
    #: Utilization inputs (operator-accepted 2026-09-25T10:15Z: underuse is the failure to surface).
    monthly_cost_usd: float | None = Field(default=None, ge=0)
    usage_ledger: bool = False  # utilization comes from the per-call ledger stream
    concurrency_slots: int | None = Field(default=None, ge=1)  # flat-price capacity, e.g. Verboo 2
    renewal_day: int | None = Field(default=None, ge=1, le=28)  # billing period start, day of month

    @model_validator(mode="after")
    def _probe_rules(self) -> EntitlementDecl:
        if self.usage_ledger and self.renewal_day is None:
            raise ValueError(
                f"{self.entitlement_id}: a per-call-ledger entitlement needs its billing period; next "
                "action: set renewal_day (the day of month the plan renews)"
            )
        if self.terms_restricted and (self.readbacks or self.vendor_cache):
            raise ValueError(
                f"{self.entitlement_id}: a terms-restricted provider is never probed; next action: "
                "remove its readbacks and vendor cache"
            )
        if self.vendor_cache is not None and self.vendor_cache not in VENDOR_CACHE_IDS:
            raise ValueError(
                f"{self.entitlement_id}: unknown vendor cache {self.vendor_cache!r}; next action: "
                f"name one of {sorted(VENDOR_CACHE_IDS)}, or add a reviewed cache reader"
            )
        for rel in self.login_files:
            if rel.startswith("/") or ".." in rel.split("/"):
                raise ValueError(
                    f"{self.entitlement_id}: login file {rel!r} must be home-relative; next "
                    "action: write it relative to $HOME with no leading / and no .."
                )
        return self


class CensusConfig(_Strict):
    schema_id: Literal["hapax.entitlement_census.v1"] = Field(alias="schema")
    description: tuple[str, ...] = ()
    hosts: tuple[HostBinding, ...] = Field(min_length=1)
    vendor_cache_max_age_seconds: int = Field(default=86400, gt=0)
    projection_markdown: str | None = None
    withheld_name_tokens: tuple[str, ...] = ()
    serving_endpoints: tuple[ServingEndpoint, ...] = ()
    metal: MetalConfig = MetalConfig()
    trend_sources: TrendSources = TrendSources()
    entitlements: tuple[EntitlementDecl, ...]

    @model_validator(mode="after")
    def _unique(self) -> CensusConfig:
        for label, ids in (
            ("entitlement_id", [e.entitlement_id for e in self.entitlements]),
            ("endpoint_id", [s.endpoint_id for s in self.serving_endpoints]),
            ("host_id", [h.host_id for h in self.hosts]),
        ):
            duplicates = sorted({i for i in ids if ids.count(i) > 1})
            if duplicates:
                raise ValueError(
                    f"duplicate {label}: {duplicates}; next action: keep one declaration per id "
                    "(rename or merge the duplicates)"
                )
        return self


def load_census_config(path: Path = ENTITLEMENT_CENSUS_CONFIG) -> CensusConfig:
    try:
        return CensusConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise CensusConfigError(
            f"entitlement census declaration {path} is invalid: {exc}; next action: repair it and "
            "rerun `scripts/hapax-entitlement-census --dry-run`"
        ) from exc


def load_registry(path: Path) -> dict[str, Any]:
    """The declared side, read strictly. An unreadable registry fails the run.

    Reading it as empty would make every held entitlement look undeclared and mint intake rows for
    all of them. Only a file that literally holds ``{}`` is an empty registry."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CensusConfigError(
            f"platform registry {path} is unreadable ({type(exc).__name__}); nothing was written. "
            "Next action: restore the registry file, then rerun the producer"
        ) from exc
    if not isinstance(payload, dict):
        raise CensusConfigError(
            f"platform registry {path} is not a JSON object; nothing was written. Next action: "
            "restore the registry file from origin/main, then rerun the producer"
        )
    for key in ("routes", "omitted_capability_shapes"):
        if key in payload and not isinstance(payload[key], list):
            raise CensusConfigError(
                f"platform registry {path}: {key!r} must be a list; nothing was written. Next "
                "action: restore the registry file from origin/main, then rerun the producer"
            )
    return payload


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _instant(value: Any) -> datetime | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, int | float):
            seconds = value / 1000 if value > 1e11 else value
            return datetime.fromtimestamp(seconds, UTC)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, OverflowError, OSError, TypeError):
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _get(payload: Any, *path: str | int) -> Any:
    node = payload
    for key in path:
        if isinstance(key, int):
            if not isinstance(node, list) or len(node) <= key:
                return None
            node = node[key]
        else:
            if not isinstance(node, dict):
                return None
            node = node.get(key)
    return node


#: Categorical facts that may leave a readback. Anything else is dropped, never projected.
_SAFE_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:+/()@,-]{0,95}$")

FactValue = str | int | float | bool | None


def _safe_fact(value: Any) -> FactValue:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value if math.isfinite(float(value)) else None
    text = str(value).strip()
    return text if _SAFE_TEXT.match(text) else None


# --- secrets --------------------------------------------------------------------------------------

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("sk- key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("bearer token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("huggingface token", re.compile(r"\bhf_[A-Za-z0-9]{20,}")),
    ("xai key", re.compile(r"\bxai-[A-Za-z0-9]{20,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
)


class SecretRegister:
    """Holds every credential value this run resolved, so output can be checked against them.

    Values live only in this process's memory; the register never renders them. ``require_clean``
    fails closed on any resolved value and on secret-shaped tokens."""

    def __init__(self) -> None:
        self._values: set[str] = set()

    def remember(self, value: str | None) -> None:
        if value and len(value) >= 8:
            self._values.add(value)

    def hits(self, text: str) -> list[str]:
        kinds = [label for label, pattern in _SECRET_PATTERNS if pattern.search(text)]
        if any(value in text for value in self._values):
            kinds.append("a credential value resolved in this run")
        return sorted(set(kinds))

    def require_clean(self, text: str, *, label: str) -> None:
        hits = self.hits(text)
        if hits:
            raise SecretLeakError(
                f"{label}: secret material detected ({', '.join(hits)}); nothing was written. Next "
                "action: find the extractor or fact that carried it and drop that field"
            )


# --- transports -----------------------------------------------------------------------------------


class HttpResponse(NamedTuple):
    status: int | None
    body: bytes
    error: str | None


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """urllib's default handler copies every header, Authorization included, onto the redirected
    request, even across hosts. Refusing makes the 3xx surface as an HTTPError: unobserved."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ARG002
        return None


_OPENER = urllib.request.build_opener(_RefuseRedirects)


def default_http_get(url: str, headers: Mapping[str, str], timeout: float) -> HttpResponse:
    """GET, and only GET: there is no method or body parameter to misuse, and no redirect."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, **dict(headers)}, method="GET"
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            return HttpResponse(
                status=int(response.status), body=response.read(MAX_BODY_BYTES), error=None
            )
    except urllib.error.HTTPError as exc:
        return HttpResponse(status=exc.code, body=b"", error=None)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return HttpResponse(status=None, body=b"", error=type(exc).__name__)


SECRET_TIMEOUT_S = 10.0


def default_resolve_secret(name: str) -> str | None:
    """Resolve one credential through the estate's FileStore interface; the value stays in memory."""
    try:
        result = subprocess.run(
            ["hapax-secret", name],
            capture_output=True,
            text=True,
            timeout=SECRET_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip() if result.returncode == 0 else ""
    return value or None


# --- held: names, login files and binaries per host ---------------------------------------------

#: Read-only. Prints names, relative paths and mtimes; never a value, never file content.
HOLDINGS_SCRIPT = r"""
set -u
PATH="$HOME/.local/bin:$HOME/.npm-global/bin:$PATH"
mode=logins
for arg in "$@"; do
  if [ "$arg" = "--bins" ]; then mode=bins; continue; fi
  if [ "$mode" = logins ]; then
    if [ -e "$HOME/$arg" ]; then printf 'L\t%s\t%s\n' "$arg" "$(stat -c %Y "$HOME/$arg")"; fi
  else
    if command -v "$arg" >/dev/null 2>&1; then printf 'B\t%s\n' "$arg"; fi
  fi
done
if [ -d "$HOME/.config/reins/secrets" ]; then
  for p in "$HOME/.config/reins/secrets"/*; do
    [ -e "$p" ] || continue
    n=${p##*/}
    printf 'F\t%s\n' "${n%.bin}"
  done
fi
if [ -d "$HOME/.password-store" ]; then
  find "$HOME/.password-store" -name '*.gpg' -printf 'P\t%P\n' 2>/dev/null | sed 's/\.gpg$//'
fi
if [ -f "$HOME/llm-stack/.env" ]; then
  grep -o '^[A-Za-z_][A-Za-z0-9_]*=' "$HOME/llm-stack/.env" | sed 's/=$//' | while read -r n; do printf 'E\t%s\n' "$n"; done
fi
printf 'H\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
"""

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@+-]{0,127}$")
_PASS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@+/-]{0,127}$")
_ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_REL_RE = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._/+-]{0,200}$")
_BIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")


class HostHoldings(_Strict):
    host_id: str
    reachable: bool
    observed_at: datetime | None
    error: str | None = None
    filestore_names: tuple[str, ...] = ()
    pass_names: tuple[str, ...] = ()
    env_names: tuple[str, ...] = ()
    login_files: dict[str, datetime] = Field(default_factory=dict)
    harness_bins: tuple[str, ...] = ()

    def credential_names(self) -> set[str]:
        return set(self.filestore_names) | {name.replace("/", "-") for name in self.pass_names}


def holdings_command(
    binding: HostBinding, *, login_files: Sequence[str], harness_bins: Sequence[str]
) -> list[str]:
    args = ["census-holdings", *login_files, "--bins", *harness_bins]
    if binding.transport == "local":
        return ["bash", "-c", HOLDINGS_SCRIPT, *args]
    assert binding.target is not None
    remote = (
        "bash -c " + shlex.quote(HOLDINGS_SCRIPT) + " " + " ".join(shlex.quote(a) for a in args)
    )
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "--", binding.target, remote]


def parse_holdings(host_id: str, text: str, *, now: datetime) -> HostHoldings:
    names: set[str] = set()
    passes: set[str] = set()
    envs: set[str] = set()
    bins: set[str] = set()
    logins: dict[str, datetime] = {}
    observed = now
    for line in text.splitlines():
        kind, _, rest = line.partition("\t")
        if kind == "F" and _NAME_RE.match(rest):
            names.add(rest)
        elif kind == "P" and _PASS_RE.match(rest) and ".." not in rest:
            passes.add(rest)
        elif kind == "E" and _ENV_RE.match(rest):
            envs.add(rest)
        elif kind == "B" and _BIN_RE.match(rest):
            bins.add(rest)
        elif kind == "L":
            rel, _, mtime = rest.partition("\t")
            stamp = _instant(int(mtime)) if mtime.isdigit() else None
            if _REL_RE.match(rel) and ".." not in rel.split("/") and stamp is not None:
                logins[rel] = stamp
        elif kind == "H":
            observed = _instant(rest) or now
    return HostHoldings(
        host_id=host_id,
        reachable=True,
        observed_at=observed,
        filestore_names=tuple(sorted(names)),
        pass_names=tuple(sorted(passes)),
        env_names=tuple(sorted(envs)),
        login_files=logins,
        harness_bins=tuple(sorted(bins)),
    )


def collect_holdings(
    binding: HostBinding,
    *,
    login_files: Sequence[str],
    harness_bins: Sequence[str],
    now: datetime,
    run: Callable[..., Any] = subprocess.run,
    timeout: float = 60,
) -> HostHoldings:
    """One read per host. An unreachable host is a row with a reason, never an omission."""
    argv = holdings_command(binding, login_files=login_files, harness_bins=harness_bins)
    try:
        result = run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return HostHoldings(
            host_id=binding.host_id,
            reachable=False,
            observed_at=None,
            error=f"{type(exc).__name__}",
        )
    if result.returncode != 0 and not (result.stdout or "").strip():
        return HostHoldings(
            host_id=binding.host_id,
            reachable=False,
            observed_at=None,
            error=f"exit_{result.returncode}",
        )
    return parse_holdings(binding.host_id, result.stdout or "", now=now)


# --- holds now: readbacks and their extractors --------------------------------------------------


# Pydantic invokes these validators through its registry; vulture cannot see that call path.
_PYDANTIC_DYNAMIC_ENTRYPOINTS = (
    ReadbackRef._allow_listed,
    DeclaredReference._dated,
    HostBinding._target,
    ServingEndpoint._bare_origin,
    HardwareFact._dated,
    TrialRecord._dated,
    EntitlementDecl._probe_rules,
    CensusConfig._unique,
    _RefuseRedirects.redirect_request,
)
