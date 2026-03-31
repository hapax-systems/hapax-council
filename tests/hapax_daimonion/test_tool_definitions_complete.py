"""Tests for complete tool metadata coverage."""

from __future__ import annotations

import logging
import unittest


class TestToolDefinitionsComplete(unittest.TestCase):
    def test_all_handlers_have_metadata(self):
        """build_registry should log no 'no metadata' warnings."""
        warnings: list[str] = []

        class _Handler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                if "no metadata" in record.getMessage():
                    warnings.append(record.getMessage())

        handler = _Handler()
        logger = logging.getLogger("agents.hapax_daimonion.tool_definitions")
        logger.addHandler(handler)
        try:
            from agents.hapax_daimonion.tool_definitions import build_registry

            build_registry(guest_mode=False)
        finally:
            logger.removeHandler(handler)

        assert warnings == [], f"Tools without metadata: {warnings}"

    def test_phone_tools_in_registry(self):
        from agents.hapax_daimonion.tool_definitions import build_registry

        reg = build_registry(guest_mode=False)
        all_names = {t.name for t in reg.all_tools()}
        for name in ["find_phone", "lock_phone", "send_to_phone", "media_control"]:
            assert name in all_names, f"Phone tool '{name}' not in registry"


if __name__ == "__main__":
    unittest.main()
