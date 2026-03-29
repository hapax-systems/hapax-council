"""Tests for WGSL shader pre-validation."""

from __future__ import annotations

import unittest

from agents.effect_graph.wgsl_compiler import validate_wgsl


class TestWgslValidation(unittest.TestCase):
    def test_valid_shader_passes(self):
        valid = "@fragment fn main() -> @location(0) vec4<f32> { return vec4(1.0); }"
        assert validate_wgsl(valid) is True

    def test_invalid_shader_fails_or_fallback(self):
        # If naga-cli is installed, this should fail validation
        # If not, fallback check passes if @fragment is present
        invalid = "this is not wgsl at all {"
        result = validate_wgsl(invalid)
        # Either naga rejects it (False) or fallback accepts it because
        # no @fragment/@compute (False). Both are correct.
        assert result is False
