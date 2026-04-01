"""Test perception backends enforce staleness thresholds."""


def test_ir_presence_uses_trace_reader():
    """IR presence backend must use read_trace or trace_age for staleness safety."""
    source = open("agents/hapax_daimonion/backends/ir_presence.py").read()
    assert "read_trace" in source or "trace_age" in source or "STALE" in source, (
        "IR presence backend must check staleness of Pi reports"
    )


def test_vision_uses_trace_reader():
    """Vision backend must use read_trace or trace_age for staleness safety."""
    source = open("agents/hapax_daimonion/backends/vision.py").read()
    assert "read_trace" in source or "trace_age" in source or "STALE" in source, (
        "Vision backend must check staleness of compositor snapshots"
    )
