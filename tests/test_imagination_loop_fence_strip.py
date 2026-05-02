"""Tests for the audit-QW1 fence-strip recovery path in imagination_loop.

Audit `/tmp/effect-cam-orchestration-audit-2026-05-02.md` §R1: pydantic-ai
structured output fails ~50% of ticks because Command-R 35B and similar
models wrap valid JSON in ```json fences. The new
``_strip_markdown_fences`` + ``_try_parse_fragment_json`` helpers recover
those fragments BEFORE the markdown-extraction fallback (which defaults
salience to 0.2 and suppresses material/dimensional richness).

The tests cover four cases:

1. Bare JSON parses correctly (passthrough — no fences to strip).
2. Fenced JSON parses correctly (the dominant audit-flagged failure mode).
3. Free-form prose returns None (callers fall through to markdown extractor).
4. Malformed fenced JSON returns None (callers fall through, no crash).

A regression pin asserts that recovered fragments preserve the model's
actual salience instead of falling to the markdown-default 0.2.
"""

from __future__ import annotations

import json

from agents.imagination_loop import (
    _extract_fragment_from_markdown,
    _strip_markdown_fences,
    _try_parse_fragment_json,
)


def _canonical_fragment_dict() -> dict:
    """A complete ImaginationFragment payload with non-default salience."""
    return {
        "dimensions": {
            "intensity": 0.6,
            "tension": 0.3,
            "depth": 0.5,
            "coherence": 0.7,
            "spectral_color": 0.4,
            "temporal_distortion": 0.2,
            "degradation": 0.1,
            "pitch_displacement": 0.5,
            "diffusion": 0.5,
        },
        "salience": 0.55,
        "continuation": False,
        "narrative": "rain over wet stone, slow gathering",
        "material": "water",
    }


# ── _strip_markdown_fences ─────────────────────────────────────────────


class TestStripMarkdownFences:
    def test_no_fence_passthrough(self) -> None:
        text = '{"salience": 0.5}'
        assert _strip_markdown_fences(text) == text

    def test_json_fence_stripped(self) -> None:
        body = '{"salience": 0.5}'
        fenced = f"```json\n{body}\n```"
        assert _strip_markdown_fences(fenced) == body

    def test_bare_fence_stripped(self) -> None:
        body = '{"salience": 0.5}'
        fenced = f"```\n{body}\n```"
        assert _strip_markdown_fences(fenced) == body

    def test_lang_fence_stripped(self) -> None:
        body = '{"salience": 0.5}'
        fenced = f"```python\n{body}\n```"
        assert _strip_markdown_fences(fenced) == body

    def test_leading_whitespace_tolerated(self) -> None:
        body = '{"salience": 0.5}'
        fenced = f"   \n```json\n{body}\n```"
        assert _strip_markdown_fences(fenced) == body

    def test_short_fence_returns_original(self) -> None:
        # Fence with no body and no newline → return original (caller
        # decides whether to bail out or fall through).
        text = "```"
        assert _strip_markdown_fences(text) == text

    def test_empty_string_returns_empty(self) -> None:
        assert _strip_markdown_fences("") == ""


# ── _try_parse_fragment_json ───────────────────────────────────────────


class TestTryParseFragmentJson:
    def test_bare_json_recovers(self) -> None:
        payload = _canonical_fragment_dict()
        text = json.dumps(payload)
        fragment = _try_parse_fragment_json(text)
        assert fragment is not None
        assert fragment.salience == 0.55
        assert fragment.material == "water"
        assert fragment.dimensions["intensity"] == 0.6
        assert len(fragment.dimensions) == 9

    def test_fenced_json_recovers(self) -> None:
        """The dominant audit-flagged failure mode: valid JSON wrapped in ```json fences."""
        payload = _canonical_fragment_dict()
        body = json.dumps(payload)
        fenced = f"```json\n{body}\n```"
        fragment = _try_parse_fragment_json(fenced)
        assert fragment is not None
        assert fragment.salience == 0.55, (
            "fence-stripped recovery must preserve the model's actual salience, "
            "NOT fall through to markdown-fallback's default 0.2"
        )
        assert fragment.material == "water"
        assert len(fragment.dimensions) == 9

    def test_bare_fence_json_recovers(self) -> None:
        """Some models emit ``` (no language tag) — must also work."""
        payload = _canonical_fragment_dict()
        body = json.dumps(payload)
        fenced = f"```\n{body}\n```"
        fragment = _try_parse_fragment_json(fenced)
        assert fragment is not None
        assert fragment.salience == 0.55

    def test_free_form_prose_returns_none(self) -> None:
        """Pure markdown / prose must return None so caller falls through."""
        text = "## Imagination\n\nI see a slow rainfall on the stones..."
        assert _try_parse_fragment_json(text) is None

    def test_malformed_fenced_json_returns_none(self) -> None:
        """Invalid JSON inside fences must not raise — return None."""
        fenced = "```json\n{not valid json}\n```"
        assert _try_parse_fragment_json(fenced) is None

    def test_json_missing_required_field_returns_none(self) -> None:
        """Validation failure (e.g., missing 'narrative') returns None."""
        partial = {"dimensions": {}, "salience": 0.5, "continuation": False}
        # Missing 'narrative' which is required (no default).
        text = json.dumps(partial)
        assert _try_parse_fragment_json(text) is None

    def test_empty_text_returns_none(self) -> None:
        assert _try_parse_fragment_json("") is None
        assert _try_parse_fragment_json("   ") is None

    def test_text_not_starting_with_brace_returns_none(self) -> None:
        """Defensive: leading prose before JSON returns None (don't try to slice)."""
        text = "Sure! Here's the JSON:\n" + json.dumps(_canonical_fragment_dict())
        # Starts with prose, not '{', not a fence either → None.
        assert _try_parse_fragment_json(text) is None


# ── Recovery-path interaction with markdown extractor ──────────────────


class TestRecoveryPathInteraction:
    def test_json_recovery_preserves_salience_vs_markdown_fallback(self) -> None:
        """Regression pin for the audit's headline finding: markdown extractor
        defaults salience to 0.2 when not in the text. The new JSON-fence
        recovery path keeps the model's actual salience (0.55 here)."""
        payload = _canonical_fragment_dict()
        fenced = f"```json\n{json.dumps(payload)}\n```"

        # Old path: markdown extractor on fenced JSON → either fails or
        # finds the literal "salience": 0.55 substring via regex.
        markdown_result = _extract_fragment_from_markdown(fenced)
        # New path: JSON recovery returns the parsed model.
        json_result = _try_parse_fragment_json(fenced)

        assert json_result is not None
        assert json_result.salience == 0.55
        # The new path's salience must equal the model's actual emission.
        # The audit's complaint was that the OLD path returned 0.20
        # (markdown default) for ~50% of fenced responses. Whether the
        # markdown extractor coincidentally finds salience here is
        # model-dependent; the regression pin is on the JSON path.
        if markdown_result is not None and markdown_result.salience == 0.2:
            # This is exactly the audit-flagged failure mode the new
            # path is designed to replace.
            assert json_result.salience > markdown_result.salience

    def test_free_form_only_recovers_via_markdown(self) -> None:
        """Markdown-style prose must still route through markdown extractor."""
        text = (
            "## Imagination\n\nA slow blue rain.\n\n"
            "## Expressive\nintensity: 0.4\nsalience: 0.6\n"
            "material: water"
        )
        assert _try_parse_fragment_json(text) is None
        markdown = _extract_fragment_from_markdown(text)
        assert markdown is not None
        assert markdown.material == "water"
