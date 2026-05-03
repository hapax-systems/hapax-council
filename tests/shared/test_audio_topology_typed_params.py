"""Tests for shared.audio_topology_typed_params (cc-task audio-audit-E Phase 0).

Pin the typed-param schema + the audit-acceptance regression: an out-of-range
value (the WET_PATH_USB_BIAS_MUSIC_DB=27 case from finding #4) MUST fail at
parse time with an explicit error pointing at the param + range.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.audio_topology_typed_params import (
    LADSPAParamSpec,
    validate_param_value,
)


class TestSchemaShape:
    def test_minimal_float_spec_constructs(self) -> None:
        spec = LADSPAParamSpec(name="Limit (dB)", type="float", default=0.0)
        assert spec.name == "Limit (dB)"
        assert spec.type == "float"
        assert spec.default == 0.0

    def test_full_spec_with_ranges(self) -> None:
        spec = LADSPAParamSpec(
            name="Input gain (dB)",
            type="float",
            range_min=-30.0,
            range_max=20.0,
            default=0.0,
        )
        assert spec.range_min == -30.0
        assert spec.range_max == 20.0

    def test_int_spec(self) -> None:
        spec = LADSPAParamSpec(
            name="Channel count", type="int", range_min=1, range_max=8, default=2
        )
        assert spec.type == "int"
        assert spec.default == 2

    def test_bool_spec(self) -> None:
        spec = LADSPAParamSpec(name="Enable", type="bool", default=True)
        assert spec.type == "bool"
        assert spec.default is True

    def test_unknown_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LADSPAParamSpec(name="x", type="string", default="hi")  # type: ignore[arg-type]

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            LADSPAParamSpec(name="x", type="float", default=0.0, foo="bar")  # type: ignore[call-arg]

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LADSPAParamSpec(name="", type="float", default=0.0)

    def test_leading_trailing_whitespace_rejected(self) -> None:
        """Likely a YAML editing accident; fail loudly per audit #4 spirit."""
        with pytest.raises(ValidationError, match="whitespace"):
            LADSPAParamSpec(name=" Input gain ", type="float", default=0.0)

    def test_inverted_range_rejected(self) -> None:
        with pytest.raises(ValidationError, match="range_min"):
            LADSPAParamSpec(name="x", type="float", range_min=10.0, range_max=-10.0, default=0.0)

    def test_bool_with_range_rejected(self) -> None:
        """Range on a bool is silent garbage today; reject it explicitly."""
        with pytest.raises(ValidationError, match="bool param"):
            LADSPAParamSpec(name="Enable", type="bool", range_min=0, default=True)

    def test_default_in_range_required(self) -> None:
        with pytest.raises(ValidationError, match="above range_max"):
            LADSPAParamSpec(
                name="Limit (dB)", type="float", range_min=-30.0, range_max=0.0, default=10.0
            )

    def test_default_below_range_min_rejected(self) -> None:
        with pytest.raises(ValidationError, match="below range_min"):
            LADSPAParamSpec(
                name="Threshold", type="float", range_min=0.0, range_max=10.0, default=-5.0
            )


