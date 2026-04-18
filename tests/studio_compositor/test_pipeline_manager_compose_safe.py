"""Phase 6c tests — PipelineManager.set_compose_safe() consumer wiring.

Validates the enforced live-egress path: when consent compose-safe is
pinned, every camera interpipesrc is swapped to its fallback and
subsequent `swap_to_primary` calls are no-ops until cleared.

Axiom: it-irreversible-broadcast T0.
"""

from __future__ import annotations

from types import SimpleNamespace

from agents.studio_compositor.pipeline_manager import PipelineManager


class _FakeProperty:
    def __init__(self) -> None:
        self.value: str | None = None

    def set_property(self, _name: str, value: str) -> None:
        self.value = value


def _make_mgr(roles: list[str]) -> tuple[PipelineManager, dict[str, _FakeProperty]]:
    """PipelineManager without GStreamer — populated directly for set_compose_safe tests."""
    mgr = PipelineManager(specs=[], gst=None, glib=None, fps=30)
    srcs: dict[str, _FakeProperty] = {}
    for role in roles:
        src = _FakeProperty()
        srcs[role] = src
        mgr._interpipe_srcs[role] = src
        mgr._fallbacks[role] = SimpleNamespace(sink_name=f"fb_{role.replace('-', '_')}")
        mgr._cameras[role] = SimpleNamespace(sink_name=f"cam_{role.replace('-', '_')}")
    return mgr, srcs


class TestSetComposeSafe:
    def test_activate_swaps_all_cameras_to_fallback(self):
        roles = ["brio-operator", "brio-room", "c920-desk"]
        mgr, srcs = _make_mgr(roles)
        for src in srcs.values():
            assert src.value is None

        mgr.set_compose_safe(True)

        assert mgr._compose_safe_pin is True
        for role, src in srcs.items():
            expected = f"fb_{role.replace('-', '_')}"
            assert src.value == expected, f"role={role} not on fallback"

    def test_pin_blocks_swap_to_primary(self):
        mgr, srcs = _make_mgr(["brio-operator"])
        mgr.set_compose_safe(True)
        assert srcs["brio-operator"].value == "fb_brio_operator"

        mgr.swap_to_primary("brio-operator")

        assert srcs["brio-operator"].value == "fb_brio_operator", (
            "swap_to_primary leaked past the compose-safe pin"
        )

    def test_deactivate_releases_pin(self):
        mgr, srcs = _make_mgr(["brio-operator"])
        mgr.set_compose_safe(True)
        mgr.set_compose_safe(False)

        assert mgr._compose_safe_pin is False

        mgr.swap_to_primary("brio-operator")
        assert srcs["brio-operator"].value == "cam_brio_operator"

    def test_idempotent_activate(self):
        mgr, srcs = _make_mgr(["brio-operator"])
        mgr.set_compose_safe(True)
        srcs["brio-operator"].value = "sentinel"
        mgr.set_compose_safe(True)
        assert srcs["brio-operator"].value == "sentinel", "idempotent activation should not re-swap"

    def test_idempotent_deactivate(self):
        mgr, srcs = _make_mgr(["brio-operator"])
        mgr.set_compose_safe(False)
        assert mgr._compose_safe_pin is False
        assert srcs["brio-operator"].value is None
