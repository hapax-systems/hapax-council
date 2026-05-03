"""Tests for shared.audio_param_bridge_schema (cc-task audio-audit-E Phase 0).

Pin the schema, lookup helpers, value validator, and the shipped YAML.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.audio_param_bridge_schema import (
    ParamBridge,
    ParamBridgeRegistry,
    load_param_bridge_schema,
    validate_value,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPPED_YAML = REPO_ROOT / "config" / "audio-param-bridge-schema.yaml"


class TestShippedYAML:
    def test_yaml_exists(self) -> None:
        assert SHIPPED_YAML.is_file()

    def test_yaml_loads_cleanly(self) -> None:
        registry = load_param_bridge_schema(SHIPPED_YAML)
        assert registry.schema_version >= 1
        assert len(registry.bridges) >= 3

    def test_canonical_chains_present(self) -> None:
        """The 3 audit-cited chains MUST be exposed; pin them so a future
        YAML edit doesn't silently drop any."""
        registry = load_param_bridge_schema(SHIPPED_YAML)
        chains = set(registry.list_chains())
        for required in ("hapax-music-loudnorm", "hapax-music-duck", "hapax-broadcast-master"):
            assert required in chains, f"required chain {required!r} missing from registry"

    def test_broadcast_master_limit_is_capped_at_zero(self) -> None:
        """Constitutional invariant: broadcast-master Limit (dB) MUST NOT be
        raised above 0.0 (would clip the broadcast). Pin the range_max so
        a future yaml edit can't accidentally widen the surface."""
        registry = load_param_bridge_schema(SHIPPED_YAML)
        bridge = registry.get("hapax-broadcast-master", "Limit (dB)")
        assert bridge is not None
        assert bridge.range_max == 0.0


class TestParamBridgeShape:
    def test_minimal_float_bridge(self) -> None:
        bridge = ParamBridge(chain="x", param="p", type="float", default=0.0, description="x")
        assert bridge.chain == "x"
        assert bridge.type == "float"

    def test_bool_with_range_rejected(self) -> None:
        with pytest.raises(ValidationError, match="bool param"):
            ParamBridge(
                chain="x", param="p", type="bool", range_min=0.0, default=True, description="x"
            )

    def test_bool_default_must_be_bool(self) -> None:
        with pytest.raises(ValidationError, match="default must be a bool"):
            ParamBridge(chain="x", param="p", type="bool", default=1, description="x")  # type: ignore[arg-type]

    def test_inverted_range_rejected(self) -> None:
        with pytest.raises(ValidationError, match="range_min"):
            ParamBridge(
                chain="x",
                param="p",
                type="float",
                range_min=10.0,
                range_max=-10.0,
                default=0.0,
                description="x",
            )

    def test_default_below_range_rejected(self) -> None:
        with pytest.raises(ValidationError, match="below range_min"):
            ParamBridge(
                chain="x",
                param="p",
                type="float",
                range_min=0.0,
                range_max=10.0,
                default=-1.0,
                description="x",
            )

    def test_default_above_range_rejected(self) -> None:
        with pytest.raises(ValidationError, match="above range_max"):
            ParamBridge(
                chain="x",
                param="p",
                type="float",
                range_min=0.0,
                range_max=10.0,
                default=20.0,
                description="x",
            )

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ParamBridge(
                chain="x",
                param="p",
                type="float",
                default=0.0,
                description="x",
                rogue="r",  # type: ignore[call-arg]
            )

    def test_non_bool_default_must_not_be_bool(self) -> None:
        """Python bool is an int subclass; would pass type=int silently."""
        with pytest.raises(ValidationError, match="non-bool param"):
            ParamBridge(
                chain="x",
                param="p",
                type="float",
                default=True,
                description="x",  # type: ignore[arg-type]
            )


class TestRegistryShape:
    def _bridge(self, chain: str = "c", param: str = "p") -> ParamBridge:
        return ParamBridge(chain=chain, param=param, type="float", default=0.0, description="x")

    def test_construct_with_one_bridge(self) -> None:
        registry = ParamBridgeRegistry(schema_version=1, bridges=(self._bridge(),))
        assert registry.schema_version == 1

    def test_duplicate_chain_param_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate"):
            ParamBridgeRegistry(
                schema_version=1,
                bridges=(self._bridge("c", "p"), self._bridge("c", "p")),
            )

    def test_same_param_different_chain_allowed(self) -> None:
        """Same param name on different chains is fine ('Limit (dB)' is on
        multiple LADSPA chains)."""
        ParamBridgeRegistry(
            schema_version=1,
            bridges=(self._bridge("c1", "Limit (dB)"), self._bridge("c2", "Limit (dB)")),
        )

    def test_get_returns_match(self) -> None:
        registry = ParamBridgeRegistry(schema_version=1, bridges=(self._bridge("c", "p"),))
        result = registry.get("c", "p")
        assert result is not None
        assert result.chain == "c"

    def test_get_returns_none_if_absent(self) -> None:
        registry = ParamBridgeRegistry(schema_version=1, bridges=(self._bridge("c", "p"),))
        assert registry.get("nope", "p") is None
        assert registry.get("c", "nope") is None

    def test_list_chains_sorted_and_deduped(self) -> None:
        registry = ParamBridgeRegistry(
            schema_version=1,
            bridges=(
                self._bridge("zeta", "p1"),
                self._bridge("alpha", "p1"),
                self._bridge("alpha", "p2"),
            ),
        )
        assert registry.list_chains() == ("alpha", "zeta")

    def test_list_params_for_chain(self) -> None:
        registry = ParamBridgeRegistry(
            schema_version=1,
            bridges=(
                self._bridge("c", "z-param"),
                self._bridge("c", "a-param"),
                self._bridge("other", "ignored"),
            ),
        )
        assert registry.list_params_for_chain("c") == ("a-param", "z-param")
        assert registry.list_params_for_chain("absent") == ()


