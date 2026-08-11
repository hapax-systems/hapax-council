from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-local-judge-container-id"
CONTAINER_ID = "a" * 64
REPLACEMENT_ID = "c" * 64
IMAGE = "ghcr.io/ggml-org/llama.cpp@sha256:" + "b" * 64


@dataclass(frozen=True)
class DockerRig:
    docker: Path
    log: Path
    exists: Path
    replacement: Path
    name: Path
    image_missing: Path
    daemon_ready_after: Path
    daemon_attempts: Path
    cidfile: Path
    env: dict[str, str]

    def run(self, action: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                str(SCRIPT),
                action,
                "--cidfile",
                str(self.cidfile),
                "--docker",
                str(self.docker),
                *args,
            ],
            text=True,
            capture_output=True,
            check=False,
            env=self.env,
        )

    def calls(self) -> list[dict[str, object]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]


def _rig(tmp_path: Path, *, running: bool = True) -> DockerRig:
    log = tmp_path / "docker.jsonl"
    exists = tmp_path / "container-exists"
    replacement = tmp_path / "same-name-replacement-exists"
    name = tmp_path / "container-name"
    image_missing = tmp_path / "image-missing"
    daemon_ready_after = tmp_path / "daemon-ready-after"
    daemon_attempts = tmp_path / "daemon-attempts"
    if running:
        exists.touch()
    name.write_text("hapax-local-judge\n", encoding="utf-8")
    docker = tmp_path / "docker"
    docker.write_text(
        "#!/usr/bin/python3\n"
        "import json, os, pathlib, sys\n"
        f"log = pathlib.Path({str(log)!r})\n"
        f"exists = pathlib.Path({str(exists)!r})\n"
        f"replacement = pathlib.Path({str(replacement)!r})\n"
        f"name = pathlib.Path({str(name)!r})\n"
        f"image_missing = pathlib.Path({str(image_missing)!r})\n"
        f"daemon_ready_after = pathlib.Path({str(daemon_ready_after)!r})\n"
        f"daemon_attempts = pathlib.Path({str(daemon_attempts)!r})\n"
        f"container_id = {CONTAINER_ID!r}\n"
        f"replacement_id = {REPLACEMENT_ID!r}\n"
        f"image = {IMAGE!r}\n"
        "args = sys.argv[1:]\n"
        "with log.open('a', encoding='utf-8') as handle:\n"
        "    handle.write(json.dumps({'host': os.environ.get('DOCKER_HOST'), 'args': args}) + '\\n')\n"
        "if args[:2] == ['version', '--format']:\n"
        "    attempt = int(daemon_attempts.read_text()) + 1 if daemon_attempts.exists() else 1\n"
        "    daemon_attempts.write_text(str(attempt))\n"
        "    ready_after = int(daemon_ready_after.read_text()) if daemon_ready_after.exists() else 999999\n"
        "    if attempt < ready_after:\n"
        "        print('daemon unavailable', file=sys.stderr)\n"
        "        raise SystemExit(1)\n"
        "    print('27.5.1')\n"
        "elif args[:3] == ['image', 'inspect', '--format']:\n"
        "    if image_missing.exists():\n"
        "        print('image absent', file=sys.stderr)\n"
        "        raise SystemExit(1)\n"
        "    print(json.dumps([image]))\n"
        "elif args and args[0] == 'inspect':\n"
        "    target = args[-1]\n"
        "    if target == container_id and exists.exists():\n"
        "        print(f'{container_id}|/{name.read_text().strip()}')\n"
        "    elif target == 'hapax-local-judge' and replacement.exists():\n"
        "        print(f'{replacement_id}|/{name.read_text().strip()}')\n"
        "    else:\n"
        "        raise SystemExit(1)\n"
        "elif args and args[0] == 'ps':\n"
        "    if exists.exists():\n"
        "        print(container_id)\n"
        "elif args and args[0] == 'stop':\n"
        "    if len(args) != 2 or args[1] != container_id:\n"
        "        raise SystemExit(7)\n"
        "    exists.unlink(missing_ok=True)\n"
        "    print(container_id)\n"
        "else:\n"
        "    raise SystemExit(9)\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    cidfile = tmp_path / "container.cid"
    cidfile.write_text(CONTAINER_ID, encoding="ascii")
    return DockerRig(
        docker=docker,
        log=log,
        exists=exists,
        replacement=replacement,
        name=name,
        image_missing=image_missing,
        daemon_ready_after=daemon_ready_after,
        daemon_attempts=daemon_attempts,
        cidfile=cidfile,
        env={
            **os.environ,
            "HAPAX_LOCAL_JUDGE_CONTAINER_ID_TEST_MODE": "1",
            "DOCKER_HOST": "tcp://hostile.invalid:2375",
            "DOCKER_CONTEXT": "hostile-context",
        },
    )


def test_wait_daemon_retries_until_the_local_server_answers(tmp_path: Path) -> None:
    rig = _rig(tmp_path)
    rig.daemon_ready_after.write_text("3", encoding="ascii")

    result = rig.run("wait-daemon", "--wait-seconds", "1", "--poll-seconds", "0.01")

    assert result.returncode == 0, result.stderr
    assert "local Docker daemon ready: server=27.5.1" in result.stdout
    assert rig.daemon_attempts.read_text(encoding="ascii") == "3"
    assert all(call["host"] == "unix:///var/run/docker.sock" for call in rig.calls())
    assert all(call["args"][:2] == ["version", "--format"] for call in rig.calls())


def test_wait_daemon_fails_with_bounded_actionable_timeout(tmp_path: Path) -> None:
    rig = _rig(tmp_path)

    result = rig.run("wait-daemon", "--wait-seconds", "0.05", "--poll-seconds", "0.01")

    assert result.returncode == 1
    assert "local Docker daemon was not ready within 0.05 seconds" in result.stderr
    assert "daemon unavailable" in result.stderr
    assert "next action:" in result.stderr


@pytest.mark.parametrize(
    ("wait_seconds", "poll_seconds"),
    (("0", "0.01"), ("301", "1"), ("1", "0"), ("1", "2")),
)
def test_wait_daemon_rejects_invalid_bounds_before_docker(
    tmp_path: Path, wait_seconds: str, poll_seconds: str
) -> None:
    rig = _rig(tmp_path)

    result = rig.run(
        "wait-daemon",
        "--wait-seconds",
        wait_seconds,
        "--poll-seconds",
        poll_seconds,
    )

    assert result.returncode == 1
    assert "Docker readiness wait bounds are invalid" in result.stderr
    assert "next action:" in result.stderr
    assert rig.calls() == []


def _stage_model(tmp_path: Path) -> tuple[Path, Path, str]:
    payload = b"measured-model"
    model_sha = hashlib.sha256(payload).hexdigest()
    model_root = tmp_path / "models" / "sha256"
    model = model_root / model_sha / "judge.gguf"
    model.parent.mkdir(parents=True)
    model.write_bytes(payload)
    model.chmod(0o444)
    return model_root, model, model_sha


def _stage_cap_attestation(
    tmp_path: Path,
    model: Path,
    model_sha: str,
    *,
    image: str = IMAGE,
) -> tuple[Path, Path]:
    state_root = tmp_path / "state" / "root-required"
    installed_root = state_root / "installed-receipts"
    cap_root = state_root / "local-judge-cap-canary"
    installed_root.mkdir(parents=True)
    cap_root.mkdir()
    state_root.chmod(0o700)
    installed_root.chmod(0o700)
    cap_root.chmod(0o700)
    candidate_sha = "d" * 40
    installed = installed_root / "oom-containment.sha"
    installed.write_text(f"{candidate_sha}\n", encoding="ascii")
    installed.chmod(0o600)
    inode = model.stat()
    receipt = cap_root / f"{candidate_sha}.env"
    receipt.write_text(
        "\n".join(
            (
                "schema=1",
                f"candidate_sha={candidate_sha}",
                "host=hapax-appendix",
                "gpu_uuid=GPU-test",
                f"image_ref={image}",
                f"image_id=sha256:{'e' * 64}",
                f"model_sha256={model_sha}",
                f"model_size_bytes={inode.st_size}",
                f"model_host_dir={model.parent}",
                f"model_identity={inode.st_dev}:{inode.st_ino}:{inode.st_ctime_ns}",
                f"workload_oid={'f' * 40}",
                "memory_bytes=4294967296",
                "memory_swap_bytes=6442450944",
                "requests=24",
                "workers=8",
                "memory_peak_bytes=1",
                "swap_peak_bytes=0",
                "completed_at_epoch=1",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    receipt.chmod(0o600)
    return state_root, receipt


def _run_preflight(
    rig: DockerRig,
    *,
    model_root: Path,
    model: Path,
    model_sha: str,
    state_root: Path | None,
) -> subprocess.CompletedProcess[str]:
    state_args = () if state_root is None else ("--state-root", str(state_root))
    return rig.run(
        "preflight",
        "--image",
        IMAGE,
        "--model-host",
        str(model),
        "--model-sha256",
        model_sha,
        "--model-size-bytes",
        str(model.stat().st_size),
        "--model-root",
        str(model_root),
        *state_args,
    )


def _replace_receipt_field(receipt: Path, field: str, value: str) -> None:
    prefix = f"{field}="
    lines = receipt.read_text(encoding="utf-8").splitlines()
    assert sum(line.startswith(prefix) for line in lines) == 1
    receipt.write_text(
        "\n".join(value if line.startswith(prefix) else line for line in lines) + "\n",
        encoding="utf-8",
    )
    receipt.chmod(0o600)


def test_stop_targets_only_the_cidfile_bound_full_id(tmp_path: Path) -> None:
    rig = _rig(tmp_path)

    result = rig.run("stop")

    assert result.returncode == 0, result.stderr
    assert not rig.cidfile.exists()
    assert not rig.exists.exists()
    calls = rig.calls()
    assert all(call["host"] == "unix:///var/run/docker.sock" for call in calls)
    assert {tuple(call["args"]) for call in calls if call["args"][0] == "stop"} == {
        ("stop", CONTAINER_ID)
    }
    assert ("stop", "hapax-local-judge") not in {tuple(call["args"]) for call in calls}


def test_managed_id_returns_only_the_cidfile_bound_identity(tmp_path: Path) -> None:
    rig = _rig(tmp_path)

    result = rig.run("managed-id")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == CONTAINER_ID
    assert [call["args"][-1] for call in rig.calls()] == [CONTAINER_ID]


def test_managed_id_refuses_same_name_replacement_for_absent_bound_id(
    tmp_path: Path,
) -> None:
    rig = _rig(tmp_path)
    rig.exists.unlink()
    rig.replacement.touch()

    result = rig.run("managed-id")

    assert result.returncode == 1
    assert "unit-owned local-judge container is absent" in result.stderr
    assert "do not accept a same-name replacement" in result.stderr
    assert [call["args"][-1] for call in rig.calls()] == [CONTAINER_ID]
    assert all("hapax-local-judge" not in call["args"] for call in rig.calls())


def test_stop_refuses_renamed_id_without_targeting_reused_name(tmp_path: Path) -> None:
    rig = _rig(tmp_path)
    rig.name.write_text("renamed-unit-container\n", encoding="utf-8")

    result = rig.run("stop")

    assert result.returncode == 1
    assert "cidfile identity mismatch" in result.stderr
    assert "next action:" in result.stderr
    assert rig.cidfile.exists()
    assert rig.exists.exists()
    assert all(call["args"][0] != "stop" for call in rig.calls())


def test_prepare_removes_cidfile_only_after_exact_id_absence_is_proven(
    tmp_path: Path,
) -> None:
    rig = _rig(tmp_path, running=False)

    result = rig.run("prepare")

    assert result.returncode == 0, result.stderr
    assert not rig.cidfile.exists()
    assert any(call["args"][0] == "ps" for call in rig.calls())


def test_unsafe_cidfile_is_rejected_without_docker_action(tmp_path: Path) -> None:
    rig = _rig(tmp_path)
    rig.cidfile.write_text("hapax-local-judge\n", encoding="ascii")

    result = rig.run("stop")

    assert result.returncode == 1
    assert "safe caller-owned 64-byte regular file" in result.stderr
    assert rig.calls() == []


def test_preflight_requires_staged_digest_image_and_content_addressed_model(
    tmp_path: Path,
) -> None:
    rig = _rig(tmp_path, running=False)
    model_root, model, model_sha = _stage_model(tmp_path)
    state_root, _ = _stage_cap_attestation(tmp_path, model, model_sha)

    result = _run_preflight(
        rig,
        model_root=model_root,
        model=model,
        model_sha=model_sha,
        state_root=state_root,
    )

    assert result.returncode == 0, result.stderr
    assert "preflight accepted" in result.stdout
    assert f"attestation_sha={'d' * 40}" in result.stdout
    assert rig.calls()[-1]["args"] == [
        "image",
        "inspect",
        "--format",
        "{{json .RepoDigests}}",
        IMAGE,
    ]
    assert rig.calls()[-1]["host"] == "unix:///var/run/docker.sock"


def test_preflight_refuses_missing_pinned_image(tmp_path: Path) -> None:
    rig = _rig(tmp_path, running=False)
    rig.image_missing.touch()
    model_root, model, model_sha = _stage_model(tmp_path)
    state_root, _ = _stage_cap_attestation(tmp_path, model, model_sha)

    result = _run_preflight(
        rig,
        model_root=model_root,
        model=model,
        model_sha=model_sha,
        state_root=state_root,
    )

    assert result.returncode == 1
    assert "pinned local-judge image is not staged" in result.stderr
    assert "next action:" in result.stderr


@pytest.mark.parametrize(
    "field",
    (
        "schema",
        "candidate_sha",
        "model_sha256",
        "model_size_bytes",
        "model_host_dir",
        "model_identity",
        "image_ref",
    ),
)
def test_preflight_refuses_cap_receipt_field_mismatch(tmp_path: Path, field: str) -> None:
    rig = _rig(tmp_path, running=False)
    model_root, model, model_sha = _stage_model(tmp_path)
    state_root, receipt = _stage_cap_attestation(tmp_path, model, model_sha)
    wrong_values = {
        "schema": "schema=2",
        "candidate_sha": f"candidate_sha={'b' * 40}",
        "model_sha256": f"model_sha256={'a' * 64}",
        "model_size_bytes": f"model_size_bytes={model.stat().st_size + 1}",
        "model_host_dir": f"model_host_dir={tmp_path / 'wrong-model-dir'}",
        "model_identity": "model_identity=1:2:3",
        "image_ref": f"image_ref=example.invalid/judge@sha256:{'9' * 64}",
    }
    _replace_receipt_field(receipt, field, wrong_values[field])

    result = _run_preflight(
        rig,
        model_root=model_root,
        model=model,
        model_sha=model_sha,
        state_root=state_root,
    )

    assert result.returncode == 1
    assert f"cap receipt {field} does not match" in result.stderr
    assert rig.calls() == []


@pytest.mark.parametrize("drift", ("in-place", "replacement"))
def test_preflight_refuses_same_size_model_identity_drift(tmp_path: Path, drift: str) -> None:
    rig = _rig(tmp_path, running=False)
    model_root, model, model_sha = _stage_model(tmp_path)
    state_root, _ = _stage_cap_attestation(tmp_path, model, model_sha)
    replacement_payload = b"tampered-model"
    assert len(replacement_payload) == model.stat().st_size
    if drift == "in-place":
        model.chmod(0o644)
        model.write_bytes(replacement_payload)
        model.chmod(0o444)
    else:
        replacement = tmp_path / "replacement.gguf"
        replacement.write_bytes(replacement_payload)
        replacement.chmod(0o444)
        os.replace(replacement, model)

    result = _run_preflight(
        rig,
        model_root=model_root,
        model=model,
        model_sha=model_sha,
        state_root=state_root,
    )

    assert result.returncode == 1
    assert "cap receipt model_identity does not match" in result.stderr
    assert rig.calls() == []


def test_preflight_test_mode_requires_isolated_state_root(tmp_path: Path) -> None:
    rig = _rig(tmp_path, running=False)
    model_root, model, model_sha = _stage_model(tmp_path)

    result = _run_preflight(
        rig,
        model_root=model_root,
        model=model,
        model_sha=model_sha,
        state_root=None,
    )

    assert result.returncode == 2
    assert "requires an isolated --state-root" in result.stderr
    assert rig.calls() == []
