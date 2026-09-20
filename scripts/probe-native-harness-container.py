#!/usr/bin/env python3
"""Measure native loading and owned Codex continuation in isolated OCI images.

No credentials, model turns, workstation home or estate services are supplied.
The exact images must already exist locally. This diagnostic does not admit a
production route or prove shell execution, semantic compliance or service readiness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import selectors
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path


def run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=True, capture_output=True, timeout=45, **kwargs)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def container(image: str, project: Path, state: Path) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "-i",
        "--name",
        f"hapax-binding-{uuid.uuid4().hex[:12]}",
        "--read-only",
        "--network=none",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=128",
        "--memory=2g",
        "--cpus=2",
        "--tmpfs",
        "/tmp:uid=1000,gid=1000,mode=1777",
        "--tmpfs",
        "/opt/hapax-agent/.cache:uid=1000,gid=1000",
        "--mount",
        f"type=bind,src={project},dst=/work,readonly",
        "--mount",
        f"type=bind,src={state},dst=/evidence",
        image,
    ]


def finish(process: subprocess.Popen, command: list[str]) -> int:
    if process.stdin and not process.stdin.closed:
        process.stdin.close()
    try:
        return process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        name = command[command.index("--name") + 1]
        run(["docker", "stop", "-t", "1", name])
        process.wait(timeout=10)
        raise RuntimeError(f"native process required forced stop: {name}") from None


class Rpc:
    def __init__(self, command: list[str], evidence: Path):
        self.command = command
        self.err = (evidence / "stderr.log").open("wb")
        self.out = (evidence / "stdout.jsonl").open("ab")
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.err
        )
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.pending = b""
        self.sequence = 0

    def send(self, item: dict) -> None:
        self.process.stdin.write(json.dumps(item).encode() + b"\n")
        self.process.stdin.flush()

    def request(self, method: str, params: dict) -> dict:
        self.sequence += 1
        self.send({"id": self.sequence, "method": method, "params": params})
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            while b"\n" in self.pending:
                line, self.pending = self.pending.split(b"\n", 1)
                self.out.write(line + b"\n")
                self.out.flush()
                item = json.loads(line)
                if item.get("id") == self.sequence:
                    return item
            if self.process.poll() is not None:
                raise RuntimeError(f"native RPC exited during {method}")
            if self.selector.select(0.2):
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise RuntimeError(f"native RPC EOF during {method}")
                self.pending += chunk
        raise TimeoutError(f"native RPC timed out: {method}")

    def close(self) -> int:
        try:
            return finish(self.process, self.command)
        finally:
            self.selector.close()
            self.err.close()
            self.out.close()


def codex(
    image: str,
    project: Path,
    state: Path,
    evidence: Path,
    *,
    cwd: str = "/work",
    resume: str | None = None,
    persist: bool = False,
) -> dict:
    evidence.mkdir()
    state.mkdir(exist_ok=True)
    for directory in ("sessions", "thread-writer-locks"):
        (state / directory).mkdir(exist_ok=True)
    command = container(image, project, evidence)
    command[-1:-1] = [
        "--tmpfs",
        "/opt/hapax-agent/.codex/skills:uid=1000,gid=1000",
        "--mount",
        f"type=bind,src={state},dst=/state",
        "--mount",
        f"type=bind,src={state / 'sessions'},dst=/opt/hapax-agent/.codex/sessions",
    ]
    command += ["app-server", "--stdio"]
    rpc = Rpc(command, evidence)
    try:
        initialized = rpc.request(
            "initialize",
            {
                "clientInfo": {"name": "hapax-instruction-probe", "version": "1"},
                "capabilities": {"experimentalApi": True},
            },
        )
        assert "result" in initialized, initialized
        rpc.send({"method": "initialized"})
        params = {
            "cwd": cwd,
            "approvalPolicy": "never",
            "sandbox": "read-only",
            "model": "gpt-6-astra",
        }
        if resume:
            params["threadId"] = resume
        else:
            params["ephemeral"] = False
        response = rpc.request("thread/resume" if resume else "thread/start", params)
        if persist:
            thread_id = response["result"]["thread"]["id"]
            injected = rpc.request(
                "thread/inject_items",
                {
                    "threadId": thread_id,
                    "items": [
                        {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": "Owned persistence fixture; no response requested.",
                                }
                            ],
                        }
                    ],
                },
            )
            assert "result" in injected, injected
    finally:
        rc = rpc.close()
    assert rc == 0, rc
    return response


def claude(image: str, project: Path, evidence: Path, cwd: str) -> list[dict]:
    evidence.mkdir()
    command = container(image, project, evidence)
    command[-1:-1] = ["--workdir", cwd]
    command += [
        "-p",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--verbose",
        "--tools",
        "",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--setting-sources",
        "user,project",
        "--settings",
        "/work/settings.json",
        "--no-session-persistence",
    ]
    with (evidence / "stdout.jsonl").open("w") as out, (evidence / "stderr.log").open("w") as err:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=out, stderr=err)
        try:
            process.stdin.write(
                json.dumps(
                    {
                        "type": "control_request",
                        "request_id": "probe",
                        "request": {"subtype": "initialize"},
                    }
                ).encode()
                + b"\n"
            )
            process.stdin.flush()
            deadline = time.monotonic() + 15
            loaded = evidence / "loaded.jsonl"
            while time.monotonic() < deadline and process.poll() is None:
                if loaded.exists() and len(loaded.read_text().splitlines()) >= 2:
                    break
                time.sleep(0.1)
        finally:
            rc = finish(process, command)
    assert rc == 0, rc
    return [json.loads(line) for line in loaded.read_text().splitlines()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--claude-image", required=True)
    parser.add_argument("--codex-image", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    # A remote replay may use an explicitly transferred source archive rather
    # than a Git checkout. Report that distinction instead of inventing a head.
    source_check = subprocess.run(
        ["git", "-C", str(args.source), "show", f"{args.source_revision}:AGENTS.md"],
        capture_output=True,
        timeout=15,
    )
    source_matches_revision = None
    if source_check.returncode == 0:
        source_matches_revision = source_check.stdout == (args.source / "AGENTS.md").read_bytes()
        if not source_matches_revision:
            raise ValueError("project instructions do not match the specified source revision")
    root = args.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=False)
    project = root / "project"
    project.mkdir()
    (project / "nested").mkdir()
    shutil.copyfile(args.source / "AGENTS.md", project / "AGENTS.md")
    (project / "CLAUDE.md").symlink_to("AGENTS.md")
    run(["git", "-C", str(project), "init", "-q"])
    (project / "capture.py").write_text(
        "import json,sys,hashlib\nfrom pathlib import Path\n"
        'x=json.load(sys.stdin)\np=Path(x["file_path"])\n'
        'x["sha256"]=hashlib.sha256(p.read_bytes()).hexdigest()\n'
        'with open("/evidence/loaded.jsonl","a") as f:f.write(json.dumps(x)+"\\n")\n'
    )
    (project / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "InstructionsLoaded": [
                        {"hooks": [{"type": "command", "command": "python3 /work/capture.py"}]}
                    ]
                }
            }
        )
    )
    summary = {
        "source_revision": args.source_revision,
        "source_matches_revision": source_matches_revision,
        "probe_sha256": digest(Path(__file__)),
        "observer_host": socket.gethostname(),
        "project_sha256": digest(project / "AGENTS.md"),
        "model_requests": 0,
        "provider_credentials": "absent",
        "network": "none",
        "may_authorize": False,
        "service_readiness": "unobserved",
        "shell_execution": "unobserved",
        "semantic_compliance": "unobserved",
        "images": {},
        "cells": [],
    }
    images = {}
    for name, reference in (("claude", args.claude_image), ("codex", args.codex_image)):
        image_id = run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", reference], text=True
        ).stdout.strip()
        if reference != image_id and "@sha256:" not in reference:
            raise ValueError("use an immutable image ID or repository digest, not a tag")
        images[name] = image_id
        installed = json.loads(
            run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--read-only",
                    "--network=none",
                    "--entrypoint=cat",
                    image_id,
                    "/opt/hapax/instruction-install.json",
                ]
            ).stdout
        )
        assert installed["source_revision"] == args.source_revision
        proof_state = root / f"{name}-filesystem-proof"
        proof_state.mkdir()
        proof_command = container(image_id, project, proof_state)
        proof_command[-1:-1] = ["--entrypoint=python3"]
        proof_command += [
            "-c",
            """import json,hashlib,errno
