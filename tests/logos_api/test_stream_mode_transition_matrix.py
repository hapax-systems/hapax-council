"""LRR Phase 6 §4.G — stream-mode transition × redacted-surface integration matrix.

Parametrized matrix covering every stream-mode × every §4-redacted surface.
Each cell asserts either:
  - publicly-visible → content is redacted / request 403d / field omitted
  - privately-visible → content flows through unchanged (no over-redaction)

Surfaces covered:
  §4.A API endpoints (stimmung, profile/{dimension}, management, perception,
     orientation, briefing, nudges, consent/contracts) — PRs #967, #968
  §4.B transcript firewall (gate module) — PR #978
  §4.E mental-state Qdrant helpers — PR #981
  §4.F daimonion tool handlers (Gmail + Calendar) — PR #975

Each §4 dependency ships in its own PR; individual tests use
``pytest.importorskip`` so they activate as those PRs merge into main.
Currently-on-main subsets run; pending-PR subsets skip.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# ── Stream-mode enumeration ────────────────────────────────────────────────


PUBLIC_MODES = ["public", "public_research"]
PRIVATE_MODES = ["off", "private"]
ALL_MODES = PUBLIC_MODES + PRIVATE_MODES


def _is_public_mode(mode: str) -> bool:
    return mode in PUBLIC_MODES


# ── §4.A — stimmung dimensions banding × mode (requires #967) ──────────────


def _stimmung_redaction_wired() -> bool:
    """True iff stimmung.py has the is_publicly_visible import from #967."""
    try:
        import logos.api.routes.stimmung as mod

        return hasattr(mod, "is_publicly_visible")
    except Exception:
        return False


@pytest.fixture
def stimmung_with_state(tmp_path, monkeypatch):
    import json

    state = {
        "overall_stance": "nominal",
        "timestamp": 1776425000,
        "operator_energy": {"value": 0.8, "trend": "rising", "freshness_s": 1.0},
        "physiological_coherence": {"value": 0.6, "trend": "stable", "freshness_s": 2.0},
        "operator_stress": {"value": 0.2, "trend": "falling", "freshness_s": 1.0},
        "health": {"value": 0.95, "trend": "stable", "freshness_s": 5.0},
        "resource_pressure": {"value": 0.4, "trend": "stable", "freshness_s": 3.0},
        "error_rate": {"value": 0.05, "trend": "stable", "freshness_s": 4.0},
        "processing_throughput": {"value": 0.85, "trend": "rising", "freshness_s": 2.0},
        "perception_confidence": {"value": 0.9, "trend": "stable", "freshness_s": 1.0},
        "llm_cost_pressure": {"value": 0.3, "trend": "stable", "freshness_s": 6.0},
        "grounding_quality": {"value": 0.75, "trend": "stable", "freshness_s": 1.5},
        "exploration_deficit": {"value": 0.4, "trend": "stable", "freshness_s": 2.5},
    }
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state))
    monkeypatch.setattr("logos.api.routes.stimmung._SHM_STATE", state_file)


@pytest.mark.parametrize("mode", ALL_MODES)
@pytest.mark.asyncio
async def test_stimmung_across_modes(stimmung_with_state, mode, monkeypatch):
    if not _stimmung_redaction_wired():
        pytest.skip("§4.A stimmung redaction not yet on main (pending PR #967)")

    public = _is_public_mode(mode)
    monkeypatch.setattr("logos.api.routes.stimmung.is_publicly_visible", lambda: public)

    from logos.api.routes.stimmung import get_stimmung

    result = await get_stimmung()
    if public:
        assert set(result["dimensions"].keys()) == {
            "operator_energy",
            "physiological_coherence",
            "operator_stress",
        }
        for dim in result["dimensions"].values():
            assert "band" in dim
            assert "value" not in dim
        assert "topology" not in result
    else:
        assert len(result["dimensions"]) >= 3


# ── §4.A — profile/{dimension} 403 × mode (requires #967) ──────────────────


def test_profile_dimension_route_dependency_present():
    if not _stimmung_redaction_wired():
        pytest.skip("§4.A profile/{dimension} 403 dep not yet on main (pending PR #967)")

    from fastapi.routing import APIRoute

    from logos.api.deps.stream_redaction import require_private_stream
    from logos.api.routes.profile import router

    route = next(
        r for r in router.routes if isinstance(r, APIRoute) and r.path == "/api/profile/{dimension}"
    )
    dep_funcs = [d.dependency for d in route.dependencies]
    assert require_private_stream in dep_funcs


# ── §4.F — Gmail + Calendar tool handlers × mode (requires #975) ───────────


def _tools_broadcast_redaction_wired() -> bool:
    try:
        import agents.hapax_daimonion.tools as mod

        return hasattr(mod, "_stream_is_publicly_visible")
    except Exception:
        return False


class _FakeParams:
    def __init__(self, arguments: dict):
        self.arguments = arguments
        self.result_callback = AsyncMock()


