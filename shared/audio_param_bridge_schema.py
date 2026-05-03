"""Audio param-bridge schema (cc-task audio-audit-E-runtime-param-bridge Phase 0).

Loads + validates ``config/audio-param-bridge-schema.yaml``. Each entry
declares a LADSPA filter-chain control input that the Phase 1 param-bridge
daemon exposes via HTTP (GET = current, POST = set) and writes back to
PipeWire via ``pw-cli set-param``.

Phase 0 (this module): the schema models, the YAML loader, the lookup
helpers (``get(chain, param)`` + ``list_chains()``), and a pre-validated
"is this value acceptable" check the daemon will call on each POST.
Phase 1 wires the HTTP endpoint, the pw-cli backend, and the JSON
persistence to ``/var/lib/hapax/audio-params.json``.

Why factor it this way:
- The schema is the load-bearing interface between the param-bridge
  daemon and the LADSPA chains. Pinning it standalone with deterministic
  tests means Phase 1 can swap implementations of the daemon (HTTP, MCP
  tool, raw RPC) without touching the schema.
- The "value acceptable" check (``validate_value``) is the safety guard
  on every POST. Making it a pure function pinned by tests means a future
  daemon can never accidentally write an out-of-range value.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

ParamType = Literal["int", "float", "bool"]
"""Currently supported control-input types.

Mirrors ``shared.audio_topology_typed_params.LADSPAParamType``; kept
distinct here because the param-bridge schema is allowed to evolve
independently of the topology schema (e.g., adding "string" for filename
control inputs in Phase 2).
"""


class ParamBridge(BaseModel):
    """One (chain, param) -> typed control endpoint mapping."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chain: str = Field(min_length=1, description="Filter-chain conf basename (no .conf)")
    param: str = Field(min_length=1, description="LADSPA control-input name (verbatim)")
    type: ParamType
    range_min: float | None = Field(
        default=None, description="Inclusive lower bound; None = unbounded"
    )
    range_max: float | None = Field(
        default=None, description="Inclusive upper bound; None = unbounded"
    )
    default: int | float | bool
    description: str = Field(min_length=1, description="Operator-facing description")

    @model_validator(mode="after")
    def _bool_no_range_default_in_range(self) -> ParamBridge:
        """bool params must not declare range fields. All non-bool defaults
        must be in [range_min, range_max]."""
        if self.type == "bool":
            if self.range_min is not None or self.range_max is not None:
                raise ValueError(f"bool param {self.chain}/{self.param}: range_min/max not allowed")
            if not isinstance(self.default, bool):
                raise ValueError(f"bool param {self.chain}/{self.param}: default must be a bool")
            return self

        # Non-bool: range consistency + default-in-range.
        if (
            self.range_min is not None
            and self.range_max is not None
            and self.range_min > self.range_max
        ):
            raise ValueError(
                f"{self.chain}/{self.param}: range_min={self.range_min} > range_max={self.range_max}"
            )
        if isinstance(self.default, bool):
            raise ValueError(
                f"non-bool param {self.chain}/{self.param}: default must be int or float, not bool"
            )
        if self.range_min is not None and self.default < self.range_min:
            raise ValueError(
                f"{self.chain}/{self.param}: default {self.default} below range_min {self.range_min}"
            )
        if self.range_max is not None and self.default > self.range_max:
            raise ValueError(
                f"{self.chain}/{self.param}: default {self.default} above range_max {self.range_max}"
            )
        return self


class ParamBridgeRegistry(BaseModel):
    """Top-level loaded schema YAML."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = Field(ge=1)
    bridges: tuple[ParamBridge, ...]

    @model_validator(mode="after")
    def _no_duplicate_chain_param_pairs(self) -> ParamBridgeRegistry:
        seen: set[tuple[str, str]] = set()
        for entry in self.bridges:
            key = (entry.chain, entry.param)
            if key in seen:
                raise ValueError(
                    f"duplicate (chain, param) entry: ({entry.chain!r}, {entry.param!r})"
                )
            seen.add(key)
        return self

    def get(self, chain: str, param: str) -> ParamBridge | None:
        """Look up a single bridge entry; None if absent."""
        for entry in self.bridges:
            if entry.chain == chain and entry.param == param:
                return entry
        return None

    def list_chains(self) -> tuple[str, ...]:
        """Sorted unique list of chains exposed by the registry."""
        return tuple(sorted({entry.chain for entry in self.bridges}))

    def list_params_for_chain(self, chain: str) -> tuple[str, ...]:
        """Sorted list of param names exposed for ``chain`` (empty if none)."""
        return tuple(sorted(entry.param for entry in self.bridges if entry.chain == chain))


def validate_value(bridge: ParamBridge, value: int | float | bool) -> int | float | bool:
    """Validate that ``value`` is acceptable for ``bridge``.

    Returns the coerced value. Raises ``ValueError`` with an explicit
    "chain/param: rejected Y (range A..B)" message — the kind of error
    the Phase 1 HTTP daemon returns as a 400 to the client.

    Mirrors the audit-E typed-params validator semantics: bool != int,
    range checks inclusive, no silent acceptance.
    """
    if bridge.type == "bool":
        if not isinstance(value, bool):
            raise ValueError(
                f"{bridge.chain}/{bridge.param}: expected bool, got "
                f"{type(value).__name__} ({value!r})"
            )
        return value

    if bridge.type == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                f"{bridge.chain}/{bridge.param}: expected int, got "
                f"{type(value).__name__} ({value!r})"
            )
        coerced: int | float = value
    else:  # float
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(
                f"{bridge.chain}/{bridge.param}: expected float, got "
                f"{type(value).__name__} ({value!r})"
            )
        coerced = float(value)

    if bridge.range_min is not None and coerced < bridge.range_min:
        raise ValueError(
            f"{bridge.chain}/{bridge.param} (range {bridge.range_min}..{bridge.range_max}): "
            f"value {value!r} is below range_min"
        )
    if bridge.range_max is not None and coerced > bridge.range_max:
        raise ValueError(
            f"{bridge.chain}/{bridge.param} (range {bridge.range_min}..{bridge.range_max}): "
            f"value {value!r} is above range_max"
        )
    return coerced


def load_param_bridge_schema(yaml_path: Path) -> ParamBridgeRegistry:
    """Load + validate the schema YAML.

    Raises ``pydantic.ValidationError`` on schema violations,
    ``FileNotFoundError`` on missing path, ``yaml.YAMLError`` on parse
    failure.
    """
    with yaml_path.open() as f:
        raw = yaml.safe_load(f)
    return ParamBridgeRegistry.model_validate(raw)
