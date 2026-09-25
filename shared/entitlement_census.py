"""Entitlement census: what is held, what it holds now, and what is declared, joined into one view.

Architecture, with the estate's nouns removed: a scheduled reconciler joins
(a) **held** -- credential-store names per host, login-file existence and mtime (never content),
    installed harness binaries;
(b) **holds now** -- one allow-listed, spend-free readback per entitlement, vendor caches that carry
    their own fetch time, and declared references that carry an expiry;
(c) **declared** -- the route registry and the quota ledger.
It emits typed deltas into the existing capability-surface intake, hands quantities to the ledger in
the ledger's own measurement shape, and regenerates one projection. A second face lists *potential*
capacity on owned hardware (the market -> experiment -> deploy funnel); dispatch never reads it.

This is the reconciler the 2026-07-02 supply model designed (section 7, sequence step 4) and never
built. It adds no store: its classifier is ``shared.entitlement_capability``, its deltas are
``shared.capability_surface_delta`` rows, its quantities use the ledger's measurement fields, and its
projection doubles as a capability-surface pack that Reins already knows how to read.

Safety properties, each pinned by ``tests/shared/test_entitlement_census_producer.py``:

* No secret value reaches output. Every rendered artifact is scanned for every credential value this
  run resolved, and for secret-shaped tokens, before anything is written. One hit writes nothing.
* No readback spends. ``READBACKS`` below is the whole allow-list (usage, plan, balance and model-list
  GETs); configuration can only name its ids. The transport has no method or body parameter.
  Claude is never probed: its windows come from the ledger's passive readers.
* A rejected key (401/403) is ``dead``, never ``held``.
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
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.capability_surface_delta import (
    CAPABILITY_SURFACE_DELTA_SCHEMA_REF,
    AuthorityCeiling,
    CapabilitySurfaceDelta,
    CapabilitySurfaceDeltaFile,
    CapabilitySurfaceDescriptor,
    FreshnessState,
    SurfaceKind,
    build_surface_delta,
)
from shared.entitlement_capability import EntitlementShape, classify_entitlement

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


class EntitlementState(StrEnum):
    LIVE = "live"  # the entitlement's own surface answered 200 in this run
    HELD = "held"  # present (name, login file, binary, fresh cache, live record); not read back
    DEAD = "dead"  # its readback rejected the credential (401/403)
    STALE = "stale"  # the only evidence is a cache or record past its bound
    UNOBSERVED = "unobserved"  # no observation was possible this run
    ABSENT = "absent"  # seen before, not seen now on any reachable host; retained, never deleted
    TERMS_RESTRICTED = "terms_restricted"  # held, and never probed by design


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
    secret: str | None

    @model_validator(mode="after")
    def _allow_listed(self) -> ReadbackRef:
        if self.readback_id not in READBACKS:
            raise ValueError(
                f"readback {self.readback_id!r} is not in the allow-list; next action: name one of "
                f"{sorted(READBACKS)}, or add a spend-free GET to READBACKS through review"
            )
        if not self.secret:
            raise ValueError(
                f"readback {self.readback_id!r} needs the credential NAME it reads with"
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
            raise ValueError("a declared reference must expire after it was recorded")
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
            raise ValueError(f"host {self.host_id!r}: a local binding takes no target")
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
            raise ValueError("base_url must be scheme://host[:port] with no path")
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


class TrialRecord(_Strict):
    model: str = Field(min_length=1)
    stage: Literal["candidate_to_experiment", "candidate_to_deploy", "deployed", "rejected"]
    evidence: str = Field(min_length=1)
    recorded_at: datetime
    expires_at: datetime


class ScoutBinding(_Strict):
    host_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    components: tuple[str, ...] = ()


class MetalConfig(_Strict):
    scout_report: ScoutBinding | None = None
    hardware: tuple[HardwareFact, ...] = ()
    trial_records: tuple[TrialRecord, ...] = ()


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

    @model_validator(mode="after")
    def _probe_rules(self) -> EntitlementDecl:
        if self.terms_restricted and (self.readbacks or self.vendor_cache):
            raise ValueError(
                f"{self.entitlement_id}: a terms-restricted provider is never probed; next action: "
                "remove its readbacks and vendor cache"
            )
        if self.vendor_cache is not None and self.vendor_cache not in VENDOR_CACHES:
            raise ValueError(f"{self.entitlement_id}: unknown vendor cache {self.vendor_cache!r}")
        for rel in self.login_files:
            if rel.startswith("/") or ".." in rel.split("/"):
                raise ValueError(f"{self.entitlement_id}: login file {rel!r} must be home-relative")
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
                raise ValueError(f"duplicate {label}: {duplicates}")
        return self


def load_census_config(path: Path = ENTITLEMENT_CENSUS_CONFIG) -> CensusConfig:
    try:
        return CensusConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise CensusConfigError(
            f"entitlement census declaration {path} is invalid: {exc}; next action: repair it and "
            "rerun `scripts/hapax-entitlement-census --dry-run`"
        ) from exc


# --- small helpers --------------------------------------------------------------------------------


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


def default_http_get(url: str, headers: Mapping[str, str], timeout: float) -> HttpResponse:
    """GET, and only GET: there is no method or body parameter to misuse."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, **dict(headers)}, method="GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResponse(
                status=int(response.status), body=response.read(MAX_BODY_BYTES), error=None
            )
    except urllib.error.HTTPError as exc:
        return HttpResponse(status=exc.code, body=b"", error=None)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return HttpResponse(status=None, body=b"", error=type(exc).__name__)


