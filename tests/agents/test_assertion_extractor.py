"""Tests for agents.assertion_extractor."""

from __future__ import annotations

from pathlib import Path

from agents.assertion_extractor.code_extractor import extract_from_python_file
from agents.assertion_extractor.yaml_extractor import extract_from_yaml_file


def test_extract_assert_statements(tmp_path: Path) -> None:
    py = tmp_path / "test_mod.py"
    py.write_text("def foo(x):\n    assert x > 0\n    return x\n")
    results = extract_from_python_file(py, repo_root=tmp_path)
    asserts = [r for r in results if "assert_statement" in r.tags]
    assert len(asserts) == 1
    assert asserts[0].source_line == 2


def test_extract_docstring_directives(tmp_path: Path) -> None:
    py = tmp_path / "directives.py"
    py.write_text('def bar():\n    """MUST NOT return None."""\n    return 1\n')
    results = extract_from_python_file(py, repo_root=tmp_path)
    directives = [r for r in results if "docstring_directive" in r.tags]
    assert len(directives) >= 1
    assert any("must" in r.tags for r in directives)


def test_extract_pydantic_validator(tmp_path: Path) -> None:
    py = tmp_path / "models.py"
    py.write_text(
        "from pydantic import field_validator\n"
        "class M:\n"
        "    @field_validator('x')\n"
        "    def check_x(cls, v):\n"
        "        return v\n"
    )
    results = extract_from_python_file(py, repo_root=tmp_path)
    validators = [r for r in results if "pydantic_validator" in r.tags]
    assert len(validators) == 1
    assert "check_x" in validators[0].text


def test_extract_invariant_comment(tmp_path: Path) -> None:
    py = tmp_path / "guarded.py"
    py.write_text("x = 1  # INVARIANT: x must always be positive\ny = 2\n")
    results = extract_from_python_file(py, repo_root=tmp_path)
    comments = [r for r in results if "invariant_comment" in r.tags]
    assert len(comments) == 1


def test_idempotent_extraction(tmp_path: Path) -> None:
    py = tmp_path / "idem.py"
    py.write_text("assert True\n")
    r1 = extract_from_python_file(py, repo_root=tmp_path)
    r2 = extract_from_python_file(py, repo_root=tmp_path)
    assert r1[0].assertion_id == r2[0].assertion_id


def test_yaml_constraint_extraction(tmp_path: Path) -> None:
    yml = tmp_path / "config.yaml"
    yml.write_text("rate_limit:\n  max: 20\n  threshold: 0.8\n  enum: [a, b, c]\n")
    results = extract_from_yaml_file(yml, repo_root=tmp_path)
    assert len(results) >= 3
    tags = {tag for r in results for tag in r.tags}
    assert "max" in tags
    assert "threshold" in tags
    assert "enum" in tags


def test_yaml_nested_walk(tmp_path: Path) -> None:
    yml = tmp_path / "nested.yaml"
    yml.write_text("outer:\n  inner:\n    minimum: 5\n    required: true\n")
    results = extract_from_yaml_file(yml, repo_root=tmp_path)
    assert len(results) >= 2


def test_syntax_error_file_skipped(tmp_path: Path) -> None:
    py = tmp_path / "broken.py"
    py.write_text("def (:\n")
    results = extract_from_python_file(py, repo_root=tmp_path)
    assert results == []


def test_empty_yaml_returns_empty(tmp_path: Path) -> None:
    yml = tmp_path / "empty.yaml"
    yml.write_text("")
    results = extract_from_yaml_file(yml, repo_root=tmp_path)
    assert results == []
