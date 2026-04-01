"""Test rate-limited staleness impingement emission."""


def test_emits_on_first_staleness():
    """First staleness detection should emit an impingement."""
    from shared.staleness_emitter import StalenessEmitter

    emitter = StalenessEmitter(cooldown_s=60.0)
    imp = emitter.maybe_emit("ir_perception")
    assert imp is not None
    assert imp.source == "staleness.ir_perception"


def test_rate_limits_emission():
    """Second call within cooldown should return None."""
    from shared.staleness_emitter import StalenessEmitter

    emitter = StalenessEmitter(cooldown_s=60.0)
    imp1 = emitter.maybe_emit("ir_perception")
    assert imp1 is not None

    imp2 = emitter.maybe_emit("ir_perception")
    assert imp2 is None


def test_different_sources_emit_independently():
    """Different source names should have independent cooldowns."""
    from shared.staleness_emitter import StalenessEmitter

    emitter = StalenessEmitter(cooldown_s=60.0)
    imp1 = emitter.maybe_emit("ir_perception")
    imp2 = emitter.maybe_emit("vision")

    assert imp1 is not None
    assert imp2 is not None