class TestValidateValue:
    def _bridge(self, **kwargs) -> ParamBridge:
        defaults = dict(
            chain="c",
            param="p",
            type="float",
            range_min=-10.0,
            range_max=10.0,
            default=0.0,
            description="x",
        )
        defaults.update(kwargs)
        return ParamBridge(**defaults)  # type: ignore[arg-type]

    def test_in_range_passes(self) -> None:
        assert validate_value(self._bridge(), -5.0) == -5.0

    def test_at_range_min_inclusive(self) -> None:
        assert validate_value(self._bridge(), -10.0) == -10.0

    def test_at_range_max_inclusive(self) -> None:
        assert validate_value(self._bridge(), 10.0) == 10.0

    def test_below_range_rejected(self) -> None:
        with pytest.raises(ValueError, match="below range_min"):
            validate_value(self._bridge(), -11.0)

    def test_above_range_rejected(self) -> None:
        with pytest.raises(ValueError, match="above range_max"):
            validate_value(self._bridge(), 11.0)

    def test_int_coerced_to_float(self) -> None:
        result = validate_value(self._bridge(), 5)
        assert result == 5.0
        assert isinstance(result, float)

    def test_int_type_rejects_float(self) -> None:
        bridge = self._bridge(type="int", range_min=0, range_max=10, default=5)
        with pytest.raises(ValueError, match="expected int"):
            validate_value(bridge, 2.5)

    def test_int_type_rejects_bool(self) -> None:
        bridge = self._bridge(type="int", range_min=0, range_max=10, default=5)
        with pytest.raises(ValueError, match="expected int"):
            validate_value(bridge, True)

    def test_bool_type_accepts_bool(self) -> None:
        bridge = ParamBridge(chain="c", param="p", type="bool", default=False, description="x")
        assert validate_value(bridge, True) is True
        assert validate_value(bridge, False) is False

    def test_bool_type_rejects_int(self) -> None:
        bridge = ParamBridge(chain="c", param="p", type="bool", default=False, description="x")
        with pytest.raises(ValueError, match="expected bool"):
            validate_value(bridge, 1)


class TestLoadParamBridgeSchema:
    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_param_bridge_schema(tmp_path / "nope.yaml")

    def test_loads_inline_yaml(self, tmp_path: Path) -> None:
        yaml_path = tmp_path / "schema.yaml"
        yaml_path.write_text(
            "schema_version: 1\n"
            "bridges:\n"
            "  - chain: hapax-test\n"
            '    param: "Limit (dB)"\n'
            "    type: float\n"
            "    range_min: -10\n"
            "    range_max: 0\n"
            "    default: -1.0\n"
            "    description: test\n"
        )
        registry = load_param_bridge_schema(yaml_path)
        assert registry.get("hapax-test", "Limit (dB)") is not None


class TestBroadcastMasterCeilingRegression:
    """Constitutional regression pin: broadcast-master Limit (dB) >= 0.0
    must always be rejected — would clip the broadcast egress."""

    def test_zero_db_at_max_inclusive(self) -> None:
        """0.0 is the documented range_max in the shipped YAML; a POST
        of exactly 0.0 is permitted (it's the absolute ceiling). The
        lockdown is on values ABOVE 0.0."""
        registry = load_param_bridge_schema(SHIPPED_YAML)
        bridge = registry.get("hapax-broadcast-master", "Limit (dB)")
        assert bridge is not None
        # Value at the max is permitted (inclusive).
        assert validate_value(bridge, 0.0) == 0.0

    def test_above_zero_db_rejected(self) -> None:
        registry = load_param_bridge_schema(SHIPPED_YAML)
        bridge = registry.get("hapax-broadcast-master", "Limit (dB)")
        assert bridge is not None
        with pytest.raises(ValueError, match="above range_max"):
            validate_value(bridge, 0.5)
