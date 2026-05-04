"""Tests for the four lore-ward Gibson-verb affordance entries.

Cc-task ``programme-wards-gibson-verb-affordances`` (2026-05-04).
Wires the four lore wards (precedent_ticker, programme_history,
research_instrument_dashboard, interactive_lore_query) into the
``shared.affordance_registry`` so the AffordancePipeline can recruit
them via cosine similarity against impingement narratives.

Per ``hapax-council/CLAUDE.md`` § Unified Semantic Recruitment, every
capability has a Gibson-verb description (15-30 words, cognitive
function not implementation). These tests pin the rubric:

* every entry exists,
* description is in the 15-30 word band,
* description is verb-led (first content word is a verb),
* entry is in ``ALL_AFFORDANCES`` so ``init_pipeline``'s
  ``index_capabilities_batch`` will pick it up,
* operational properties are consistent (visual medium, persistence,
  consent gate where required).
"""

from __future__ import annotations

import re

import pytest

from shared.affordance_registry import (
    ALL_AFFORDANCES,
    LORE_WARD_AFFORDANCES,
)

# Source IDs from the ward classes — these MUST match the ``source_id``
# attribute on each CairoSource subclass so AffordancePipeline recruitment
# winners route back to the correct in-tree ward.
LORE_WARD_NAMES = (
    "lore_ward.precedent_ticker",
    "lore_ward.programme_history",
    "lore_ward.research_instrument_dashboard",
    "lore_ward.interactive_lore_query",
)


# Verb-led check is permissive — we accept any English verb as the first
# content word, including imperatives ("Render", "Surface", "Display",
# "Respond"). This list is the set we use across the lore-ward entries;
# adding an entry with a different leading verb is fine, just extend the
# set so the rubric stays mechanically checkable.
LEADING_VERBS_ACCEPTED = frozenset(
    {
        # Lore-ward leading verbs in this PR
        "surface",
        "render",
        "display",
        "respond",
        # Other Gibson-verb leads commonly used elsewhere in the registry
        "compose",
        "compute",
        "highlight",
        "sense",
        "recall",
        "elevate",
        "track",
        "report",
        "acknowledge",
        "answer",
        "swap",
        "bias",
    }
)


def _word_count(text: str) -> int:
    """Count words separated by whitespace, ignoring punctuation."""

    return len(re.findall(r"\b[\w'-]+\b", text))


def _first_content_word(text: str) -> str:
    """Return the first content word, lowercased."""

    match = re.search(r"\b([\w'-]+)\b", text)
    return match.group(1).lower() if match else ""


# ── 1. Inventory ────────────────────────────────────────────────────────────


class TestLoreWardInventory:
    def test_all_four_wards_have_entries(self):
        names = {rec.name for rec in LORE_WARD_AFFORDANCES}
        assert names == set(LORE_WARD_NAMES), f"expected exactly the 4 lore-ward names, got {names}"

    @pytest.mark.parametrize("name", LORE_WARD_NAMES)
    def test_entry_in_all_affordances(self, name):
        names = {rec.name for rec in ALL_AFFORDANCES}
        assert name in names, f"{name!r} missing from ALL_AFFORDANCES — pipeline won't recruit it"

    def test_no_duplicate_lore_ward_names(self):
        names = [rec.name for rec in LORE_WARD_AFFORDANCES]
        assert len(names) == len(set(names))

    def test_lore_ward_namespace_is_consistent(self):
        """Every lore-ward entry uses the ``lore_ward.`` prefix."""

        for rec in LORE_WARD_AFFORDANCES:
            assert rec.name.startswith("lore_ward."), (
                f"{rec.name!r} not under the lore_ward namespace"
            )


# ── 2. Gibson-verb description rubric ───────────────────────────────────────


class TestGibsonVerbDescriptionRubric:
    @pytest.mark.parametrize("rec", LORE_WARD_AFFORDANCES, ids=lambda r: r.name)
    def test_word_count_in_band(self, rec):
        """Per CLAUDE.md unified semantic recruitment: 15-30 words.

        Tighter than free-form so the embedding cosine target stays
        focused on cognitive function rather than incidental detail.
        """

        wc = _word_count(rec.description)
        assert 15 <= wc <= 30, (
            f"{rec.name!r}: description is {wc} words "
            f"(target 15-30); description={rec.description!r}"
        )

    @pytest.mark.parametrize("rec", LORE_WARD_AFFORDANCES, ids=lambda r: r.name)
    def test_verb_led(self, rec):
        first = _first_content_word(rec.description)
        assert first in LEADING_VERBS_ACCEPTED, (
            f"{rec.name!r}: description does not lead with an accepted "
            f"Gibson-verb (got {first!r}; accepted={sorted(LEADING_VERBS_ACCEPTED)})"
        )

    @pytest.mark.parametrize("rec", LORE_WARD_AFFORDANCES, ids=lambda r: r.name)
    def test_description_is_non_empty_and_stripped(self, rec):
        assert rec.description == rec.description.strip()
        assert rec.description, f"{rec.name!r}: description empty"

    @pytest.mark.parametrize("rec", LORE_WARD_AFFORDANCES, ids=lambda r: r.name)
    def test_description_avoids_implementation_detail(self, rec):
        """Cognitive function, not implementation — flag obvious leaks.

        The rubric says "cognitive function, not implementation". This
        test catches obvious implementation-detail leaks (file paths,
        class names, library names) that would dilute the embedding
        cosine target. Not exhaustive — a description-quality audit
        for the whole registry is its own follow-up.
        """

        forbidden_substrings = (
            ".py",
            "CairoSource",
            "import ",
            "subclass",
            "/dev/shm",
            "Pango",
            "Cairo.Context",
        )
        text = rec.description
        for token in forbidden_substrings:
            assert token not in text, (
                f"{rec.name!r}: description contains implementation-detail "
                f"token {token!r}: {text!r}"
            )


