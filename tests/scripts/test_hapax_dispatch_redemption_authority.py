from __future__ import annotations

import importlib.machinery
import importlib.util
import socket
import threading
import time
from pathlib import Path
from types import ModuleType

from shared.governance.dispatch_redemption import (
    DispatchLaunchRedemptionAuthority,
    DispatchLaunchRedemptionServer,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-dispatch-redemption-authority"


def _load_authority_script() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader(
        "hapax_dispatch_redemption_authority", str(SCRIPT)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_runtime_receipt_refuses_socket_without_protocol_witness(tmp_path: Path) -> None:
    script = _load_authority_script()
    runtime_dir = tmp_path / "coord"
    runtime_dir.mkdir()
    runtime_dir.chmod(0o750)
    socket_path = runtime_dir / "dispatch-redemption.sock"

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as fake_server:
        fake_server.bind(str(socket_path))
        socket_path.chmod(0o660)
        fake_server.listen(1)

        receipt = script.runtime_receipt(runtime_dir, socket_path)

    assert receipt["healthy"] is False
    assert receipt["protocol_probe"]["ok"] is False


def test_runtime_receipt_requires_live_governor_protocol(tmp_path: Path) -> None:
    script = _load_authority_script()
    runtime_dir = tmp_path / "coord"
    socket_path = runtime_dir / "dispatch-redemption.sock"
    server = DispatchLaunchRedemptionServer(
        DispatchLaunchRedemptionAuthority(now=lambda: 1000.0),
        socket_path=socket_path,
    )
    thread = threading.Thread(target=server.serve_once, kwargs={"timeout_s": 5.0})
    thread.start()

    receipt = _receipt_with_retry(script, runtime_dir, socket_path)
    thread.join(timeout=5)

    assert receipt["healthy"] is True
    assert receipt["runtime_dir"]["mode"] == "0750"
    assert receipt["socket"]["mode"] == "0660"
    assert receipt["protocol_probe"] == {"ok": True, "reason": "protocol_witnessed"}


def _receipt_with_retry(
    script: ModuleType, runtime_dir: Path, socket_path: Path
) -> dict[str, object]:
    last: dict[str, object] | None = None
    for _ in range(100):
        last = script.runtime_receipt(runtime_dir, socket_path)
        if last["healthy"] is True:
            return last
        time.sleep(0.01)
    assert last is not None
    return last
