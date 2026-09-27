#!/usr/bin/env python3
"""Manual Linux discovery fixture: native inspection only, no inference turn."""

import argparse
import fcntl
import hashlib
import json
import os
import pty
import re
import select
import struct
import subprocess
import termios
import time
from pathlib import Path


def put(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def run(command, project, env, prefix):
    with prefix.with_suffix(".stdout").open("wb") as out:
        with prefix.with_suffix(".stderr").open("wb") as err:
            process = subprocess.Popen(
                command,
                cwd=project,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
            )
            try:
                return process.wait(timeout=15)
            finally:
                stop(process)


def plain(data):
    text = data.decode("utf-8", errors="replace")
    text = re.sub(r"\x1b\][^\x07]*(?:\x07|\x1b\\)", "", text)
    return re.sub(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|[ -/]*[@-~])", "", text)


def muse(binary, project, env, log_path):
    master, slave = pty.openpty()
    process = None
    data = bytearray()
    query_tail = b""
    forced = False
    try:
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                [
                    binary,
                    "--provider",
                    "echo",
                    "--approval-judge",
                    "off",
                    "--disable-shell",
                    "--disable-write",
                    "--trust-workspace",
                ],
                cwd=project,
                env=env,
                stdin=slave,
                stdout=slave,
                stderr=slave,
            )
            os.close(slave)
            slave = -1

            def capture(seconds):
                nonlocal query_tail
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    if not select.select(
                        [master], [], [], min(0.1, max(0, deadline - time.monotonic()))
                    )[0]:
                        continue
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    log.write(chunk)
                    log.flush()
                    data.extend(chunk)
                    combined = query_tail + chunk
                    for _ in range(combined.count(b"\x1b[6n")):
                        os.write(master, b"\x1b[1;1R")
                    query_tail = combined[-3:]
                    if len(data) > 4 * 1024 * 1024:
                        raise RuntimeError("TUI capture exceeded 4 MiB; inspect raw log")

            deadline = time.monotonic() + 10
            while process.poll() is None and time.monotonic() < deadline:
                capture(0.1)
                if "❯" in plain(data) and "echo" in plain(data):
                    break
            else:
                raise RuntimeError("Muse prompt unobserved; inspect raw log")
            os.write(master, b"/rules")
            capture(0.5)  # A combined command/Enter write is treated as paste.
            offset = len(data)
            os.write(master, b"\r")
            capture(5)
            report = plain(data[offset:])
            os.write(master, b"/exit")
            capture(0.5)
            os.write(master, b"\r")
            capture(2)
            forced = process.poll() is None
    finally:
        if process is not None:
            stop(process)
        os.close(master)
        if slave >= 0:
            os.close(slave)
    compact = re.sub(r"\s+", "", report)
    checks = {
        "rules_report": "Rules loaded this session (in precedence order):" in report,
        "native_global": "user: $CONFIG_DIR/AGENTS.md" in report,
        "empty_project": "project: none" in report,
    }
    for vendor, relative in (("Claude Code", ".claude/CLAUDE.md"), ("Codex", ".codex/AGENTS.md")):
        expected = f"{vendor} rules at {env['HOME']}/{relative} — not read;"
        checks[relative] = re.sub(r"\s+", "", expected) in compact
    return {"checks": checks, "exit_code": process.returncode, "terminated": forced}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grok", required=True, type=Path, help="Absolute native ELF path")
    parser.add_argument("--muse", required=True, type=Path, help="Absolute native ELF path")
    parser.add_argument("--output-dir", required=True, type=Path, help="New directory only")
    args = parser.parse_args()
    for binary in (args.grok, args.muse):
        if not binary.is_absolute() or not binary.is_file() or not os.access(binary, os.X_OK):
            parser.error(f"Select an existing absolute native executable: {binary}")
        with binary.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                parser.error(f"Native Linux ELF required; wrappers are excluded: {binary}")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    cells = []
    for client in ("grok", "muse"):
        for enabled in (True, False):
            case = output / f"{client}-{str(enabled).lower()}"
            home, project = case / "home", case / "project"
            project.mkdir(parents=True)
            env = {
                "PATH": os.defpath,
                "HOME": str(home),
                "TERM": "xterm-256color",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
            }
            for key, relative in (
                ("XDG_CONFIG_HOME", ".config"),
                ("XDG_DATA_HOME", ".local/share"),
                ("XDG_STATE_HOME", ".local/state"),
                ("XDG_CACHE_HOME", ".cache"),
                ("XDG_RUNTIME_DIR", "runtime"),
                ("TMPDIR", "tmp"),
            ):
                directory = home / relative
                directory.mkdir(parents=True, mode=0o700)
                env[key] = str(directory)
            cell = {
                "case": case.name,
                "binary": str(getattr(args, client).resolve()),
                "binary_sha256": hashlib.sha256(getattr(args, client).read_bytes()).hexdigest(),
                "status": "unobserved",
                "raw_logs": [],
            }
            cells.append(cell)
            try:
                cell["raw_logs"] += [str(case / "git.stdout"), str(case / "git.stderr")]
                if run(["git", "init", "--quiet", "--template="], project, env, case / "git"):
                    raise RuntimeError("Fixture git init failed; inspect git.stderr")
                put(home / ".claude/CLAUDE.md", "Fixture foreign Claude global instruction.\n")
                if client == "grok":
                    env["GROK_HOME"] = str(home / ".grok")
                    env["GROK_FOLDER_TRUST"] = "0"  # This isolated fixture process only.
                    fixtures = {
                        home / ".grok/AGENTS.md": True,
                        project / "AGENTS.md": True,
                        project / "CLAUDE.md": True,
                        home / ".claude/CLAUDE.md": enabled,
                        project / ".claude/CLAUDE.md": enabled,
                        home / ".claude/rules/unique.md": not enabled,
                    }
                    for path in fixtures:
                        put(path, f"Fixture instruction: {path.relative_to(case)}.\n")
                    put(
                        home / ".grok/config.toml",
                        f"[compat.claude]\nagents = {str(enabled).lower()}\n"
                        f"rules = {str(not enabled).lower()}\n",
                    )
                    cell["raw_logs"] += [str(case / "inspect.stdout"), str(case / "inspect.stderr")]
                    code = run(
                        [cell["binary"], "inspect", "--json"],
                        project,
                        env,
                        case / "inspect",
                    )
                    receipt = json.loads((case / "inspect.stdout").read_text())
                    active = {
                        entry["path"]
                        for entry in receipt["projectInstructions"]
                        if not entry.get("disabled", False)
                        and entry.get("compatibilityStatus") != "disabled"
                    }
                    cell.update(
                        exit_code=code,
                        version=receipt.get("grokVersion"),
                        active_paths=sorted(active),
                    )
                    cell["checks"] = {
                        "inspect_exit": code == 0,
                        "fixture_trusted": receipt.get("projectTrusted") is True,
                        "active_fixture_paths": active
                        == {str(p) for p, on in fixtures.items() if on},
                    }
                else:
                    put(
                        home / ".config/muse/AGENTS.md", "Fixture native Muse global instruction.\n"
                    )
                    put(home / ".codex/AGENTS.md", "Fixture foreign Codex global instruction.\n")
                    put(
                        home / ".config/muse/settings.json",
                        json.dumps(
                            {
                                "schema_version": 1,
                                "provider": "echo",
                                "context": {
                                    "foreign_personal_rules": enabled,
                                    "foreign_personal_skills": True,
                                },
                            }
                        )
                        + "\n",
                    )
                    cell["raw_logs"].append(str(case / "tui.log"))
                    cell.update(muse(cell["binary"], project, env, case / "tui.log"))
                cell["status"] = (
                    "observed" if all(cell["checks"].values()) else "unobserved_or_mismatch"
                )
            except (
                OSError,
                ValueError,
                KeyError,
                TypeError,
                RuntimeError,
                subprocess.TimeoutExpired,
            ) as exc:
                cell["error"] = f"{type(exc).__name__}: {exc}; inspect raw_logs"
    summary = {"may_authorize": False, "semantic_uptake": "unobserved", "cells": cells}
    put(output / "summary.json", json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if all(cell["status"] == "observed" for cell in cells) else 1


if __name__ == "__main__":
    raise SystemExit(main())