# ── 3. Operational properties ───────────────────────────────────────────────


class TestLoreWardOperationalProperties:
    @pytest.mark.parametrize("rec", LORE_WARD_AFFORDANCES, ids=lambda r: r.name)
    def test_medium_is_visual(self, rec):
        """Every lore ward renders to a Cairo surface — medium='visual'."""

        assert rec.operational.medium == "visual"

    @pytest.mark.parametrize("rec", LORE_WARD_AFFORDANCES, ids=lambda r: r.name)
    def test_daemon_is_compositor(self, rec):
        """Lore wards live in the studio_compositor daemon."""

        assert rec.daemon == "compositor"

    def test_interactive_lore_query_is_consent_gated(self):
        """``interactive_lore_query`` reads chat-author identifiers — gate it.

        Per ``interpersonal_transparency`` axiom, the chat-authority
        allowlist IS the consent record. ``consent_required=True``
        surfaces the gate to the pipeline so non-allowlisted contexts
        route around the ward at recruitment time rather than at render.
        """

        rec = next(r for r in LORE_WARD_AFFORDANCES if r.name == "lore_ward.interactive_lore_query")
        assert rec.operational.consent_required is True

    @pytest.mark.parametrize(
        "name",
        [
            "lore_ward.precedent_ticker",
            "lore_ward.programme_history",
            "lore_ward.research_instrument_dashboard",
        ],
    )
    def test_non_chat_wards_are_consent_free(self, name):
        """Wards that don't read chat-author identifiers don't need consent."""

        rec = next(r for r in LORE_WARD_AFFORDANCES if r.name == name)
        assert rec.operational.consent_required is False

    @pytest.mark.parametrize("rec", LORE_WARD_AFFORDANCES, ids=lambda r: r.name)
    def test_persistence_is_session(self, rec):
        """Lore-ward state is per-session (no cross-session memory)."""

        assert rec.operational.persistence == "session"

    def test_query_ward_has_fast_latency(self):
        """``interactive_lore_query`` reacts to chat (cadence ≤2 Hz, fast tier)."""

        rec = next(r for r in LORE_WARD_AFFORDANCES if r.name == "lore_ward.interactive_lore_query")
        assert rec.operational.latency_class == "fast"

    @pytest.mark.parametrize(
        "name",
        [
            "lore_ward.precedent_ticker",
            "lore_ward.programme_history",
            "lore_ward.research_instrument_dashboard",
        ],
    )
    def test_long_horizon_wards_are_slow_latency(self, name):
        """Static-ish surfaces (history / dashboard) use the slow tier."""

        rec = next(r for r in LORE_WARD_AFFORDANCES if r.name == name)
        assert rec.operational.latency_class == "slow"


# ── 4. Embedding-pipeline integration ───────────────────────────────────────


class TestEmbeddingPipelineIntegration:
    """Soft check that ``init_pipeline.index_capabilities_batch`` will see
    the new entries when the daimonion next starts.

    We can't run the live pipeline here without Qdrant, but we can confirm
    the entries flow through ``ALL_AFFORDANCES`` (which is what
    ``init_pipeline`` reads — see
    ``agents/hapax_daimonion/init_pipeline.py``).
    """

    def test_all_affordances_includes_lore_wards(self):
        all_names = {rec.name for rec in ALL_AFFORDANCES}
        for name in LORE_WARD_NAMES:
            assert name in all_names

    def test_index_pipeline_reads_all_affordances(self):
        """Pin the import path the daimonion uses on startup.

        If this import path moves, the new entries silently won't reach
        the pipeline; pinning the path here catches that drift.
        """

        from agents.hapax_daimonion import init_pipeline

        source = init_pipeline.__file__
        text = open(source, encoding="utf-8").read()
        assert "ALL_AFFORDANCES" in text
        assert "index_capabilities_batch" in text
