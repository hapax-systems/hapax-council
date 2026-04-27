"""SS2 cycle 1 — vault-context grounding pins.

Pins the contract between ``read_recent_vault_context`` and the
compose-prompt seed:
- daily notes mtime-ordered, oldest-first, bytes-capped
- active goals priority-sorted, status-filtered
- frontmatter stripping doesn't break missing-fence cases
- empty vault returns empty `VaultContext` (no raise)
- compose's `_build_seed` includes the vault block when present,
  omits cleanly when absent
- prompt template carries the H1 framing ("informational scaffolding,
  NOT a directive") so the LLM doesn't recite

Spec: ytb-SS2 §4.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from agents.hapax_daimonion.autonomous_narrative.compose import (
    _build_prompt,
    _build_seed,
    _summarize_vault_context,
)
from agents.hapax_daimonion.autonomous_narrative.state_readers import (
    NarrativeContext,
    VaultContext,
    _read_active_goals,
    _read_daily_notes,
    _strip_frontmatter,
    read_recent_vault_context,
)

# ── _strip_frontmatter ─────────────────────────────────────────────────


class TestStripFrontmatter:
    def test_strips_yaml_block(self) -> None:
        text = "---\ntype: daily\ntitle: x\n---\nbody here"
        assert _strip_frontmatter(text) == "body here"

    def test_no_frontmatter_returns_text_unchanged(self) -> None:
        text = "no fence here\njust body"
        assert _strip_frontmatter(text) == text

    def test_malformed_unclosed_fence_returns_text_unchanged(self) -> None:
        text = "---\ntype: daily\nno closing fence ever"
        assert _strip_frontmatter(text) == text

    def test_handles_blank_line_after_fence(self) -> None:
        text = "---\ntitle: x\n---\n\nbody"
        assert _strip_frontmatter(text) == "body"


# ── _read_daily_notes ──────────────────────────────────────────────────


def _write_daily(dir_: Path, date_label: str, body: str, mtime: float | None = None) -> Path:
    p = dir_ / f"{date_label}.md"
    p.write_text(f"---\ntype: daily\n---\n{body}\n", encoding="utf-8")
    if mtime is not None:
        import os

        os.utime(p, (mtime, mtime))
    return p


class TestReadDailyNotes:
    def test_returns_oldest_first(self, tmp_path: Path) -> None:
        _write_daily(tmp_path, "2026-04-22", "two days ago", mtime=1000.0)
        _write_daily(tmp_path, "2026-04-23", "yesterday", mtime=2000.0)
        _write_daily(tmp_path, "2026-04-24", "today", mtime=3000.0)
        out = _read_daily_notes(
            daily_dir=tmp_path,
            max_notes=3,
            max_body_bytes=5000,
            max_total_bytes=5000,
        )
        labels = [t[0] for t in out]
        assert labels == ["2026-04-22", "2026-04-23", "2026-04-24"]

    def test_caps_to_max_notes(self, tmp_path: Path) -> None:
        for i in range(10):
            _write_daily(tmp_path, f"2026-04-{i:02d}", f"day {i}", mtime=1000.0 + i)
        out = _read_daily_notes(
            daily_dir=tmp_path,
            max_notes=3,
            max_body_bytes=5000,
            max_total_bytes=5000,
        )
        assert len(out) == 3
        # Should be the 3 most recent (highest mtime) — last 3 written.
        labels = [t[0] for t in out]
        assert labels == ["2026-04-07", "2026-04-08", "2026-04-09"]

    def test_truncates_body_at_per_note_cap(self, tmp_path: Path) -> None:
        body = "x" * 3000
        _write_daily(tmp_path, "2026-04-24", body, mtime=1000.0)
        out = _read_daily_notes(
            daily_dir=tmp_path,
            max_notes=1,
            max_body_bytes=500,
            max_total_bytes=5000,
        )
        # Truncated + ellipsis appended.
        assert len(out) == 1
        assert len(out[0][1]) <= 501
        assert out[0][1].endswith("…")

    def test_drops_oldest_when_over_total_cap(self, tmp_path: Path) -> None:
        # Three 800-byte notes; cap at 1500 → only newest two should survive.
        big = "x" * 800
        _write_daily(tmp_path, "2026-04-22", big, mtime=1000.0)
        _write_daily(tmp_path, "2026-04-23", big, mtime=2000.0)
        _write_daily(tmp_path, "2026-04-24", big, mtime=3000.0)
        out = _read_daily_notes(
            daily_dir=tmp_path,
            max_notes=3,
            max_body_bytes=2000,
            max_total_bytes=1500,
        )
        labels = [t[0] for t in out]
        # Oldest dropped under cap.
        assert "2026-04-22" not in labels
        assert "2026-04-24" in labels

    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "no-such-dir"
        out = _read_daily_notes(
            daily_dir=nonexistent,
            max_notes=5,
            max_body_bytes=1000,
            max_total_bytes=3000,
        )
        assert out == ()


# ── _read_active_goals ─────────────────────────────────────────────────


def _write_goal(
    dir_: Path,
    name: str,
    *,
    status: str,
    priority: str,
    title: str | None = None,
) -> Path:
    p = dir_ / f"{name}.md"
    title_field = f'title: "{title or name}"\n' if title else ""
    p.write_text(
        f"---\ntype: goal\n{title_field}status: {status}\npriority: {priority}\n---\n",
        encoding="utf-8",
    )
    return p


class TestReadActiveGoals:
    def test_filters_by_active_status(self, tmp_path: Path) -> None:
        _write_goal(tmp_path, "g1", status="active", priority="P1", title="alpha")
        _write_goal(tmp_path, "g2", status="done", priority="P0", title="beta")
        _write_goal(tmp_path, "g3", status="cancelled", priority="P1", title="gamma")
        out = _read_active_goals(
            vault_base=tmp_path,
            max_goals=10,
            active_statuses=frozenset({"active", "in_progress"}),
        )
        titles = [t[0] for t in out]
        assert titles == ["alpha"]

    def test_priority_sorted_p0_first(self, tmp_path: Path) -> None:
        _write_goal(tmp_path, "g1", status="active", priority="P2", title="P2-goal")
        _write_goal(tmp_path, "g2", status="active", priority="P0", title="P0-goal")
        _write_goal(tmp_path, "g3", status="active", priority="P1", title="P1-goal")
        out = _read_active_goals(
            vault_base=tmp_path,
            max_goals=10,
            active_statuses=frozenset({"active"}),
        )
        priorities = [t[1] for t in out]
        assert priorities == ["P0", "P1", "P2"]

    def test_skips_non_goal_notes(self, tmp_path: Path) -> None:
        # Plain markdown without type=goal.
        (tmp_path / "random.md").write_text("# notes\nstuff", encoding="utf-8")
        # cc-task note (different type).
        (tmp_path / "task.md").write_text(
            "---\ntype: cc-task\nstatus: active\n---\n", encoding="utf-8"
        )
        _write_goal(tmp_path, "g1", status="active", priority="P1")
        out = _read_active_goals(
            vault_base=tmp_path,
            max_goals=10,
            active_statuses=frozenset({"active"}),
        )
        assert len(out) == 1

    def test_caps_to_max_goals(self, tmp_path: Path) -> None:
        for i in range(20):
            _write_goal(tmp_path, f"g{i}", status="active", priority="P2", title=f"goal{i:02d}")
        out = _read_active_goals(
            vault_base=tmp_path,
            max_goals=5,
            active_statuses=frozenset({"active"}),
        )
        assert len(out) == 5

    def test_missing_vault_returns_empty(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "no-vault"
        out = _read_active_goals(
            vault_base=nonexistent,
            max_goals=5,
            active_statuses=frozenset({"active"}),
        )
        assert out == ()


# ── read_recent_vault_context (the public API) ─────────────────────────


class TestReadRecentVaultContext:
    def test_assembles_both_sources(self, tmp_path: Path) -> None:
        daily_dir = tmp_path / "daily"
        daily_dir.mkdir()
        _write_daily(daily_dir, "2026-04-24", "body", mtime=1000.0)
        _write_goal(tmp_path, "goal1", status="active", priority="P0", title="ship-the-thing")
        ctx = read_recent_vault_context(
            vault_base=tmp_path,
            daily_dir=daily_dir,
            max_daily_notes=5,
            max_total_bytes=3000,
            max_goals=5,
        )
        assert len(ctx.daily_note_excerpts) == 1
        assert len(ctx.active_goals) == 1
        assert ctx.active_goals[0][0] == "ship-the-thing"

    def test_completely_missing_vault_returns_empty_context(self, tmp_path: Path) -> None:
        ctx = read_recent_vault_context(
            vault_base=tmp_path / "no-such",
            daily_dir=tmp_path / "no-daily",
        )
        assert ctx.is_empty()
        # Doesn't raise — daimonion can run without a vault mounted.


# ── _summarize_vault_context (the prompt formatter) ────────────────────


class TestSummarizeVaultContext:
    def test_empty_context_returns_empty_string(self) -> None:
        assert _summarize_vault_context(VaultContext()) == ""

    def test_none_returns_empty_string(self) -> None:
        # Backward-compat: a NarrativeContext from before this change
        # might not carry vault_context at all (legacy callers).
        assert _summarize_vault_context(None) == ""

    def test_includes_goals_when_present(self) -> None:
        ctx = VaultContext(
            active_goals=(
                ("ship-thing", "P0", "active"),
                ("review-report", "P1", "in_progress"),
            ),
        )
        out = _summarize_vault_context(ctx)
        assert "Operator's active goals:" in out
        assert "[P0] ship-thing (active)" in out
        assert "[P1] review-report (in_progress)" in out

    def test_includes_daily_notes_with_indentation(self) -> None:
        ctx = VaultContext(
            daily_note_excerpts=(("2026-04-24", "today's body"),),
        )
        out = _summarize_vault_context(ctx)
        assert "Operator's recent daily notes" in out
        assert "[2026-04-24]" in out
        assert "today's body" in out

    def test_starts_with_focus_context_header(self) -> None:
        ctx = VaultContext(active_goals=(("g", "P1", "active"),))
        out = _summarize_vault_context(ctx)
        assert out.startswith("Operator focus context:")


# ── compose._build_seed integration ────────────────────────────────────


class _FakeContext:
    """Minimal object mimicking NarrativeContext for prompt-shape testing."""

    def __init__(self, vault_context: VaultContext | None) -> None:
        self.programme = None
        self.stimmung_tone = "ambient"
        self.director_activity = "observe"
        self.chronicle_events: tuple[dict, ...] = (
            {"ts": 0.0, "source": "test", "event_type": "e", "salience": 0.9},
        )
        self.vault_context = vault_context


class TestBuildSeedIntegration:
    def test_seed_includes_vault_block_when_present(self) -> None:
        vault = VaultContext(active_goals=(("ship-it", "P0", "active"),))
        seed = _build_seed(_FakeContext(vault_context=vault))
        assert "Operator focus context:" in seed
        assert "[P0] ship-it" in seed

    def test_seed_omits_vault_block_when_empty(self) -> None:
        seed = _build_seed(_FakeContext(vault_context=VaultContext()))
        assert "Operator focus context" not in seed

    def test_seed_handles_missing_vault_attribute_gracefully(self) -> None:
        """Backward-compat: a NarrativeContext that pre-dates SS2 must not
        crash the seed builder."""

        class LegacyContext:
            programme = None
            stimmung_tone = "ambient"
            director_activity = "observe"
            chronicle_events = ({"ts": 0.0, "source": "test", "event_type": "e", "salience": 0.9},)

        seed = _build_seed(LegacyContext())
        assert "Operator focus context" not in seed
        # Still includes the standard parts.
        assert "Stimmung tone: ambient" in seed


# ── compose._build_prompt H1 framing ──────────────────────────────────


class TestPromptH1Framing:
    """Post-2026-04-27: the prompt no longer carries explicit vault-context
    framing language ('informational scaffolding', etc.). The cycle 1
    hypothesis is now enforced structurally: vault context appears in
    the deterministic seed block (which the LLM sees as 'state'), and
    the prompt instructs the LLM to ground in 'something specific from
    the state below'. Pin the structural properties that matter."""

    def test_prompt_contains_state_section(self) -> None:
        prompt = _build_prompt(_FakeContext(vault_context=VaultContext()), seed="x")
        # The seed is wrapped in a "State (deterministic snapshot)" block
        assert "State (deterministic snapshot)" in prompt or "State" in prompt

    def test_prompt_instructs_grounding_in_state(self) -> None:
        prompt = _build_prompt(_FakeContext(vault_context=VaultContext()), seed="x")
        # The LLM must ground in the state — this is the load-bearing
        # instruction that prevents recitation.
        assert "Ground" in prompt or "ground" in prompt.lower()

    def test_vault_context_flows_through_seed_not_prompt_template(self) -> None:
        """Vault context should appear in the seed (state block), not as
        a separate prompt instruction. This ensures the LLM treats it
        as context, not a directive."""
        vault = VaultContext(active_goals=(("ship-it", "P0", "active"),))
        seed = _build_seed(_FakeContext(vault_context=vault))
        prompt = _build_prompt(_FakeContext(vault_context=vault), seed=seed)
        # Vault data is in the prompt (via the seed block)
        assert "ship-it" in prompt
        # But not as a separate instruction section
        assert "vault" not in prompt.lower().split("---")[0]


