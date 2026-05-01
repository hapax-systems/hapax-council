"""Tests for ``scripts/cc-task-braid-runner.py``.

Phase 2 of the braid-schema v1.1 evolution. Validates:
  - v1 formula stability (existing 22 tasks compute identically)
  - v1.1 formula matches spec §Schema Specification predicted re-ranking
  - Schema dispatch by ``braid_schema`` discriminator
  - Frontmatter parsing
  - Validation warnings on out-of-range fields
  - forcing-function-urgency timeline mapping
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "cc-task-braid-runner.py"


def _load_module() -> ModuleType:
    name = "cc_task_braid_runner_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_M = _load_module()


def _make_task(**kwargs: object) -> object:
    """Build a TaskFrontmatter with sensible defaults."""
    base = dict(
        task_id="t",
        path=Path("/tmp/t.md"),
        braid_schema="1",
        engagement=0.0,
        monetary=0.0,
        research=0.0,
        tree_effect=0.0,
        evidence_confidence=0.0,
        risk_penalty=0.0,
        forcing_function_window=None,
        unblock_breadth=None,
        polysemic_channels=None,
        funnel_role=None,
        compounding_curve=None,
        axiomatic_strain=None,
        declared_score=None,
    )
    base.update(kwargs)
    return _M.TaskFrontmatter(**base)


# ---------------------------------------------------------------------------
# v1 formula stability
# ---------------------------------------------------------------------------


def test_v1_zero_dimensions_score_zero() -> None:
    t = _make_task(braid_schema="1")
    assert _M.compute_v1_score(t) == 0.0


def test_v1_full_dimensions_match_formula() -> None:
    """E=M=R=10, T=10, C=10, P=0 → 0.35*10 + 0.30*10 + 0.25*10 + 0.10*10 = 10.0."""
    t = _make_task(
        braid_schema="1",
        engagement=10,
        monetary=10,
        research=10,
        tree_effect=10,
        evidence_confidence=10,
    )
    assert _M.compute_v1_score(t) == 10.0


def test_v1_min_emr_is_safety_device() -> None:
    """E=10, M=10, R=0 → min(0)=0; safety device drops contribution sharply."""
    t = _make_task(braid_schema="1", engagement=10, monetary=10, research=0, tree_effect=0)
    # 0.35*0 + 0.30*(20/3) + 0.25*0 + 0.10*0 = 2.0
    assert abs(_M.compute_v1_score(t) - 2.0) < 0.01


def test_v1_risk_penalty_subtracts() -> None:
    t = _make_task(
        braid_schema="1",
        engagement=10,
        monetary=10,
        research=10,
        tree_effect=10,
        evidence_confidence=10,
        risk_penalty=2.0,
    )
    assert _M.compute_v1_score(t) == 8.0


# ---------------------------------------------------------------------------
# v1.1 formula
# ---------------------------------------------------------------------------


def test_v11_zero_with_no_optional_fields_matches_v1_skeleton() -> None:
    """v1.1 formula with all v1.1 fields null reduces to weight-shifted v1 skeleton."""
    t = _make_task(
        braid_schema="1.1",
        engagement=10,
        monetary=10,
        research=10,
        tree_effect=10,
        evidence_confidence=10,
    )
    # 0.30*10 + 0.25*10 + 0.20*10 + 0 + 0 + 0 + 0.10*10 = 8.5
    assert abs(_M.compute_v11_score(t) - 8.5) < 0.01


def test_v11_unblock_breadth_lifts_score() -> None:
    """Wyoming-style: U=12 lifts foundational task above v1 baseline."""
    t = _make_task(
        braid_schema="1.1",
        engagement=8,
        monetary=8,
        research=4,
        tree_effect=10,
        evidence_confidence=8,
        unblock_breadth=12.0,
    )
    score = _M.compute_v11_score(t)
    # 0.30*4 + 0.25*(20/3) + 0.20*10 + 0.10*(12/1.5) + 0 + 0 + 0.10*8 = 1.2 + 1.667 + 2.0 + 0.8 + 0.8 = 6.467
    assert abs(score - 6.467) < 0.05


def test_v11_polysemic_seven_channels_adds_zero_point_seven() -> None:
    t = _make_task(
        braid_schema="1.1",
        polysemic_channels=[1, 2, 3, 4, 5, 6, 7],
    )
    score = _M.compute_v11_score(t)
    # All other terms zero; 0.10 * 7 = 0.70
    assert abs(score - 0.70) < 0.01


def test_v11_axiomatic_strain_subtracts() -> None:
    t = _make_task(
        braid_schema="1.1",
        engagement=10,
        monetary=10,
        research=10,
        tree_effect=10,
        evidence_confidence=10,
        axiomatic_strain=2.0,
    )
    # baseline 8.5 - 2.0 = 6.5
    assert abs(_M.compute_v11_score(t) - 6.5) < 0.01


# ---------------------------------------------------------------------------
# Forcing-function urgency mapping
# ---------------------------------------------------------------------------


def test_forcing_function_urgency_under_30_days() -> None:
    today = date(2026, 5, 1)
    assert _M._forcing_function_urgency("regulatory:2026-05-15", today) == 10.0


def test_forcing_function_urgency_under_90_days() -> None:
    today = date(2026, 5, 1)
    assert _M._forcing_function_urgency("regulatory:2026-06-30", today) == 8.0


def test_forcing_function_urgency_under_365_days() -> None:
    today = date(2026, 5, 1)
    assert _M._forcing_function_urgency("regulatory:2026-12-01", today) == 5.0


def test_forcing_function_urgency_far_future() -> None:
    today = date(2026, 5, 1)
    assert _M._forcing_function_urgency("regulatory:2028-01-01", today) == 2.0


def test_forcing_function_urgency_window_closed_returns_zero() -> None:
    today = date(2026, 5, 1)
    assert _M._forcing_function_urgency("regulatory:2026-04-01", today) == 0.0


def test_forcing_function_urgency_none_returns_zero() -> None:
    assert _M._forcing_function_urgency(None) == 0.0
    assert _M._forcing_function_urgency("none") == 0.0


def test_forcing_function_urgency_invalid_format_returns_zero() -> None:
    assert _M._forcing_function_urgency("badformat") == 0.0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_validate_polysemic_out_of_range() -> None:
    t = _make_task(braid_schema="1.1", polysemic_channels=[1, 2, 99])
    warnings = _M.validate(t)
    assert any("out-of-range" in w for w in warnings)


def test_validate_funnel_role_unknown() -> None:
    t = _make_task(braid_schema="1.1", funnel_role="bogus")
    warnings = _M.validate(t)
    assert any("braid_funnel_role" in w for w in warnings)


def test_validate_compounding_curve_unknown() -> None:
    t = _make_task(braid_schema="1.1", compounding_curve="exponential")
    warnings = _M.validate(t)
    assert any("braid_compounding_curve" in w for w in warnings)


def test_validate_forcing_function_invalid() -> None:
    t = _make_task(braid_schema="1.1", forcing_function_window="not-a-format")
    warnings = _M.validate(t)
    assert any("braid_forcing_function_window" in w for w in warnings)


def test_validate_v1_task_no_warnings_for_v11_fields() -> None:
    """v1 tasks should not produce v1.1-field validation warnings."""
    t = _make_task(braid_schema="1", polysemic_channels=[99])
    assert _M.validate(t) == ()


# ---------------------------------------------------------------------------
# Schema dispatch
# ---------------------------------------------------------------------------


def test_score_task_v1_uses_v1_formula() -> None:
    t = _make_task(
        braid_schema="1",
        engagement=10,
        monetary=10,
        research=10,
        tree_effect=10,
        evidence_confidence=10,
    )
    result = _M.score_task(t)
    assert result.schema == "1"
    assert result.score == 10.0


def test_score_task_v11_uses_v11_formula() -> None:
    t = _make_task(
        braid_schema="1.1",
        engagement=10,
        monetary=10,
        research=10,
        tree_effect=10,
        evidence_confidence=10,
    )
    result = _M.score_task(t)
    assert result.schema == "1.1"
    # 8.5 per the v11 baseline test above
    assert abs(result.score - 8.5) < 0.01


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------


def test_load_v1_task(tmp_path: Path) -> None:
    p = tmp_path / "active" / "t1.md"
    p.parent.mkdir(parents=True)
    p.write_text(
        """---
