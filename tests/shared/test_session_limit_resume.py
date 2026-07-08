"""Session-limit self-resume (operator directive 2026-06-11): the limit message
tells us when to resume — parse it, receipt it, gate on it, wake on it."""

from __future__ import annotations

from datetime import UTC, datetime

from shared.quota_wall import _parse_record, parse_reset_phrase
from shared.sdlc_pressure_gate import admission_state, session_limit_until

NOW = datetime(2026, 6, 11, 7, 38, tzinfo=UTC)  # 02:38 America/Chicago (CDT)


def test_parse_reset_phrase_am():
    assert parse_reset_phrase("resets 5am (America/Chicago)", now=NOW) == "2026-06-11T10:00:00Z"


def test_parse_reset_phrase_pm_with_minutes():
    assert parse_reset_phrase("resets 5:30pm (America/Chicago)", now=NOW) == "2026-06-11T22:30:00Z"


def test_parse_reset_phrase_rolls_to_tomorrow():
    later = datetime(2026, 6, 11, 11, 0, tzinfo=UTC)  # 06:00 CDT, past 5am
    assert parse_reset_phrase("resets 5am (America/Chicago)", now=later) == "2026-06-12T10:00:00Z"


def test_parse_reset_phrase_garbage_returns_none():
    assert parse_reset_phrase("no phrase here") is None
    assert parse_reset_phrase("resets 5am (Not/AZone)") is None


def test_session_limit_result_record_recognized():
    sig = _parse_record(
        {
            "type": "result",
            "subtype": "success",
            "is_error": True,
            "api_error_status": 429,
            "result": "You've hit your session limit · resets 5am (America/Chicago)",
        }
    )
    assert sig is not None and sig.kind == "session_limit"
    assert sig.resets_at is not None and sig.resets_at.endswith("Z")


def test_session_limit_text_without_status_still_recognized():
    sig = _parse_record(
        {
            "type": "result",
            "result": "You've hit your session limit · resets 11pm (America/Chicago)",
        }
    )
    assert sig is not None and sig.kind == "session_limit"


def test_beacon_reads_future_receipts(tmp_path):
    (tmp_path / "zeta-quota-wall.yaml").write_text("resets_at: '2099-01-01T00:00:00Z'\n")
    (tmp_path / "eta-quota-wall.yaml").write_text(
        "resets_at: '2000-01-01T00:00:00Z'\n"
    )  # past: ignored
    got = session_limit_until(receipts_dir=tmp_path, now=1000.0)
    assert got is not None and got[1] == "zeta-quota-wall.yaml"


def test_beacon_ignores_route_scoped_quota_exhaustion_receipts(tmp_path):
    (tmp_path / "cx-glmcp-review-glm52-quota-wall.yaml").write_text(
        "\n".join(
            [
                "schema: hapax.glmcp_quota_hold.v1",
                "status: quota_blocked",
                "role: cx-glmcp-review-glm52",
                "provider: z_ai-glm-coding-plan",
                "route_id: glmcp.review.direct",
                "capacity_pool: subscription_quota",
                "supported_tool: hapax-glmcp-reviewer",
                "signal_kind: glmcp_quota_admission_error",
                "rate_limit_type: quota_exhausted",
                "resets_at: 2099-01-01T00:00:00Z",
            ]
        )
    )

    assert session_limit_until(receipts_dir=tmp_path, now=1000.0) is None


def test_gate_closes_on_limit_beacon(tmp_path, monkeypatch):
    import shared.sdlc_pressure_gate as g

    (tmp_path / "zeta-quota-wall.yaml").write_text("resets_at: '2099-01-01T00:00:00Z'\n")
    monkeypatch.setattr(g, "QUOTA_RECEIPTS_DIR", tmp_path)
    d = admission_state(state_path=tmp_path / "s.json")
    assert d.state == "closed"
    assert any("session-limit" in r for r in d.reasons)


def test_gate_open_when_no_future_receipts(tmp_path, monkeypatch):
    import shared.sdlc_pressure_gate as g

    monkeypatch.setattr(g, "QUOTA_RECEIPTS_DIR", tmp_path)
    monkeypatch.setattr(g, "read_psi", lambda *a, **k: g.PsiReading(1.0, 1.0))
    monkeypatch.setattr(g, "read_load_per_core", lambda *a, **k: 0.1)
    monkeypatch.setattr(g, "read_working_mode", lambda: "research")
    monkeypatch.setattr(g, "read_production_sli", lambda **k: "unknown")
    d = admission_state(state_path=tmp_path / "s.json")
    assert d.state == "open"
