"""Tests for shared.audio_conf_ownership (cc-task audio-audit-E Phase 0).

Pin the ownership YAML schema, the lookup helpers, the unit-name suffix
guard, the duplicate-path guard, and the counter labels.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.audio_conf_ownership import (
    ConfOwnership,
    ConfOwnershipRegistry,
    hapax_audio_conf_reload_total,
    load_conf_ownership,
)


@pytest.fixture(autouse=True)
def _reset_counter():
    hapax_audio_conf_reload_total.clear()
    yield
    hapax_audio_conf_reload_total.clear()


REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPPED_YAML = REPO_ROOT / "config" / "audio-conf-ownership.yaml"


class TestShippedYAMLSanity:
    """The yaml committed in this PR must load + validate cleanly."""

    def test_yaml_file_exists(self) -> None:
        assert SHIPPED_YAML.is_file()

    def test_yaml_loads_via_loader(self) -> None:
        registry = load_conf_ownership(SHIPPED_YAML)
        assert registry.schema_version >= 1
        assert len(registry.ownerships) >= 1

    def test_topology_yaml_is_owned(self) -> None:
        """The audio-topology.yaml ownership entry is the canonical example;
        pin its presence so a future YAML edit doesn't silently drop it."""
        registry = load_conf_ownership(SHIPPED_YAML)
        unit = registry.unit_for_path("config/audio-topology.yaml")
        assert unit is not None
        assert "audio" in unit


class TestConfOwnershipShape:
    def test_minimal_entry_constructs(self) -> None:
        entry = ConfOwnership(
            path="config/example.yaml",
            owning_unit="hapax-example.service",
            validator_schema="audio_topology",
            description="Example",
        )
        assert entry.path == "config/example.yaml"
        assert entry.owning_unit == "hapax-example.service"

    def test_unit_must_end_with_systemd_suffix(self) -> None:
        with pytest.raises(ValidationError, match="\\.service"):
            ConfOwnership(
                path="x", owning_unit="hapax-example", validator_schema="none", description="x"
            )

    def test_target_unit_accepted(self) -> None:
        ConfOwnership(
            path="x", owning_unit="hapax-stack.target", validator_schema="none", description="x"
        )

    def test_timer_unit_accepted(self) -> None:
        ConfOwnership(
            path="x", owning_unit="hapax-rebuild.timer", validator_schema="none", description="x"
        )

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ConfOwnership(
                path="x",
                owning_unit="hapax-example.service",
                validator_schema="none",
                description="x",
                rogue_field="foo",  # type: ignore[call-arg]
            )

    def test_unknown_schema_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ConfOwnership(
                path="x",
                owning_unit="hapax-example.service",
                validator_schema="bogus_schema",  # type: ignore[arg-type]
                description="x",
            )

    def test_empty_path_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ConfOwnership(
                path="", owning_unit="hapax-x.service", validator_schema="none", description="x"
            )

    def test_empty_description_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ConfOwnership(
                path="x", owning_unit="hapax-x.service", validator_schema="none", description=""
            )


class TestRegistryShape:
    def test_construct_with_one_ownership(self) -> None:
        registry = ConfOwnershipRegistry(
            schema_version=1,
            ownerships=(
                ConfOwnership(
                    path="x",
                    owning_unit="hapax-x.service",
                    validator_schema="none",
                    description="x",
                ),
            ),
        )
        assert registry.schema_version == 1
        assert len(registry.ownerships) == 1

    def test_schema_version_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ConfOwnershipRegistry(schema_version=0, ownerships=())

    def test_duplicate_path_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate path"):
            ConfOwnershipRegistry(
                schema_version=1,
                ownerships=(
                    ConfOwnership(
                        path="config/x.yaml",
                        owning_unit="hapax-a.service",
                        validator_schema="none",
                        description="a",
                    ),
                    ConfOwnership(
                        path="config/x.yaml",
                        owning_unit="hapax-b.service",
                        validator_schema="none",
                        description="b",
                    ),
                ),
            )


class TestLookupHelpers:
    def _registry_with(
        self, path: str, unit: str, validator_schema: str = "none"
    ) -> ConfOwnershipRegistry:
        return ConfOwnershipRegistry(
            schema_version=1,
            ownerships=(
                ConfOwnership(
                    path=path,
                    owning_unit=unit,
                    validator_schema=validator_schema,  # type: ignore[arg-type]
                    description="x",
                ),
            ),
        )

    def test_unit_for_known_path(self) -> None:
        reg = self._registry_with("config/x.yaml", "hapax-x.service")
        assert reg.unit_for_path("config/x.yaml") == "hapax-x.service"

    def test_unit_for_unknown_path_is_none(self) -> None:
        reg = self._registry_with("config/x.yaml", "hapax-x.service")
        assert reg.unit_for_path("config/unknown.yaml") is None

    def test_schema_for_known_path(self) -> None:
        reg = self._registry_with("config/x.yaml", "hapax-x.service", "audio_topology")
        assert reg.schema_for_path("config/x.yaml") == "audio_topology"

    def test_schema_for_unknown_path_is_none(self) -> None:
        reg = self._registry_with("config/x.yaml", "hapax-x.service")
        assert reg.schema_for_path("config/unknown.yaml") is None


class TestLoadConfOwnership:
    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_conf_ownership(tmp_path / "nope.yaml")

    def test_loads_minimal_inline_yaml(self, tmp_path: Path) -> None:
        yaml_path = tmp_path / "ownership.yaml"
        yaml_path.write_text(
            "schema_version: 1\n"
            "ownerships:\n"
            "  - path: config/x.yaml\n"
            "    owning_unit: hapax-x.service\n"
            "    validator_schema: none\n"
            "    description: a brief description\n"
        )
        registry = load_conf_ownership(yaml_path)
        assert registry.schema_version == 1
        assert registry.unit_for_path("config/x.yaml") == "hapax-x.service"


class TestReloadCounter:
    def _value(self, file: str, outcome: str) -> float:
        return hapax_audio_conf_reload_total.labels(file=file, outcome=outcome)._value.get()

    def test_success_label_increments(self) -> None:
        hapax_audio_conf_reload_total.labels(file="config/x.yaml", outcome="success").inc()
        assert self._value("config/x.yaml", "success") == 1

    def test_distinct_outcome_labels_separate_series(self) -> None:
        for outcome in ("success", "validation-failed", "systemctl-failed", "unowned-path"):
            hapax_audio_conf_reload_total.labels(file="config/x.yaml", outcome=outcome).inc()
        for outcome in ("success", "validation-failed", "systemctl-failed", "unowned-path"):
            assert self._value("config/x.yaml", outcome) == 1
