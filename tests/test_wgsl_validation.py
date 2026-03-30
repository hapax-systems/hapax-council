"""Tests for WGSL shader pre-validation."""

from __future__ import annotations

import unittest

from agents.effect_graph.wgsl_compiler import validate_wgsl


class TestWgslValidation(unittest.TestCase):
    def test_valid_shader_passes(self):
        valid = "@fragment fn main() -> @location(0) vec4<f32> { return vec4(1.0); }"
        assert validate_wgsl(valid) is True

    def test_invalid_shader_fails_with_naga(self):
        import shutil

        invalid = "this is not wgsl at all {"
        result = validate_wgsl(invalid)
        if shutil.which("naga"):
            # naga-cli installed — should reject invalid source
            assert result is False
        else:
            # No naga-cli — validation skipped, returns True
            assert result is True
