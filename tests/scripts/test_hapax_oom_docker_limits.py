from __future__ import annotations

import json
import os
import runpy
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/hapax-oom-docker-limits"
CONTAINER_ID = "a" * 64


def _env(
    tmp_path: Path,
    *,
    ps_failure: bool = False,
    wrong_identity: bool = False,
    inventory_flip: bool = False,
) -> dict[str, str]:
    audit = tmp_path / "audit"
    audit.write_text(
        "#!/bin/sh\nprintf 'appendix\\t32G\\t37G\\t32G\\t38G\\t16G\\t20G\\t12G\\t16384\\t10\\n'\n",
        encoding="utf-8",
    )
    audit.chmod(0o755)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"Memory": 0, "MemorySwap": 0}), encoding="utf-8")
    calls = tmp_path / "docker-calls"
    counter = tmp_path / "inventory-count"
    docker = tmp_path / "docker"
    inspected_id = "b" * 64 if wrong_identity else CONTAINER_ID
    ps_handler = (
        "  count=int(counter.read_text()) if counter.exists() else 0\n"
        "  counter.write_text(str(count+1))\n"
        "  if count: sys.exit(0)\n"
        if inventory_flip
        else ""
    )
    docker.write_text(
        "#!/usr/bin/python3\n"
        "import json, os, pathlib, sys\n"
        f"state=pathlib.Path({str(state)!r})\n"
        f"calls=pathlib.Path({str(calls)!r})\n"
        f"counter=pathlib.Path({str(counter)!r})\n"
        f"cid={CONTAINER_ID!r}\n"
        "args=sys.argv[1:]\n"
        "with calls.open('a') as f: f.write(' '.join(args)+'\\n')\n"
        "args=args[4:]\n"
        "if args == ['ps','-aq','--no-trunc']:\n"
        f"{ps_handler}"
        f"  {'sys.exit(2)' if ps_failure else 'print(cid)'}\n"
        "elif args[:2] == ['inspect','--format']:\n"
        "  value=json.loads(state.read_text())\n"
        f"  print(json.dumps({{'Id': {inspected_id!r}, 'HostConfig': {{**value, 'OomKillDisable': False}}}}))\n"
        "elif args[:1] == ['update']:\n"
        "  value=json.loads(state.read_text())\n"
        "  value['Memory']=int(args[2]); value['MemorySwap']=int(args[4])\n"
        "  state.write_text(json.dumps(value)); print(cid)\n"
        "else: sys.exit(3)\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    return {
        **os.environ,
        "HAPAX_OOM_DOCKER_TEST_MODE": "1",
        "HAPAX_OOM_DOCKER_TEST_DOCKER": str(docker),
        "HAPAX_OOM_DOCKER_TEST_AUDIT": str(audit),
    }


def _run(env: dict[str, str], action: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), action], text=True, capture_output=True, env=env, check=False
    )


def test_uncapped_container_is_audited_then_updated_and_read_back(tmp_path: Path) -> None:
    env = _env(tmp_path)
    before = _run(env, "--audit")
    assert before.returncode == 1
    assert json.loads(before.stdout)["checks"][0]["status"] == "gap"
    applied = _run(env, "--apply")
    assert applied.returncode == 0, applied.stderr
    after = _run(env, "--audit")
    assert after.returncode == 0, after.stderr
    assert json.loads(after.stdout)["checks"][0]["status"] == "pass"
    calls = (tmp_path / "docker-calls").read_text(encoding="utf-8")
    assert "update --memory 8589934592 --memory-swap 10737418240" in calls


def test_inventory_failure_cannot_update_any_container(tmp_path: Path) -> None:
    env = _env(tmp_path, ps_failure=True)
    result = _run(env, "--apply")
    assert result.returncode != 0
    assert "inventory" in result.stderr
    assert " update " not in (tmp_path / "docker-calls").read_text(encoding="utf-8")


def test_changed_inspect_identity_cannot_update_container(tmp_path: Path) -> None:
    env = _env(tmp_path, wrong_identity=True)
    result = _run(env, "--apply")
    assert result.returncode != 0
    assert "identity" in result.stderr
    assert " update " not in (tmp_path / "docker-calls").read_text(encoding="utf-8")


def test_audit_refuses_changing_inventory(tmp_path: Path) -> None:
    result = _run(_env(tmp_path, inventory_flip=True), "--audit")
    assert result.returncode == 1
    check = json.loads(result.stdout)["checks"][0]
    assert check["name"] == "docker_inventory" and check["status"] == "error"


def test_installed_helper_refuses_test_docker_selector(monkeypatch: pytest.MonkeyPatch) -> None:
    namespace = runpy.run_path(str(SCRIPT))
    selector = namespace["_tools"]
    monkeypatch.setitem(selector.__globals__, "__file__", "/usr/local/sbin/hapax-oom-docker-limits")
    monkeypatch.setenv("HAPAX_OOM_DOCKER_TEST_MODE", "1")
    with pytest.raises(namespace["DockerPolicyError"], match="installed Docker policy refuses"):
        selector()