type: cc-task
task_id: t1
braid_schema: 1
braid_engagement: 5
braid_monetary: 4
braid_research: 6
braid_tree_effect: 3
braid_evidence_confidence: 7
braid_risk_penalty: 0.0
braid_score: 4.5
---

body
""",
        encoding="utf-8",
    )
    t = _M.load_task_frontmatter(p)
    assert t is not None
    assert t.task_id == "t1"
    assert t.braid_schema == "1"
    assert t.engagement == 5.0
    assert t.declared_score == 4.5


def test_load_v11_task_with_optional_fields(tmp_path: Path) -> None:
    p = tmp_path / "active" / "t2.md"
    p.parent.mkdir(parents=True)
    p.write_text(
        """---
type: cc-task
task_id: t2
braid_schema: 1.1
braid_engagement: 8
braid_monetary: 8
braid_research: 4
braid_tree_effect: 10
braid_evidence_confidence: 8
braid_risk_penalty: 0.0
braid_unblock_breadth: 12
braid_polysemic_channels: [1, 2, 3, 4, 5, 6, 7]
braid_funnel_role: inbound
braid_compounding_curve: preferential_attachment
braid_forcing_function_window: regulatory:2026-08-02
braid_axiomatic_strain: 0
---

body
""",
        encoding="utf-8",
    )
    t = _M.load_task_frontmatter(p)
    assert t is not None
    assert t.braid_schema == "1.1"
    assert t.unblock_breadth == 12.0
    assert t.polysemic_channels == [1, 2, 3, 4, 5, 6, 7]
    assert t.funnel_role == "inbound"
    assert t.forcing_function_window == "regulatory:2026-08-02"


def test_load_skips_non_cc_task(tmp_path: Path) -> None:
    p = tmp_path / "active" / "not-a-task.md"
    p.parent.mkdir(parents=True)
    p.write_text("---\ntype: notes\n---\n", encoding="utf-8")
    assert _M.load_task_frontmatter(p) is None


def test_load_skips_no_frontmatter(tmp_path: Path) -> None:
    p = tmp_path / "active" / "no-fm.md"
    p.parent.mkdir(parents=True)
    p.write_text("just body\n", encoding="utf-8")
    assert _M.load_task_frontmatter(p) is None


# ---------------------------------------------------------------------------
# Walk vault
# ---------------------------------------------------------------------------


def test_walk_vault_finds_active_and_closed(tmp_path: Path) -> None:
    (tmp_path / "active").mkdir()
    (tmp_path / "closed").mkdir()

    (tmp_path / "active" / "a.md").write_text(
        "---\ntype: cc-task\ntask_id: a\nbraid_schema: 1\n---\n", encoding="utf-8"
    )
    (tmp_path / "closed" / "b.md").write_text(
        "---\ntype: cc-task\ntask_id: b\nbraid_schema: 1.1\n---\n", encoding="utf-8"
    )

    tasks = _M.walk_vault(tmp_path)
    assert len(tasks) == 2
    ids = {t.task_id for t in tasks}
    assert ids == {"a", "b"}
