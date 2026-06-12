"""Template registry + deterministic rotation for no-op canaries.

The repo-side registry (config/failure-taxonomy/noop-canaries.yaml) holds
only decoy TEMPLATES — a pinned healthy target file plus a plausible
complaint. The live (month, tier) -> task_id mapping lives vault-side
(see noop_canary.store), so a lane grepping the repo sees templates but
not which live task is a decoy (partial blindness, accepted + measured).

Template health is the "healthy code" invariant: a template whose pinned
sha256 no longer matches the repo must read probe-error, never green.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

SUPPORTED_SCHEMA_VERSIONS = frozenset({1})
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_REQUIRED_TEMPLATE_FIELDS = (
    "id",
    "target_file",
    "target_sha256",
    "task_id_pattern",
    "title",
    "complaint",
    "authority_case",
    "parent_spec",
    "priority",
)


class RegistryError(ValueError):
    """Raised when the registry file or a lookup argument is invalid."""


@dataclass(frozen=True)
class CanaryTemplate:
    id: str
    target_file: str
    target_sha256: str
    task_id_pattern: str
    title: str
    complaint: str
    authority_case: str
    parent_spec: str
    priority: str


@dataclass(frozen=True)
class TemplateHealth:
    healthy: bool
    reason: str | None = None


@dataclass(frozen=True)
class Registry:
    schema_version: int
    active_since: str
    platform_tiers: tuple[str, ...]
    templates: tuple[CanaryTemplate, ...]


def load_registry(path: Path) -> Registry:
    """Parse and validate the canary template registry."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RegistryError(f"{path}: registry must be a mapping")

    schema_version = raw.get("schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise RegistryError(f"{path}: unsupported schema_version {schema_version!r}")

    active_since = str(raw.get("active_since", ""))
    if not _MONTH_RE.match(active_since):
        raise RegistryError(f"{path}: active_since must be YYYY-MM, got {active_since!r}")

    tiers = raw.get("platform_tiers")
    if not isinstance(tiers, list) or not tiers:
        raise RegistryError(f"{path}: platform_tiers must be a non-empty list")

    raw_templates = raw.get("templates")
    if not isinstance(raw_templates, list) or not raw_templates:
        raise RegistryError(f"{path}: templates must be a non-empty list")

    templates: list[CanaryTemplate] = []
    seen_ids: set[str] = set()
    for idx, entry in enumerate(raw_templates):
        if not isinstance(entry, dict):
            raise RegistryError(f"{path}: templates[{idx}] must be a mapping")
        missing = [f for f in _REQUIRED_TEMPLATE_FIELDS if not str(entry.get(f, "")).strip()]
        if missing:
            raise RegistryError(f"{path}: templates[{idx}] missing fields: {', '.join(missing)}")
        tpl_id = str(entry["id"])
        if tpl_id in seen_ids:
            raise RegistryError(f"{path}: duplicate template id {tpl_id!r}")
        seen_ids.add(tpl_id)
        templates.append(
            CanaryTemplate(**{field: str(entry[field]) for field in _REQUIRED_TEMPLATE_FIELDS})
        )

    return Registry(
        schema_version=int(schema_version),
        active_since=active_since,
        platform_tiers=tuple(str(t) for t in tiers),
        templates=tuple(templates),
    )


def template_health(template: CanaryTemplate, *, repo_root: Path) -> TemplateHealth:
    """Check the healthy-code invariant: pinned sha256 still matches the repo."""
    target = repo_root / template.target_file
    if not target.is_file():
        return TemplateHealth(healthy=False, reason="target_missing")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    if digest != template.target_sha256:
        return TemplateHealth(healthy=False, reason="target_sha_mismatch")
    return TemplateHealth(healthy=True)


def month_index(month: str) -> int:
    """Months since year 0 for YYYY-MM strings (rotation arithmetic)."""
    if not _MONTH_RE.match(month):
        raise RegistryError(f"month must be YYYY-MM, got {month!r}")
    year, mon = month.split("-")
    return int(year) * 12 + (int(mon) - 1)


def select_template(registry: Registry, *, month: str, tier: str) -> CanaryTemplate:
    """Deterministic month x tier rotation over the template list.

    Consecutive months walk the template list; tiers are offset so the
    fleet does not all receive the same decoy in one month. Pure function
    of (registry, month, tier) — no wall-clock, no randomness.
    """
    if tier not in registry.platform_tiers:
        raise RegistryError(f"unknown platform tier {tier!r}")
    offset = month_index(month) - month_index(registry.active_since)
    if offset < 0:
        raise RegistryError(f"month {month!r} predates active_since {registry.active_since!r}")
    tier_offset = registry.platform_tiers.index(tier)
    return registry.templates[(offset + tier_offset) % len(registry.templates)]
