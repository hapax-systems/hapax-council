"""Tests for logos.copilot — CopilotEngine rule evaluation."""

from __future__ import annotations

from logos.copilot import (
    _BOOTSTRAPPING_OBSERVATIONS,
    _READINESS_COOLDOWN,
    CopilotContext,
    CopilotEngine,
)


def _engine() -> CopilotEngine:
    return CopilotEngine()


def test_health_degraded_priority():
    """Health degradation beats ambient status."""
    ctx = CopilotContext(
        health_changed=True,
        health_status="degraded",
        failed_checks=["docker_health"],
        session_age_s=120,
    )
    msg = _engine().evaluate(ctx)
    assert "health just dropped" in msg
    assert "docker_health" in msg


def test_agent_just_completed_success():
    """Recent successful agent run gets 'nice' acknowledgment."""
    ctx = CopilotContext(
        last_agent_run="briefing",
        last_agent_exit=0,
        last_agent_duration=4.2,
        last_agent_elapsed=2.0,
        session_age_s=120,
    )
    msg = _engine().evaluate(ctx)
    assert "nice" in msg
    assert "briefing" in msg
    assert "4.2s" in msg


def test_agent_just_completed_failure():
    """Recent failed agent run gets failure message."""
    ctx = CopilotContext(
        last_agent_run="health-monitor",
        last_agent_exit=1,
        last_agent_elapsed=3.0,
        session_age_s=120,
    )
    msg = _engine().evaluate(ctx)
    assert "health-monitor" in msg
    assert "failed" in msg


def test_just_returned_from_chat_with_items():
    """Returning from chat with pending items."""
    ctx = CopilotContext(
        just_returned_from="chat",
        action_item_count=3,
        session_age_s=120,
    )
    msg = _engine().evaluate(ctx)
    assert "back from chat" in msg
    assert "3 items" in msg


def test_just_returned_from_chat_all_clear():
    """Returning from chat with nothing pending."""
    ctx = CopilotContext(
        just_returned_from="chat",
        action_item_count=0,
        session_age_s=120,
    )
    msg = _engine().evaluate(ctx)
    assert "back from chat" in msg
    assert "nothing pressing" in msg


def test_briefing_stale_with_items():
    """Stale briefing + pending items triggers concern."""
    ctx = CopilotContext(
        briefing_age_h=30.0,
        action_item_count=5,
        health_status="healthy",
        session_age_s=120,
    )
    msg = _engine().evaluate(ctx)
    assert "briefing is 30h old" in msg
    assert "5 items" in msg


def test_ongoing_degraded_health():
    """Ongoing degraded health without transition."""
    ctx = CopilotContext(
        health_status="degraded",
        health_changed=False,
        healthy_count=42,
        total_checks=44,
        failed_checks=["qdrant_collections"],
        session_age_s=120,
    )
    msg = _engine().evaluate(ctx)
    assert "42/44" in msg
    assert "qdrant_collections" in msg


def test_high_vram_usage():
    """High VRAM usage triggers warning."""
    ctx = CopilotContext(
        health_status="healthy",
        vram_pct=92.0,
        loaded_model="qwen3:30b-a3b",
        session_age_s=120,
    )
    msg = _engine().evaluate(ctx)
    assert "92%" in msg
    assert "qwen3:30b-a3b" in msg
    assert "queue" in msg


def test_drift_significant():
    """Significant drift triggers concern."""
    ctx = CopilotContext(
        health_status="healthy",
        drift_count=8,
        session_age_s=120,
    )
    msg = _engine().evaluate(ctx)
    assert "8 drift items" in msg
    assert "diverging" in msg


def test_idle_with_items_stays_quiet():
    """5+ min idle with pending items — copilot stays observational (items visible on dashboard)."""
    ctx = CopilotContext(
        idle_seconds=360,
        action_item_count=3,
        health_status="healthy",
        session_age_s=600,
    )
    msg = _engine().evaluate(ctx)
    # Copilot no longer directs attention to items — they're on the dashboard
    assert "quiet session" in msg
    assert "still here" not in msg


