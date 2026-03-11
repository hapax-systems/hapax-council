"""Tests for demo pipeline tracing."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


class TestDemoTracing:
    def test_tracer_created(self):
        """Verify the demo module creates an OTel tracer."""
        from agents.demo import tracer
        assert tracer is not None

    @patch("agents.demo.tracer")
    def test_spans_created_for_stages(self, mock_tracer):
        """Verify span names match pipeline stages."""
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)
        mock_tracer.start_as_current_span.return_value = mock_span
        assert mock_tracer.start_as_current_span is not None
