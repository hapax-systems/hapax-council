#!/usr/bin/env python3
"""Replay the Linux instruction-loader fixture; no user turn or model request.

Writes only to a new output directory. Never edits the source checkout, installs
a client, changes estate trust, or inherits provider credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

CAPTURE = """import hashlib, json, sys
from pathlib import Path
event = json.load(sys.stdin)
if event.get("memory_type") == "Project":
    body = Path(event["file_path"]).read_bytes()
    event["observed_file_bytes"] = len(body)
    event["observed_file_sha256"] = hashlib.sha256(body).hexdigest()
with Path(sys.argv[1]).open("a") as out:
    out.write(json.dumps(event) + "\\n")
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claude", required=True, help="Existing native Claude executable")
    parser.add_argument("--instructions", type=Path, default=Path("AGENTS.md"))
    parser.add_argument("--output-dir", type=Path, required=True, help="Must not already exist")
    args = parser.parse_args()
    binary = shutil.which(args.claude)
    if binary is None:
        parser.error("--claude must identify an existing executable; no installation is attempted")
    binary = str(Path(binary).resolve())
    source = args.instructions.resolve(strict=True)
    body = source.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    project = output / "project"
    nested = project / "nested"
    nested.mkdir(parents=True)
    (project / "AGENTS.md").write_bytes(body)
    (project / "CLAUDE.md").symlink_to("AGENTS.md")
    home = output / "home"
    home.mkdir()
    capture = output / "capture.py"
    capture.write_text(CAPTURE)
    # A small allowlist avoids inheriting auth, proxy, provider, and harness config.
    env = {
        "PATH": os.defpath,
        "HOME": str(home),
        "DISABLE_AUTOUPDATER": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    }
    version = subprocess.check_output([binary, "--version"], env=env, text=True, timeout=30).strip()
    revision = subprocess.run(
        ["git", "-C", str(source.parent), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    committed = subprocess.run(
        ["git", "-C", str(source.parent), "show", f"HEAD:./{source.name}"],
        capture_output=True,
        check=True,
    ).stdout
    summary = {
        "source_head": revision,
        "source_path": source.name,
        "source_matches_head": committed == body,
        "canonical_bytes": len(body),
        "canonical_sha256": digest,
        "client_version": version,
        "client_sha256": hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
        "environment": {key: value.replace(str(output), "<fixture>") for key, value in env.items()},
        "user_turns": 0,
        "initialize_receipt_timeout_seconds": 10,
        "cells": [],
    }
    initialize = (
        json.dumps(
            {
                "type": "control_request",
                "request_id": "instruction-probe",
                "request": {"subtype": "initialize"},
            }
        )
        + "\n"
    )
    for label, cwd in (("root", project), ("nested", nested)):
        config = output / f"{label}-config"
        config.mkdir()
        events_path = output / f"{label}-instructions.jsonl"
        hook = shlex.join([sys.executable, str(capture), str(events_path)])
        settings = {
            "hooks": {"InstructionsLoaded": [{"hooks": [{"type": "command", "command": hook}]}]}
        }
        settings_path = output / f"{label}-settings.json"
        settings_path.write_text(json.dumps(settings))
        command = [
            binary,
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
            "project",
            "--settings",
            str(settings_path),
            "--no-session-persistence",
        ]
        # Keep SDK input open until an instruction receipt arrives. EOF directly
        # after initialize can race older clients' asynchronous memory loader.
        # File-backed output avoids a full stdout pipe blocking initialization.
        with (
            (output / f"{label}-stdout.jsonl").open("w") as stdout,
            (output / f"{label}-stderr.log").open("w") as stderr,
            subprocess.Popen(
                command,
                cwd=cwd,
                env={**env, "CLAUDE_CONFIG_DIR": str(config)},
                stdin=subprocess.PIPE,
                stdout=stdout,
                stderr=stderr,
                text=True,
            ) as process,
        ):
            assert process.stdin is not None
            process.stdin.write(initialize)
            process.stdin.flush()
            deadline = time.monotonic() + summary["initialize_receipt_timeout_seconds"]
            while process.poll() is None and time.monotonic() < deadline:
                if events_path.exists() and events_path.read_text().endswith("\n"):
                    break
                time.sleep(0.05)
            try:
                process.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise
        events = (
            [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
            if events_path.exists()
            else []
        )
        project_events = [event for event in events if event.get("memory_type") == "Project"]
        passed = (
            process.returncode == 0
            and len(project_events) == 1
            and all(
                event.get("file_path") == str(project / "CLAUDE.md")
                and event.get("observed_file_sha256") == digest
                and event.get("load_reason") == "session_start"
                for event in project_events
            )
        )
        # Keep full native receipts in scratch; publish only instruction facts.
        summary["cells"].append(
            {
                "cwd": label,
                "exit_code": process.returncode,
                "passed": passed,
                "command": [
                    part.replace(binary, "<claude>").replace(str(output), "<fixture>")
                    for part in command
                ],
                "events": [
                    {
                        key: str(event[key]).replace(str(output), "<fixture>")
                        for key in (
                            "hook_event_name",
                            "file_path",
                            "memory_type",
                            "load_reason",
                            "observed_file_bytes",
                            "observed_file_sha256",
                        )
                        if key in event
                    }
                    for event in project_events
                ],
            }
        )
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(output / "summary.json")
    return 0 if all(cell["passed"] for cell in summary["cells"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
