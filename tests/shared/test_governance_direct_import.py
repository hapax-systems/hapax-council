"""Direct governance import path tests."""

from __future__ import annotations

from pathlib import Path


def test_shared_governance_uses_repo_policyflow_without_manual_pythonpath() -> None:
    import policyflow

    import shared.governance as governance

    policyflow_path = Path(policyflow.__file__).resolve()
    assert "packages/policyflow/src/policyflow" in policyflow_path.as_posix()
    assert governance.Principal.__name__ == "Principal"