from pathlib import Path
installed=json.loads(Path("/opt/hapax/instruction-install.json").read_text())
for item in installed["files"]:
    assert hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest()==item["sha256"]
for name in ("/work/AGENTS.md", "/opt/hapax-agent/.codex/AGENTS.md"):
    try:
        with open(name,"ab") as stream: stream.write(b"unexpected mutation")
    except OSError as exc:
        assert exc.errno in (errno.EROFS,errno.EACCES)
    else: raise AssertionError("immutable input was writable: "+name)
Path("/evidence/owned-write").write_text("owned state remains writable")
print(json.dumps({"instruction_hashes_match":True,"input_writes_denied":True,
"owned_state_writable":True,"os_packages_sha256":hashlib.sha256(Path("/opt/hapax/os-packages.txt").read_bytes()).hexdigest()}))
""",
        ]
        proof = json.loads(run(proof_command).stdout)
        version = run(
            ["docker", "run", "--rm", "--read-only", "--network=none", image_id, "--version"],
            text=True,
        ).stdout.strip()
        summary["images"][name] = {
            "id": image_id,
            "version": version,
            "instruction_install": installed,
            "filesystem": proof,
        }
    expected_sources = ["/opt/hapax-agent/.codex/AGENTS.md", "/work/AGENTS.md"]
    for label, cwd in (("root", "/work"), ("nested", "/work/nested")):
        events = claude(images["claude"], project, root / f"claude-{label}", cwd)
        expected_hash = next(
            f["sha256"]
            for f in summary["images"]["claude"]["instruction_install"]["files"]
            if f["binding"] == "claude"
        )
        assert sorted(e["file_path"] for e in events) == [
            "/opt/hapax-agent/.claude/CLAUDE.md",
            "/work/CLAUDE.md",
        ]
        assert {e["sha256"] for e in events} == {expected_hash, summary["project_sha256"]}
        summary["cells"].append(
            {
                "platform": "claude",
                "cwd": cwd,
                "files": [{"path": e["file_path"], "sha256": e["sha256"]} for e in events],
                "pass": True,
            }
        )
        state = root / f"state-{label}"
        started = codex(
            images["codex"], project, state, root / f"codex-{label}", cwd=cwd, persist=True
        )["result"]
        assert started["instructionSources"] == expected_sources, started["instructionSources"]
        thread_id = started["thread"]["id"]
        resumed = codex(
            images["codex"],
            project,
            state,
            root / f"codex-resume-{label}",
            cwd=cwd,
            resume=thread_id,
        )["result"]
        assert resumed["thread"]["id"] == thread_id
        assert resumed["instructionSources"] == expected_sources
        assert any(
            "Owned persistence fixture" in p.read_text()
            for p in (state / "sessions").rglob("*.jsonl")
        )
        summary["cells"].append(
            {
                "platform": "codex",
                "cwd": cwd,
                "instruction_sources": started["instructionSources"],
                "resume": "same_native_session",
                "owned_state_persisted": True,
                "pass": True,
            }
        )
    (project / "AGENTS.override.md").write_text("Unexpected fixture override.\n")
    overridden = codex(images["codex"], project, root / "state-override", root / "codex-override")[
        "result"
    ]
    assert overridden["instructionSources"] != expected_sources
    assert "/work/AGENTS.override.md" in overridden["instructionSources"]
    (project / "AGENTS.override.md").unlink()
    (project / "AGENTS.md").unlink()
    missing = codex(images["codex"], project, root / "state-missing", root / "codex-missing")[
        "result"
    ]
    assert missing["instructionSources"] == expected_sources[:1]
    wrong = codex(
        images["codex"],
        project,
        root / "state-root",
        root / "codex-wrong-resume",
        resume="00000000-0000-4000-8000-000000000000",
    )
    assert "error" in wrong
    summary["negative_cells"] = {
        "override_mismatch_detected": True,
        "missing_instruction_detected": True,
        "wrong_resume_id_rejected": True,
    }
    # Preserve the positive fixture for inspection after exercising absence.
    shutil.copyfile(args.source / "AGENTS.md", project / "AGENTS.md")
    (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
