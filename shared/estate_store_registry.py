"""Validated, enumeration-only reader for the estate store registry.

Consumers receive declared stores from the passive artifact.  This module does not
discover filesystem paths for them: reality discovery belongs to the drift sweep,
whose output is a finding rather than an implicit source list.
"""

from __future__ import annotations

import fnmatch
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY_PATH = REPO_ROOT / "config" / "estate-store-registry.yaml"
SCHEMA = "hapax.estate-store-registry/v1"
ALLOWED_ACTIONS = frozenset({"flag-only"})
ALLOWED_LIFECYCLES = frozenset({"grandfathered", "registered", "known-gap"})
NAMED_CONSUMERS = frozenset(
    {"assemble", "brief-dispatch", "census", "drift-sweep", "pillar-matcher", "task-intake"}
)


class RegistryError(ValueError):
    """The registry cannot safely serve as an enumeration source."""


@dataclass(frozen=True)
class Store:
    id: str
    writers: tuple[str, ...]
    hosts: tuple[str, ...]
    locator: str
    locator_kind: str
    store_class: str
    action: str
    lifecycle: str
    discovery_evidence: str
    consumers: tuple[str, ...]


@dataclass(frozen=True)
class Registry:
    path: Path
    stage: str
    policy: dict[str, str]
    hosts: dict[str, dict[str, Any]]
    scan_roots: tuple[dict[str, Any], ...]
    stores: tuple[Store, ...]

    def host_id(self, observed: str | None = None) -> str:
        value = (observed or socket.gethostname()).strip().casefold()
        matches = [
            host_id
            for host_id, config in self.hosts.items()
            if value == host_id.casefold()
            or value in {str(alias).casefold() for alias in config.get("aliases", [])}
        ]
        if len(matches) != 1:
            raise RegistryError(
                f"host {value!r} is not uniquely declared in {self.path}; "
                "add its alias and peer binding before running"
            )
        return matches[0]

    def peer(self, host_id: str) -> tuple[str, str]:
        config = self.hosts.get(host_id)
        if config is None:
            raise RegistryError(f"host {host_id!r} is not declared")
        peer_id = str(config.get("peer") or "")
        peer = self.hosts.get(peer_id)
        if peer is None or not peer.get("ssh_target"):
            raise RegistryError(
                f"host {host_id!r} has no machine-checkable peer ssh target; "
                "declare hosts.<peer>.ssh_target before running"
            )
        return peer_id, str(peer["ssh_target"])


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RegistryError(f"{label} must be a mapping")
    return value


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise RegistryError(f"{label} must be a non-empty list of strings")
    return tuple(value)


