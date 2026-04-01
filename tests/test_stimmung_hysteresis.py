"""Test stimmung stance hysteresis."""


def test_stance_degrades_immediately():
    from shared.stimmung import StimmungCollector

    collector = StimmungCollector()
    collector.update_health(healthy=10, total=10)
    snap1 = collector.snapshot()
    assert snap1.overall_stance == "nominal"
    collector.update_health(healthy=3, total=10)
    snap2 = collector.snapshot()
    assert snap2.overall_stance in ("cautious", "degraded", "critical")


def test_stance_requires_sustained_improvement():
    from shared.stimmung import StimmungCollector

    collector = StimmungCollector()
    collector.update_health(healthy=3, total=10)
    snap1 = collector.snapshot()
    degraded_stance = snap1.overall_stance
    assert degraded_stance != "nominal"
    # One good reading should NOT recover immediately
    collector.update_health(healthy=10, total=10)
    snap2 = collector.snapshot()
    assert snap2.overall_stance == degraded_stance or snap2.overall_stance != "nominal"


def test_recovery_after_threshold():
    from shared.stimmung import StimmungCollector

    collector = StimmungCollector()
    # Degrade
    collector.update_health(healthy=3, total=10)
    snap = collector.snapshot()
    assert snap.overall_stance != "nominal"
    # 3 consecutive nominal readings should recover
    for _ in range(3):
        collector.update_health(healthy=10, total=10)
        snap = collector.snapshot()
    assert snap.overall_stance == "nominal"