def test_idle_all_clear():
    """5+ min idle with no items triggers calm."""
    ctx = CopilotContext(
        idle_seconds=400,
        action_item_count=0,
        health_status="healthy",
        session_age_s=600,
    )
    msg = _engine().evaluate(ctx)
    assert "quiet session" in msg
    assert "smooth" in msg


def test_session_greeting():
    """First 60s gets greeting with summary."""
    ctx = CopilotContext(
        session_age_s=10,
        action_item_count=3,
        health_status="healthy",
        hour=9,
    )
    msg = _engine().evaluate(ctx)
    assert "morning" in msg
    assert "3 items" in msg
    assert "healthy" in msg


def test_session_greeting_afternoon():
    """Afternoon session greeting."""
    ctx = CopilotContext(
        session_age_s=5,
        health_status="healthy",
        hour=14,
    )
    msg = _engine().evaluate(ctx)
    assert "afternoon" in msg


def test_ambient_fallback():
    """Default ambient status when nothing specific is happening."""
    ctx = CopilotContext(
        health_status="healthy",
        briefing_age_h=5.0,
        session_age_s=120,
    )
    msg = _engine().evaluate(ctx)
    assert "stack healthy" in msg
    assert "briefing 5h old" in msg


def test_all_clear():
    """All clear when nothing to report."""
    ctx = CopilotContext(session_age_s=120)
    msg = _engine().evaluate(ctx)
    assert "all clear" in msg


def test_priority_ordering():
    """Health degradation wins over stale briefing."""
    ctx = CopilotContext(
        health_changed=True,
        health_status="degraded",
        failed_checks=["docker_health"],
        briefing_age_h=30.0,
        action_item_count=5,
        session_age_s=120,
    )
    msg = _engine().evaluate(ctx)
    # Health degradation (P1) should win over briefing staleness (P2)
    assert "health just dropped" in msg


def test_health_failed_status():
    """Failed health status shows check count."""
    ctx = CopilotContext(
        health_status="failed",
        failed_checks=["docker_health", "qdrant", "litellm"],
        session_age_s=120,
    )
    msg = _engine().evaluate(ctx)
    assert "failed" in msg
    assert "3 checks" in msg


# ── Readiness awareness tests ───────────────────────────────────────────────


def test_bootstrapping_message_fires():
    """Bootstrapping readiness alert fires when cooldown expired."""
    engine = _engine()
    ctx = CopilotContext(
        health_status="healthy",
        readiness_level="bootstrapping",
        readiness_top_gap="no interview conducted",
        readiness_gaps=["no interview conducted"],
        interview_conducted=False,
        session_age_s=120,
    )
    msg = engine.evaluate(ctx)
    assert msg in _BOOTSTRAPPING_OBSERVATIONS


def test_bootstrapping_cooldown_prevents_rapid_fire():
    """Bootstrapping messages respect cooldown — don't fire every eval."""
    engine = _engine()
    ctx = CopilotContext(
        health_status="healthy",
        readiness_level="bootstrapping",
        readiness_top_gap="no interview conducted",
        readiness_gaps=["no interview conducted"],
        interview_conducted=False,
        session_age_s=120,
    )
    # First eval fires (cooldown starts at -5, so eval 1 is at distance 6)
    msg1 = engine.evaluate(ctx)
    assert msg1 in _BOOTSTRAPPING_OBSERVATIONS

    # Second eval should NOT fire — cooldown not expired
    msg2 = engine.evaluate(ctx)
    assert msg2 not in _BOOTSTRAPPING_OBSERVATIONS


