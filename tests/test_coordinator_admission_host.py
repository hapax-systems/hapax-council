"""The coordinator must admit dispatch on the DISPATCH TARGET's pressure, not local.

Regression for the wrong-host admission bug: ``Coordinator.tick`` called
``admission_state()`` with no ``target_host``, so appendix-bound SDLC dispatch was
gated on **local podium** PSI/load. When podium ran hot with PRODUCTION work the
gate went ``closed`` and starved appendix (which was idle) — the documented "raw PSI
starved appendix lanes ~4h" incident. Dev/SDLC execution is confined to appendix
(``LOCAL_DEV_TARGET``); admission must read that host.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.coordinator.core import Coordinator
from shared.dispatcher_policy import LOCAL_DEV_TARGET


def test_tick_admits_on_the_dispatch_target_not_local(tmp_path: Path) -> None:
    coord = Coordinator()
    with (
        patch.object(coord, "_scan_tasks", return_value=[]),
        patch.object(coord, "_check_lanes", return_value={}),
        patch("agents.coordinator.core.admission_state") as mock_admission,
        patch("agents.coordinator.core.SHM_DIR", tmp_path / "shm"),
        patch("agents.coordinator.core.SHM_FILE", tmp_path / "shm" / "state.json"),
        patch("subprocess.run"),
    ):
        # 'closed' takes the minimal downstream path (no reoffer, no dispatch),
        # so the test isolates the admission call itself.
        mock_admission.return_value = MagicMock(state="closed")
        coord.tick()

    mock_admission.assert_called_once_with(target_host=LOCAL_DEV_TARGET)


def test_local_dev_target_is_the_confined_dev_host() -> None:
    # Guards the fix's premise: the constant the coordinator admits on is the
    # appendix dev host, per the dev->appendix confinement.
    assert LOCAL_DEV_TARGET == "appendix"
