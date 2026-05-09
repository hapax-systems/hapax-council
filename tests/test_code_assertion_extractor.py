"""Tests for shared.code_assertion_extractor."""

from __future__ import annotations

import textwrap
from pathlib import Path

from shared.assertion_model import AssertionType, SourceType
from shared.code_assertion_extractor import extract_from_python_file


def _write_py(tmp_path: Path, code: str) -> Path:
    p = tmp_path / "sample.py"
    p.write_text(textwrap.dedent(code), encoding="utf-8")
    return p


class TestAssertExtraction:
    def test_simple_assert(self, tmp_path: Path) -> None:
        p = _write_py(
            tmp_path,
            """\
            x = 1
            assert x > 0
        """,
        )
        results = extract_from_python_file(p)
        asserts = [r for r in results if r.assertion_type == AssertionType.INVARIANT]
        assert len(asserts) == 1
        assert "x > 0" in asserts[0].text
        assert asserts[0].source_type == SourceType.CODE
        assert asserts[0].provenance.extraction_method == "ast_assert_visitor"

    def test_assert_with_message(self, tmp_path: Path) -> None:
        p = _write_py(
            tmp_path,
            """\
            val = None
            assert val is not None, "val must be set"
        """,
        )
        results = extract_from_python_file(p)
        asserts = [r for r in results if r.assertion_type == AssertionType.INVARIANT]
        assert len(asserts) == 1
        assert "val is not None" in asserts[0].text
        assert "val must be set" in asserts[0].text

    def test_multiple_asserts(self, tmp_path: Path) -> None:
        p = _write_py(
            tmp_path,
            """\
            def check(a, b):
                assert a > 0
                assert b > 0
                assert a != b
        """,
        )
        results = extract_from_python_file(p)
        asserts = [r for r in results if r.assertion_type == AssertionType.INVARIANT]
        assert len(asserts) == 3

    def test_assert_source_span(self, tmp_path: Path) -> None:
        p = _write_py(
            tmp_path,
            """\
            x = 1
            y = 2
            assert x < y
        """,
        )
        results = extract_from_python_file(p)
        asserts = [r for r in results if r.assertion_type == AssertionType.INVARIANT]
        assert asserts[0].source_span is not None
        assert asserts[0].source_span[0] == 3

    def test_assert_confidence(self, tmp_path: Path) -> None:
        p = _write_py(
            tmp_path,
            """\
            assert True
        """,
        )
        results = extract_from_python_file(p)
        assert results[0].confidence == 0.9


class TestDocstringExtraction:
    def test_must_in_module_docstring(self, tmp_path: Path) -> None:
        p = _write_py(
            tmp_path,
            '''\
            """Callers MUST validate input before calling."""
        ''',
        )
        results = extract_from_python_file(p)
        constraints = [r for r in results if r.assertion_type == AssertionType.CONSTRAINT]
        assert len(constraints) == 1
        assert "MUST" in constraints[0].text
        assert constraints[0].provenance.extraction_method == "ast_docstring_deontic"
        assert "keyword:MUST" in constraints[0].tags

    def test_never_in_function_docstring(self, tmp_path: Path) -> None:
        p = _write_py(
            tmp_path,
            '''\
            def dangerous():
                """This function NEVER returns None."""
                return 42
        ''',
        )
        results = extract_from_python_file(p)
        constraints = [r for r in results if r.assertion_type == AssertionType.CONSTRAINT]
        assert len(constraints) == 1
        assert "NEVER" in constraints[0].text

    def test_always_in_class_docstring(self, tmp_path: Path) -> None:
        p = _write_py(
            tmp_path,
            '''\
            class Gateway:
                """The gateway ALWAYS validates tokens."""
                pass
        ''',
        )
        results = extract_from_python_file(p)
        constraints = [r for r in results if r.assertion_type == AssertionType.CONSTRAINT]
        assert len(constraints) == 1
        assert "ALWAYS" in constraints[0].text

    def test_multiple_deontic_sentences(self, tmp_path: Path) -> None:
        p = _write_py(
            tmp_path,
            '''\
            """Callers MUST check permissions. Implementations NEVER cache state."""
        ''',
        )
        results = extract_from_python_file(p)
        constraints = [r for r in results if r.assertion_type == AssertionType.CONSTRAINT]
        assert len(constraints) == 2

    def test_no_deontic_keywords(self, tmp_path: Path) -> None:
        p = _write_py(
            tmp_path,
            '''\
            """A regular docstring with no constraints."""
        ''',
        )
        results = extract_from_python_file(p)
        constraints = [r for r in results if r.assertion_type == AssertionType.CONSTRAINT]
        assert len(constraints) == 0

    def test_lowercase_must_ignored(self, tmp_path: Path) -> None:
        p = _write_py(
            tmp_path,
            '''\
            """You must do this."""
        ''',
        )
        results = extract_from_python_file(p)
        constraints = [r for r in results if r.assertion_type == AssertionType.CONSTRAINT]
        assert len(constraints) == 0

    def test_docstring_confidence(self, tmp_path: Path) -> None:
        p = _write_py(
            tmp_path,
            '''\
            """Callers MUST validate input."""
        ''',
        )
        results = extract_from_python_file(p)
        constraints = [r for r in results if r.assertion_type == AssertionType.CONSTRAINT]
        assert constraints[0].confidence == 0.8


