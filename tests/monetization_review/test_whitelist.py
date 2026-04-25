"""Whitelist semantics + the critical Ring-1-high invariant.

Plan §Phase 10 success criteria — the hard test that the operator
whitelist NEVER bypasses the Ring 1 high-risk filter lives here as
``TestNeverBypassesRing1High``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from agents.monetization_review.whitelist import (
    EMPTY_WHITELIST_TEMPLATE,
    Whitelist,
)


@dataclass
class _Candidate:
    """Minimal SelectionCandidate-like for gate.assess()."""

    capability_name: str
    payload: dict[str, Any]


class TestEmptyAndMissing:
    def test_empty_whitelist_has_no_entries(self) -> None:
        wl = Whitelist.empty()
        assert wl.exact == ()
        assert wl.regex == ()
        assert wl.capabilities == frozenset()

    def test_load_missing_file_returns_empty(self, tmp_path: Path) -> None:
        wl = Whitelist.load(tmp_path / "nonexistent.yaml")
        assert wl.exact == ()
        assert wl.regex == ()
        assert wl.capabilities == frozenset()


class TestLoad:
    def test_loads_exact_strings(self, tmp_path: Path) -> None:
        path = tmp_path / "wl.yaml"
        path.write_text("exact:\n  - hello world\n  - foo bar\n", encoding="utf-8")
        wl = Whitelist.load(path)
        assert wl.exact == ("hello world", "foo bar")

    def test_loads_regex_with_notes(self, tmp_path: Path) -> None:
        path = tmp_path / "wl.yaml"
        # Single-quoted YAML scalar — backslash is literal, so the YAML
        # source ``'^safe \d+$'`` parses to the Python string
        # ``^safe \d+$`` which compiles to the digit-class regex.
        path.write_text(
            "regex:\n  - pattern: '^safe \\d+$'\n    note: operator approved\n",
            encoding="utf-8",
        )
        wl = Whitelist.load(path)
        assert len(wl.regex) == 1
        pattern, note = wl.regex[0]
        assert pattern.pattern == r"^safe \d+$"
        assert note == "operator approved"

    def test_loads_bare_regex_strings(self, tmp_path: Path) -> None:
        path = tmp_path / "wl.yaml"
        path.write_text("regex:\n  - 'abc.*'\n", encoding="utf-8")
        wl = Whitelist.load(path)
        assert len(wl.regex) == 1
        assert wl.regex[0][0].pattern == "abc.*"

    def test_loads_capability_names(self, tmp_path: Path) -> None:
        path = tmp_path / "wl.yaml"
        path.write_text(
            "capabilities:\n  - knowledge.web_search\n  - chronicle.synthesize\n", encoding="utf-8"
        )
        wl = Whitelist.load(path)
        assert wl.capabilities == frozenset({"knowledge.web_search", "chronicle.synthesize"})

    def test_malformed_yaml_returns_empty_no_raise(self, tmp_path: Path) -> None:
        path = tmp_path / "wl.yaml"
        path.write_text("exact: [unterminated\n", encoding="utf-8")
        wl = Whitelist.load(path)
        assert wl.exact == ()
        assert wl.regex == ()

    def test_invalid_regex_skipped_with_warn(self, tmp_path: Path, caplog: Any) -> None:
        path = tmp_path / "wl.yaml"
        path.write_text("regex:\n  - '[unterminated'\n  - 'good.*'\n", encoding="utf-8")
        wl = Whitelist.load(path)
        assert len(wl.regex) == 1
        assert wl.regex[0][0].pattern == "good.*"


class TestMatch:
    def test_exact_match_hit(self) -> None:
        wl = Whitelist(exact=("hello world",))
        matched, reason = wl.matches_payload("hello world")
        assert matched
        assert "exact-match" in reason

    def test_exact_match_miss(self) -> None:
        wl = Whitelist(exact=("hello world",))
        matched, reason = wl.matches_payload("hello world!")
        assert not matched
        assert reason == ""

    def test_regex_match_hit(self) -> None:
        wl = Whitelist(regex=((re.compile(r"^safe \d+$"), "approved"),))
        matched, reason = wl.matches_payload("safe 42")
        assert matched
        assert "approved" in reason

    def test_regex_search_not_anchored_by_default(self) -> None:
        wl = Whitelist(regex=((re.compile(r"midword"), ""),))
        matched, _ = wl.matches_payload("a midword phrase")
        assert matched

    def test_capability_match_hit(self) -> None:
        wl = Whitelist(capabilities=frozenset({"knowledge.web_search"}))
        matched, reason = wl.matches_capability("knowledge.web_search")
        assert matched
        assert "knowledge.web_search" in reason

    def test_capability_match_miss(self) -> None:
        wl = Whitelist(capabilities=frozenset({"knowledge.web_search"}))
        matched, _ = wl.matches_capability("chronicle.synthesize")
        assert not matched

    def test_payload_string_coercion(self) -> None:
        wl = Whitelist(exact=("{'k': 'v'}",))
        matched, _ = wl.matches_payload({"k": "v"})
        assert matched


class TestAppend:
    def test_append_exact_creates_file(self, tmp_path: Path) -> None:
        path = tmp_path / "wl.yaml"
        wl = Whitelist.empty()
        wl.append_exact("hello", path=path)
        assert path.exists()
        loaded = Whitelist.load(path)
        assert "hello" in loaded.exact

    def test_append_regex_validates(self, tmp_path: Path) -> None:
        path = tmp_path / "wl.yaml"
        wl = Whitelist.empty()
        with pytest.raises(re.error):
            wl.append_regex("[unterminated", path=path)

    def test_append_persists_across_load(self, tmp_path: Path) -> None:
        path = tmp_path / "wl.yaml"
        wl = Whitelist.empty()
        wl.append_exact("phrase one", path=path)
        wl.append_capability("cap.one", path=path)
        wl.append_regex(r"^pat\d+$", note="note", path=path)
        loaded = Whitelist.load(path)
        assert "phrase one" in loaded.exact
        assert "cap.one" in loaded.capabilities
        assert any(p.pattern == r"^pat\d+$" for p, _ in loaded.regex)


class TestNeverBypassesRing1High:
    """Critical invariant from plan §Phase 10 success criteria.

    The operator whitelist NARROWS Ring 2 only. It MUST NEVER allow a
    capability whose Ring 1 catalog declaration is ``risk == "high"``.

    Tests construct the active whitelist with the broadest possible
    matches (capability-name + exact-payload + regex-catch-all) and
    assert that a Ring-1-high candidate still blocks unconditionally.
    """

    def test_capability_whitelist_does_not_bypass_ring1_high(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Force the gate to load our fully-permissive whitelist.
        path = tmp_path / "wl.yaml"
        path.write_text(
            "exact:\n  - any payload\nregex:\n  - '.*'\ncapabilities:\n  - dangerous.cap\n",
            encoding="utf-8",
        )
        from shared.governance import monetization_safety as gate_mod

        gate_mod.reload_whitelist(path)
        try:
            candidate = _Candidate(
                capability_name="dangerous.cap",
                payload={"monetization_risk": "high", "risk_reason": "catalog floor"},
            )
            assessment = gate_mod.GATE.assess(
                candidate,
                programme=None,
                surface=gate_mod.SurfaceKind.TTS,
                rendered_payload="any payload",
            )
            assert assessment.allowed is False
            assert assessment.risk == "high"
            assert "high-risk" in assessment.reason or "blocked" in assessment.reason
        finally:
            gate_mod.reload_whitelist(tmp_path / "_nonexistent.yaml")

    def test_payload_whitelist_does_not_bypass_ring1_high(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "wl.yaml"
        path.write_text("exact:\n  - exact payload\n", encoding="utf-8")
        from shared.governance import monetization_safety as gate_mod

        gate_mod.reload_whitelist(path)
        try:
            candidate = _Candidate(
                capability_name="dangerous.cap",
                payload={"monetization_risk": "high"},
            )
            # Even though the rendered payload exactly matches, Ring 1 high
            # short-circuits before any whitelist lookup.
            assessment = gate_mod.GATE.assess(
                candidate,
                programme=None,
                surface=gate_mod.SurfaceKind.TTS,
                rendered_payload="exact payload",
            )
            assert assessment.allowed is False
            assert assessment.risk == "high"
        finally:
            gate_mod.reload_whitelist(tmp_path / "_nonexistent.yaml")

    def test_no_ring2_no_whitelist_consulted(self, tmp_path: Path) -> None:
        """Whitelist must not affect Ring-1-only flow even on medium risk."""
        path = tmp_path / "wl.yaml"
        path.write_text("capabilities:\n  - medium.cap\n", encoding="utf-8")
        from shared.governance import monetization_safety as gate_mod

        gate_mod.reload_whitelist(path)
        try:
            # Medium-risk + no programme opt-in + no Ring 2 classifier passed.
            # Whitelist must NOT short-circuit — Ring 2 wasn't used.
            candidate = _Candidate(
                capability_name="medium.cap",
                payload={"monetization_risk": "medium"},
            )
            assessment = gate_mod.GATE.assess(candidate, programme=None)
            assert assessment.allowed is False
            assert "programme opt-in" in assessment.reason
        finally:
            gate_mod.reload_whitelist(tmp_path / "_nonexistent.yaml")


class TestEmptyTemplate:
    def test_template_is_valid_yaml(self) -> None:
        import yaml

        parsed = yaml.safe_load(EMPTY_WHITELIST_TEMPLATE)
        assert isinstance(parsed, dict)
        assert parsed.get("exact") == []
        assert parsed.get("regex") == []
        assert parsed.get("capabilities") == []
