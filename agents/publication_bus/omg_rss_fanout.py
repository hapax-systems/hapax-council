"""omg.lol cross-weblog Bearer fanout — Phase 1.

Per cc-task ``pub-bus-omg-lol-rss-fanout``. Fans out a single weblog
entry across multiple operator-owned omg.lol addresses (hapax,
oudepode, …) via the omg.lol Bearer-token API. Each target gets the
same content prefixed with a loop-prevention header so re-runs (or
fanouts of fanouts) don't loop.

Drop 5 §3 mechanic #3. Constitutional fit:

- **Full-automation:** uses the existing :class:`shared.omg_lol_client.OmgLolClient`
  (no new auth surface).
- **Single-operator:** all target addresses are operator-owned per the
  ``single_user`` axiom.
- **Refusal-as-data:** when the omg-lol client is disabled (no operator
  bearer-token), the fanout records ``client-disabled`` per target —
  visible on the metric and downstream observability.

Phase 1 ships the fanout function + config loader + tests + the bare
``config/omg-lol-fanout.yaml`` (operator fills in addresses post-bootstrap).
Phase 2 will wire the chronicle-event listener that drives fanout
on every weblog publish.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml
from prometheus_client import Counter

from shared.public_gate_receipts import (
    PUBLIC_GATE_RECEIPT_PREFIXES as _PUBLIC_GATE_RECEIPT_PREFIXES,
)
from shared.public_gate_receipts import public_gate_receipt_value_present

log = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH: Path = Path(__file__).resolve().parents[2] / "config" / "omg-lol-fanout.yaml"
"""Repository-relative config path: ``<repo>/config/omg-lol-fanout.yaml``."""

FANOUT_LOOP_HEADER_PREFIX: str = "<!-- X-Hapax-Fanout-Source:"
"""HTML-comment header prepended to fanned-out content. Loop-prevention
checks for this substring in incoming content before re-fanning out."""

FANOUT_REQUIRED_GATES: tuple[str, ...] = (
    "source_artifact_public_safe",
    "source_refs_present",
    "rights_privacy_redaction_pass",
    "target_surface_allowlist_pass",
    "fanout_loop_prevention_present",
    "claim_review_current",
    "no_direct_public_egress",
)
FANOUT_ALLOWED_GATE_IDS = frozenset(FANOUT_REQUIRED_GATES)
"""Receipt ids required before any cross-weblog public fanout egress."""

PUBLIC_GATE_RECEIPT_PREFIXES = _PUBLIC_GATE_RECEIPT_PREFIXES
"""Durable public-gate receipt ref prefixes accepted for fanout egress."""

PUBLIC_GATE_RECEIPT_ROOTS: tuple[Path, ...] = (
    Path.home() / ".cache" / "hapax" / "relay" / "receipts",
    Path(__file__).resolve().parents[2] / "docs" / "research" / "evidence",
)

OMG_LOL_ADDRESS_RE = re.compile(r"\A[a-z0-9][a-z0-9-]{0,62}\Z")
"""Conservative omg.lol address segment accepted before public fanout egress."""

omg_fanouts_total = Counter(
    "hapax_publication_bus_omg_fanouts_total",
    "omg.lol cross-weblog fanout outcomes per source + target + result.",
    ["source", "target", "result"],
)


@dataclass
class OmgFanoutConfig:
    """Acyclic fanout graph: every address fans out to every other.

    The cc-task spec calls for an "address graph (acyclic)"; Phase 1
    treats this as a complete graph (every-to-every), with
    loop-prevention via the embedded source header rather than a
    runtime topology check. Phase 2 may add per-edge overrides
    (e.g., hapax → oudepode but not hapax → third) if the operator
    needs finer routing.
    """

    addresses: list[str] = field(default_factory=list)
    required_gates: list[str] = field(default_factory=lambda: list(FANOUT_REQUIRED_GATES))
    gate_policy_error: str | None = None


def load_fanout_config(*, path: Path = DEFAULT_CONFIG_PATH) -> OmgFanoutConfig:
    """Load the fanout config from YAML; return empty config when absent."""
    if not path.exists():
        return OmgFanoutConfig()
    raw = yaml.safe_load(path.read_text()) or {}
    if not isinstance(raw, dict):
        return OmgFanoutConfig()
    addresses = raw.get("addresses", [])
    if not isinstance(addresses, list):
        addresses = []
        address_policy_error = (
            "fanout config addresses must be a list; next action: restore a list of "
            "operator-owned omg.lol address ids before public fanout"
        )
    else:
        addresses, address_policy_error = _configured_addresses(addresses)
    required_gates, gate_policy_error = _configured_required_gates(
        raw.get("publication_frontmatter_policy")
    )
    return OmgFanoutConfig(
        addresses=addresses,
        required_gates=required_gates,
        gate_policy_error=_join_policy_errors(address_policy_error, gate_policy_error),
    )


def _join_policy_errors(*errors: str | None) -> str | None:
    present = [error for error in errors if error]
    return "; ".join(present) if present else None


def _safe_omg_lol_address(value: object) -> bool:
    return isinstance(value, str) and OMG_LOL_ADDRESS_RE.fullmatch(value.strip()) is not None


def _duplicate_values(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        else:
            seen.add(value)
    return sorted(duplicates)


def _configured_addresses(values: Sequence[object]) -> tuple[list[str], str | None]:
    addresses: list[str] = []
    malformed = []
    for value in values:
        if _safe_omg_lol_address(value):
            addresses.append(str(value).strip())
        else:
            malformed.append(repr(value))
    errors: list[str] = []
    if malformed:
        errors.append(
            "fanout config addresses contains malformed address ids: "
            + ", ".join(sorted(malformed))
            + "; next action: use lowercase omg.lol address path segments only"
        )
    duplicates = _duplicate_values(addresses)
    if duplicates:
        errors.append(
            "fanout config addresses contains duplicate address ids: "
            + ", ".join(duplicates)
            + "; next action: list each target address once before public fanout"
        )
    return addresses, _join_policy_errors(*errors)


def _configured_required_gates(policy: object) -> tuple[list[str], str | None]:
    baseline = list(FANOUT_REQUIRED_GATES)
    if not isinstance(policy, dict):
        return baseline, (
            "fanout config missing publication_frontmatter_policy; next action: restore "
            "required publication gate policy before public fanout"
        )

    configured = policy.get("required_gates")
    if not isinstance(configured, list) or not configured:
        return baseline, (
            "fanout config publication_frontmatter_policy.required_gates must be a "
            "non-empty list; next action: restore the full required gate list before "
            "public fanout"
        )

    normalized: list[str] = []
    malformed = False
    for gate in configured:
        if not isinstance(gate, str) or not gate.strip():
            malformed = True
            continue
        normalized.append(gate.strip())

    required = list(dict.fromkeys([*baseline, *normalized]))
    if malformed:
        return required, (
            "fanout config required_gates contains blank or non-string gate ids; "
            "next action: remove malformed gate ids before public fanout"
        )

    missing = sorted(set(FANOUT_REQUIRED_GATES) - set(normalized))
    if missing:
        return required, (
            "fanout config required_gates missing required gate ids: "
            + ", ".join(missing)
            + "; next action: restore every FANOUT_REQUIRED_GATES id before public fanout"
        )

    unknown = sorted(set(normalized) - FANOUT_ALLOWED_GATE_IDS)
    if unknown:
        return required, (
            "fanout config required_gates contains unknown gate ids: "
            + ", ".join(unknown)
            + "; next action: use only FANOUT_REQUIRED_GATES ids before public fanout"
        )

    return required, None


def _receipt_value_present(
    gate: str,
    value: object,
    *,
    bindings: Mapping[str, object] | None = None,
) -> bool:
    return public_gate_receipt_value_present(
        value,
        expected_gate=gate,
        roots=PUBLIC_GATE_RECEIPT_ROOTS,
        bindings=bindings,
    )


def _missing_gate_receipts(
    required_gates: Sequence[str],
    gate_receipts: Mapping[str, object] | None,
    *,
    bindings: Mapping[str, object] | None = None,
) -> list[str]:
    receipts = gate_receipts or {}
    return sorted(
        gate
        for gate in required_gates
        if not _receipt_value_present(gate, receipts.get(gate), bindings=bindings)
    )


def _effective_required_gates(config: OmgFanoutConfig) -> tuple[list[str], str | None]:
    malformed = False
    configured: list[str] = []
    for gate in config.required_gates:
        if not isinstance(gate, str) or not gate.strip():
            malformed = True
            continue
        configured.append(gate.strip())

    required = list(dict.fromkeys([*FANOUT_REQUIRED_GATES, *configured]))
    if malformed:
        return required, (
            "fanout config required_gates contains blank or non-string gate ids; "
            "next action: remove malformed gate ids before public fanout"
        )
    unknown = sorted(set(configured) - FANOUT_ALLOWED_GATE_IDS)
    if unknown:
        return required, (
            "fanout config required_gates contains unknown gate ids: "
            + ", ".join(unknown)
            + "; next action: use only FANOUT_REQUIRED_GATES ids before public fanout"
        )
    return required, None


def _fanout_address_policy_error(*, source_address: str, targets: Sequence[str]) -> str | None:
    errors: list[str] = []
    if not _safe_omg_lol_address(source_address):
        errors.append(
            "fanout source_address is malformed; next action: use a lowercase omg.lol "
            "address path segment before public fanout"
        )
    malformed_targets = [target for target in targets if not _safe_omg_lol_address(target)]
    if malformed_targets:
        errors.append(
            "fanout target addresses contain malformed address ids: "
            + ", ".join(sorted(malformed_targets))
            + "; next action: use lowercase omg.lol address path segments only"
        )
    duplicate_targets = _duplicate_values(list(targets))
    if duplicate_targets:
        errors.append(
            "fanout target addresses contain duplicate address ids: "
            + ", ".join(duplicate_targets)
            + "; next action: list each target address once before public fanout"
        )
    return _join_policy_errors(*errors)


def _fanout_receipt_bindings(
    *,
    source_address: str,
    entry_id: str,
    content: str,
    targets: Sequence[str],
) -> dict[str, object]:
    return {
        "source_address": source_address,
        "entry_id": entry_id,
        "content_sha256": sha256(content.encode("utf-8")).hexdigest(),
        "target_addresses": tuple(sorted(targets)),
    }


def fanout(
    *,
    source_address: str,
    entry_id: str,
    content: str,
    config: OmgFanoutConfig,
    client: Any,
    gate_receipts: Mapping[str, object] | None = None,
) -> dict[str, str]:
    """Fan out one entry to every address in ``config`` other than the source.

    Returns ``{target_address: outcome}`` where outcome is one of:
    ``ok`` (set_entry returned a body), ``error`` (set_entry returned
    None), ``client-disabled`` (the client object is disabled — usually
    because no operator bearer-token is configured), ``gate-policy-blocked``
    (configured gate policy is unavailable or malformed), or ``gate-blocked``
    (required gate receipts are missing or invalid). Targets identical
    to ``source_address`` are skipped.

    Loop-prevention: when ``content`` already contains
    :data:`FANOUT_LOOP_HEADER_PREFIX`, the fanout is a no-op (returns
    empty dict). This catches re-fanouts from a peer-driven flow and
    prevents A→B→A loops without requiring graph-topology validation.
    """
    if FANOUT_LOOP_HEADER_PREFIX in content:
        log.debug("fanout skipped — loop-prevention header detected")
        return {}

    targets = [addr for addr in config.addresses if addr != source_address]
    required_gates, boundary_gate_policy_error = _effective_required_gates(config)
    address_policy_error = _fanout_address_policy_error(
        source_address=source_address,
        targets=targets,
    )
    gate_policy_error = _join_policy_errors(
        config.gate_policy_error,
        boundary_gate_policy_error,
        address_policy_error,
    )
    if gate_policy_error:
        log.error("fanout blocked before public egress; %s", gate_policy_error)
        for target in targets:
            omg_fanouts_total.labels(
                source=source_address, target=target, result="gate-policy-blocked"
            ).inc()
        return {target: "gate-policy-blocked" for target in targets}

    if not targets:
        return {}

    receipt_bindings = _fanout_receipt_bindings(
        source_address=source_address,
        entry_id=entry_id,
        content=content,
        targets=targets,
    )
    missing_receipts = _missing_gate_receipts(
        required_gates,
        gate_receipts,
        bindings=receipt_bindings,
    )
    if missing_receipts:
        missing_text = ", ".join(missing_receipts)
        log.error(
            "fanout blocked before public egress; missing or invalid publication gate "
            "receipts: %s; next action: record durable public-gate receipt refs before "
            "fanout",
            missing_text,
        )
        for target in targets:
            omg_fanouts_total.labels(
                source=source_address, target=target, result="gate-blocked"
            ).inc()
        return {target: "gate-blocked" for target in targets}

    body = f"{FANOUT_LOOP_HEADER_PREFIX} {source_address} -->\n{content}"
    outcomes: dict[str, str] = {}

    if not getattr(client, "enabled", True):
        for target in targets:
            outcomes[target] = "client-disabled"
            omg_fanouts_total.labels(
                source=source_address, target=target, result="client-disabled"
            ).inc()
        return outcomes

    for target in targets:
        result = client.set_entry(target, entry_id, content=body)
        outcome = "ok" if result is not None else "error"
        outcomes[target] = outcome
        omg_fanouts_total.labels(source=source_address, target=target, result=outcome).inc()

    return outcomes


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "FANOUT_REQUIRED_GATES",
    "FANOUT_LOOP_HEADER_PREFIX",
    "OmgFanoutConfig",
    "fanout",
    "load_fanout_config",
    "omg_fanouts_total",
]