class TestValidateParamValue:
    """The hot-path validator the Phase 1 loader will call per YAML entry."""

    def test_in_range_float_passes(self) -> None:
        spec = LADSPAParamSpec(
            name="Limit (dB)", type="float", range_min=-30.0, range_max=0.0, default=-1.5
        )
        assert validate_param_value(spec, -2.0) == -2.0

    def test_at_range_min_inclusive(self) -> None:
        spec = LADSPAParamSpec(name="x", type="float", range_min=-30.0, range_max=0.0, default=-1.0)
        assert validate_param_value(spec, -30.0) == -30.0

    def test_at_range_max_inclusive(self) -> None:
        spec = LADSPAParamSpec(name="x", type="float", range_min=-30.0, range_max=0.0, default=-1.0)
        assert validate_param_value(spec, 0.0) == 0.0

    def test_int_coerced_to_float(self) -> None:
        spec = LADSPAParamSpec(name="x", type="float", range_min=-30.0, range_max=0.0, default=-1.0)
        result = validate_param_value(spec, -5)
        assert result == -5.0
        assert isinstance(result, float)

    def test_above_range_rejected_explicit_message(self) -> None:
        """Audit acceptance: out-of-range fails with explicit error pointing
        at the param. This is the WET_PATH_USB_BIAS_MUSIC_DB=27 regression
        pin from finding #4."""
        spec = LADSPAParamSpec(
            name="WET_PATH_USB_BIAS_MUSIC_DB",
            type="float",
            range_min=-12.0,
            range_max=12.0,
            default=0.0,
        )
        with pytest.raises(ValueError) as exc:
            validate_param_value(spec, 27.0)
        msg = str(exc.value)
        assert "WET_PATH_USB_BIAS_MUSIC_DB" in msg
        assert "above range_max" in msg
        assert "27" in msg

    def test_below_range_rejected(self) -> None:
        spec = LADSPAParamSpec(name="x", type="float", range_min=0.0, range_max=10.0, default=5.0)
        with pytest.raises(ValueError, match="below range_min"):
            validate_param_value(spec, -1.0)

    def test_unbounded_min_passes_arbitrary_low(self) -> None:
        spec = LADSPAParamSpec(name="x", type="float", range_max=0.0, default=-1.0)
        assert validate_param_value(spec, -1e9) == -1e9

    def test_unbounded_max_passes_arbitrary_high(self) -> None:
        spec = LADSPAParamSpec(name="x", type="float", range_min=0.0, default=1.0)
        assert validate_param_value(spec, 1e9) == 1e9

    def test_int_type_rejects_float(self) -> None:
        spec = LADSPAParamSpec(name="x", type="int", default=2)
        with pytest.raises(ValueError, match="expected int"):
            validate_param_value(spec, 2.5)

    def test_int_type_rejects_bool(self) -> None:
        """Python bool is an int subclass; would silently pass without the
        explicit check. Audit #4: silent acceptance is the bug."""
        spec = LADSPAParamSpec(name="x", type="int", default=2)
        with pytest.raises(ValueError, match="expected int"):
            validate_param_value(spec, True)

    def test_float_type_rejects_bool(self) -> None:
        spec = LADSPAParamSpec(name="x", type="float", default=0.0)
        with pytest.raises(ValueError, match="expected float"):
            validate_param_value(spec, True)

    def test_float_type_rejects_string(self) -> None:
        spec = LADSPAParamSpec(name="x", type="float", default=0.0)
        with pytest.raises(ValueError, match="expected float"):
            validate_param_value(spec, "27")

    def test_bool_type_accepts_bool(self) -> None:
        spec = LADSPAParamSpec(name="Enable", type="bool", default=False)
        assert validate_param_value(spec, True) is True
        assert validate_param_value(spec, False) is False

    def test_bool_type_rejects_int(self) -> None:
        spec = LADSPAParamSpec(name="Enable", type="bool", default=False)
        with pytest.raises(ValueError, match="expected bool"):
            validate_param_value(spec, 1)


class TestAuditFinding4Regression:
    """Pin the exact failure mode that motivated this cc-task."""

    def test_wet_path_usb_bias_music_db_27_fails_at_parse_not_load(self) -> None:
        spec = LADSPAParamSpec(
            name="WET_PATH_USB_BIAS_MUSIC_DB",
            type="float",
            range_min=-12.0,
            range_max=12.0,
            default=0.0,
        )
        with pytest.raises(ValueError) as exc:
            validate_param_value(spec, 27.0)
        # Error message must carry: param name, range, offending value
        msg = str(exc.value)
        assert "WET_PATH_USB_BIAS_MUSIC_DB" in msg
        assert "-12.0" in msg
        assert "12.0" in msg
        assert "27" in msg
