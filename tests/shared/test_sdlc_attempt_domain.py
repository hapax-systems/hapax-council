"""The CPU fence must not supply claim-transfer terminality by availability."""

from pathlib import Path

import pytest

import shared.sdlc_pressure_gate as pressure
from tests.scripts.test_hapax_methodology_dispatch import _dispatcher_module


@pytest.mark.parametrize("attached", [False, True])
@pytest.mark.parametrize("systemd_run", [None, "/usr/bin/systemd-run"])
@pytest.mark.parametrize("available", [False, True])
def test_cpu_fence_shapes_refuse_an_attempt_domain_before_any_probe(
    monkeypatch: pytest.MonkeyPatch,
    attached: bool,
    systemd_run: str | None,
    available: bool,
) -> None:
    def forbidden(*args, **kwargs):
        pytest.fail("An unqualified attempt must not launch or probe a scope")

    monkeypatch.setattr(pressure, "sdlc_slice_available", forbidden)
    monkeypatch.setattr(pressure.subprocess, "run", forbidden)
    with pytest.raises(pressure.SdlcAttemptDomainError) as raised:
        pressure.sdlc_slice_wrap(
            ["synthetic-launcher"],
            already_attached=attached,
            systemd_run=systemd_run,
            slice_available=available,
            require_attempt_domain=True,
        )
    assert raised.value.reason_code == "claim_rebind_attempt_domain_unqualified"
    assert "claim-bound" in raised.value.repair_action


def test_dispatch_attempt_requirement_cannot_take_the_test_or_cpu_fence_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dispatcher = _dispatcher_module()
    marker = tmp_path / "launched"

    def launch(*args, **kwargs):
        marker.write_text("launched")
        return 0

    monkeypatch.setattr(dispatcher.subprocess, "call", launch)
    monkeypatch.setenv("HAPAX_SDLC_SLICE_ATTACHED", "1")
    # PYTEST_CURRENT_TEST is deliberately present: even that shortcut cannot
    # convert an explicit terminal-domain request into an ordinary launch.
    with pytest.raises(pressure.SdlcAttemptDomainError) as raised:
        dispatcher._sliced_call(["synthetic-launcher"], require_attempt_domain=True)
    assert not marker.exists()
    assert raised.value.reason_code == "claim_rebind_attempt_domain_unqualified"