def load_registry(path: Path = DEFAULT_REGISTRY_PATH) -> Registry:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RegistryError(f"cannot read registry {path}: {exc}") from exc
    root = _mapping(payload, "registry")
    if root.get("schema") != SCHEMA:
        raise RegistryError(f"registry schema must be {SCHEMA!r}")
    if root.get("stage") != "report-only":
        raise RegistryError("Stage 1 registry must declare stage: report-only")

    policy = _mapping(root.get("policy"), "policy")
    if policy.get("unregistered_action") != "flag-only":
        raise RegistryError("Stage 1 unregistered_action must be flag-only")
    if policy.get("vendor_root_action") != "flag-only":
        raise RegistryError("vendor roots are permanently flag-only")

    host_rows = _mapping(root.get("hosts"), "hosts")
    scan_roots = root.get("scan_roots")
    store_rows = root.get("stores")
    if not isinstance(scan_roots, list) or not scan_roots:
        raise RegistryError("scan_roots must be a non-empty list")
    if not isinstance(store_rows, list) or not store_rows:
        raise RegistryError("stores must be a non-empty list")

    stores: list[Store] = []
    seen: set[str] = set()
    for number, raw in enumerate(store_rows, 1):
        row = _mapping(raw, f"stores[{number}]")
        store_id = str(row.get("id") or "")
        if not store_id or store_id in seen:
            raise RegistryError(f"stores[{number}].id is empty or duplicated: {store_id!r}")
        seen.add(store_id)
        action = str(row.get("action") or "")
        lifecycle = str(row.get("lifecycle") or "")
        store_class = str(row.get("class") or "")
        locator = str(row.get("locator") or "")
        locator_kind = str(row.get("locator_kind") or "")
        evidence = str(row.get("discovery_evidence") or "")
        if action not in ALLOWED_ACTIONS:
            raise RegistryError(f"store {store_id!r} has non-reporting action {action!r}")
        if store_class == "vendor-root" and action != "flag-only":
            raise RegistryError(f"vendor root {store_id!r} must remain flag-only")
        if lifecycle not in ALLOWED_LIFECYCLES:
            raise RegistryError(f"store {store_id!r} has invalid lifecycle {lifecycle!r}")
        if lifecycle == "known-gap" and locator != "absent":
            raise RegistryError(f"known gap {store_id!r} must record locator: absent")
        if locator_kind not in {"filesystem", "filesystem-glob", "external", "absent"}:
            raise RegistryError(f"store {store_id!r} has invalid locator_kind {locator_kind!r}")
        if not locator or not evidence or not store_class:
            raise RegistryError(
                f"store {store_id!r} must declare locator, class, and discovery_evidence"
            )
        consumers = _strings(row.get("consumers"), f"store {store_id}.consumers")
        unknown_consumers = set(consumers) - NAMED_CONSUMERS
        if unknown_consumers:
            raise RegistryError(
                f"store {store_id!r} names undeclared consumers: {sorted(unknown_consumers)}"
            )
        stores.append(
            Store(
                id=store_id,
                writers=_strings(row.get("writers"), f"store {store_id}.writers"),
                hosts=_strings(row.get("hosts"), f"store {store_id}.hosts"),
                locator=locator,
                locator_kind=locator_kind,
                store_class=store_class,
                action=action,
                lifecycle=lifecycle,
                discovery_evidence=evidence,
                consumers=consumers,
            )
        )
    return Registry(
        path=path,
        stage=str(root["stage"]),
        policy={str(key): str(value) for key, value in policy.items()},
        hosts={str(key): _mapping(value, f"hosts.{key}") for key, value in host_rows.items()},
        scan_roots=tuple(_mapping(row, "scan root") for row in scan_roots),
        stores=tuple(stores),
    )


def bindings(home: Path) -> dict[str, str]:
    return {"home": str(home), "vault": str(home / "Documents" / "Personal")}


def resolve_locator(locator: str, *, home: Path) -> str:
    try:
        return locator.format_map(bindings(home))
    except KeyError as exc:
        raise RegistryError(f"unknown locator binding {exc.args[0]!r} in {locator!r}") from exc


def enumerate_stores(
    registry: Registry,
    *,
    consumer: str,
    host: str,
    home: Path,
) -> tuple[Store, ...]:
    """Return only declared registry rows; never discover paths from the filesystem."""
    if consumer not in NAMED_CONSUMERS:
        raise RegistryError(f"consumer {consumer!r} is not declared")
    selected = []
    for store in registry.stores:
        if consumer not in store.consumers or host not in store.hosts and "*" not in store.hosts:
            continue
        selected.append(
            Store(
                **{
                    **store.__dict__,
                    "locator": resolve_locator(store.locator, home=home),
                }
            )
        )
    return tuple(selected)


def _glob_matches_path(candidate: str, pattern: str) -> bool:
    """Match a locator glob without allowing ``*`` to cross path components."""
    candidate_parts = Path(candidate).parts
    pattern_parts = Path(pattern).parts
    return len(candidate_parts) == len(pattern_parts) and all(
        fnmatch.fnmatchcase(value, expected)
        for value, expected in zip(candidate_parts, pattern_parts, strict=True)
    )


def matching_store(registry: Registry, path: Path, *, host: str, home: Path) -> Store | None:
    candidate = str(path)
    for store in registry.stores:
        if host not in store.hosts and "*" not in store.hosts:
            continue
        if store.locator_kind not in {"filesystem", "filesystem-glob"}:
            continue
        locator = resolve_locator(store.locator, home=home)
        if (store.locator_kind == "filesystem" and candidate == locator) or (
            store.locator_kind == "filesystem-glob" and _glob_matches_path(candidate, locator)
        ):
            return store
    return None


def store_by_id(registry: Registry, store_id: str) -> Store | None:
    return next((store for store in registry.stores if store.id == store_id), None)


def store_contains_path(store: Store, path: Path, *, home: Path) -> bool:
    """Check an artifact against one declared store boundary."""
    if store.locator_kind == "filesystem":
        root = Path(resolve_locator(store.locator, home=home))
        return path == root or root in path.parents
    if store.locator_kind == "filesystem-glob":
        return _glob_matches_path(str(path), resolve_locator(store.locator, home=home))
    return False
