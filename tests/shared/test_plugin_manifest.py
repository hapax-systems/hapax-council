"""Tests for shared.plugin_manifest.

102-LOC Pydantic schema for compositor plugin manifests
(``plugins/{name}/manifest.json``). Strict validation (extra=forbid)
catches typos at load. Untested before this commit.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.plugin_manifest import (
    PluginManifest,
    PluginParam,
)


def _valid_manifest_dict() -> dict:
    return {
        "name": "gst-crossfade",
        "version": "1.0.0",
        "kind": "shader",
        "backend": "wgsl_render",
        "description": "Cross-fade between two sources",
        "author": "alpha",
        "license": "MIT",
    }


# ── PluginParam ────────────────────────────────────────────────────


class TestPluginParam:
    def test_minimal_float_param(self) -> None:
        p = PluginParam(type="float", default=0.5)
        assert p.type == "float"
        assert p.default == 0.5

    def test_int_param_with_range(self) -> None:
        p = PluginParam(type="int", default=10, min=0, max=100)
        assert p.min == 0
        assert p.max == 100

    def test_enum_param_values(self) -> None:
        p = PluginParam(
            type="enum",
            default="medium",
            enum_values=["low", "medium", "high"],
        )
        assert p.enum_values == ["low", "medium", "high"]

    def test_extra_field_rejected(self) -> None:
        """extra='forbid' surfaces typos at load time."""
        with pytest.raises(ValidationError):
            PluginParam(
                type="float",
                default=0.5,
                ranage=10,  # type: ignore[call-arg] — typo for 'range'
            )

    def test_invalid_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PluginParam(type="vector3", default=[0, 0, 0])  # type: ignore[arg-type]


# ── PluginManifest field validation ────────────────────────────────


class TestPluginManifestValidation:
    def test_valid_minimal_manifest(self) -> None:
        m = PluginManifest.model_validate(_valid_manifest_dict())
        assert m.name == "gst-crossfade"
        assert m.kind == "shader"
        assert m.backend == "wgsl_render"
        assert m.params == {}
        assert m.tags == []

    def test_name_required(self) -> None:
        d = _valid_manifest_dict()
        del d["name"]
        with pytest.raises(ValidationError):
            PluginManifest.model_validate(d)

    def test_name_empty_rejected(self) -> None:
        d = _valid_manifest_dict()
        d["name"] = ""
        with pytest.raises(ValidationError):
            PluginManifest.model_validate(d)

    def test_name_too_long_rejected(self) -> None:
        d = _valid_manifest_dict()
        d["name"] = "x" * 65
        with pytest.raises(ValidationError):
            PluginManifest.model_validate(d)

    @pytest.mark.parametrize(
        "version",
        ["1.0.0", "0.1.0", "10.20.30"],
    )
    def test_valid_semver(self, version: str) -> None:
        d = _valid_manifest_dict()
        d["version"] = version
        m = PluginManifest.model_validate(d)
        assert m.version == version

    @pytest.mark.parametrize(
        "version",
        ["1.0", "v1.0.0", "1.0.0-beta", "1.0.0.0", ""],
    )
    def test_invalid_semver_rejected(self, version: str) -> None:
        d = _valid_manifest_dict()
        d["version"] = version
        with pytest.raises(ValidationError):
            PluginManifest.model_validate(d)

    def test_extra_top_level_field_rejected(self) -> None:
        d = _valid_manifest_dict()
        d["unknown_field"] = "x"
        with pytest.raises(ValidationError):
            PluginManifest.model_validate(d)

    @pytest.mark.parametrize(
        "kind",
        [
            "camera",
            "video",
            "shader",
            "image",
            "text",
            "cairo",
            "external_rgba",
            "ndi",
            "generative",
        ],
    )
    def test_valid_kinds(self, kind: str) -> None:
        d = _valid_manifest_dict()
        d["kind"] = kind
        m = PluginManifest.model_validate(d)
        assert m.kind == kind

    def test_invalid_kind_rejected(self) -> None:
        d = _valid_manifest_dict()
        d["kind"] = "particles"
        with pytest.raises(ValidationError):
            PluginManifest.model_validate(d)

    def test_backend_required(self) -> None:
        d = _valid_manifest_dict()
        del d["backend"]
        with pytest.raises(ValidationError):
            PluginManifest.model_validate(d)


# ── Optional fields ────────────────────────────────────────────────


class TestOptionalFields:
    def test_default_optionals_unset(self) -> None:
        m = PluginManifest.model_validate(_valid_manifest_dict())
        assert m.source_module is None
        assert m.shader is None
        assert m.tags == []
        assert m.params == {}

    def test_params_dict_validates_each(self) -> None:
        d = _valid_manifest_dict()
        d["params"] = {
            "alpha": {"type": "float", "default": 0.5, "min": 0.0, "max": 1.0},
            "speed": {"type": "int", "default": 30},
        }
        m = PluginManifest.model_validate(d)
        assert m.params["alpha"].min == 0.0
        assert m.params["speed"].default == 30

    def test_params_with_invalid_inner_rejected(self) -> None:
        d = _valid_manifest_dict()
        d["params"] = {
            "p": {"type": "shape3d", "default": "x"},
        }
        with pytest.raises(ValidationError):
            PluginManifest.model_validate(d)

    def test_tags_round_trip(self) -> None:
        d = _valid_manifest_dict()
        d["tags"] = ["audio-reactive", "experimental"]
        m = PluginManifest.model_validate(d)
        assert m.tags == ["audio-reactive", "experimental"]

    def test_source_module_optional(self) -> None:
        d = _valid_manifest_dict()
        d["source_module"] = "agents.studio_compositor.plugins.x"
        m = PluginManifest.model_validate(d)
        assert m.source_module == "agents.studio_compositor.plugins.x"

    def test_shader_optional(self) -> None:
        d = _valid_manifest_dict()
        d["shader"] = "shader.wgsl"
        m = PluginManifest.model_validate(d)
        assert m.shader == "shader.wgsl"
