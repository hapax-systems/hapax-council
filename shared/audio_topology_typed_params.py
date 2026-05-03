"""Typed LADSPA parameter validation (cc-task audio-audit-E-topology-schema-v3 Phase 0).

Audit Finding #4 (WET_PATH_USB_BIAS_MUSIC_DB=27 silently rejected by LADSPA)
was caused by untyped envvars feeding LADSPA control inputs. The value sat
in audio-topology.yaml as a string-keyed dict entry, and PipeWire
filter-chain silently dropped the out-of-range value at LADSPA-load time.
Auditor E's fix: type each param with a declared range so the rejection
happens at parse time (Pydantic ValidationError) instead of at runtime
(silent LADSPA reject).

Phase 0 (this module): the typed-param schema + validator. Phase 1 wires
``params: list[LADSPAParamSpec]`` into ``shared/audio_topology.Node`` and
swaps the existing untyped ``dict[str, str|int|float|bool]`` for the
validated form.

Why factor it this way:
- The schema is small enough to pin standalone with deterministic tests;
  Phase 1 then only has to swap the field type on Node, not redesign the
  validation rules.
- The existing Node typed chain params (chain_kind, release_s, …) demonstrate
  that schema v3 evolution is incremental — this PR continues the
  ``schema v3 = typed`` arc.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

LADSPAParamType = Literal["int", "float", "bool"]
"""Currently supported LADSPA control-input types.

LADSPA actually models ports as ``LADSPA_PortDescriptor`` with hint flags
(integer, toggled, sample-rate-relative, …). Phase 1 maps these three
Python-side types onto the LADSPA hint set:
- ``"int"``    -> ``LADSPA_HINT_INTEGER``
- ``"float"``  -> default (real-valued)
- ``"bool"``   -> ``LADSPA_HINT_TOGGLED``
"""


class LADSPAParamSpec(BaseModel):
    """Declared shape of a single LADSPA control-input parameter.

    Carried inside a ``Node``'s ``params`` list at schema v3+. Replaces the
    schema-v2 untyped ``dict[str, str|int|float|bool]`` form which let
    out-of-range values slip past Pydantic and only fail (silently) at
    LADSPA load time.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, description="LADSPA control-input name (e.g. 'Limit (dB)')")
    type: LADSPAParamType
    range_min: float | None = Field(
        default=None,
        description="Inclusive lower bound; None = unbounded. Type bool ignores this.",
    )
    range_max: float | None = Field(
        default=None,
        description="Inclusive upper bound; None = unbounded. Type bool ignores this.",
    )
    default: int | float | bool

    @field_validator("name")
    @classmethod
    def _name_no_internal_whitespace_collapse(cls, v: str) -> str:
        # LADSPA names are user-facing strings (e.g. "Limit (dB)") and
        # whitespace is significant. Reject leading/trailing whitespace
        # which is almost always a YAML editing accident.
        if v != v.strip():
            raise ValueError(f"name must not have leading/trailing whitespace: {v!r}")
        return v

    @model_validator(mode="after")
    def _validate_range_consistency(self) -> LADSPAParamSpec:
        if self.type == "bool":
            # Range fields are meaningless for bool; reject them rather than
            # silently ignoring (which audit finding #4 taught us not to do).
            if self.range_min is not None or self.range_max is not None:
                raise ValueError(f"bool param {self.name!r} must not declare range_min/range_max")
        else:
            if (
                self.range_min is not None
                and self.range_max is not None
                and self.range_min > self.range_max
            ):
                raise ValueError(
                    f"param {self.name!r}: range_min={self.range_min} > range_max={self.range_max}"
                )
        # Default must be in-range and the right type.
        validate_param_value(self, self.default)
        return self


def validate_param_value(spec: LADSPAParamSpec, value: Any) -> int | float | bool:
    """Validate + coerce ``value`` against ``spec``.

    Returns the coerced value. Raises ``ValueError`` with an explicit
    "param X (range A..B): rejected Y" message — the kind of error the
    audit-E acceptance criterion calls for. Phase 1's loader passes the
    YAML file path / line number through the wrapping pydantic
    ValidationError so users can locate the offending entry.
    """
    if spec.type == "bool":
        if not isinstance(value, bool):
            raise ValueError(
                f"param {spec.name!r}: expected bool, got {type(value).__name__} ({value!r})"
            )
        return value

    if spec.type == "int":
        # Reject bool here; in Python, bool is a subclass of int and would
        # otherwise sneak through. Audit #4 cared about silent acceptance.
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                f"param {spec.name!r}: expected int, got {type(value).__name__} ({value!r})"
            )
        coerced: int | float = value
    else:  # float
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(
                f"param {spec.name!r}: expected float, got {type(value).__name__} ({value!r})"
            )
        coerced = float(value)

    if spec.range_min is not None and coerced < spec.range_min:
        raise ValueError(
            f"param {spec.name!r} (range {spec.range_min}..{spec.range_max}): "
            f"value {value!r} is below range_min"
        )
    if spec.range_max is not None and coerced > spec.range_max:
        raise ValueError(
            f"param {spec.name!r} (range {spec.range_min}..{spec.range_max}): "
            f"value {value!r} is above range_max"
        )

    return coerced