def test_bootstrapping_rotation_advances():
    """Successive bootstrapping messages rotate through the pool."""
    engine = _engine()
    ctx = CopilotContext(
        health_status="healthy",
        readiness_level="bootstrapping",
        readiness_top_gap="no interview conducted",
        readiness_gaps=["no interview conducted"],
        interview_conducted=False,
        session_age_s=120,
    )
    messages = []
    for _ in range(3):
        # Burn through cooldown
        for _ in range(_READINESS_COOLDOWN - 1):
            engine._eval_count += 1
        msg = engine.evaluate(ctx)
        if msg in _BOOTSTRAPPING_OBSERVATIONS:
            messages.append(msg)

    # Should have at least 2 different messages
    assert len(set(messages)) >= 2


def test_p1_beats_bootstrapping():
    """Health transition (P1) wins over bootstrapping readiness (P2-R)."""
    engine = _engine()
    ctx = CopilotContext(
        health_changed=True,
        health_status="degraded",
        failed_checks=["docker_health"],
        readiness_level="bootstrapping",
        readiness_top_gap="no interview conducted",
        readiness_gaps=["no interview conducted"],
        interview_conducted=False,
        session_age_s=120,
    )
    msg = engine.evaluate(ctx)
    assert "health just dropped" in msg


def test_idle_readiness_rotation():
    """Idle eval with readiness gaps rotates readiness observations."""
    engine = _engine()
    # Set eval_count to a multiple of 3 so modulo check passes
    engine._eval_count = 2  # will become 3 after evaluate increments
    ctx = CopilotContext(
        idle_seconds=400,
        action_item_count=0,
        health_status="healthy",
        readiness_level="developing",
        readiness_gaps=["priorities not validated"],
        session_age_s=600,
    )
    msg = engine.evaluate(ctx)
    # Should be a readiness message, not "quiet session"
    assert "quiet session" not in msg


def test_idle_no_readiness_gaps_stays_quiet():
    """Idle eval with operational readiness stays 'quiet session'."""
    engine = _engine()
    engine._eval_count = 2  # becomes 3
    ctx = CopilotContext(
        idle_seconds=400,
        action_item_count=0,
        health_status="healthy",
        readiness_level="operational",
        session_age_s=600,
    )
    msg = engine.evaluate(ctx)
    assert "quiet session" in msg


def test_greeting_appends_top_gap():
    """Session greeting appends readiness gap when bootstrapping."""
    ctx = CopilotContext(
        session_age_s=10,
        health_status="healthy",
        readiness_level="bootstrapping",
        readiness_top_gap="no interview conducted",
        hour=9,
    )
    msg = _engine().evaluate(ctx)
    assert "morning" in msg
    assert "no interview conducted" in msg


def test_greeting_no_gap_when_operational():
    """Session greeting omits readiness gap when operational."""
    ctx = CopilotContext(
        session_age_s=10,
        health_status="healthy",
        readiness_level="operational",
        readiness_top_gap="",
        hour=9,
    )
    msg = _engine().evaluate(ctx)
    assert "morning" in msg
    assert "interview" not in msg


def test_ambient_with_bootstrapping():
    """Ambient status surfaces readiness when no operational items and P2-R on cooldown."""
    engine = _engine()
    # Set last readiness eval to current count so P2-R cooldown is active
    engine._last_readiness_eval = engine._eval_count
    ctx = CopilotContext(
        readiness_level="bootstrapping",
        readiness_top_gap="no interview conducted",
        session_age_s=120,
    )
    msg = engine.evaluate(ctx)
    assert "no interview conducted" in msg
    assert "all clear" not in msg


def test_ambient_operational_all_clear():
    """Ambient status says 'all clear' when operational and no items."""
    ctx = CopilotContext(
        readiness_level="operational",
        session_age_s=120,
    )
    msg = _engine().evaluate(ctx)
    assert "all clear" in msg