class TestValidatorExtraction:
    def test_field_validator(self, tmp_path: Path) -> None:
        p = _write_py(
            tmp_path,
            """\
            from pydantic import BaseModel, field_validator

            class Config(BaseModel):
                port: int

                @field_validator("port")
                @classmethod
                def check_port(cls, v):
                    if v < 0 or v > 65535:
                        raise ValueError("invalid port")
                    return v
        """,
        )
        results = extract_from_python_file(p)
        validators = [
            r for r in results if r.provenance.extraction_method == "ast_pydantic_validator"
        ]
        assert len(validators) == 1
        assert "Config.check_port" in validators[0].text
        assert "'port'" in validators[0].text
        assert "validator_type:field_validator" in validators[0].tags

    def test_model_validator(self, tmp_path: Path) -> None:
        p = _write_py(
            tmp_path,
            """\
            from pydantic import BaseModel, model_validator

            class Range(BaseModel):
                lo: int
                hi: int

                @model_validator(mode="after")
                def check_range(self):
                    if self.lo > self.hi:
                        raise ValueError("lo > hi")
                    return self
        """,
        )
        results = extract_from_python_file(p)
        validators = [
            r for r in results if r.provenance.extraction_method == "ast_pydantic_validator"
        ]
        assert len(validators) == 1
        assert "Range.check_range" in validators[0].text
        assert "model validator" in validators[0].text
        assert "mode=after" in validators[0].text
        assert "validator_type:model_validator" in validators[0].tags

    def test_validator_with_docstring(self, tmp_path: Path) -> None:
        p = _write_py(
            tmp_path,
            '''\
            from pydantic import BaseModel, field_validator

            class Item(BaseModel):
                name: str

                @field_validator("name")
                @classmethod
                def strip_name(cls, v):
                    """Strip whitespace from name."""
                    return v.strip()
        ''',
        )
        results = extract_from_python_file(p)
        validators = [
            r for r in results if r.provenance.extraction_method == "ast_pydantic_validator"
        ]
        assert len(validators) == 1
        assert "Strip whitespace" in validators[0].text

    def test_validator_confidence(self, tmp_path: Path) -> None:
        p = _write_py(
            tmp_path,
            """\
            from pydantic import BaseModel, field_validator

            class X(BaseModel):
                v: int

                @field_validator("v")
                @classmethod
                def check(cls, v):
                    return v
        """,
        )
        results = extract_from_python_file(p)
        validators = [
            r for r in results if r.provenance.extraction_method == "ast_pydantic_validator"
        ]
        assert validators[0].confidence == 0.85


class TestFileHandling:
    def test_syntax_error_returns_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.py"
        p.write_text("def broken(:\n", encoding="utf-8")
        assert extract_from_python_file(p) == []

    def test_nonexistent_file_returns_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "missing.py"
        assert extract_from_python_file(p) == []

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.py"
        p.write_text("", encoding="utf-8")
        assert extract_from_python_file(p) == []

    def test_assertion_ids_are_deterministic(self, tmp_path: Path) -> None:
        p = _write_py(
            tmp_path,
            """\
            assert True
        """,
        )
        r1 = extract_from_python_file(p)
        r2 = extract_from_python_file(p)
        assert r1[0].assertion_id == r2[0].assertion_id
        assert len(r1[0].assertion_id) == 16


class TestCombinedExtraction:
    def test_all_three_types_from_one_file(self, tmp_path: Path) -> None:
        p = _write_py(
            tmp_path,
            '''\
            """Callers MUST authenticate first."""

            from pydantic import BaseModel, field_validator

            class Service(BaseModel):
                name: str

                @field_validator("name")
                @classmethod
                def check_name(cls, v):
                    assert v, "name required"
                    return v.strip()

            def run():
                svc = Service(name="test")
                assert svc.name
        ''',
        )
        results = extract_from_python_file(p)
        invariants = [r for r in results if r.assertion_type == AssertionType.INVARIANT]
        constraints = [r for r in results if r.assertion_type == AssertionType.CONSTRAINT]
        assert len(invariants) >= 2
        assert len(constraints) >= 2
