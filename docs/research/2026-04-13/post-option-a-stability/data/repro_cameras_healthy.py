"""Reproduction harness for the studio_compositor_cameras_healthy gauge bug.

Run from the council repo root with:
    uv run python docs/research/2026-04-13/post-option-a-stability/data/repro_cameras_healthy.py

Expected output demonstrates that the gauge always reads 0.0 regardless of
how many cameras are registered or transitioned to HEALTHY.
"""

from __future__ import annotations

from agents.studio_compositor import metrics


def _read_gauge(name: str) -> float:
    """Pull a single unlabeled Gauge value out of the module-level REGISTRY."""
    val = metrics.REGISTRY.get_sample_value(name)
    return float("nan") if val is None else val


def scenario(label: str) -> None:
    h = _read_gauge("studio_compositor_cameras_healthy")
    t = _read_gauge("studio_compositor_cameras_total")
    print(f"  {label}: cameras_total={t} cameras_healthy={h}")


def main() -> None:
    print("=== Reproduction: studio_compositor_cameras_healthy accumulator bug ===")
    scenario("t0 empty")

    # Register two cameras — both start in HEALTHY per register_camera()
    metrics.register_camera("repro-brio", "logitech-brio")
    metrics.register_camera("repro-c920", "logitech-c920")
    scenario("after register_camera x2 (both HEALTHY)")

    # Transition one to DEGRADED
    metrics.on_state_transition("repro-brio", "healthy", "degraded")
    scenario("after 1 healthy->degraded")

    # Transition back
    metrics.on_state_transition("repro-brio", "degraded", "healthy")
    scenario("after degraded->healthy")

    # Transition one to OFFLINE
    metrics.on_state_transition("repro-c920", "healthy", "offline")
    scenario("after 1 healthy->offline")

    # Cleanup so tests don't inherit state
    metrics.shutdown()
    scenario("after shutdown")

    print()
    print("EXPECTED (if fix were applied):")
    print("  t0 empty: 0/0")
    print("  after register x2: 2/2")
    print("  after 1 healthy->degraded: 1/2")
    print("  after degraded->healthy: 2/2")
    print("  after 1 healthy->offline: 1/2")
    print("  after shutdown: 0/0")


if __name__ == "__main__":
    main()
