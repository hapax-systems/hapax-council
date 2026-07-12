"""Self-contained tests for the derived lane-liveness eligibility gate at the
dispatch chokepoint (``run_atomic_dispatch_launch``).

The gate refuses a retired lane unless ``reactivate_retired`` is set; the
launcher must never be reached for a retired lane. The MQ/event internals are
mocked so the gate is exercised in isolation. See ``shared/relay_lifecycle``
+ design-of-record ``non-boutique-codex-auth-and-lane-liveness-design-2026-07-03.md``.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from unittest import mock

import pytest

from shared.coord_dispatch import (
    CoordDispatchError,
    DispatchLaunchRequest,
    run_atomic_dispatch_launch,
)

MOD = "shared.coord_dispatch"


def _request(lane: str = "cx-retired", *, reactivate: bool = False) -> DispatchLaunchRequest:
    return DispatchLaunchRequest(
        task_id="T1",
        lane=lane,
        platform="codex",
        mode="headless",
        profile="p",
        authority_case="CASE-CAPACITY-ROUTING-001",
        parent_spec="spec",
        message_id="M1",
        mq_db_path=Path("/dev/null"),
        event_log=mock.Mock(),
        reactivate_retired=reactivate,
    )


@contextlib.contextmanager
def _mocked_internals():
    """Mock the MQ/event internals so the gate is tested in isolation."""
    with (
        mock.patch(f"{MOD}.replay_terminal_result", return_value=None) as replay,
        mock.patch(f"{MOD}._refuse_inflight_idempotency_key") as inflight,
        mock.patch(f"{MOD}._accept_dispatch_message") as accept,
        mock.patch(f"{MOD}._cleanup_dispatch_message") as cleanup,
        mock.patch(f"{MOD}._append_dispatch_event") as append,
    ):
        yield {
            "replay": replay,
            "inflight": inflight,
            "accept": accept,
            "cleanup": cleanup,
            "append": append,
        }


def test_reactivate_retired_defaults_false() -> None:
    assert _request().reactivate_retired is False


def test_retired_lane_refused_before_launch() -> None:
    request = _request()
    launch = mock.Mock(return_value=0)
    with _mocked_internals() as internals, mock.patch(f"{MOD}.lane_is_retired", return_value=True):
        with pytest.raises(CoordDispatchError, match="lane_retired"):
            run_atomic_dispatch_launch(request, launch)
        launch.assert_not_called()  # the gate refused before the launcher
        internals["cleanup"].assert_called_once_with(
            request,
            idempotency_key=request.effective_idempotency_key,
            state="deferred",
            returncode=71,
        )
        internals["append"].assert_not_called()


def test_reactivate_bypasses_gate_for_sanctioned_reactivation() -> None:
    # reactivate_retired=True (threaded from allow_codex_governed_relay_reactivation
    # for the P0-drain lanes) must NOT be refused -- the sanctioned --force path.
    launch = mock.Mock(return_value=0)
    with _mocked_internals(), mock.patch(f"{MOD}.lane_is_retired", return_value=True):
        run_atomic_dispatch_launch(_request(reactivate=True), launch)
        launch.assert_called_once()


def test_non_retired_lane_proceeds_to_launch() -> None:
    launch = mock.Mock(return_value=0)
    with _mocked_internals(), mock.patch(f"{MOD}.lane_is_retired", return_value=False):
        run_atomic_dispatch_launch(_request(lane="cx-live"), launch)
        launch.assert_called_once()


def test_coordinator_relay_retired_delegates_to_shared_predicate() -> None:
    # The repoint (agents/coordinator/core.py::_relay_status_is_retired) closes the
    # SUPERSEDED/CLOSED/ANTIGRAVITY_TAKEOVER vocabulary gap the coordinator
    # previously missed (it routed them -> launcher refused -> rc=6).
    from agents.coordinator.core import _relay_status_is_retired

    # Broad-9 vocabulary (the launcher's — the refusal surface): the coordinator
    # previously missed SUPERSEDED/CLOSED/ANTIGRAVITY_TAKEOVER -> routed -> rc=6.
    assert _relay_status_is_retired("retired") is True
    assert _relay_status_is_retired("wound-down") is True
    assert _relay_status_is_retired("superseded") is True
    assert _relay_status_is_retired("superseded-by-cx-blue") is True
    assert _relay_status_is_retired("closed") is True
    assert _relay_status_is_retired("closed-by-operator") is True
    assert _relay_status_is_retired("antigravity_takeover") is True
    assert _relay_status_is_retired("active") is False
    assert _relay_status_is_retired(None) is False
