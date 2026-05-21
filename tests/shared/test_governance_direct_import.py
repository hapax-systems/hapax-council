"""Direct governance import path tests."""

from __future__ import annotations

from pathlib import Path


def test_shared_governance_uses_repo_agentgov_without_manual_pythonpath() -> None:
    import agentgov

    import shared.governance as governance

    agentgov_path = Path(agentgov.__file__).resolve()
    assert "packages/agentgov/src/agentgov" in agentgov_path.as_posix()
    assert governance.Principal.__name__ == "Principal"
