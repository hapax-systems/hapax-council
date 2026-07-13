"""Pressure-signal trust fixes (operator directive 2026-06-10):
host-aware admission + production-SLI veto on proxy panic + fail-open + legibility."""

from __future__ import annotations

import json

from shared.sdlc_pressure_gate import (
    GateState,
    PressureReading,
    admission_state,
    decide,
    read_production_sli,
    read_remote_pressure,
)


def _r(psi=0.0, load=0.0, mode="research", sli="unknown", team=None, host=None):
    return PressureReading(
        psi_some_avg10=psi,
        psi_some_avg60=psi,
        load_per_core=load,
        working_mode=mode,
        team_level=team,
        production_sli=sli,
        target_host=host,
    )


def test_healthy_sli_softens_proxy_panic():
    # psi 70 = closed_enter(65) normally; healthy SLI -> one step down -> paced
    s = decide(_r(psi=70.0, sli="healthy"), None, now=100.0)
    assert s.state == "paced"
    # and the 2026-06-10 incident profile (psi ~60, healthy audio) -> OPEN... 60>35 paced_enter -> softened -> open
    s2 = decide(_r(psi=60.0, sli="healthy"), None, now=100.0)
    assert s2.state == "open"


def test_unhealthy_or_unknown_sli_keeps_raw_thresholds():
    assert decide(_r(psi=70.0, sli="unhealthy"), None, 100.0).state == "closed"
    assert decide(_r(psi=70.0, sli="unknown"), None, 100.0).state == "closed"


def test_fortress_never_softened():
    s = decide(_r(psi=45.0, mode="fortress", sli="healthy"), None, 100.0)
    assert s.state == "closed"  # fortress closed_enter=40; softening must not apply


def test_team_load_never_softened():
    s = decide(_r(psi=5.0, sli="healthy", team="red"), None, 100.0)
    assert s.state == "closed"


def test_remote_target_fail_open(monkeypatch, tmp_path):
    import shared.sdlc_pressure_gate as g

    monkeypatch.setattr(g, "local_hostname", lambda: "podium")
    monkeypatch.setattr(g, "read_remote_pressure", lambda host, timeout_s=4.0: None)
    d = admission_state(target_host="hapax-appendix", state_path=tmp_path / "s.json")
    assert d.state == "open"
    assert any("FAIL-OPEN" in r for r in d.reasons)


def test_live_remote_pressure_execution_is_held(monkeypatch):
    import shared.sdlc_pressure_gate as g

    def forbidden(*_args, **_kwargs):
        raise AssertionError("remote pressure observation must not execute a process")

    monkeypatch.setattr(g.subprocess, "run", forbidden)
    assert read_remote_pressure("appendix") is None


def test_remote_target_uses_remote_pressure(monkeypatch, tmp_path):
    import shared.sdlc_pressure_gate as g
    from shared.sdlc_pressure_gate import PsiReading

    monkeypatch.setattr(g, "local_hostname", lambda: "podium")
    monkeypatch.setattr(
        g, "read_remote_pressure", lambda host, timeout_s=4.0: (PsiReading(2.0, 2.0), 0.1)
    )
    monkeypatch.setattr(g, "read_working_mode", lambda: "research")
    d = admission_state(target_host="hapax-appendix", state_path=tmp_path / "s.json")
    assert d.state == "open"
    assert any("hapax-appendix" in r for r in d.reasons)


def test_sli_reader_fresh_healthy(tmp_path):
    f = tmp_path / "audio.json"
    f.write_text(json.dumps({"audio_safe_for_broadcast": {"safe": True, "checked_at": 1000.0}}))
    assert read_production_sli(f, now=1050.0) == "healthy"
    assert read_production_sli(f, now=1000.0 + 9999) == "unknown"  # stale
    f.write_text(json.dumps({"audio_safe_for_broadcast": {"safe": False, "checked_at": 1000.0}}))
    assert read_production_sli(f, now=1050.0) == "unhealthy"


def test_escalation_still_immediate_under_softening():
    prev = GateState("open", 0.0)
    s = decide(_r(psi=99.0, sli="healthy"), prev, now=5.0)
    assert s.state == "paced"  # 99 -> closed raw, softened to paced, escalates immediately
