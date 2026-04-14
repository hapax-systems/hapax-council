"""W1.8: structured JSON timestamp microseconds.

Regression pin for the bug where ``datefmt="%Y-%m-%dT%H:%M:%S.%fZ"`` left
``%f`` as a literal because ``logging.Formatter.formatTime`` uses C
strftime, which doesn't expand ``%f``. The override routes through
``datetime.strftime`` instead.

Both ``shared/log_setup.py`` and ``agents/_log_setup.py`` carry the same
formatter (vendored duplicates); both are tested.
"""

from __future__ import annotations

import json
import logging
import re

import pytest

ISO_MICROSECOND_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


def _emit_one_record_through(module_name: str) -> dict[str, str]:
    """Configure ``module_name``.configure_logging once, emit a single
    INFO record, and return the parsed JSON dict.
    """
    import importlib
    import io
    import sys

    mod = importlib.import_module(module_name)

    # Capture stdout (the JSON handler writes to sys.stdout).
    captured = io.StringIO()
    real_stdout = sys.stdout
    sys.stdout = captured
    try:
        mod.configure_logging(agent="test", level="INFO", human_readable=False)
        logging.getLogger("test_logger").info("hello world")
    finally:
        sys.stdout = real_stdout
        # Drop handlers so the next test gets a clean slate.
        logging.getLogger().handlers.clear()

    # The single emitted line is a JSON object.
    line = captured.getvalue().strip()
    assert line, f"no log line emitted via {module_name}"
    return json.loads(line)


@pytest.mark.parametrize(
    "module_name",
    ["shared.log_setup", "agents._log_setup"],
)
class TestStructuredJsonTimestamp:
    def test_timestamp_has_six_microsecond_digits(self, module_name: str) -> None:
        try:
            from pythonjsonlogger.json import JsonFormatter  # noqa: F401
        except ImportError:
            pytest.skip("pythonjsonlogger not installed")

        record = _emit_one_record_through(module_name)
        ts = record.get("timestamp")
        assert ts is not None, f"{module_name} omitted timestamp field"
        assert ISO_MICROSECOND_RE.match(ts), (
            f"{module_name} timestamp is not ISO-8601 with microseconds: {ts!r}"
        )

    def test_timestamp_does_not_contain_literal_format_directive(self, module_name: str) -> None:
        try:
            from pythonjsonlogger.json import JsonFormatter  # noqa: F401
        except ImportError:
            pytest.skip("pythonjsonlogger not installed")

        record = _emit_one_record_through(module_name)
        ts = record["timestamp"]
        # The pre-fix bug left ``%f`` literal in the string.
        assert "%f" not in ts, f"{module_name} still leaks %f literal: {ts!r}"
        assert "%Y" not in ts
        assert "%H" not in ts

    def test_other_required_fields_present(self, module_name: str) -> None:
        try:
            from pythonjsonlogger.json import JsonFormatter  # noqa: F401
        except ImportError:
            pytest.skip("pythonjsonlogger not installed")

        record = _emit_one_record_through(module_name)
        # Sanity check that the rest of the formatter still produces
        # the structured fields downstream filters depend on.
        for key in ("level", "logger", "service", "agent", "message"):
            assert key in record, f"{module_name} missing required field {key!r}"
        assert record["level"] == "INFO"
        assert record["agent"] == "test"
        assert record["message"] == "hello world"
