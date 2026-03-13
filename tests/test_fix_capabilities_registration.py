"""Tests for fix capabilities auto-registration."""


class TestLoadBuiltinCapabilities:
    """Tests for load_builtin_capabilities()."""

    def setup_method(self):
        """Clear registry before each test."""
        import shared.fix_capabilities as mod

        mod._REGISTRY.clear()

    def test_load_registers_ollama(self):
        from shared.fix_capabilities import get_capability_for_group, load_builtin_capabilities

        load_builtin_capabilities()
        cap = get_capability_for_group("gpu")
        assert cap is not None
        assert cap.name == "ollama"

    def test_load_registers_docker(self):
        from shared.fix_capabilities import get_capability_for_group, load_builtin_capabilities

        load_builtin_capabilities()
        cap = get_capability_for_group("docker")
        assert cap is not None
        assert cap.name == "docker"

    def test_load_registers_systemd(self):
        from shared.fix_capabilities import get_capability_for_group, load_builtin_capabilities

        load_builtin_capabilities()
        cap = get_capability_for_group("systemd")
        assert cap is not None
        assert cap.name == "systemd"

    def test_load_registers_filesystem(self):
        from shared.fix_capabilities import get_capability_for_group, load_builtin_capabilities

        load_builtin_capabilities()
        cap = get_capability_for_group("disk")
        assert cap is not None
        assert cap.name == "filesystem"

    def test_load_is_idempotent(self):
        from shared.fix_capabilities import get_all_capabilities, load_builtin_capabilities

        load_builtin_capabilities()
        first_count = len(get_all_capabilities())

        load_builtin_capabilities()
        second_count = len(get_all_capabilities())

        assert first_count == 6
        assert second_count == 6
