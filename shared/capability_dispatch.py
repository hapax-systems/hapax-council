"""Capability dispatch — the friendly one-command surface over the routing spine.

The capability-routing spine works (``evaluate_dispatch_policy`` routes correctly;
several routes are live). What was missing is (1) a human surface — you had to
hand-craft ``hapax-methodology-dispatch`` flags — and (2) the *observability view*:
which of the fleet's capabilities are actually USED vs sitting LATENT ("we are
slower and worse" for not using them).

This module supplies both, the right way *per the spine* — it does NOT write a
parallel ledger. ``hapax-methodology-dispatch`` already persists every dispatch to
``~/.cache/hapax/orchestration/methodology-dispatch.jsonl`` (``write_receipt``) and
emits gate-events. So here we add only the two genuinely-missing pieces:

1. The capability ALIAS layer (capability-difference axiom: each named capability /
   variant is a routable surface). Friendly name -> governed ``route_id``, validated
   against the registry's ``required_route_ids`` (the SSOT) so the table cannot drift.
2. The UTILIZATION view: roll the existing dispatch ledger into active-vs-latent —
   the "latent resource" metric made visible.

cost/quality population (per-route cost from LiteLLM ``_response_cost``, execution-
derived quality from the gate-event/floor-checker) is the measurement-completion
follow-on; this module exposes what the spine already records.

Design: ``~/projects/cost-offload-program/CAPABILITY-ROUTING-DESIGN-2026-06-16.md`` §4;
RESUME ``30-areas/hapax/capability-dispatch-spine-RESUME-2026-06-27.md`` P1.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_REGISTRY_PATH = _REPO_ROOT / "config" / "platform-capability-registry.json"

# The (platform, mode) pairs ``hapax-methodology-dispatch`` can actually spawn a
# lane for — mirroring its ``launchers`` dict. This literal is rechecked at RUNTIME
# against the live ``--list-platform-paths`` by test_launchable_paths_match_live_dispatcher
# (which fails, not silently passes, when the dispatcher is runnable), so drift surfaces.
# Launchability is a (platform, mode) property, NOT platform alone: ``api`` and
# ``local_tool`` ARE valid --platform values but are receipt-only ("no spawnable
# lane"), so they must NOT be shown as launch capacity. A valid-but-non-launchable
# route (api receipt-only, glmcp review seat, local worker) resolves but fails
# CLOSED with a pointer to its real surface rather than pretending.
LAUNCHABLE_PATHS: frozenset[tuple[str, str]] = frozenset(
    {
        ("claude", "headless"),
        ("claude", "interactive"),
        ("codex", "headless"),
        ("vibe", "headless"),
    }
)

# Friendly capability name -> governed route_id. Every value MUST be a real entry
# in the registry's required_route_ids (resolve validates this). Ergonomic aliases
# only; the route_id (``<platform>.<mode>.<profile>``) is the authority.
CAPABILITY_ALIASES: dict[str, str] = {
    "codex": "codex.headless.full",
    "codex-spark": "codex.headless.spark",
    "claude": "claude.headless.full",
    "claude-opus": "claude.headless.opus",
    "claude-sonnet": "claude.headless.sonnet",
    "claude-haiku": "claude.headless.haiku",
    "claude-interactive": "claude.interactive.full",
    "api": "api.headless.provider_gateway",
    "api-frontier": "api.headless.api_frontier",
    "openrouter": "api.headless.openrouter",
    "openrouter-frontier": "api.headless.openrouter",
    "vibe": "vibe.headless.full",
    # valid routes, but reached via a different surface (not a spawnable lane):
    "glmcp-review": "glmcp.review.direct",
    "local-worker": "local_tool.local.worker",
}

# Capabilities the operator names that have NO governed route yet — fail CLOSED
# with the exact follow-on that defines them (never a silent bypass).
UNROUTED_POINTERS: dict[str, str] = {
    "agy": "Antigrav is deprecated/excised; define measured agy supply leaves with route/resource/governance receipts before dispatch.",
    "antigrav": "Antigrav is deprecated/excised; define measured agy supply leaves with route/resource/governance receipts before dispatch.",
    "antigravity": "Antigrav is deprecated/excised; define measured agy supply leaves with route/resource/governance receipts before dispatch.",
    "antigrav.interactive.full": "Antigrav is deprecated/excised; define measured agy supply leaves with route/resource/governance receipts before dispatch.",
    "gemini-cli": "Gemini CLI is retired/excised; define measured agy supply leaves with route/resource/governance receipts before dispatch.",
    "fugu": "no route yet — P2: define codex.headless.fugu (codex -p fugu / Sakana). See RESUME §P2.",
    "fugu-ultra": "no route yet — P2: define codex.headless.fugu_ultra. See RESUME §P2.",
    "gemini": "Gemini/agy is a provider or carrier label, not capability supply; mint measured model/profile/context/tool leaves before dispatch.",
    "sakana": "= fugu (Sakana); no route yet — P2 (codex.headless.fugu) / P4 design. See RESUME.",
    "glmcp": "worker route not minted — P3: glmcp-workhorse-bakeoff must emit promote_to_dispatch_shadow first.",
    "glm": "worker route not minted — P3: glmcp-workhorse-bakeoff (review seat = 'glmcp-review').",
}


def load_valid_route_ids(registry_path: Path | str | None = None) -> frozenset[str]:
    """Return the registry's ``required_route_ids`` (the route SSOT). Empty on error."""
    target = Path(registry_path) if registry_path is not None else DEFAULT_REGISTRY_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    route_ids = data.get("required_route_ids")
    if not isinstance(route_ids, list):
        return frozenset()
    return frozenset(str(r) for r in route_ids)


