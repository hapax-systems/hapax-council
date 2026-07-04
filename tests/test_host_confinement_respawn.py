"""KIND-5 dissolution (MOVE 4): topology-derived local-dev-respawn suppression.

The hidden static flag HAPAX_LOCAL_DEV_MAINTENANCE_MODE=appendix-only gated whether
the lane watchdog/supervisor suppress local dev-lane (idle-await) respawns. A static
per-host flag is KIND-5 (boutique): set wrong per-host it silently over-suppresses
(the dispatch wedge) or under-suppresses (dev leaks onto podium). The derived truth
is topology: suppress local dev respawns iff THIS host is not the dev-dispatch target
(no-dev-on-podium). Fail-CLOSED to suppress — the unsafe direction is respawning dev
on a non-target host (a leaked lane); over-suppression is a recoverable idle state.
"""

from __future__ import annotations

import importlib
from typing import Any

hc = importlib.import_module("shared.host_confinement")


class TestDevDispatchTargetHost:
    def test_defaults_to_appendix_when_unset(self, monkeypatch: Any) -> None:
        monkeypatch.delenv("HAPAX_DISPATCH_HOST", raising=False)
        monkeypatch.delenv("HAPAX_DEFAULT_DISPATCH_HOST", raising=False)
        # dev/SDLC is confined to appendix — the effective_dispatch_host default.
        assert hc.dev_dispatch_target_host() == "hapax-appendix"

    def test_explicit_dispatch_host_wins(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("HAPAX_DISPATCH_HOST", "podium")
        assert hc.dev_dispatch_target_host() == "hapax-podium"

    def test_default_dispatch_host_second(self, monkeypatch: Any) -> None:
        monkeypatch.delenv("HAPAX_DISPATCH_HOST", raising=False)
        monkeypatch.setenv("HAPAX_DEFAULT_DISPATCH_HOST", "appendix")
        assert hc.dev_dispatch_target_host() == "hapax-appendix"


class TestShouldSuppressLocalDevRespawn:
    def test_non_target_host_suppresses(self) -> None:
        block, _ = hc.should_suppress_local_dev_respawn("hapax-podium", "hapax-appendix")
        assert block is True

    def test_target_host_does_not_suppress(self) -> None:
        block, _ = hc.should_suppress_local_dev_respawn("hapax-appendix", "hapax-appendix")
        assert block is False

    def test_alias_normalized_target_matches(self) -> None:
        # bare 'appendix' must normalize equal to 'hapax-appendix' (no false suppress).
        block, _ = hc.should_suppress_local_dev_respawn("appendix", "appendix")
        assert block is False

    def test_unknown_current_host_fails_closed_to_suppress(self) -> None:
        block, reason = hc.should_suppress_local_dev_respawn("", "hapax-appendix")
        assert block is True
        assert "fail" in reason.lower() or "unknown" in reason.lower()

    def test_target_defaults_when_omitted(self, monkeypatch: Any) -> None:
        monkeypatch.delenv("HAPAX_DISPATCH_HOST", raising=False)
        monkeypatch.delenv("HAPAX_DEFAULT_DISPATCH_HOST", raising=False)
        # target omitted -> derived (appendix); podium is not it -> suppress.
        block, _ = hc.should_suppress_local_dev_respawn("hapax-podium")
        assert block is True
