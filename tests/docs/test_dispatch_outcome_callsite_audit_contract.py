from pathlib import Path

AUDIT_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "superpowers"
    / "audits"
    / "2026-04-30-dispatch-outcome-callsite-audit.md"
)


def _audit_text() -> str:
    return AUDIT_PATH.read_text(encoding="utf-8")


def test_dispatch_outcome_audit_preserves_required_search_evidence() -> None:
    text = _audit_text()

    assert 'rg -n "record_outcome|success=True|success: bool" agents shared logos tests' in text
    assert "Result: 148 matching lines including tests." in text
    assert "Result: 60 matching lines." in text
    assert "Result: 92 matching lines." in text


def test_dispatch_outcome_audit_classifies_required_risk_postures() -> None:
    text = _audit_text()

    for posture in (
        "`witnessed_migration`",
        "`commanded_deferred`",
        "`internal_only`",
        "`exploration_only`",
        "`blocked_safe`",
        "`already_adapted`",
    ):
        assert posture in text


def test_dispatch_outcome_audit_keeps_high_risk_runtime_surfaces_visible() -> None:
    text = _audit_text()

    for surface in (
        "agents/hapax_daimonion/run_loops_aux.py:755-767",
        "agents/hapax_daimonion/run_loops_aux.py:270-302",
        "agents/hapax_daimonion/run_loops_aux.py:781-815",
        "agents/hapax_daimonion/run_loops_aux.py:818-841",
        "agents/hapax_daimonion/run_loops_aux.py:313-447",
        "agents/reverie/mixer.py:304-347",
    ):
        assert surface in text

    assert "broadcast manifest" in text
    assert "kill-switch evidence" in text
    assert "fresh speech route plus public/private egress witness" in text


def test_dispatch_outcome_audit_rejects_boolean_public_authority() -> None:
    text = _audit_text()

    assert "no direct boolean success can be cited as public" in text
    assert "truth authority" in text
    assert "claim-bearing output" in text
