"""Tests for GLSL ES 1.0 → WGSL transpiler."""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.effect_graph.wgsl_transpiler import (
    adapt_glsl,
    transpile_all_nodes,
    transpile_glsl_to_wgsl,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_SHADER = """\
#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform float u_mix;
void main() {
    vec4 c = texture2D(tex, v_texcoord);
    gl_FragColor = c * u_mix;
}
"""

NO_UNIFORM_SHADER = """\
#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
void main() {
    gl_FragColor = vec4(v_texcoord, 0.0, 1.0);
}
"""

SAMPLER_ONLY_SHADER = """\
#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
void main() {
    gl_FragColor = texture2D(tex, v_texcoord);
}
"""

TWO_SAMPLER_SHADER = """\
#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D tex;
uniform sampler2D tex_b;
uniform float u_mix;
void main() {
    vec4 a = texture2D(tex, v_texcoord);
    vec4 b = texture2D(tex_b, v_texcoord);
    gl_FragColor = mix(a, b, u_mix);
}
"""


# ---------------------------------------------------------------------------
# adapt_glsl tests
# ---------------------------------------------------------------------------


class TestAdaptGlsl:
    def test_rewrites_version(self):
        result = adapt_glsl(MINIMAL_SHADER)
        assert "#version 450" in result
        assert "#version 100" not in result

    def test_removes_precision(self):
        result = adapt_glsl(MINIMAL_SHADER)
        assert "precision mediump" not in result
        assert "#ifdef GL_ES" not in result
        assert "#endif" not in result

    def test_converts_varying_to_layout_in(self):
        result = adapt_glsl(MINIMAL_SHADER)
        assert "layout(location=0) in vec2 v_texcoord;" in result
        assert "varying" not in result

    def test_collects_uniforms_into_ubo(self):
        result = adapt_glsl(MINIMAL_SHADER)
        assert "layout(set=1, binding=0) uniform Params {" in result
        assert "float u_mix;" in result

    def test_splits_sampler2d(self):
        result = adapt_glsl(MINIMAL_SHADER)
        assert "layout(set=0, binding=0) uniform texture2D tex;" in result
        assert "layout(set=0, binding=1) uniform sampler tex_sampler;" in result

    def test_converts_texture2d_calls(self):
        result = adapt_glsl(MINIMAL_SHADER)
        assert "texture(sampler2D(tex, tex_sampler)," in result
        assert "texture2D(" not in result

    def test_converts_gl_fragcolor(self):
        result = adapt_glsl(MINIMAL_SHADER)
        assert "layout(location=0) out vec4 fragColor;" in result
        assert "fragColor = c * u_mix;" in result
        assert "gl_FragColor" not in result

    def test_no_uniforms(self):
        result = adapt_glsl(NO_UNIFORM_SHADER)
        assert "#version 450" in result
        assert "Params" not in result
        assert "texture2D" not in result  # no sampler → no texture2D references
        assert "fragColor = vec4(v_texcoord, 0.0, 1.0);" in result

    def test_sampler_only_no_scalar_uniforms(self):
        result = adapt_glsl(SAMPLER_ONLY_SHADER)
        assert "layout(set=0, binding=0) uniform texture2D tex;" in result
        assert "layout(set=0, binding=1) uniform sampler tex_sampler;" in result
        assert "Params" not in result  # no scalar uniforms → no UBO

    def test_two_samplers(self):
        result = adapt_glsl(TWO_SAMPLER_SHADER)
        assert "layout(set=0, binding=0) uniform texture2D tex;" in result
        assert "layout(set=0, binding=1) uniform sampler tex_sampler;" in result
        assert "layout(set=0, binding=2) uniform texture2D tex_b;" in result
        assert "layout(set=0, binding=3) uniform sampler tex_b_sampler;" in result
        assert "texture(sampler2D(tex, tex_sampler)," in result
        assert "texture(sampler2D(tex_b, tex_b_sampler)," in result

    def test_multiple_scalar_uniforms(self):
        shader = """\
#version 100
#ifdef GL_ES
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform float u_a;
uniform float u_b;
uniform float u_c;
void main() {
    gl_FragColor = vec4(u_a, u_b, u_c, 1.0);
}
"""
        result = adapt_glsl(shader)
        assert "float u_a;" in result
        assert "float u_b;" in result
        assert "float u_c;" in result
        assert result.count("uniform Params") == 1


# ---------------------------------------------------------------------------
# transpile_glsl_to_wgsl tests
# ---------------------------------------------------------------------------


class TestTranspileGlslToWgsl:
    def test_simple_passthrough(self):
        wgsl = transpile_glsl_to_wgsl(SAMPLER_ONLY_SHADER)
        assert "texture_2d" in wgsl or "textureSample" in wgsl
        assert "fn main" in wgsl

    def test_minimal_shader(self):
        wgsl = transpile_glsl_to_wgsl(MINIMAL_SHADER)
        assert "fn main" in wgsl

    def test_invalid_glsl_raises(self):
        with pytest.raises(RuntimeError, match="naga failed"):
            transpile_glsl_to_wgsl("this is not valid glsl at all {{{")


# ---------------------------------------------------------------------------
# transpile_all_nodes tests
# ---------------------------------------------------------------------------


class TestTranspileAllNodes:
    def test_batch_success_count(self, tmp_path: Path):
        nodes = tmp_path / "nodes"
        nodes.mkdir()
        # Write two valid shaders
        (nodes / "a.frag").write_text(SAMPLER_ONLY_SHADER)
        (nodes / "b.frag").write_text(NO_UNIFORM_SHADER)

        result = transpile_all_nodes(nodes)
        assert result["total"] == 2
        assert result["success"] == 2
        assert result["failed"] == 0
        assert (nodes / "a.wgsl").exists()
        assert (nodes / "b.wgsl").exists()

    def test_batch_with_failure(self, tmp_path: Path):
        nodes = tmp_path / "nodes"
        nodes.mkdir()
        (nodes / "good.frag").write_text(SAMPLER_ONLY_SHADER)
        (nodes / "bad.frag").write_text("not valid glsl {{{")

        result = transpile_all_nodes(nodes)
        assert result["total"] == 2
        assert result["success"] == 1
        assert result["failed"] == 1
        assert len(result["failures"]) == 1
        assert result["failures"][0]["file"] == "bad.frag"