def test_developing_message_formats_gap():
    """Developing observation pool fills {gap} placeholder when idle."""
    engine = _engine()
    # Set eval_count so that after increment it's divisible by 3 (triggers idle readiness)
    engine._eval_count = 2  # becomes 3 after evaluate increments
    ctx = CopilotContext(
        idle_seconds=400,
        action_item_count=0,
        health_status="healthy",
        readiness_level="developing",
        readiness_gaps=["priorities not validated", "neurocognitive patterns undiscovered"],
        session_age_s=600,
    )
    msg = engine.evaluate(ctx)
    # Should be a developing pool message, not "quiet session"
    assert "quiet session" not in msg
    # {gap} placeholder must be resolved
    assert "{gap}" not in msg


def test_idle_with_probe_surfaces_question():
    """Probe surfaces during idle when eval count aligns."""
    from logos.micro_probes import MicroProbe

    probe = MicroProbe(
        dimension="neurocognitive",
        topic="task_initiation",
        question="What gets you to start a task?",
        rationale="understanding inertia helps",
        follow_up_hint="explore triggers",
        priority=90,
    )
    engine = _engine()
    # Set eval_count so that after increment it's divisible by 4
    engine._eval_count = 3  # becomes 4 after evaluate increments
    ctx = CopilotContext(
        idle_seconds=400,
        action_item_count=0,
        health_status="healthy",
        readiness_level="operational",
        session_age_s=600,
        current_probe=probe,
    )
    msg = engine.evaluate(ctx)
    assert "understanding inertia helps" in msg
    assert "What gets you to start a task?" in msg


def test_idle_without_probe_stays_quiet():
    """No probe = quiet session as before."""
    engine = _engine()
    engine._eval_count = 3
    ctx = CopilotContext(
        idle_seconds=400,
        action_item_count=0,
        health_status="healthy",
        readiness_level="operational",
        session_age_s=600,
        current_probe=None,
    )
    msg = engine.evaluate(ctx)
    assert "quiet session" in msg


def test_developing_message_gap_fallback():
    """Developing {gap} placeholder falls back when readiness_gaps is empty."""
    engine = _engine()
    engine._eval_count = 2  # becomes 3
    ctx = CopilotContext(
        idle_seconds=400,
        action_item_count=0,
        health_status="healthy",
        readiness_level="developing",
        readiness_gaps=[],  # empty — shouldn't crash or show literal {gap}
        session_age_s=600,
    )
    msg = engine.evaluate(ctx)
    assert "{gap}" not in msg


# ── Data freshness tests ──────────────────────────────────────────────────


def test_fast_cache_stale():
    """Fast cache > 90s triggers freshness warning."""
    ctx = CopilotContext(
        health_status="healthy",
        fast_cache_age_s=120,
        session_age_s=300,
    )
    msg = _engine().evaluate(ctx)
    assert "120s stale" in msg
    assert "fast refresh" in msg


def test_slow_cache_stale():
    """Slow cache > 900s (15min) triggers freshness warning."""
    ctx = CopilotContext(
        health_status="healthy",
        slow_cache_age_s=960,
        session_age_s=1200,
    )
    msg = _engine().evaluate(ctx)
    assert "16m stale" in msg
    assert "slow refresh" in msg


def test_cache_fresh_no_warning():
    """Fresh cache ages don't trigger warnings."""
    ctx = CopilotContext(
        health_status="healthy",
        fast_cache_age_s=25,
        slow_cache_age_s=200,
        session_age_s=300,
    )
    msg = _engine().evaluate(ctx)
    assert "stale" not in msg


def test_cache_not_tracked_no_warning():
    """Default -1 (not tracked) doesn't trigger warnings."""
    ctx = CopilotContext(
        health_status="healthy",
        fast_cache_age_s=-1,
        slow_cache_age_s=-1,
        session_age_s=300,
    )
    msg = _engine().evaluate(ctx)
    assert "stale" not in msg


def test_fast_stale_beats_slow_stale():
    """Fast cache staleness (higher priority) shown over slow."""
    ctx = CopilotContext(
        health_status="healthy",
        fast_cache_age_s=100,
        slow_cache_age_s=1000,
        session_age_s=1200,
    )
    msg = _engine().evaluate(ctx)
    assert "fast refresh" in msg
