"""Lexicon-scan gate for the anti-parasocial implication (su-anti-parasocial-001).

Pins ``axioms/implications/anti-parasocial.yaml``: forbidden host-mode
lexicon must not appear in narration/caption/metadata rendering code
paths. Catches new sites that would silently introduce parasocial
framing to broadcast surfaces.

Scope: this test scans LLM prompt templates and string literals in the
narration/caption/metadata renderers. It does NOT scan documentation
prose, axiom rationale, design-language docs, or test fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
IMPLICATION_PATH = REPO_ROOT / "axioms" / "implications" / "anti-parasocial.yaml"

# Files / dirs in scope for the scan. Narration + caption + metadata
# code paths that render to broadcast surfaces.
SCAN_TARGETS: tuple[Path, ...] = (
    REPO_ROOT / "agents" / "studio_compositor" / "director_loop.py",
    REPO_ROOT / "agents" / "live_captions",
    REPO_ROOT / "agents" / "code_narration",
    REPO_ROOT / "agents" / "hapax_daimonion" / "autonomous_narrative",
)

# Files explicitly excluded — partner-in-conversation declaration,
# axiom rationale prose, design-language docs, and the existing
# host-mode SCRUBBER (compose.py contains regex patterns that MATCH
# the lexicon because it's scrubbing for it; including it would be a
# self-referential false positive).
SCAN_EXCLUDES: tuple[Path, ...] = (
    REPO_ROOT / "agents" / "hapax_daimonion" / "persona.py",
    REPO_ROOT / "agents" / "hapax_daimonion" / "autonomous_narrative" / "compose.py",
)


def _load_forbidden_patterns() -> list[str]:
    data = yaml.safe_load(IMPLICATION_PATH.read_text(encoding="utf-8"))
    return list(data["forbidden_patterns"]["patterns"])


def _iter_python_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target] if target.suffix == ".py" else []
    return sorted(p for p in target.rglob("*.py") if "__pycache__" not in p.parts)


def _scan_file_for_pattern(path: Path, pattern: str) -> list[tuple[int, str]]:
    # Return (line_no, line) tuples where pattern appears. Case-insensitive
    # substring match. Skips lines inside triple-quoted strings (heuristic:
    # toggles state on each line that contains an odd number of triple-quote
    # delimiters). Comments are excluded too.
    hits: list[tuple[int, str]] = []
    pat_lower = pattern.lower()
    in_triple = False
    triple_delim = ""
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.rstrip()
        stripped = line.lstrip()
        if in_triple:
            if triple_delim in line:
                in_triple = False
            continue
        # Detect entering triple-quoted block
        for delim in ('"""', "'''"):
            count = stripped.count(delim)
            if count % 2 == 1:
                in_triple = True
                triple_delim = delim
                break
        if in_triple:
            continue
        # Skip comments
        if stripped.startswith("#"):
            continue
        if pat_lower in line.lower():
            hits.append((lineno, line))
    return hits


class TestAntiParasocialLexicon:
    def test_implication_yaml_loads(self) -> None:
        data = yaml.safe_load(IMPLICATION_PATH.read_text(encoding="utf-8"))
        assert data["implication_id"] == "su-anti-parasocial-001"
        assert data["axiom_id"] == "single_user"
        assert "forbidden_patterns" in data
        patterns = data["forbidden_patterns"]["patterns"]
        assert isinstance(patterns, list)
        assert len(patterns) > 0

    def test_no_forbidden_pattern_in_narration_code(self) -> None:
        """No host-mode lexicon in narration / caption / metadata code paths."""
        patterns = _load_forbidden_patterns()
        violations: list[tuple[Path, str, int, str]] = []
        for target in SCAN_TARGETS:
            if not target.exists():
                continue
            for path in _iter_python_files(target):
                if path in SCAN_EXCLUDES:
                    continue
                for pattern in patterns:
                    for lineno, line in _scan_file_for_pattern(path, pattern):
                        violations.append((path, pattern, lineno, line))
        if violations:
            msg_lines = ["Anti-parasocial lexicon violations:"]
            for path, pattern, lineno, line in violations:
                rel = path.relative_to(REPO_ROOT)
                msg_lines.append(f"  {rel}:{lineno} pattern={pattern!r}: {line.strip()}")
            msg_lines.append("")
            msg_lines.append(
                "These host-mode patterns are forbidden in narration/caption/metadata "
                "rendering code per axioms/implications/anti-parasocial.yaml. "
                "If the match is in documentation prose or a partner-in-conversation "
                "declaration, add the file to SCAN_EXCLUDES."
            )
            pytest.fail("\n".join(msg_lines))

    def test_referenced_excludes_exist(self) -> None:
        """Sanity: SCAN_EXCLUDES paths are real (catches stale excludes)."""
        for path in SCAN_EXCLUDES:
            assert path.exists(), f"SCAN_EXCLUDES references missing path: {path}"
