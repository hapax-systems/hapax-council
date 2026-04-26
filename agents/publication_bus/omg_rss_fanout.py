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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from prometheus_client import Counter

log = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH: Path = Path(__file__).resolve().parents[2] / "config" / "omg-lol-fanout.yaml"
"""Repository-relative config path: ``<repo>/config/omg-lol-fanout.yaml``."""

FANOUT_LOOP_HEADER_PREFIX: str = "<!-- X-Hapax-Fanout-Source:"
"""HTML-comment header prepended to fanned-out content. Loop-prevention
checks for this substring in incoming content before re-fanning out."""

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
    return OmgFanoutConfig(addresses=[str(a) for a in addresses])


def fanout(
    *,
    source_address: str,
    entry_id: str,
    content: str,
    config: OmgFanoutConfig,
    client: Any,
) -> dict[str, str]:
    """Fan out one entry to every address in ``config`` other than the source.

    Returns ``{target_address: outcome}`` where outcome is one of:
    ``ok`` (set_entry returned a body), ``error`` (set_entry returned
    None), ``client-disabled`` (the client object is disabled — usually
    because no operator bearer-token is configured). Targets identical
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
    if not targets:
        return {}

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
    "FANOUT_LOOP_HEADER_PREFIX",
    "OmgFanoutConfig",
    "fanout",
    "load_fanout_config",
    "omg_fanouts_total",
]
