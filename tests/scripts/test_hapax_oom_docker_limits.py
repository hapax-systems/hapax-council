from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/hapax-oom-docker-limits"
CONTAINER_ID = "a" * 64


def _env(
    tmp_path: Path, *, ps_failure: bool = False, wrong_identity: bool = False
) -> dict[str, str]:
    audit = tmp_path / "audit"
    audit.write_text(
        "#!/bin/sh\nprintf 'appendix\\t32G\\t37G\\t32G\\t38G\\t16G\\t20G\\t16384\\t10\\n'\n",
        encoding="utf-8",
    )
    audit.chmod(0o755)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"Memory": 0, "MemorySwap": 0}), encoding="utf-8")
    calls = tmp_path / "docker-calls"
    docker = tmp_path / "docker"
    inspected_id = "b" * 64 if wrong_identity else CONTAINER_ID
    docker.write_text(
        "#!/usr/bin/python3\n"
        "import json, os, pathlib, sys\n"
        f"state=pathlib.Path({str(state)!r})\n"
        f"calls=pathlib.Path({str(calls)!r})\n"
        f"cid={CONTAINER_ID!r}\n"
        "args=sys.argv[1:]\n"
        "with calls.open('a') as f: f.write(' '.join(args)+'\\n')\n"
        "args=args[4:]\n"
        "if args == ['ps','-aq','--no-trunc']:\n"
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
