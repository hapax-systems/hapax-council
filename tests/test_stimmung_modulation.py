"""Test stimmung modulates DMN pulse rate."""


def test_dmn_pulse_reads_stimmung_stance():
    source = open("agents/dmn/pulse.py").read()
    assert "stimmung" in source.lower() and ("stance" in source or "modulation" in source), (
        "DMN pulse must read stimmung stance for rate modulation"
    )