def registry_error(registry_path: Path | str | None = None) -> str | None:
    """Return a human detail if the registry can't be read as expected, else None.

    Distinguishes a real READ failure (missing file / malformed JSON / missing or
    empty ``required_route_ids``) from a successfully-read registry, so callers can
    name the actual fault instead of collapsing it into "route absent" / "0/0".
    """
    target = Path(registry_path) if registry_path is not None else DEFAULT_REGISTRY_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except OSError as exc:
        return f"registry unreadable: {exc}"
    except ValueError as exc:
        return f"registry malformed JSON: {exc}"
    route_ids = data.get("required_route_ids")
    if not isinstance(route_ids, list):
        return "registry missing required_route_ids list"
    if not route_ids:
        return "registry required_route_ids is empty"
    return None


def split_route_id(route_id: str) -> tuple[str, str, str] | None:
    """``<platform>.<mode>.<profile>`` -> parts, profile keeping any trailing dots."""
    parts = route_id.split(".", 2)
    if len(parts) != 3 or not all(parts):
        return None
    return parts[0], parts[1], parts[2]


@dataclass(frozen=True)
class ResolveResult:
    """Outcome of mapping a capability name to a launchable governed route."""

    capability: str
    ok: bool  # True only when the route is real AND launchable via hapax-methodology-dispatch
    reason: str  # why not, when ok is False (the honest pointer)
    route_id: str | None = None
    platform: str | None = None
    mode: str | None = None
    profile: str | None = None


def resolve_capability(name: str, *, valid_route_ids: Iterable[str] | None = None) -> ResolveResult:
    """Resolve a capability name to a launchable route, the right way per the spine.

    Accepts a friendly alias OR a raw ``route_id``. ``ok`` is True only when the
    route exists in the registry AND its (platform, mode) is a spawnable lane. A
    real-but-non-launchable route (api receipt-only, glmcp review seat, local
    worker) and an entirely un-routed capability (fugu/sakana/glmcp-worker) both
    fail CLOSED with a pointer.
    """
    valid = frozenset(valid_route_ids) if valid_route_ids is not None else load_valid_route_ids()
    key = name.strip().lower()

    route_id = CAPABILITY_ALIASES.get(key, key if key in valid else None)
    if route_id is None:
        if key in UNROUTED_POINTERS:
            return ResolveResult(capability=name, ok=False, reason=UNROUTED_POINTERS[key])
        known = ", ".join(sorted(CAPABILITY_ALIASES))
        return ResolveResult(
            capability=name, ok=False, reason=f"unknown capability '{name}'. known: {known}"
        )

    if route_id not in valid:
        return ResolveResult(
            capability=name,
            ok=False,
            reason=f"alias maps to '{route_id}', which is not in the registry's required_route_ids",
            route_id=route_id,
        )

    parts = split_route_id(route_id)
    if parts is None:
        return ResolveResult(
            capability=name, ok=False, reason=f"malformed route_id '{route_id}'", route_id=route_id
        )
    platform, mode, profile = parts
    if (platform, mode) not in LAUNCHABLE_PATHS:
        return ResolveResult(
            capability=name,
            ok=False,
            reason=(
                f"route '{route_id}' exists but ({platform},{mode}) is not a spawnable lane; "
                "it is receipt-only or reached via its own surface (review plane / local alias), "
                "not cc-dispatch"
            ),
            route_id=route_id,
            platform=platform,
            mode=mode,
            profile=profile,
        )
    return ResolveResult(
        capability=name,
        ok=True,
        reason="",
        route_id=route_id,
        platform=platform,
        mode=mode,
        profile=profile,
    )