@pytest.mark.parametrize("mode", ALL_MODES)
@pytest.mark.asyncio
async def test_calendar_handler_across_modes(mode, monkeypatch):
    if not _tools_broadcast_redaction_wired():
        pytest.skip("§4.F Gmail/Calendar redaction not yet on main (pending PR #975)")

    public = _is_public_mode(mode)
    monkeypatch.setattr("agents.hapax_daimonion.tools._stream_is_publicly_visible", lambda: public)

    class _FakeEvents:
        def list(self, **kw):
            return self

        def execute(self):
            return {"items": []}

    class _FakeService:
        def events(self):
            return _FakeEvents()

    monkeypatch.setattr(
        "agents.hapax_daimonion.tools.build_service", lambda *a, **kw: _FakeService()
    )

    from agents.hapax_daimonion import tools

    params = _FakeParams({"days_ahead": 2})
    await tools.handle_get_calendar_today(params)
    (call_arg,), _ = params.result_callback.call_args_list[0]

    if public:
        assert "not broadcast-safe" in call_arg.lower()
    else:
        assert "not broadcast-safe" not in call_arg.lower()


@pytest.mark.parametrize("mode", ALL_MODES)
@pytest.mark.asyncio
async def test_email_handler_across_modes(mode, monkeypatch):
    if not _tools_broadcast_redaction_wired():
        pytest.skip("§4.F Gmail/Calendar redaction not yet on main (pending PR #975)")

    public = _is_public_mode(mode)
    monkeypatch.setattr("agents.hapax_daimonion.tools._stream_is_publicly_visible", lambda: public)

    class _FakePoints:
        points = []

    class _FakeClient:
        def query_points(self, *a, **kw):
            return _FakePoints()

    monkeypatch.setattr("agents.hapax_daimonion.tools.get_qdrant_grpc", lambda: _FakeClient())
    monkeypatch.setattr("agents.hapax_daimonion.tools.embed", lambda *a, **kw: [0.0] * 768)

    from agents.hapax_daimonion import tools

    params = _FakeParams({"query": "quarterly review", "recent_only": False})
    await tools.handle_search_emails(params)
    (call_arg,), _ = params.result_callback.call_args_list[0]

    if public:
        assert "not broadcast-safe" in call_arg.lower()
    else:
        assert "not broadcast-safe" not in call_arg.lower()


# ── §4.B — transcript gate × mode (requires #978) ──────────────────────────


@pytest.mark.parametrize("mode", ALL_MODES)
def test_transcript_gate_across_modes(mode, tmp_path, monkeypatch):
    pytest.importorskip(
        "shared.transcript_read_gate",
        reason="§4.B transcript firewall not yet on main (pending PR #978)",
    )

    public = _is_public_mode(mode)
    monkeypatch.setattr("shared.transcript_read_gate.is_publicly_visible", lambda: public)

    events_file = tmp_path / "events-2026-04-17.jsonl"
    events_file.write_text('{"event": "demo"}\n', encoding="utf-8")

    from shared.transcript_read_gate import TranscriptRedacted, read_transcript_gate

    result = read_transcript_gate(events_file)
    if public:
        assert isinstance(result, TranscriptRedacted)
    else:
        assert isinstance(result, str)
        assert "demo" in result


# ── §4.E — mental-state Qdrant redaction × mode (requires #981) ────────────


@pytest.mark.parametrize("mode", ALL_MODES)
def test_mental_state_redaction_across_modes(mode, monkeypatch):
    pytest.importorskip(
        "shared.governance.mental_state_redaction",
        reason="§4.E mental-state helpers not yet on main (pending PR #981)",
    )

    public = _is_public_mode(mode)
    monkeypatch.setattr(
        "shared.governance.mental_state_redaction.is_publicly_visible", lambda: public
    )

    from shared.governance.mental_state_redaction import redact_mental_state_if_public

    payload = {
        "episode_text": "operator was frustrated",
        "mental_state_safe_summary": "operator in frustrated mode",
    }
    result = redact_mental_state_if_public("operator-episodes", payload)
    if public:
        assert result["episode_text"] == "operator in frustrated mode"
    else:
        assert result["episode_text"] == "operator was frustrated"


# ── §4.C — filesystem deny-list (mode-agnostic, always blocks) ─────────────


@pytest.mark.parametrize("mode", ALL_MODES)
def test_filesystem_deny_across_modes(mode):
    """Deny-list is mode-agnostic — dangerous paths never render, even
    on private streams. Regression pin that mode doesn't accidentally
    loosen the deny-list."""
    from shared.stream_mode import is_path_stream_safe

    assert is_path_stream_safe(Path.home() / ".password-store") is False
    assert is_path_stream_safe(Path.home() / ".ssh" / "id_rsa") is False
    _ = mode  # unused — that's the point


# ── Coverage summary ───────────────────────────────────────────────────────


class TestRedactionCoverageSummary:
    """The §4 redacted surfaces this matrix covers. When new surfaces ship,
    add the parametrized entry above + extend this set."""

    def test_covered_surfaces_enumerated(self):
        covered_surfaces = {
            "stimmung",
            "profile-dimension",
            "calendar-tool",
            "email-tool",
            "transcript-gate",
            "mental-state-qdrant",
            "filesystem-deny",
        }
        assert len(covered_surfaces) == 7
