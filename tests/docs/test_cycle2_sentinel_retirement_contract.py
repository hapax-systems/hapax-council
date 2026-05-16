"""Regression pins for retiring sentinel from the grounding treatment narrative."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROOFS = REPO_ROOT / "agents" / "hapax_daimonion" / "proofs"

KEY_PROOF_DOCS = (
    PROOFS / "README.md",
    PROOFS / "POSITION.md",
    PROOFS / "PACKAGE-ASSESSMENT.md",
    PROOFS / "CYCLE-2-PREREGISTRATION.md",
    PROOFS / "CONTEXT-AS-COMPUTATION.md",
    PROOFS / "THEORETICAL-FOUNDATIONS.md",
    PROOFS / "ADDITIVE-VS-THRESHOLD.md",
)

FORBIDDEN_FRAMES = (
    "4-component package (thread, message drop, cross-session memory, sentinel)",
    "The 4 components map to a clean decomposition",
    "| **Context Maintenance** | Drop | Sentinel |",
    "`C_sentinel`: Verify injected fact in output, update V",
    "Sentinel (STABLE) | Early (primacy) | Computational anchor",
    "Sentinel Fact | 75% | Partially | Yes | Cross-session context verification",
    "stable_frame=true, grounding_directive=true, effort_modulation=true, cross_session=true, sentinel=true",
)


def _all_key_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in KEY_PROOF_DOCS)


def test_sentinel_is_not_framed_as_grounding_treatment_component() -> None:
    body = _all_key_text()

    for phrase in FORBIDDEN_FRAMES:
        assert phrase not in body


def test_sentinel_is_preserved_as_prompt_integrity_diagnostic() -> None:
    prereg = (PROOFS / "CYCLE-2-PREREGISTRATION.md").read_text(encoding="utf-8")
    readme = (PROOFS / "README.md").read_text(encoding="utf-8")
    package = (PROOFS / "PACKAGE-ASSESSMENT.md").read_text(encoding="utf-8")

    assert "Dependent measure, not treatment component" in prereg
    assert "pre-registered diagnostic" in readme
    assert "Prompt-integrity diagnostic, not treatment" in package


def test_grounding_phase_table_excludes_sentinel_from_treatment_flags() -> None:
    prereg = (PROOFS / "CYCLE-2-PREREGISTRATION.md").read_text(encoding="utf-8")

    phase_table = prereg.split("### 2.4 Phase Change Decision Rules", 1)[0]
    assert "Treatment Flags" in phase_table
    assert "sentinel=true" not in phase_table
    assert "sentinel=false" not in phase_table
