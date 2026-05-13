"""Tests for deterministic publication codebase consistency checks."""

from __future__ import annotations

from pathlib import Path

from shared.publication_hardening.codebase import (
    CodebaseConsistencyVerifier,
    CodebaseDecision,
    verify_publication_codebase,
)


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


def test_existing_repo_path_passes(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "shared").mkdir()
    (root / "shared" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")

    report = verify_publication_codebase(
        "The implementation lives at `shared/module.py`.",
        repo_root=root,
    )

    assert report.decision == CodebaseDecision.PASS
    assert report.findings[0].check_id == "repo_path_exists"
    assert report.findings[0].evidence_refs == (str(root / "shared" / "module.py"),)


def test_missing_repo_path_holds(tmp_path: Path) -> None:
    root = _repo(tmp_path)

    report = verify_publication_codebase(
        "The implementation lives at `shared/missing.py`.",
        repo_root=root,
    )

    assert report.decision == CodebaseDecision.HOLD
    assert any(f.check_id == "repo_path_missing" for f in report.findings)


def test_python_snippet_parses_and_import_attribute_resolves(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    package = root / "shared" / "publication_hardening"
    package.mkdir(parents=True)
    (package / "review.py").write_text("class ReviewPass:\n    pass\n", encoding="utf-8")

    report = verify_publication_codebase(
        "```python\nfrom shared.publication_hardening.review import ReviewPass\n```",
        repo_root=root,
    )

    assert report.decision == CodebaseDecision.PASS
    assert any(f.check_id == "python_snippet_syntax" for f in report.findings)
    assert any(f.check_id == "python_import_module_exists" for f in report.findings)


def test_python_snippet_syntax_error_rejects(tmp_path: Path) -> None:
    root = _repo(tmp_path)

    report = verify_publication_codebase("```python\nif True print('bad')\n```", repo_root=root)

    assert report.decision == CodebaseDecision.REJECT
    assert any(f.check_id == "python_snippet_syntax" for f in report.findings)


def test_python_import_missing_attribute_holds(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    package = root / "shared" / "publication_hardening"
    package.mkdir(parents=True)
    (package / "review.py").write_text("class ReviewPass:\n    pass\n", encoding="utf-8")

    report = verify_publication_codebase(
        "```python\nfrom shared.publication_hardening.review import MissingName\n```",
        repo_root=root,
    )

    assert report.decision == CodebaseDecision.HOLD
    assert any(f.check_id == "python_import_attribute_missing" for f in report.findings)


def test_shell_snippet_uses_injected_syntax_checker_without_execution(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    sentinel = tmp_path / "should-not-run"
    calls: list[str] = []

    def checker(script: str) -> str | None:
        calls.append(script)
        return None

    report = verify_publication_codebase(
        f"```bash\ntouch {sentinel}\n```",
        repo_root=root,
        shell_syntax_checker=checker,
    )

    assert report.decision == CodebaseDecision.PASS
    assert calls == [f"touch {sentinel}\n"]
    assert not sentinel.exists()


def test_shell_snippet_syntax_error_rejects(tmp_path: Path) -> None:
    root = _repo(tmp_path)

    report = verify_publication_codebase(
        "```sh\nif true; then\n```",
        repo_root=root,
        shell_syntax_checker=lambda _script: "unexpected EOF",
    )

    assert report.decision == CodebaseDecision.REJECT
    assert any(f.check_id == "shell_snippet_syntax" for f in report.findings)


def test_numeric_claim_without_expectation_holds(tmp_path: Path) -> None:
    root = _repo(tmp_path)

    report = verify_publication_codebase("The repo has 41 hooks.", repo_root=root)

    assert report.decision == CodebaseDecision.HOLD
    assert report.numeric_claims[0].text == "41 hooks"
    assert any(f.check_id == "numeric_claim_unverified" for f in report.findings)


def test_numeric_claim_with_expectation_passes(tmp_path: Path) -> None:
    root = _repo(tmp_path)

    report = verify_publication_codebase(
        "The repo has 41 hooks.",
        repo_root=root,
        numeric_expectations={"hooks": 41},
    )

    assert report.decision == CodebaseDecision.PASS
    assert any(f.check_id == "numeric_claim_verified" for f in report.findings)


def test_numeric_claim_mismatch_rejects(tmp_path: Path) -> None:
    root = _repo(tmp_path)

    report = verify_publication_codebase(
        "The repo has 41 hooks.",
        repo_root=root,
        numeric_expectations={"hooks": 40},
    )

    assert report.decision == CodebaseDecision.REJECT
    assert any(f.check_id == "numeric_claim_mismatch" for f in report.findings)


def test_currentness_claim_requires_evidence_refs(tmp_path: Path) -> None:
    root = _repo(tmp_path)

    report = verify_publication_codebase("The livestream is currently green.", repo_root=root)

    assert report.decision == CodebaseDecision.HOLD
    assert report.currentness_claims[0].keyword == "currently"
    assert any(f.check_id == "currentness_claim_missing_evidence" for f in report.findings)


def test_currentness_claim_with_evidence_passes(tmp_path: Path) -> None:
    root = _repo(tmp_path)

    report = verify_publication_codebase(
        "The livestream is currently green.",
        repo_root=root,
        currentness_evidence_refs=("receipt:/tmp/readiness.json",),
    )

    assert report.decision == CodebaseDecision.PASS
    finding = next(f for f in report.findings if f.check_id == "currentness_claim_evidence_present")
    assert finding.evidence_refs == ("receipt:/tmp/readiness.json",)


def test_aggregate_reject_dominates_hold(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    verifier = CodebaseConsistencyVerifier(repo_root=root)

    report = verifier.verify_text("The repo has 41 hooks.\n```python\nif True print('bad')\n```")

    assert report.decision == CodebaseDecision.REJECT
    assert any(f.decision == CodebaseDecision.HOLD for f in report.findings)
    assert any(f.decision == CodebaseDecision.REJECT for f in report.findings)
