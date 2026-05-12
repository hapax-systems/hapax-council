from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "verify-weblog-producer-deploy.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("verify_weblog_producer_deploy", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def deploy_module(monkeypatch: pytest.MonkeyPatch) -> Any:
    module = _load_module()
    monkeypatch.setattr(module, "check_service_running", lambda: True)
    monkeypatch.setattr(module, "publish_test_post", lambda: True)
    monkeypatch.setattr(
        module,
        "wait_for_event",
        lambda after_ts: {
            "event_id": "rvpe:omg_weblog:deploy-verify-weblog-producer",
            "event_type": "omg.weblog",
            "state_kind": "weblog.entry",
            "salience": 1.0,
        },
    )
    monkeypatch.setattr(module, "check_social_fanout", lambda event_id: {})
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    return module


def test_cleanup_runs_by_default(deploy_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    deleted = False

    def _delete_test_post() -> bool:
        nonlocal deleted
        deleted = True
        return True

    monkeypatch.setattr(deploy_module, "delete_test_post", _delete_test_post)

    assert deploy_module.main([]) == 0
    assert deleted is True


def test_no_cleanup_opt_out_leaves_test_post(
    deploy_module: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    deleted = False

    def _delete_test_post() -> bool:
        nonlocal deleted
        deleted = True
        return True

    monkeypatch.setattr(deploy_module, "delete_test_post", _delete_test_post)

    assert deploy_module.main(["--no-cleanup"]) == 0
    assert deleted is False
