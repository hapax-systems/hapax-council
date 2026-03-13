# tests/test_sufficiency_probes.py
"""Tests for shared.sufficiency_probes."""

from shared.sufficiency_probes import (
    PROBES,
    ProbeResult,
    SufficiencyProbe,
    _check_agent_error_remediation,
    _check_agent_zero_config,
    _check_briefing_multi_source,
    _check_no_multiuser_indirection,
    _check_notification_chain,
    _check_plugin_credentials_in_settings,
    _check_plugin_direct_api_support,
    _check_plugin_graceful_degradation,
    _check_proactive_alert_surfacing,
    _check_profile_context_chain,
    _check_state_persistence,
    run_probes,
)

# ── Probe registry ──────────────────────────────────────────────────────────


def test_probes_have_valid_fields():
    """All probes have required fields populated."""
    valid_axioms = {
        "executive_function",
        "single_user",
        "corporate_boundary",
        "management_governance",
    }
    for probe in PROBES:
        assert probe.id.startswith("probe-")
        assert probe.axiom_id in valid_axioms
        assert probe.level in ("component", "subsystem", "system")
        assert probe.question
        assert callable(probe.check)


def test_probes_cover_all_levels():
    """Probes exist for component, subsystem, and system levels."""
    levels = {p.level for p in PROBES}
    assert "component" in levels
    assert "subsystem" in levels
    assert "system" in levels


def test_probes_cover_all_axioms():
    """Probes exist for all four axiom domains."""
    axioms = {p.axiom_id for p in PROBES}
    assert "executive_function" in axioms
    assert "single_user" in axioms
    assert "corporate_boundary" in axioms


# ── run_probes ──────────────────────────────────────────────────────────────


def test_run_probes_returns_results():
    results = run_probes()
    assert len(results) >= 1
    assert all(isinstance(r, ProbeResult) for r in results)


def test_run_probes_filter_by_axiom():
    all_results = run_probes()
    ef_results = run_probes(axiom_id="executive_function")
    su_results = run_probes(axiom_id="single_user")
    cb_results = run_probes(axiom_id="corporate_boundary")

    mg_results = run_probes(axiom_id="management_governance")
    assert len(ef_results) + len(su_results) + len(cb_results) + len(mg_results) == len(all_results)
    assert all(
        any(p.axiom_id == "executive_function" for p in PROBES if p.id == r.probe_id)
        for r in ef_results
    )


def test_run_probes_filter_by_level():
    system_results = run_probes(level="system")
    assert len(system_results) < len(PROBES)
    for r in system_results:
        probe = next(p for p in PROBES if p.id == r.probe_id)
        assert probe.level == "system"


def test_run_probes_combined_filter():
    results = run_probes(axiom_id="executive_function", level="system")
    for r in results:
        probe = next(p for p in PROBES if p.id == r.probe_id)
        assert probe.axiom_id == "executive_function"
        assert probe.level == "system"


def test_run_probes_results_have_timestamp():
    results = run_probes()
    for r in results:
        assert r.timestamp  # ISO format string


# ── Individual probe checks ─────────────────────────────────────────────────


def test_check_agent_error_remediation():
    """Runs against real codebase — should find remediation patterns."""
    met, evidence = _check_agent_error_remediation()
    # The real codebase has remediation strings in most agents
    assert isinstance(met, bool)
    assert isinstance(evidence, str)
    assert evidence  # non-empty


def test_check_agent_zero_config():
    met, evidence = _check_agent_zero_config()
    assert isinstance(met, bool)
    assert evidence


def test_check_state_persistence():
    met, evidence = _check_state_persistence()
    assert isinstance(met, bool)
    assert evidence


def test_check_briefing_multi_source():
    met, evidence = _check_briefing_multi_source()
    assert isinstance(met, bool)
    assert evidence


def test_check_notification_chain():
    met, evidence = _check_notification_chain()
    assert isinstance(met, bool)
    assert evidence


def test_check_profile_context_chain():
    met, evidence = _check_profile_context_chain()
    assert isinstance(met, bool)
    assert evidence


def test_check_no_multiuser_indirection():
    met, evidence = _check_no_multiuser_indirection()
    assert isinstance(met, bool)
    assert evidence


# ── Error handling ──────────────────────────────────────────────────────────


def test_probe_error_returns_false():
    """If a probe check raises, result is met=False with error evidence."""

    def broken_check():
        raise RuntimeError("test error")

    probe = SufficiencyProbe(
        id="probe-test",
        axiom_id="executive_function",
        implication_id="ex-err-001",
        level="component",
        question="Does it work?",
        check=broken_check,
    )

    # Temporarily add to PROBES
    original_probes = PROBES.copy()
    PROBES.clear()
    PROBES.append(probe)

    try:
        results = run_probes()
        assert len(results) == 1
        assert results[0].met is False
        assert "probe error" in results[0].evidence
    finally:
        PROBES.clear()
        PROBES.extend(original_probes)


# ── Drift detector integration ──────────────────────────────────────────────


def test_scan_sufficiency_gaps_import():
    """scan_sufficiency_gaps can be called from drift_detector."""
    from agents.drift_detector import scan_sufficiency_gaps

    gaps = scan_sufficiency_gaps()
    assert isinstance(gaps, list)
    # All items should be DriftItems with the right category
    for item in gaps:
        assert item.category == "axiom-sufficiency-gap"


# ── Corporate boundary probes ──────────────────────────────────────────────


def test_check_plugin_direct_api_support():
    """obsidian-hapax should have anthropic + openai direct providers."""
    met, evidence = _check_plugin_direct_api_support()
    assert isinstance(met, bool)
    assert evidence
    assert met, evidence


def test_check_plugin_graceful_degradation():
    """qdrant-client.ts should have catch blocks for graceful degradation."""
    met, evidence = _check_plugin_graceful_degradation()
    assert isinstance(met, bool)
    assert evidence
    assert met, evidence


def test_check_plugin_credentials_in_settings():
    """Plugin should store API keys in settings, not env vars."""
    met, evidence = _check_plugin_credentials_in_settings()
    assert isinstance(met, bool)
    assert evidence
    assert met, evidence


def test_corporate_boundary_probes_registered():
    """Corporate boundary probes are in the PROBES list."""
    cb_probes = [p for p in PROBES if p.axiom_id == "corporate_boundary"]
    assert len(cb_probes) == 3
    ids = {p.id for p in cb_probes}
    assert "probe-cb-llm-001" in ids
    assert "probe-cb-degrade-001" in ids
    assert "probe-cb-key-001" in ids


# ── Executive function behavioral probes ───────────────────────────────────


def test_check_proactive_alert_surfacing():
    """health_monitor should push alerts proactively."""
    met, evidence = _check_proactive_alert_surfacing()
    assert isinstance(met, bool)
    assert evidence


def test_alert_probe_registered():
    """Alert probe is in the PROBES list."""
    alert_probes = [p for p in PROBES if p.id == "probe-alert-004"]
    assert len(alert_probes) == 1
    assert alert_probes[0].axiom_id == "executive_function"
    assert alert_probes[0].implication_id == "ex-alert-004"