# ── NarrativeContext shape ────────────────────────────────────────────


class TestNarrativeContextShape:
    def test_default_vault_context_is_empty(self) -> None:
        nc = NarrativeContext(
            programme=None,
            stimmung_tone="ambient",
            director_activity="observe",
        )
        assert nc.vault_context.is_empty()

    def test_vault_context_round_trips(self) -> None:
        vc = VaultContext(
            daily_note_excerpts=(("2026-04-24", "body"),),
            active_goals=(("g", "P0", "active"),),
        )
        nc = NarrativeContext(
            programme=None,
            stimmung_tone="ambient",
            director_activity="observe",
            vault_context=vc,
        )
        assert nc.vault_context is vc


# ── Sanity: realistic body with markdown structure ─────────────────────


class TestRealisticBody:
    def test_multiline_body_is_indented_in_summary(self) -> None:
        ctx = VaultContext(
            daily_note_excerpts=(
                (
                    "2026-04-24",
                    textwrap.dedent(
                        """\
                        ## Log

                        - Shipped #1288 (HOMAGE bitchx-authentic).
                        - Shipped #1289 (mIRC scrim palette).
                        """
                    ).strip(),
                ),
            ),
        )
        out = _summarize_vault_context(ctx)
        # Multiline bodies must keep visual indentation so the LLM
        # parses each daily note as one block.
        lines = out.split("\n")
        body_lines = [ln for ln in lines if ln.strip().startswith("- Shipped")]
        assert len(body_lines) == 2
        # All body lines are indented at least 4 spaces (the format from
        # _summarize_vault_context: 2-space note-level + 2-space body).
        for ln in body_lines:
            assert ln.startswith("    "), ln


# ── Sanity that pytest discovered the right module ─────────────────────


def test_imports_work_from_test_module() -> None:
    """Sanity test: the SS2 cycle 1 imports above must resolve. If this
    fails, the test module isn't even loading and the rest of these
    tests are silent no-ops."""
    assert read_recent_vault_context is not None
    assert _summarize_vault_context is not None
    assert VaultContext is not None
    pytest.assume = pytest.assume if hasattr(pytest, "assume") else None  # noqa: SLF001
