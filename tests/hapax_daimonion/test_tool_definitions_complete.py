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

    def test_no_handlers_missing_for_metadata(self):
        """build_registry should log no 'missing handlers' warnings — tools
        declared in _META that lack a handler entry are unreachable.
        Live regression: phone_notifications was in _META but PHONE_TOOL_HANDLERS
        and PHONE_TOOL_DEFINITIONS lacked it, so the LLM could never invoke it."""
        warnings: list[str] = []

        class _Handler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                if "missing handlers" in record.getMessage():
                    warnings.append(record.getMessage())

        handler = _Handler()
        logger = logging.getLogger("agents.hapax_daimonion.tool_definitions")
        logger.addHandler(handler)
        try:
            from agents.hapax_daimonion.tool_definitions import build_registry

            build_registry(guest_mode=False)
        finally:
            logger.removeHandler(handler)

        assert warnings == [], f"Tools in _META without handlers: {warnings}"

    def test_phone_tools_in_registry(self):
        from agents.hapax_daimonion.tool_definitions import build_registry

        reg = build_registry(guest_mode=False)
        all_names = {t.name for t in reg.all_tools()}
        for name in [
            "find_phone",
            "lock_phone",
            "send_to_phone",
            "media_control",
            "phone_notifications",
        ]:
            assert name in all_names, f"Phone tool '{name}' not in registry"


if __name__ == "__main__":
    unittest.main()