def launchable_aliases(valid_route_ids: Iterable[str] | None = None) -> dict[str, str]:
    """The alias->route_id map restricted to routes cc-dispatch can actually spawn."""
    valid = frozenset(valid_route_ids) if valid_route_ids is not None else load_valid_route_ids()
    out: dict[str, str] = {}
    for alias, route_id in CAPABILITY_ALIASES.items():
        parts = split_route_id(route_id)
        if route_id in valid and parts is not None and (parts[0], parts[1]) in LAUNCHABLE_PATHS:
            out[alias] = route_id
    return out


# --- the dispatch ledger the spine already writes (we READ it, never duplicate) ---


def default_dispatch_ledger() -> Path:
    """``methodology-dispatch.jsonl`` in the orchestration ledger dir (NOT tmpfs).

    Mirrors ``hapax-methodology-dispatch.orchestration_ledger_dir()`` so the reader
    and the writer agree without importing the script.
    """
    base = os.environ.get(
        "HAPAX_ORCHESTRATION_LEDGER_DIR", str(Path.home() / ".cache" / "hapax" / "orchestration")
    )
    return Path(base) / "methodology-dispatch.jsonl"


def read_dispatch_ledger(path: Path | str | None = None) -> Iterator[dict]:
    """Yield dispatch records from the spine's ledger; skip blank/corrupt lines.

    Degrades to empty on ANY read failure (missing / a directory / unreadable /
    disappears mid-read) — a bad ledger path must never crash ``--utilization``;
    it must yield no history. (``OSError`` covers FileNotFound/IsADirectory/Permission.)
    """
    target = Path(path) if path is not None else default_dispatch_ledger()
    try:
        with target.open(encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    yield obj
    except OSError:
        return


def ledger_health(path: Path | str | None = None) -> tuple[bool, int]:
    """``(exists, corrupt_row_count)`` for the dispatch ledger.

    Lets callers WARN that a LATENT scorecard reflects MISSING or DAMAGED evidence
    (no ledger / corrupt rows) rather than verified non-use — ``read_dispatch_ledger``
    silently skips both, which would otherwise hide bad observability input.
    """
    target = Path(path) if path is not None else default_dispatch_ledger()
    if not target.exists():
        return (False, 0)
    try:
        corrupt = 0
        with target.open(encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    json.loads(line)
                except ValueError:
                    corrupt += 1
        return (True, corrupt)
    except OSError:
        return (False, 0)  # exists but unreadable (dir/permission) -> treat as absent, warn


def record_route_id(record: dict) -> str | None:
    """Reconstruct ``<platform>.<mode>.<profile>`` from a ledger record, if present."""
    platform, mode, profile = record.get("platform"), record.get("mode"), record.get("profile")
    if platform and mode and profile:
        return f"{platform}.{mode}.{profile}"
    return None


@dataclass(frozen=True)
class CapabilityUtilization:
    """The 'latent resource' scorecard: which launchable capabilities are used vs idle."""

    known: list[str]  # launchable route_ids cc-dispatch can drive
    active: list[str]  # known routes with >=1 launched dispatch in the ledger
    latent: list[str]  # known routes never launched (the unused resources)
    counts: dict[str, int] = field(default_factory=dict)  # route_id -> launched dispatch count
    alias_for: dict[str, str] = field(default_factory=dict)  # route_id -> primary friendly alias


def _primary_alias_by_route() -> dict[str, str]:
    """route_id -> the first friendly alias declared for it (stable display name)."""
    out: dict[str, str] = {}
    for alias, route_id in CAPABILITY_ALIASES.items():
        out.setdefault(route_id, alias)
    return out


def utilization(
    records: Iterable[dict],
    *,
    valid_route_ids: Iterable[str] | None = None,
    launched_only: bool = True,
) -> CapabilityUtilization:
    """Roll the spine's dispatch ledger into the active-vs-latent capability scorecard.

    ``known`` = the launchable routes (the ones cc-dispatch can drive). ``active`` =
    those with at least one (launched, by default) dispatch in the ledger; ``latent``
    = launchable routes never used. ``counts`` tallies every observed route_id,
    including ones outside the launchable set (surfaces drift / ad-hoc dispatch).
    """
    known = sorted(set(launchable_aliases(valid_route_ids).values()))
    counts: dict[str, int] = {}
    for rec in records:
        if launched_only and not rec.get("launched"):
            continue
        route_id = record_route_id(rec)
        if route_id is None:
            continue
        counts[route_id] = counts.get(route_id, 0) + 1
    active = [r for r in known if counts.get(r, 0) > 0]
    latent = [r for r in known if counts.get(r, 0) == 0]
    alias_for = {r: a for r, a in _primary_alias_by_route().items() if r in known}
    return CapabilityUtilization(
        known=known, active=active, latent=latent, counts=counts, alias_for=alias_for
    )