def default_resolve_secret(name: str) -> str | None:
    """Resolve one credential through the estate's FileStore interface; the value stays in memory."""
    try:
        result = subprocess.run(
            ["hapax-secret", name], capture_output=True, text=True, timeout=30, check=False
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


def _measurement(
    capacity_id: str,
    *,
    quantity: float,
    unit: str,
    window: str | None,
    observed_at: datetime,
    resets_at: datetime | None,
    source: str,
    details: dict[str, FactValue] | None = None,
) -> dict[str, Any]:
    """The quota ledger's measurement fields (A1's ``QuotaMeasurement``), as plain JSON."""
    fresh_until = observed_at + MEASUREMENT_TTL
    if resets_at is not None:
        fresh_until = min(fresh_until, resets_at)
    return {
        "capacity_id": capacity_id,
        "quantity": float(quantity),
        "unit": unit,
        "window": window,
        "resets_at": _iso(resets_at),
        "label": "observed",
        "source": source,
        "observed_at": _iso(observed_at),
        "measurement_fresh_until": _iso(fresh_until),
        "reason_code": None,
        "details": details or {},
    }


@dataclass
class Extracted:
    facts: dict[str, FactValue] = field(default_factory=dict)
    measurements: list[dict[str, Any]] = field(default_factory=list)


def _pct(used: Any, limit: Any) -> float | None:
    u, lim = _number(used), _number(limit)
    if u is None or lim is None or lim <= 0:
        return None
    return round(u / lim * 100, 4)


def _x_kimi(payload: Any, at: datetime, src: str) -> Extracted:
    out = Extracted()
    weekly = _pct(_get(payload, "usage", "used"), _get(payload, "usage", "limit"))
    if weekly is not None:
        out.facts["weekly_used_pct"] = weekly
        out.measurements.append(
            _measurement(
                "kimi.subscription.weekly",
                quantity=weekly,
                unit="percent_used",
                window="10080m",
                observed_at=at,
                resets_at=_instant(_get(payload, "usage", "resetTime")),
                source=src,
            )
        )
    for limit in _get(payload, "limits") or []:
        minutes = _number(_get(limit, "window", "duration"))
        pct = _pct(_get(limit, "detail", "used"), _get(limit, "detail", "limit"))
        if (
            minutes is None
            or pct is None
            or _get(limit, "window", "timeUnit") != "TIME_UNIT_MINUTE"
        ):
            continue
        name = "five_hour" if int(minutes) == 300 else f"{int(minutes)}m"
        out.facts[f"{name}_used_pct"] = pct
        out.measurements.append(
            _measurement(
                f"kimi.subscription.{name}",
                quantity=pct,
                unit="percent_used",
                window=f"{int(minutes)}m",
                observed_at=at,
                resets_at=_instant(_get(limit, "detail", "resetTime")),
                source=src,
            )
        )
    amount = _number(_get(payload, "booster_wallet", "balance", "amount"))
    unit = _safe_fact(_get(payload, "booster_wallet", "balance", "unit"))
    if amount is not None:
        # Unit scale unverified (E0): recorded raw, never converted.
        out.measurements.append(
            _measurement(
                "kimi.booster.balance",
                quantity=amount,
                unit=f"raw:{unit or 'unknown'}",
                window=None,
                observed_at=at,
                resets_at=None,
                source=src,
                details={"scale": "unverified"},
            )
        )
    return out


_GLM_WINDOWS = {(3, 5): ("five_hour", "300m"), (6, 1): ("weekly", "10080m")}


def _x_glm(payload: Any, at: datetime, src: str) -> Extracted:
    out = Extracted(facts={"plan": _safe_fact(_get(payload, "data", "level"))})
    for limit in _get(payload, "data", "limits") or []:
        pct = _number(_get(limit, "percentage"))
        if pct is None:
            continue
        unit, number = _get(limit, "unit"), _get(limit, "number")
        reset = _instant(_get(limit, "nextResetTime"))
        if _get(limit, "type") == "TOKENS_LIMIT" and (unit, number) in _GLM_WINDOWS:
            name, window = _GLM_WINDOWS[(unit, number)]
            out.facts[f"{name}_used_pct"] = pct
            out.measurements.append(
                _measurement(
                    f"glm.subscription.{name}",
                    quantity=pct,
                    unit="percent_used",
                    window=window,
                    observed_at=at,
                    resets_at=reset,
                    source=src,
                )
            )
        elif _get(limit, "type") == "TIME_LIMIT":
            out.measurements.append(
                _measurement(
                    "glm.mcp_tools.period",
                    quantity=pct,
                    unit="percent_used",
                    window=f"unit{unit}x{number}",
                    observed_at=at,
                    resets_at=reset,
                    source=src,
                    details={
                        "limit": _number(_get(limit, "usage")),
                        "used": _number(_get(limit, "currentValue")),
                    },
                )
            )
    return out


def _x_sakana(payload: Any, at: datetime, src: str) -> Extracted:
    out = Extracted(
        facts={
            "plan": _safe_fact(_get(payload, "plan")),
            "billing_mode": _safe_fact(_get(payload, "billing_mode")),
        }
    )
    seconds = _number(_get(payload, "window_seconds")) or 18000
    for key, name, window in (
        (
            "window_usage",
            "five_hour" if int(seconds) == 18000 else f"{int(seconds // 60)}m",
            f"{int(seconds // 60)}m",
        ),
        ("weekly_usage", "weekly", "10080m"),
    ):
        pct = _number(_get(payload, key, "usage_percent"))
        if pct is None:
            continue
        out.facts[f"{name}_used_pct"] = pct
        out.measurements.append(
            _measurement(
                f"fugu.subscription.{name}",
                quantity=pct,
                unit="percent_used",
                window=window,
                observed_at=at,
                resets_at=_instant(_get(payload, key, "reset_at")),
                source=src,
            )
        )
    micro = _number(_get(payload, "pay_as_you_go", "available_amount_micro_usd"))
    if micro is not None:
        out.measurements.append(
            _measurement(
                "fugu.payg.balance",
                quantity=micro / 1_000_000,
                unit="USD",
                window=None,
                observed_at=at,
                resets_at=None,
                source=src,
            )
        )
    return out


def _x_openrouter_credits(payload: Any, at: datetime, src: str) -> Extracted:
    out = Extracted()
    credits, usage = (
        _number(_get(payload, "data", "total_credits")),
        _number(_get(payload, "data", "total_usage")),
    )
    if credits is not None and usage is not None:
        balance = round(credits - usage, 4)
        out.facts["balance_usd"] = balance
        out.measurements.append(
            _measurement(
                "openrouter.prepaid.balance",
                quantity=balance,
                unit="USD",
                window=None,
                observed_at=at,
                resets_at=None,
                source=src,
            )
        )
    return out


def _x_openrouter_key(payload: Any, at: datetime, src: str) -> Extracted:
    data = _get(payload, "data") if isinstance(_get(payload, "data"), dict) else payload
    out = Extracted(
        facts={
            "key_limit_usd": _number(_get(data, "limit")),
            "key_usage_daily_usd": _number(_get(data, "usage_daily")),
            "key_usage_weekly_usd": _number(_get(data, "usage_weekly")),
        }
    )
    weekly = _number(_get(data, "usage_weekly"))
    if weekly is not None:
        out.measurements.append(
            _measurement(
                "openrouter.key.spend_weekly",
                quantity=weekly,
                unit="USD",
                window="10080m",
                observed_at=at,
                resets_at=None,
                source=src,
            )
        )
    return out


def _x_featherless(payload: Any, at: datetime, src: str) -> Extracted:
    return Extracted(
        facts={
            "plan": _safe_fact(_get(payload, "id")),
            "concurrency": _number(_get(payload, "concurrency")),
        }
    )


def _x_hf(payload: Any, at: datetime, src: str) -> Extracted:
    period_end = _instant(_get(payload, "periodEnd"))
    return Extracted(
        facts={
            "is_pro": _get(payload, "isPro") if isinstance(_get(payload, "isPro"), bool) else None,
            "period_end": _iso(period_end),
            "token_role": _safe_fact(_get(payload, "auth", "accessToken", "role")),
        }
    )


def _x_tavily(payload: Any, at: datetime, src: str) -> Extracted:
    out = Extracted(
        facts={
            "plan": _safe_fact(_get(payload, "account", "current_plan")),
            "paygo_usage": _number(_get(payload, "account", "paygo_usage")),
        }
    )
    used, limit = _get(payload, "account", "plan_usage"), _get(payload, "account", "plan_limit")
    pct = _pct(used, limit)
    if pct is not None:
        out.measurements.append(
            _measurement(
                "tavily.plan.usage",
                quantity=pct,
                unit="percent_used",
                window="plan_period",
                observed_at=at,
                resets_at=None,
                source=src,
                details={"used": _number(used), "limit": _number(limit)},
            )
        )
    return out


def _x_firecrawl(payload: Any, at: datetime, src: str) -> Extracted:
    remaining = _number(_get(payload, "data", "remainingCredits"))
    out = Extracted(
        facts={
            "plan_credits": _number(_get(payload, "data", "planCredits")),
            "remaining_credits": remaining,
            "period_end": _iso(_instant(_get(payload, "data", "billingPeriodEnd"))),
        }
    )
    if remaining is not None:
        out.measurements.append(
            _measurement(
                "firecrawl.credits.remaining",
                quantity=remaining,
                unit="credits",
                window="billing_period",
                observed_at=at,
                resets_at=_instant(_get(payload, "data", "billingPeriodEnd")),
                source=src,
            )
        )
    return out


def _x_elevenlabs(payload: Any, at: datetime, src: str) -> Extracted:
    out = Extracted(
        facts={
            "tier": _safe_fact(_get(payload, "tier")),
            "status": _safe_fact(_get(payload, "status")),
        }
    )
    pct = _pct(_get(payload, "character_count"), _get(payload, "character_limit"))
    if pct is not None:
        out.measurements.append(
            _measurement(
                "elevenlabs.characters.used",
                quantity=pct,
                unit="percent_used",
                window="billing_period",
                observed_at=at,
                resets_at=_instant(_get(payload, "next_character_count_reset_unix")),
                source=src,
                details={"limit": _number(_get(payload, "character_limit"))},
            )
        )
    return out


def _x_status_only(payload: Any, at: datetime, src: str) -> Extracted:
    return Extracted()


def _x_model_list(payload: Any, at: datetime, src: str) -> Extracted:
    ids = [_get(m, "id") for m in (_get(payload, "data") or [])]
    ids += [_get(m, "name") for m in (_get(payload, "models") or [])]
    safe = [t for t in (_safe_fact(i) for i in ids if i) if isinstance(t, str)]
    return Extracted(facts={"models": ", ".join(safe[:16]), "model_count": len(ids)})


EXTRACTORS: Mapping[str, Callable[[Any, datetime, str], Extracted]] = MappingProxyType(
    {
        "kimi_usages": _x_kimi,
        "glm_quota_limit": _x_glm,
        "sakana_usage": _x_sakana,
        "openrouter_credits": _x_openrouter_credits,
        "openrouter_key": _x_openrouter_key,
        "featherless_plan": _x_featherless,
        "hf_whoami": _x_hf,
        "tavily_usage": _x_tavily,
        "firecrawl_credit_usage": _x_firecrawl,
        "elevenlabs_subscription": _x_elevenlabs,
        "status_only": _x_status_only,
        "model_list": _x_model_list,
    }
)


class ReadbackResult(_Strict):
    readback_id: str
    outcome: Literal["live", "dead", "unobserved"]
    http_status: int | None
    observed_at: datetime
    reason: str | None = None
    facts: dict[str, FactValue] = Field(default_factory=dict)
    measurements: tuple[dict[str, Any], ...] = ()


def _outcome(
    readback_id: str,
    response: HttpResponse,
    extractor: str,
    *,
    now: datetime,
) -> ReadbackResult:
    source = f"entitlement-census:{readback_id}"
    # Only 401 proves the credential was rejected. A 403 can be an edge block (Featherless answers
    # 403 to urllib's default User-Agent and 200 to curl's, same key, 2026-09-25T00:31Z) or a scope
    # the key lacks (OpenRouter /activity), so it narrows to unobserved: never dead, never held.
    if response.status == 401:
        return ReadbackResult(
            readback_id=readback_id,
            outcome="dead",
            http_status=401,
            observed_at=now,
            reason="http_401_credential_rejected",
        )
    if response.status == 403:
        return ReadbackResult(
            readback_id=readback_id,
            outcome="unobserved",
            http_status=403,
            observed_at=now,
            reason="http_403_forbidden_unclassified (credential, scope or edge block)",
        )
    if response.status is None:
        return ReadbackResult(
            readback_id=readback_id,
            outcome="unobserved",
            http_status=None,
            observed_at=now,
            reason=f"transport_{response.error or 'error'}",
        )
    if response.status != 200:
        return ReadbackResult(
            readback_id=readback_id,
            outcome="unobserved",
            http_status=response.status,
            observed_at=now,
            reason=f"http_{response.status}",
        )
    try:
        payload = json.loads(response.body) if response.body else {}
    except ValueError:
        return ReadbackResult(
            readback_id=readback_id,
            outcome="live",
            http_status=200,
            observed_at=now,
            reason="body_unparseable",
        )
    extracted = EXTRACTORS[extractor](payload, now, source)
    facts = {k: v for k, v in extracted.facts.items() if v is not None}
    return ReadbackResult(
        readback_id=readback_id,
        outcome="live",
        http_status=200,
        observed_at=now,
        facts=facts,
        measurements=tuple(extracted.measurements),
    )


def run_readback(
    ref: ReadbackRef,
    *,
    now: datetime,
    resolve_secret: Callable[[str], str | None],
    http_get: Callable[[str, dict[str, str], float], HttpResponse],
    secrets: SecretRegister,
) -> ReadbackResult:
    spec = READBACKS[ref.readback_id]
    assert ref.secret is not None
    value = resolve_secret(ref.secret)
    if not value:
        return ReadbackResult(
            readback_id=ref.readback_id,
            outcome="unobserved",
            http_status=None,
            observed_at=now,
            reason="secret_unresolvable",
        )
    secrets.remember(value)
    header, template = _AUTH_HEADERS[spec.auth]
    headers = {header: template.format(value), **dict(spec.extra_headers)}
    response = http_get(spec.url, headers, READBACK_TIMEOUT_S)
    return _outcome(ref.readback_id, response, spec.extractor, now=now)


# --- holds now: vendor caches ---------------------------------------------------------------------


@dataclass(frozen=True)
class VendorCacheReading:
    cache_id: str
    fetched_at: datetime | None
    facts: dict[str, FactValue]
    reason: str | None = None


def _grok_cache(raw: bytes) -> tuple[datetime | None, dict[str, FactValue]]:
    outer = json.loads(raw)
    payload = outer.get("payload") if isinstance(outer, dict) else None
    inner = json.loads(payload) if isinstance(payload, str) else payload
    return _instant(_get(inner, "fetched_at")), {
        "tier": _safe_fact(_get(inner, "settings", "subscription_tier_display"))
    }


def _vibe_cache(raw: bytes) -> tuple[datetime | None, dict[str, FactValue]]:
    entries = [e for e in (json.loads(raw) or {}).values() if isinstance(e, dict)]
    stamped = [(_instant(_get(e, "stored_at_timestamp")), e) for e in entries]
    stamped = [(t, e) for t, e in stamped if t is not None]
    if not stamped:
        return None, {}
    at, newest = max(stamped, key=lambda pair: pair[0])
    return at, {
        "plan_type": _safe_fact(_get(newest, "payload", "plan_type")),
        "plan_name": _safe_fact(_get(newest, "payload", "plan_name")),
        "cached_accounts": len(stamped),
    }


VENDOR_CACHES: Mapping[
    str, tuple[str, Callable[[bytes], tuple[datetime | None, dict[str, FactValue]]]]
] = MappingProxyType(
    {
        "grok_settings_cache": (".grok/settings_cache.json", _grok_cache),
        "vibe_whoami_cache": (".vibe/whoami_cache.json", _vibe_cache),
    }
)


def read_vendor_cache(
    cache_id: str, read_home_file: Callable[[str], bytes | None]
) -> VendorCacheReading:
    rel, parse = VENDOR_CACHES[cache_id]
    raw = read_home_file(rel)
    if raw is None:
        return VendorCacheReading(cache_id, None, {}, "cache_absent")
    try:
        fetched_at, facts = parse(raw)
    except (ValueError, TypeError, AttributeError):
        return VendorCacheReading(cache_id, None, {}, "cache_unparseable")
    return VendorCacheReading(
        cache_id, fetched_at, {k: v for k, v in facts.items() if v is not None}
    )


# --- the joined row -------------------------------------------------------------------------------


class CensusRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entitlement_id: str
    provider: str
    kind: EntitlementKind
    identified: bool
    entitlement_shape: str
    cost_class: CostClass
    state: EntitlementState
    evidence_class: EvidenceClass
    freshness: FreshnessState
    recruitment_stage: RecruitmentStage
    observed_at: datetime | None = None
    fresh_until: datetime | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    hosts: tuple[str, ...] = ()
    credential_names: tuple[str, ...] = ()
    login_files: tuple[str, ...] = ()
    harnesses: tuple[str, ...] = ()
    readbacks: tuple[dict[str, Any], ...] = ()
    facts: dict[str, FactValue] = Field(default_factory=dict)
    measurements: tuple[dict[str, Any], ...] = ()
    declared_routes: tuple[str, ...] = ()
    declared_shapes: tuple[str, ...] = ()
    ledger: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    notes: str | None = None


_FRESHNESS = {
    EntitlementState.LIVE: FreshnessState.FRESH,
    EntitlementState.DEAD: FreshnessState.FRESH,
    EntitlementState.HELD: FreshnessState.HELD,
    EntitlementState.STALE: FreshnessState.STALE,
    EntitlementState.ABSENT: FreshnessState.ABSENT,
    EntitlementState.UNOBSERVED: FreshnessState.UNKNOWN,
    EntitlementState.TERMS_RESTRICTED: FreshnessState.DARK,
}

_SHAPE_KIND = {
    EntitlementShape.COGNITION_WAREHOUSE: EntitlementKind.COGNITION,
    EntitlementShape.COGNITION_PROVIDER: EntitlementKind.COGNITION,
    EntitlementShape.WEB_GROUNDING: EntitlementKind.GROUNDING,
    EntitlementShape.MODALITY: EntitlementKind.MODALITY,
}


@dataclass(frozen=True)
class _Prior:
    first_seen: datetime | None
    last_seen: datetime | None
    hosts: tuple[str, ...]
    provider: str
    kind: str
    shape: str


def _prior_rows(prior_view: Mapping[str, Any] | None) -> dict[str, _Prior]:
    out: dict[str, _Prior] = {}
    for row in (prior_view or {}).get("rows") or []:
        if not isinstance(row, dict) or not isinstance(row.get("entitlement_id"), str):
            continue
        out[row["entitlement_id"]] = _Prior(
            first_seen=_instant(row.get("first_seen")),
            last_seen=_instant(row.get("last_seen")),
            hosts=tuple(h for h in row.get("hosts") or [] if isinstance(h, str)),
            provider=str(row.get("provider") or "unknown"),
            kind=str(row.get("kind") or EntitlementKind.RESOURCE.value),
            shape=str(row.get("entitlement_shape") or EntitlementShape.NON_CAPABILITY.value),
        )
    return out


def _recruitment(
    state: EntitlementState,
    *,
    declared_routes: Sequence[Mapping[str, Any]],
    declared: bool,
    measured: bool,
) -> RecruitmentStage:
    """The routing table's ladder (also ``QuotaSnapshot.stage``). Recruitment, never admission."""
    if state in {EntitlementState.DEAD, EntitlementState.ABSENT, EntitlementState.TERMS_RESTRICTED}:
        return "unusable"
    if not declared:
        return "unusable" if state is EntitlementState.UNOBSERVED else "usable-undeclared"
    if measured and any(r.get("route_state") in ROUTABLE_ROUTE_STATES for r in declared_routes):
        return "routable"
    return "declared-measured" if measured else "declared-unmeasured"


def _retained(
    entitlement_id: str,
    prior: _Prior | None,
    unreachable: set[str],
) -> tuple[EntitlementState, list[str]]:
    """No evidence now: unobserved if a host it lived on could not be read, else absent or unobserved."""
    if prior is not None:
        blind = sorted(set(prior.hosts) & unreachable)
        if blind:
            return EntitlementState.UNOBSERVED, [
                f"host {h} unreachable this run; last seen there" for h in blind
            ]
        if prior.last_seen is not None:
            return EntitlementState.ABSENT, [
                "not seen on any reachable host; retained with last_seen"
            ]
    return EntitlementState.UNOBSERVED, ["no evidence on any observed host"]


@dataclass
class CensusRun:
    now: datetime
    config: CensusConfig
    rows: list[CensusRow]
    holdings: list[HostHoldings]
    unclassified: dict[str, Any]
    potential: dict[str, Any]
    descriptors: list[CapabilitySurfaceDescriptor]
    deltas: list[CapabilitySurfaceDelta]
    measurements: list[dict[str, Any]]
    secrets: SecretRegister


def _registry_rows(registry: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    return [r for r in registry.get(key) or [] if isinstance(r, dict)]


def _decl_row(
    decl: EntitlementDecl,
    *,
    now: datetime,
    config: CensusConfig,
    holdings: Sequence[HostHoldings],
    readbacks: Mapping[tuple[str, str | None], ReadbackResult],
    cache: VendorCacheReading | None,
    registry: Mapping[str, Any],
    ledger: Mapping[str, Any] | None,
    prior: _Prior | None,
) -> CensusRow:
    reasons: list[str] = []
    hosts: set[str] = set()
    creds: set[str] = set()
    logins: dict[str, datetime] = {}
    bins: set[str] = set()
    presence_at: datetime | None = None
    for h in holdings:
        if not h.reachable:
            continue
        found = False
        for name in h.credential_names() & set(decl.credential_names):
            creds.add(name)
            found = True
        for env in set(h.env_names) & set(decl.env_names):
            creds.add(f"env:{env}")
            found = True
        for rel in set(h.login_files) & set(decl.login_files):
            logins[rel] = max(logins.get(rel, h.login_files[rel]), h.login_files[rel])
            found = True
        for binary in set(h.harness_bins) & set(decl.harness_bins):
            bins.add(binary)
            found = True
        if found:
            hosts.add(h.host_id)
            if h.observed_at is not None:
                presence_at = max(presence_at or h.observed_at, h.observed_at)
    unreachable = {h.host_id for h in holdings if not h.reachable}

    results = [
        readbacks[(r.readback_id, r.secret)]
        for r in decl.readbacks
        if (r.readback_id, r.secret) in readbacks
    ]
    live = [r for r in results if r.outcome == "live"]
    dead = [r for r in results if r.outcome == "dead"]
    for r in results:
        if r.reason:
            reasons.append(f"{r.readback_id}: {r.reason}")
    facts: dict[str, FactValue] = {}
    measurements: list[dict[str, Any]] = []
    for r in live:
        facts.update(r.facts)
        measurements.extend(r.measurements)
    if decl.measurement_prefixes:
        measurements = [
            m for m in measurements if m["capacity_id"].startswith(decl.measurement_prefixes)
        ]
    if cache is not None:
        if cache.reason:
            reasons.append(f"{cache.cache_id}: {cache.reason}")
        facts.update({f"cache_{k}" if k in facts else k: v for k, v in cache.facts.items()})
    refs_live = [r for r in decl.declared_refs if r.expires_at > now]
    refs_expired = [r for r in decl.declared_refs if r.expires_at <= now]
    for ref in refs_expired:
        reasons.append(f"declared reference expired {_iso(ref.expires_at)}: {ref.fact}")
    held_now = bool(creds or logins or bins)
    max_age = timedelta(seconds=config.vendor_cache_max_age_seconds)

    observed_at: datetime | None = None
    fresh_until: datetime | None = None
    if decl.terms_restricted and (held_now or decl.declared_refs):
        state = EntitlementState.TERMS_RESTRICTED
        evidence = EvidenceClass.NAME_ONLY if held_now else EvidenceClass.RECORDED
        observed_at = presence_at or max((r.recorded_at for r in decl.declared_refs), default=None)
        reasons.append("terms restrict scripted calls: never probed")
    elif live:
        state, evidence = EntitlementState.LIVE, EvidenceClass.LIVE
        observed_at = max(r.observed_at for r in live)
        fresh_until = observed_at + MEASUREMENT_TTL
    elif dead:
        state, evidence = EntitlementState.DEAD, EvidenceClass.LIVE
        observed_at = max(r.observed_at for r in dead)
        fresh_until = observed_at + MEASUREMENT_TTL
    elif cache is not None and cache.fetched_at is not None:
        evidence = EvidenceClass.VENDOR_CACHE
        observed_at = cache.fetched_at
        fresh_until = cache.fetched_at + max_age
        if now - cache.fetched_at > max_age:
            state = EntitlementState.STALE
            reasons.append(
                f"vendor cache fetched {_iso(cache.fetched_at)}, past its {max_age} bound"
            )
        else:
            state = EntitlementState.HELD
    elif held_now:
        state = EntitlementState.HELD
        evidence = EvidenceClass.NATIVE_RECORD if logins else EvidenceClass.NAME_ONLY
        observed_at = presence_at
        fresh_until = presence_at + PRESENCE_TTL if presence_at else None
    elif refs_live:
        state, evidence = EntitlementState.HELD, EvidenceClass.RECORDED
        observed_at = max(r.recorded_at for r in refs_live)
        fresh_until = min(r.expires_at for r in refs_live)
    elif refs_expired:
        state, evidence = EntitlementState.STALE, EvidenceClass.RECORDED
        observed_at = max(r.recorded_at for r in refs_expired)
    else:
        state, retained = _retained(decl.entitlement_id, prior, unreachable)
        evidence = EvidenceClass.NONE
        reasons.extend(retained)
    if held_now and unreachable:
        reasons.append(f"not observed on unreachable host(s): {', '.join(sorted(unreachable))}")

    present_now = (
        held_now or bool(live or dead) or (cache is not None and cache.fetched_at is not None)
    )
    last_seen = now if present_now else (prior.last_seen if prior else None)
    first_seen = (prior.first_seen if prior and prior.first_seen else None) or (
        now if present_now else None
    )
    if not present_now and prior is not None:
        hosts = set(prior.hosts)

    routes = _registry_rows(registry, "routes")
    shapes = _registry_rows(registry, "omitted_capability_shapes")
    declared_routes = [
        r
        for r in routes
        if r.get("platform") in decl.registry_platforms
        or r.get("route_id") in decl.registry_route_ids
    ]
    declared_shapes = [s for s in shapes if s.get("shape_id") in decl.registry_shape_ids]
    route_ids = {str(r.get("route_id")) for r in routes}
    for missing in sorted(set(decl.registry_route_ids) - route_ids):
        reasons.append(f"declared route {missing} is absent from the registry")
    ledger_rows = [
        s
        for s in ((ledger or {}).get("quota_snapshots") or [])
        if isinstance(s, dict) and s.get("provider") in decl.ledger_providers
    ]
    ledger_summary = tuple(
        f"{s.get('route_id') or s.get('capacity_id') or s.get('snapshot_id')}:{s.get('subscription_quota_state')}"
        for s in ledger_rows
    )
    ledger_fresh = any(s.get("subscription_quota_state") == "fresh" for s in ledger_rows)
    if measurements and any(s.get("subscription_quota_state") == "unknown" for s in ledger_rows):
        reasons.append(
            "ledger reads unknown; this run measured it (quantities handed to the ledger)"
        )

    return CensusRow(
        entitlement_id=decl.entitlement_id,
        provider=decl.provider,
        kind=decl.kind,
        identified=True,
        entitlement_shape=_decl_shape(decl).value,
        cost_class=decl.cost_class,
        state=state,
        evidence_class=evidence,
        freshness=_FRESHNESS[state],
        recruitment_stage=_recruitment(
            state,
            declared_routes=declared_routes,
            declared=bool(declared_routes or declared_shapes),
            measured=bool(measurements) or ledger_fresh,
        ),
        observed_at=observed_at,
        fresh_until=fresh_until,
        first_seen=first_seen,
        last_seen=last_seen,
        hosts=tuple(sorted(hosts)),
        credential_names=tuple(sorted(creds)),
        login_files=tuple(f"{rel} (mtime {_iso(at)})" for rel, at in sorted(logins.items())),
        harnesses=tuple(sorted(bins)),
        readbacks=tuple(
            {
                "readback_id": r.readback_id,
                "outcome": r.outcome,
                "http_status": r.http_status,
                "observed_at": _iso(r.observed_at),
            }
            for r in results
        ),
        facts={k: v for k, v in facts.items() if v is not None},
        measurements=tuple(measurements),
        declared_routes=tuple(sorted(str(r.get("route_id")) for r in declared_routes)),
        declared_shapes=tuple(sorted(str(s.get("shape_id")) for s in declared_shapes)),
        ledger=ledger_summary,
        reasons=tuple(reasons),
        notes=decl.notes,
    )


def _decl_shape(decl: EntitlementDecl) -> EntitlementShape:
    for name in decl.credential_names:
        shape = classify_entitlement(name)
        if shape is not EntitlementShape.NON_CAPABILITY:
            return shape
    return {
        EntitlementKind.COGNITION: EntitlementShape.COGNITION_PROVIDER,
        EntitlementKind.GROUNDING: EntitlementShape.WEB_GROUNDING,
        EntitlementKind.MODALITY: EntitlementShape.MODALITY,
    }.get(decl.kind, EntitlementShape.NON_CAPABILITY)


def _withheld(name: str, tokens: Sequence[str]) -> bool:
    lowered = name.lower()
    return any(token.lower() in lowered for token in tokens)


def _unidentified_rows(
    config: CensusConfig,
    *,
    now: datetime,
    holdings: Sequence[HostHoldings],
    priors: Mapping[str, _Prior],
) -> tuple[list[CensusRow], dict[str, Any]]:
    claimed = {n for d in config.entitlements for n in (*d.credential_names, *d.env_names)}
    seen: dict[str, set[str]] = {}
    observed: dict[str, datetime] = {}
    for h in holdings:
        if not h.reachable:
            continue
        for name in h.credential_names() | set(h.env_names):
            if name in claimed:
                continue
            seen.setdefault(name, set()).add(h.host_id)
            if h.observed_at is not None:
                observed[name] = max(observed.get(name, h.observed_at), h.observed_at)
    rows: list[CensusRow] = []
    listed: list[dict[str, Any]] = []
    withheld = 0
    for name in sorted(seen):
        shape = classify_entitlement(name)
        if shape is EntitlementShape.NON_CAPABILITY:
            if _withheld(name, config.withheld_name_tokens):
                withheld += 1
            else:
                listed.append({"name": name, "hosts": sorted(seen[name])})
            continue
        row_id = f"unidentified.{name.lower()}"
        prior = priors.get(row_id)
        rows.append(
            CensusRow(
                entitlement_id=row_id,
                provider="unidentified",
                kind=_SHAPE_KIND.get(shape, EntitlementKind.RESOURCE),
                identified=False,
                entitlement_shape=shape.value,
                cost_class=CostClass.UNOBSERVED,
                state=EntitlementState.HELD,
                evidence_class=EvidenceClass.NAME_ONLY,
                freshness=FreshnessState.HELD,
                recruitment_stage="usable-undeclared",
                observed_at=observed.get(name),
                fresh_until=observed[name] + PRESENCE_TTL if name in observed else None,
                first_seen=(prior.first_seen if prior else None) or now,
                last_seen=now,
                hosts=tuple(sorted(seen[name])),
                credential_names=(name,),
                reasons=("credential name not in the census catalogue; classified by name only",),
            )
        )
    present = {row.entitlement_id for row in rows}
    unreachable = {h.host_id for h in holdings if not h.reachable}
    for row_id, prior in sorted(priors.items()):
        if not row_id.startswith("unidentified.") or row_id in present:
            continue
        state, reasons = _retained(row_id, prior, unreachable)
        rows.append(
            CensusRow(
                entitlement_id=row_id,
                provider=prior.provider,
                kind=EntitlementKind(prior.kind)
                if prior.kind in EntitlementKind._value2member_map_
                else EntitlementKind.RESOURCE,
                identified=False,
                entitlement_shape=prior.shape,
                cost_class=CostClass.UNOBSERVED,
                state=state,
                evidence_class=EvidenceClass.NONE,
                freshness=_FRESHNESS[state],
                recruitment_stage="unusable",
                first_seen=prior.first_seen,
                last_seen=prior.last_seen,
                hosts=prior.hosts,
                credential_names=(row_id.removeprefix("unidentified."),),
                reasons=tuple(reasons),
            )
        )
    return rows, {"count": len(listed) + withheld, "withheld": withheld, "names": listed}


def _serving_row(
    endpoint: ServingEndpoint,
    *,
    now: datetime,
    http_get: Callable[[str, dict[str, str], float], HttpResponse],
    registry: Mapping[str, Any],
    prior: _Prior | None,
) -> CensusRow:
    response = http_get(endpoint.base_url + endpoint.models_path, {}, SERVING_TIMEOUT_S)
    result = _outcome(f"serving:{endpoint.endpoint_id}", response, "model_list", now=now)
    row_id = f"serving.{endpoint.endpoint_id}"
    reasons: list[str] = []
    if result.outcome == "live":
        state, evidence = EntitlementState.LIVE, EvidenceClass.LIVE
    else:
        state, evidence = EntitlementState.UNOBSERVED, EvidenceClass.NONE
        reasons.append(
            "auth required on a model listing"
            if result.outcome == "dead"
            else (result.reason or "no answer")
        )
    local_routes = [
        r for r in _registry_rows(registry, "routes") if r.get("platform") == "local_tool"
    ]
    return CensusRow(
        entitlement_id=row_id,
        provider="owned",
        kind=EntitlementKind.LOCAL,
        identified=True,
        entitlement_shape="local_serving",
        cost_class=CostClass.LOCAL,
        state=state,
        evidence_class=evidence,
        freshness=_FRESHNESS[state],
        recruitment_stage=_recruitment(
            state,
            declared_routes=local_routes,
            declared=bool(local_routes),
            measured=state is EntitlementState.LIVE,
        ),
        observed_at=now,
        fresh_until=now + MEASUREMENT_TTL if state is EntitlementState.LIVE else None,
        first_seen=(prior.first_seen if prior and prior.first_seen else None)
        or (now if state is EntitlementState.LIVE else None),
        last_seen=now if state is EntitlementState.LIVE else (prior.last_seen if prior else None),
        hosts=(endpoint.host_id,),
        readbacks=(
            {
                "readback_id": row_id,
                "outcome": result.outcome,
                "http_status": result.http_status,
                "observed_at": _iso(now),
            },
        ),
        facts={k: v for k, v in result.facts.items() if v is not None},
        declared_routes=tuple(sorted(str(r.get("route_id")) for r in local_routes)),
        reasons=tuple(reasons),
        notes="a serving binding of owned compute, not an entitlement of its own",
    )


# --- the potential face ---------------------------------------------------------------------------


def _potential(
    config: CensusConfig,
    *,
    now: datetime,
    serving: Sequence[CensusRow],
    scout_report: Mapping[str, Any] | None,
    gpu_probe: Callable[[str], tuple[bool, list[str]]] | None,
) -> dict[str, Any]:
    metal = config.metal
    experiment: list[dict[str, Any]] = []
    scout_meta: dict[str, Any] = {"bound": metal.scout_report is not None}
    if metal.scout_report is not None:
        report = scout_report or {}
        scout_meta.update(
            generated_at=_safe_fact(report.get("generated_at")), read=bool(scout_report)
        )
        for rec in report.get("recommendations") or []:
            if (
                not isinstance(rec, dict)
                or rec.get("component") not in metal.scout_report.components
            ):
                continue
            if rec.get("tier") not in {"adopt", "evaluate"}:
                continue
            names = [_safe_fact(_get(f, "name")) for f in rec.get("findings") or []]
            experiment.append(
                {
                    "component": _safe_fact(rec.get("component")),
                    "tier": _safe_fact(rec.get("tier")),
                    "current": _safe_fact(rec.get("current")),
                    "confidence": _safe_fact(rec.get("confidence")),
                    "candidates": [n for n in names if isinstance(n, str)][:6],
                    "source": "scout",
                }
            )
    stages: dict[str, list[dict[str, Any]]] = {
        "candidate_to_experiment": experiment,
        "candidate_to_deploy": [],
        "deployed": [],
        "rejected": [],
    }
    for trial in metal.trial_records:
        stages[trial.stage].append(
            {
                "model": trial.model,
                "evidence": trial.evidence,
                "source": "trial record",
                "recorded_at": _iso(trial.recorded_at),
                "stale": trial.expires_at <= now,
            }
        )
    for row in serving:
        if row.state is EntitlementState.LIVE and row.facts.get("models"):
            stages["deployed"].append(
                {
                    "endpoint": row.entitlement_id,
                    "host_id": row.hosts[0] if row.hosts else None,
                    "models": row.facts["models"],
                    "source": "serving readback",
                    "observed_at": _iso(row.observed_at),
                }
            )
    probes: dict[str, tuple[bool, list[str]]] = {}
    hardware: list[dict[str, Any]] = []
    for fact in metal.hardware:
        item: dict[str, Any] = {
            "host_id": fact.host_id,
            "device": fact.device,
            "memory_gb": fact.memory_gb,
            "availability": fact.availability,
            "until": fact.until,
            "source": fact.source,
            "recorded_at": _iso(fact.recorded_at),
            "stale": fact.expires_at <= now,
        }
        if fact.enumerate_gpu:
            if gpu_probe is not None and fact.host_id not in probes:
                probes[fact.host_id] = gpu_probe(fact.host_id)
            reachable, gpus = probes.get(fact.host_id, (False, []))
            if any(fact.enumerate_gpu in gpu for gpu in gpus):
                item["availability"] = "enumerated"
                item["readback"] = f"GPU enumerated at {_iso(now)}"
            else:
                item["readback"] = (
                    f"not enumerated at {_iso(now)}"
                    if reachable
                    else "no hardware readback this run; stays as declared"
                )
        hardware.append(item)
    return {
        "dispatch_reads": False,
        "note": "Potential capacity on owned hardware. Planning, procurement and experiment selection "
        "read this face; dispatch never does.",
        "stage_order": ["on_market", "candidate_to_experiment", "candidate_to_deploy", "deployed"],
        "filters": {
            "on_market->candidate_to_experiment": "scout hard constraints: local, hardware fit (memory, host), licence",
            "candidate_to_experiment->candidate_to_deploy": "measured task fit (trial records, purpose floors)",
            "candidate_to_deploy->deployed": "a serving readback on a fleet host",
        },
        "stages": stages,
        "hardware": hardware,
        "scout": scout_meta,
    }


# --- deltas ---------------------------------------------------------------------------------------

_SURFACE_KIND = {
    EntitlementKind.COGNITION: SurfaceKind.MODEL_ROUTE,
    EntitlementKind.GROUNDING: SurfaceKind.MCP_TOOL,
    EntitlementKind.MODALITY: SurfaceKind.MODEL_ROUTE,
    EntitlementKind.LOCAL: SurfaceKind.LOCAL_TOOL,
}
_DELTA_KINDS = frozenset(_SURFACE_KIND)


def _descriptor(
    surface_id: str,
    *,
    descriptor_ref: str,
    kind: EntitlementKind,
    now: datetime,
    pools: Sequence[str],
    money_rail: bool,
    provider: str | None,
) -> CapabilitySurfaceDescriptor:
    return CapabilitySurfaceDescriptor(
        surface_id=surface_id,
        descriptor_ref=descriptor_ref,
        surface_kind=_SURFACE_KIND.get(kind, SurfaceKind.MODEL_ROUTE),
        authority_ceiling=AuthorityCeiling.UNKNOWN,
        observed_at=now,
        stale_after="1h",
        evidence_refs=[f"entitlement-census:{TASK_REF}", "frame/ENTITLEMENT-CENSUS-R2-20260924.md"],
        provider_id=provider,
        resource_pools=list(pools),
        money_rail=money_rail,
    )


def census_surface_deltas(
    config: CensusConfig,
    rows: Sequence[CensusRow],
    registry: Mapping[str, Any],
    *,
    now: datetime,
) -> tuple[list[CapabilitySurfaceDescriptor], list[CapabilitySurfaceDelta]]:
    """Held-but-undeclared, declared-but-dead and misclassified, as existing delta rows.

    Descriptor refs carry no timestamps, so delta ids are stable and the intake never re-mints."""
    by_id = {row.entitlement_id: row for row in rows}
    descriptors: list[CapabilitySurfaceDescriptor] = []
    deltas: list[CapabilitySurfaceDelta] = []

    def emit(
        prior: CapabilitySurfaceDescriptor | None, observed: CapabilitySurfaceDescriptor | None
    ) -> None:
        delta = build_surface_delta(
            prior=prior,
            observed=observed,
            source="entitlement-census",
            detected_by=PRODUCER_REF,
            now=now,
            remediation_ref=TASK_REF,
        )
        if delta is not None:
            descriptors.extend(d for d in (prior, observed) if d is not None)
            deltas.append(delta)

    held = {
        EntitlementState.LIVE,
        EntitlementState.HELD,
        EntitlementState.STALE,
        EntitlementState.TERMS_RESTRICTED,
    }
    gone = {EntitlementState.DEAD, EntitlementState.ABSENT}
    route_backers: dict[str, list[CensusRow]] = {}
    shapes = {
        str(s.get("shape_id")): s for s in _registry_rows(registry, "omitted_capability_shapes")
    }
    for decl in config.entitlements:
        row = by_id.get(decl.entitlement_id)
        if row is None or decl.kind not in _DELTA_KINDS:
            continue
        money = decl.cost_class in {CostClass.PREPAID, CostClass.PAYG}
        if not (row.declared_routes or row.declared_shapes) and row.state in held:
            emit(
                None,
                _descriptor(
                    f"entitlement.{decl.entitlement_id}",
                    descriptor_ref=f"entitlement-census:{decl.entitlement_id}",
                    kind=decl.kind,
                    now=now,
                    pools=[decl.cost_class.value],
                    money_rail=money,
                    provider=decl.provider,
                ),
            )
        for route_id in row.declared_routes:
            route_backers.setdefault(route_id, []).append(row)
        if decl.expected_shape_class:
            for shape_id in row.declared_shapes:
                shape_class = str(shapes.get(shape_id, {}).get("shape_class") or "")
                if shape_class and shape_class != decl.expected_shape_class:
                    emit(
                        _descriptor(
                            shape_id,
                            descriptor_ref=f"platform-capability-registry:{shape_id}",
                            kind=decl.kind,
                            now=now,
                            pools=[shape_class],
                            money_rail=money,
                            provider=decl.provider,
                        ),
                        _descriptor(
                            shape_id,
                            descriptor_ref=f"entitlement-census:{decl.entitlement_id}:{decl.expected_shape_class}",
                            kind=decl.kind,
                            now=now,
                            pools=[decl.expected_shape_class],
                            money_rail=money,
                            provider=decl.provider,
                        ),
                    )
    for route_id, backers in sorted(route_backers.items()):
        if backers and all(b.state in gone for b in backers):
            emit(
                _descriptor(
                    route_id,
                    descriptor_ref=f"platform-capability-registry:{route_id}",
                    kind=backers[0].kind,
                    now=now,
                    pools=[backers[0].cost_class.value],
                    money_rail=backers[0].cost_class in {CostClass.PREPAID, CostClass.PAYG},
                    provider=backers[0].provider,
                ),
                None,
            )
    return descriptors, deltas


def delta_file(run: CensusRun) -> CapabilitySurfaceDeltaFile | None:
    if not run.deltas:
        return None
    unique = {d.surface_id + "|" + d.descriptor_ref: d for d in run.descriptors}
    return CapabilitySurfaceDeltaFile(
        schema_ref=CAPABILITY_SURFACE_DELTA_SCHEMA_REF,
        generated_from=[PRODUCER_REF, f"cc-task:{TASK_REF}"],
        declared_at=run.now,
        descriptors=list(unique.values()),
        deltas=run.deltas,
    )


# --- the run --------------------------------------------------------------------------------------


def run_census(
    config: CensusConfig,
    *,
    now: datetime,
    holdings: Sequence[HostHoldings],
    registry: Mapping[str, Any],
    ledger: Mapping[str, Any] | None,
    prior_view: Mapping[str, Any] | None,
    resolve_secret: Callable[[str], str | None],
    http_get: Callable[[str, dict[str, str], float], HttpResponse],
    read_home_file: Callable[[str], bytes | None],
    scout_report: Mapping[str, Any] | None = None,
    gpu_probe: Callable[[str], tuple[bool, list[str]]] | None = None,
) -> CensusRun:
    secrets = SecretRegister()
    priors = _prior_rows(prior_view)
    held_names = (
        set().union(*(h.credential_names() for h in holdings if h.reachable)) if holdings else set()
    )

    readbacks: dict[tuple[str, str | None], ReadbackResult] = {}
    for decl in config.entitlements:
        # A terms-restricted declaration cannot carry a readback (EntitlementDecl._probe_rules),
        # so it is never probed here: the declaration is the boundary.
        for ref in decl.readbacks:
            key = (ref.readback_id, ref.secret)
            if key in readbacks:
                continue
            if ref.secret not in held_names:
                readbacks[key] = ReadbackResult(
                    readback_id=ref.readback_id,
                    outcome="unobserved",
                    http_status=None,
                    observed_at=now,
                    reason="credential_not_held_on_a_reachable_host",
                )
                continue
            readbacks[key] = run_readback(
                ref, now=now, resolve_secret=resolve_secret, http_get=http_get, secrets=secrets
            )

    caches = {
        decl.vendor_cache: read_vendor_cache(decl.vendor_cache, read_home_file)
        for decl in config.entitlements
        if decl.vendor_cache
    }
    rows = [
        _decl_row(
            decl,
            now=now,
            config=config,
            holdings=holdings,
            readbacks=readbacks,
            cache=caches.get(decl.vendor_cache) if decl.vendor_cache else None,
            registry=registry,
            ledger=ledger,
            prior=priors.get(decl.entitlement_id),
        )
        for decl in config.entitlements
    ]
    serving = [
        _serving_row(
            ep,
            now=now,
            http_get=http_get,
            registry=registry,
            prior=priors.get(f"serving.{ep.endpoint_id}"),
        )
        for ep in config.serving_endpoints
    ]
    unidentified, unclassified = _unidentified_rows(
        config, now=now, holdings=holdings, priors=priors
    )
    all_rows = [*rows, *serving, *unidentified]
    descriptors, deltas = census_surface_deltas(config, rows, registry, now=now)
    measurements: dict[str, dict[str, Any]] = {}
    for row in rows:
        for m in row.measurements:
            measurements.setdefault(m["capacity_id"], m)
    return CensusRun(
        now=now,
        config=config,
        rows=all_rows,
        holdings=list(holdings),
        unclassified=unclassified,
        potential=_potential(
            config, now=now, serving=serving, scout_report=scout_report, gpu_probe=gpu_probe
        ),
        descriptors=descriptors,
        deltas=deltas,
        measurements=list(measurements.values()),
        secrets=secrets,
    )


# --- projection -----------------------------------------------------------------------------------


def _row_view(row: CensusRow) -> dict[str, Any]:
    data = row.model_dump(mode="json")
    # Reins capability-surface pack fields (reins api/reins_read.py::_capability_pack_row).
    data["capability_id"] = row.entitlement_id
    data["status"] = row.state.value
    data["routing_meaning"] = (
        f"{row.recruitment_stage}; {row.cost_class.value}; evidence {row.evidence_class.value}"
    )
    data["blocker"] = "; ".join(row.reasons)
    data["spend_model"] = row.cost_class.value
    data["evidence_refs"] = [f"entitlement-census:{row.entitlement_id}"]
    return data


def render_view(run: CensusRun, *, now: datetime) -> dict[str, Any]:
    states: dict[str, int] = {}
    stages: dict[str, int] = {}
    for row in run.rows:
        states[row.state.value] = states.get(row.state.value, 0) + 1
        stages[row.recruitment_stage] = stages.get(row.recruitment_stage, 0) + 1
    return {
        "schema": VIEW_SCHEMA,
        "pack_id": "entitlement-census",
        "generated_at": _iso(now),
        "producer": PRODUCER_REF,
        "task": TASK_REF,
        "faces": {
            "supply": "rows: held, entitled or authorized capacity with freshness; dispatch-facing",
            "potential": "potential: the funnel for owned hardware; never dispatch-facing",
        },
        "summary": {
            "rows": len(run.rows),
            "by_state": dict(sorted(states.items())),
            "by_recruitment_stage": dict(sorted(stages.items())),
            "deltas": len(run.deltas),
            "measurements": len(run.measurements),
        },
        "hosts": [
            {
                "host_id": h.host_id,
                "reachable": h.reachable,
                "observed_at": _iso(h.observed_at),
                "error": h.error,
                "credential_names": len(h.filestore_names),
                "pass_names": len(h.pass_names),
                "env_names": len(h.env_names),
            }
            for h in run.holdings
        ],
        "rows": [_row_view(row) for row in run.rows],
        "unclassified_names": run.unclassified,
        "potential": run.potential,
        "deltas": [
            {"delta_id": d.delta_id, "surface_id": d.surface_id, "delta_kind": d.delta_kind.value}
            for d in run.deltas
        ],
    }


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "/").replace("\n", " ")


def _quantities(row: Mapping[str, Any]) -> str:
    parts = []
    for m in row.get("measurements") or []:
        reset = f" -> {m['resets_at']}" if m.get("resets_at") else ""
        parts.append(f"{m['capacity_id'].split('.', 1)[-1]} {m['quantity']:g} {m['unit']}{reset}")
    for key in ("plan", "tier", "plan_name", "models"):
        if row.get("facts", {}).get(key):
            parts.append(f"{key} {row['facts'][key]}")
    return "; ".join(parts)


def render_markdown(view: Mapping[str, Any]) -> str:
    lines = [
        "---",
        "type: generated-projection",
        f"generated_at: {view['generated_at']}",
        f"producer: {view['producer']}",
        f"task: {view['task']}",
        "lineage: frame/ENTITLEMENT-CENSUS-20260924.md (R1), frame/ENTITLEMENT-CENSUS-R2-20260924.md (R2, accepted)",
        "---",
        "",
        "# Entitlement census (live projection)",
        "",
        "**Generated. Do not edit.** Regenerated on every producer run. The JSON beside it is",
        "`~/.cache/hapax/entitlement-census/view.json`; quantities go to the quota ledger. A row that is stale",
        "or missing shows as stale or missing: nothing is dropped.",
        "",
        f"Summary: {json.dumps(view['summary']['by_state'])}; recruitment stages "
        f"{json.dumps(view['summary']['by_recruitment_stage'])}; {view['summary']['deltas']} deltas.",
        "Recruitment stage is the routing table's ladder. It is not formal admission.",
        "",
        "## Hosts",
        "",
        "| host | reachable | observed | credential names | pass names | env names | error |",
        "|---|---|---|---|---|---|---|",
    ]
    for h in view["hosts"]:
        lines.append(
            f"| {h['host_id']} | {h['reachable']} | {h['observed_at'] or ''} | {h['credential_names']} | "
            f"{h['pass_names']} | {h['env_names']} | {_cell(h['error'])} |"
        )
    sections = (
        ("Cognition", lambda r: r["kind"] == "cognition" and r["identified"]),
        (
            "Grounding and modality",
            lambda r: r["kind"] in {"grounding", "modality"} and r["identified"],
        ),
        ("Serving endpoints (owned compute)", lambda r: r["kind"] == "local"),
        ("Resources", lambda r: r["kind"] == "resource" and r["identified"]),
        (
            "Unidentified (credential names outside the catalogue, classified by name)",
            lambda r: not r["identified"],
        ),
    )
    for title, keep in sections:
        rows = [r for r in view["rows"] if keep(r)]
        lines += [
            "",
            f"## {title} ({len(rows)})",
            "",
            "| entitlement | state | freshness | stage | cost | evidence · observed | quantities | hosts | declared | ledger | reasons |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for r in rows:
            declared = ", ".join([*r["declared_routes"], *r["declared_shapes"]])
            lines.append(
                f"| {r['entitlement_id']} | {r['state']} | {r['freshness']} | {r['recruitment_stage']} | "
                f"{r['cost_class']} | {r['evidence_class']} · {r['observed_at'] or '—'} | {_cell(_quantities(r))} | "
                f"{', '.join(r['hosts'])} | {_cell(declared)} | {_cell(', '.join(r['ledger']))} | "
                f"{_cell('; '.join(r['reasons']))} |"
            )
    unc = view["unclassified_names"]
    lines += [
        "",
        f"## Unclassified credential names ({unc['count']}; {unc['withheld']} withheld as identity- or money-sensitive)",
        "",
        "Infrastructure credentials the classifier does not treat as capability. Listed, never dropped.",
        "",
        ", ".join(f"`{n['name']}`" for n in unc["names"]) or "none",
        "",
        "## Deltas emitted to the capability-surface intake",
        "",
    ]
    lines += [
        f"- `{d['surface_id']}`: {d['delta_kind']} (`{d['delta_id']}`)" for d in view["deltas"]
    ] or ["- none"]
    pot = view["potential"]
    lines += [
        "",
        "## Potential face: owned metal (dispatch never reads this)",
        "",
        "Stages: "
        + " -> ".join(pot["stage_order"])
        + ". Filters: "
        + "; ".join(f"{k}: {v}" for k, v in pot["filters"].items())
        + ".",
        "",
        "| stage | item | detail | source |",
        "|---|---|---|---|",
    ]
    for stage, items in pot["stages"].items():
        for item in items:
            name = item.get("component") or item.get("model") or item.get("endpoint")
            detail = item.get("candidates") or item.get("models") or item.get("evidence")
            if isinstance(detail, list):
                detail = ", ".join(detail)
            lines.append(
                f"| {stage} | {_cell(name)} | {_cell(detail)} | {_cell(item.get('source'))} |"
            )
    lines += [
        "",
        "| host | device | memory GB | availability | until | readback | stale |",
        "|---|---|---|---|---|---|---|",
    ]
    for hw in pot["hardware"]:
        lines.append(
            f"| {hw['host_id']} | {_cell(hw['device'])} | {hw['memory_gb']:g} | {hw['availability']} | "
            f"{_cell(hw.get('until'))} | {_cell(hw.get('readback'))} | {hw['stale']} |"
        )
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_outputs(
    run: CensusRun,
    *,
    output_root: Path,
    projection_md: Path | None,
    now: datetime,
) -> dict[str, Path]:
    """Render everything, scan everything, and only then write anything."""
    view = render_view(run, now=now)
    rendered: dict[Path, str] = {
        output_root / "view.json": json.dumps(view, indent=2, sort_keys=True) + "\n",
        output_root / "measurements.json": json.dumps(
            {"producer": PRODUCER_REF, "generated_at": _iso(now), "measurements": run.measurements},
            indent=2,
            sort_keys=True,
        )
        + "\n",
    }
    deltas = delta_file(run)
    if deltas is not None:
        rendered[output_root / "surface-deltas.json"] = deltas.model_dump_json(indent=2) + "\n"
    if projection_md is not None:
        rendered[projection_md] = render_markdown(view)
    for path, text in rendered.items():
        run.secrets.require_clean(text, label=path.name)
    for path, text in rendered.items():
        _atomic_write(path, text)
    return {path.name: path for path in rendered}
