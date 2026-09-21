#!/usr/bin/env python3
"""Measure a trusted source-analysis call; not a production worker admission.

The outer OCI boundary is explicit. Bridge egress is unrestricted. Access tokens
stay in native process memory; the host retains refresh ownership. An existing
output directory is never relaunched. --replay verifies a completed bundle only;
interrupted controllers require inspection of the recorded, owned container.
"""

import argparse
import hashlib
import inspect
import json
import os
import selectors
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from shared.capability_execution import resolve_execution_descriptor  # noqa: E402
from shared.codex_execution_receipt import check_rollout  # noqa: E402
from shared.codex_oauth_refresher import load_access_token, needs_refresh  # noqa: E402
from shared.content_address import ContentAddress  # noqa: E402
from shared.execution_observer import observe_native_lifecycle  # noqa: E402


def reference(path, root):
    return ContentAddress(ref=str(path.relative_to(root)), sha256=digest(path)).model_dump()


def source_manifest(source):
    source = source.resolve(strict=True)
    manifest = {}
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            target = path.resolve(strict=True)
            if not target.is_relative_to(source):
                raise ValueError(
                    "source packet has an external symlink; supply a closed source packet"
                )
            manifest[str(path.relative_to(source))] = {"symlink": os.readlink(path)}
        elif path.is_file():
            manifest[str(path.relative_to(source))] = {"sha256": digest(path)}
    return manifest


def requested_inputs(args, descriptor):
    return {
        "image": args.image,
        "route": args.route,
        "descriptor": descriptor.model_dump(mode="json"),
        "source_manifest": source_manifest(args.source),
        "prompt_sha256": digest(args.prompt) if args.prompt else None,
        "execute": args.execute,
        "cancel_after_tool": args.cancel_after_tool,
        "controller_sha256": digest(Path(__file__)),
        "native_profile": "outer-oci-readonly-no-apps-v1",
        "runtime": args.docker_host or "local:" + socket.gethostname(),
    }


def checked_replay(output, request):
    anchor = json.loads((output / "launch.json").read_text())
    # Reader upgrades do not change the recorded execution. All demand inputs
    # still match; the original controller digest stays in the bound receipt.
    expected = {**request, "controller_sha256": anchor["request"]["controller_sha256"]}
    if anchor["request"] != expected:
        raise ValueError(
            "invocation inputs changed; retained invocation cannot be reused or relaunched"
        )
    ref = ContentAddress.model_validate_json((output / "receipt-ref.json").read_text())
    if ref.ref != "receipt.json" or digest(output / ref.ref) != ref.sha256:
        raise ValueError("receipt reference changed; invocation remains unverified")
    receipt = json.loads((output / ref.ref).read_text())
    if (
        receipt.get("schema") != "hapax.native_execution_probe.v1"
        or receipt.get("request") != anchor["request"]
    ):
        raise ValueError("receipt does not bind this invocation")
    if not receipt.get("complete"):
        raise ValueError(
            "previous invocation incomplete; inspect its owned runtime, do not relaunch"
        )
    if not {"native_stream", "result", "request"}.issubset(receipt["artifacts"]):
        raise ValueError("receipt omits required native result artifacts")
    for item in receipt["artifacts"].values():
        address = ContentAddress.model_validate(item)
        path = (output / address.ref).resolve(strict=True)
        if not path.is_relative_to(output.resolve()) or digest(path) != address.sha256:
            raise ValueError(
                "execution artifact missing, outside bundle, or changed; do not relaunch"
            )
    if not (output / receipt["artifacts"]["result"]["ref"]).read_bytes().strip():
        raise ValueError("result artifact is empty")
    observed = observe_native_lifecycle(
        output / receipt["artifacts"]["native_stream"]["ref"],
        platform="codex-app-server",
        process_returncode=receipt.get("runtime_exit_code"),
    )
    if not observed["complete"] or observed["session_id"] != receipt.get("session_id"):
        raise ValueError("native completion no longer verifies")
    return ref.model_dump()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args, **kw):
    return subprocess.run(args, check=True, capture_output=True, timeout=45, **kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--prompt", type=Path)
    ap.add_argument("--route", default="codex.headless.full")
    ap.add_argument("--docker-host")
    ap.add_argument("--runtime-source", type=Path)
    ap.add_argument("--runtime-state", type=Path)
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--cancel-after-tool", action="store_true")
    args = ap.parse_args()
    if not args.image.startswith("sha256:") or len(args.image) != 71:
        ap.error("--image requires the exact local sha256 image ID")
    if args.execute and args.prompt is None:
        ap.error("--execute requires --prompt")
    if args.cancel_after_tool and not args.execute:
        ap.error("--cancel-after-tool requires --execute")
    descriptor = resolve_execution_descriptor(
        args.route, registry_path=SOURCE / "config/platform-capability-registry.json"
    )
    from shared.capability_execution import codex_execution_args

    codex_execution_args(descriptor)
    invocation_inputs = requested_inputs(args, descriptor)
    if args.replay:
        print(
            json.dumps(
                {
                    "replayed": True,
                    "result_ref": checked_replay(args.output, invocation_inputs),
                    "provider_invocations": 0,
                }
            )
        )
        return 0
    args.output.mkdir(mode=0o700)
    # Exclusive directory creation is the invocation anchor. An interrupted or
    # concurrent call cannot silently repeat a provider invocation at this path.
    with (args.output / "request.json").open("x") as handle:
        json.dump(invocation_inputs, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    directory_fd = os.open(args.output, os.O_DIRECTORY)
    os.fsync(directory_fd)
    os.close(directory_fd)
    parent_fd = os.open(args.output.parent, os.O_DIRECTORY)
    os.fsync(parent_fd)
    os.close(parent_fd)
    state = args.output / "state"
    for part in ("", "sessions", "thread-writer-locks"):
        (state / part).mkdir(exist_ok=True)
    auth_path = Path.home() / ".codex/auth.json"
    token = load_access_token(auth_path)
    if needs_refresh(token, margin_s=1800):
        raise RuntimeError(
            "saved access credential missing or expires within trial window; no refresh attempted"
        )
    account = json.loads(auth_path.read_text())
    if account.get("auth_mode") != "chatgpt" or account.get("OPENAI_API_KEY"):
        raise RuntimeError("trial requires existing subscription auth without API key")
    account_id = account["tokens"]["account_id"]
    # Never transmit the refresh token or mount/copy the saved auth cache.
    sensitive = [v for v in account["tokens"].values() if isinstance(v, str) and v]
    auth_before = digest(auth_path)
    source = args.source.resolve(strict=True)
    runtime_source = args.runtime_source or source
    runtime_state = args.runtime_state or state
    docker = ["docker"] + (["--host", args.docker_host] if args.docker_host else [])
    if args.docker_host and (args.runtime_source is None or args.runtime_state is None):
        raise ValueError("remote measurement requires explicit runtime source and state bindings")
    name = "hapax-execution-" + uuid.uuid4().hex[:12]
    command = docker + [
        "create",
        "-i",
        "--name",
        name,
        "--read-only",
        "--network=bridge",
        "--user=1000:1000",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=128",
        "--memory=2g",
        "--cpus=2",
        "--tmpfs",
        "/tmp:uid=1000,gid=1000,mode=1777",
        "--tmpfs",
        "/opt/hapax-agent/.cache:uid=1000,gid=1000",
        "--tmpfs",
        "/opt/hapax-agent/.codex/skills:uid=1000,gid=1000",
        "--mount",
        f"type=bind,src={runtime_source},dst=/work,readonly",
        "--mount",
        f"type=bind,src={runtime_state},dst=/state",
        "--mount",
        f"type=bind,src={runtime_state}/sessions,dst=/opt/hapax-agent/.codex/sessions",
        args.image,
        "--disable",
        "apps",
        "--disable",
        "plugins",
        "--disable",
        "remote_plugin",
        "--disable",
        "multi_agent",
        "-c",
        'web_search="disabled"',
        "-c",
        'cli_auth_credentials_store="ephemeral"',
        "-c",
        'forced_login_method="chatgpt"',
        "-c",
        'model_provider="openai"',
        "app-server",
        "--stdio",
    ]
    cid = run(command, text=True).stdout.strip()
    receipt = {
        "schema": "hapax.native_execution_probe.v1",
        "container_id": cid,
        "request": invocation_inputs,
        "image": args.image,
        "descriptor": descriptor.model_dump(mode="json"),
        "route": args.route,
        "authority": "support_non_authoritative",
        "may_authorize": False,
        "refresh_credential_transmitted": False,
        "credential_storage": "ephemeral",
        "credential_ref": "native-saved-chatgpt-auth/access-token",
        "network_policy": "Docker bridge; egress not allowlisted",
        "tool_boundary": "outer OCI container; trusted source only",
        "complete": False,
    }
    with (args.output / "launch.json").open("x") as handle:
        json.dump(receipt, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    process = subprocess.Popen(
        docker + ["start", "-ai", cid],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    pending = b""
    sequence = 0
    events = []

    def scrub(text):
        for value in sensitive:
            text = text.replace(value, "[redacted]")
        return text

    err = []

    def readerr():
        for line in process.stderr:
            err.append(scrub(line.decode(errors="replace")))

    reader = threading.Thread(target=readerr, daemon=True)
    reader.start()

    def send(item):
        process.stdin.write(json.dumps(item).encode() + b"\n")
        process.stdin.flush()

    def next_event(deadline):
        nonlocal pending
        while time.monotonic() < deadline:
            if b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                item = json.loads(scrub(line.decode()))
                events.append(item)
                with (args.output / "native.jsonl").open("a") as f:
                    f.write(json.dumps(item) + "\n")
                if item.get("method") == "account/chatgptAuthTokens/refresh":
                    send(
                        {
                            "id": item["id"],
                            "error": {
                                "code": -32000,
                                "message": "bounded trial does not own credential refresh",
                            },
                        }
                    )
                    raise RuntimeError(
                        "external credential refresh requested; trial stopped without fallback"
                    )
                return item
            if selector.select(0.2):
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    raise RuntimeError("native RPC closed unexpectedly")
                pending += chunk
        raise TimeoutError("native response deadline exceeded")

    def request(method, params):
        nonlocal sequence
        sequence += 1
        send({"id": sequence, "method": method, "params": params})
        deadline = time.monotonic() + 45
        while True:
            item = next_event(deadline)
            if item.get("id") == sequence:
                if "error" in item:
                    raise RuntimeError(method + " failed: " + json.dumps(item["error"]))
                return item["result"]

    started = time.monotonic()

    def interrupted(signum, _frame):
        receipt["controller_signal"] = signum
        raise InterruptedError("controller cancellation requested")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    manifest_program = (
        "import hashlib,json,os\nfrom pathlib import Path\n"
        + inspect.getsource(digest)
        + "\n"
        + inspect.getsource(source_manifest)
        + "\nprint(json.dumps(source_manifest(Path('/work')),sort_keys=True))\n"
    )

    def verify_runtime_source():
        actual = json.loads(
            run(docker + ["exec", cid, "python3", "-c", manifest_program], text=True).stdout
        )
        if actual != invocation_inputs["source_manifest"]:
            raise ValueError("mounted runtime source differs from the declared source packet")
        return True

    try:
        request(
            "initialize",
            {
                "clientInfo": {"name": "hapax-bounded-execution-probe", "version": "1"},
                "capabilities": {"experimentalApi": True},
            },
        )
        send({"method": "initialized"})
        receipt["runtime_source_verified_before"] = verify_runtime_source()
        login = request(
            "account/login/start",
            {"type": "chatgptAuthTokens", "accessToken": token.raw, "chatgptAccountId": account_id},
        )
        receipt["native_auth_mode"] = login.get("type")
        assert login.get("type") == "chatgptAuthTokens", (
            "subscription external-token mode not confirmed"
        )
        receipt["rate_limits"] = request("account/rateLimits/read", {})
        if receipt["rate_limits"].get("ordinaryUsageAllowed") is not True:
            raise RuntimeError(
                "ordinary subscription usage not confirmed; no credits or API fallback"
            )
        if args.execute:
            if args.prompt is None:
                raise ValueError("--execute requires an explicit --prompt file")
            prompt = args.prompt.read_text()
            thread = request(
                "thread/start",
                {
                    "cwd": "/work",
                    "approvalPolicy": "never",
                    "sandbox": "danger-full-access",
                    "model": str(descriptor.model_id),
                    "ephemeral": False,
                },
            )
            tid = thread["thread"]["id"]
            receipt["session_id"] = tid
            receipt["instruction_sources"] = thread.get("instructionSources")
            turn = request(
                "turn/start",
                {
                    "threadId": tid,
                    "input": [{"type": "text", "text": prompt}],
                    "effort": str(descriptor.effort),
                },
            )
            turn_id = turn["turn"]["id"]
            receipt["turn_id"] = turn_id
            deadline = time.monotonic() + 900
            while True:
                item = next_event(deadline)
                if (
                    args.cancel_after_tool
                    and not receipt.get("interrupt_requested")
                    and item.get("method") == "item/started"
                    and item["params"]["item"].get("type") == "commandExecution"
                ):
                    receipt["interrupt_requested"] = True
                    request("turn/interrupt", {"threadId": tid, "turnId": turn_id})
                    finished = [
                        e
                        for e in events
                        if e.get("method") == "turn/completed"
                        and e["params"]["turn"]["id"] == turn_id
                    ]
                    if finished:
                        receipt["native_terminal"] = finished[-1]["params"]["turn"]
                        break
                if (
                    item.get("method") == "turn/completed"
                    and item["params"]["turn"]["id"] == turn_id
                ):
                    receipt["native_terminal"] = item["params"]["turn"]
                    break
            messages = [
                e["params"]["item"]["text"]
                for e in events
                if e.get("method") == "item/completed"
                and e.get("params", {}).get("item", {}).get("type") == "agentMessage"
                and e["params"]["item"].get("phase") == "final_answer"
                and e["params"].get("threadId") == tid
                and e["params"].get("turnId") == turn_id
            ]
            result = args.output / "result.md"
            result.write_text("\n\n".join(messages))
            receipt["result"] = {"ref": str(result), "sha256": digest(result)}
            receipt["native_tools_completed"] = sum(
                e.get("method") == "item/completed"
                and e.get("params", {}).get("item", {}).get("type") == "commandExecution"
                and e["params"]["item"].get("exitCode") == 0
                for e in events
            )
        receipt["runtime_source_verified_after"] = verify_runtime_source()
        process.stdin.close()
        process.wait(timeout=15)
        wait = run(docker + ["wait", cid], text=True)
        receipt["runtime_exit_code"] = int(wait.stdout.strip())
        container_info = json.loads(run(docker + ["inspect", cid], text=True).stdout)[0]
        receipt["observed_image"] = container_info["Image"]
        receipt["runtime_state"] = {
            k: container_info["State"][k]
            for k in ("Status", "Running", "ExitCode", "OOMKilled", "Error")
        }
        assert not receipt["runtime_state"]["Running"]
        if args.docker_host:
            run(docker + ["cp", cid + ":/state/.", str(state)])
        if args.execute:
            rollouts = list((state / "sessions").rglob("*.jsonl"))
            identity = [
                x for p in rollouts for x in check_rollout(p, descriptor, route_id=args.route)
            ]
            receipt["identity"] = identity
            lifecycle = observe_native_lifecycle(
                args.output / "native.jsonl",
                platform="codex-app-server",
                process_returncode=receipt["runtime_exit_code"],
            )
            receipt["native_lifecycle"] = lifecycle
            session_ids = {
                json.loads(line)["payload"].get("id")
                for p in rollouts
                for line in p.read_text().splitlines()
                if json.loads(line).get("type") == "session_meta"
            }
            receipt["native_session_ids"] = sorted(session_ids)
            receipt["unexpected_mcp"] = sorted(
                {
                    e["params"]["name"]
                    for e in events
                    if e.get("method") == "mcpServer/startupStatus/updated"
                }
            )
            receipt["source_unchanged"] = requested_inputs(args, descriptor) == invocation_inputs
            receipt["artifacts"] = {
                name: reference(path, args.output)
                for name, path in {
                    "native_stream": args.output / "native.jsonl",
                    "result": result,
                    "request": args.output / "request.json",
                }.items()
            }
            for index, path in enumerate(rollouts):
                receipt["artifacts"][f"rollout_{index}"] = reference(path, args.output)
            receipt["complete"] = bool(
                identity
                and all(x["status"] == "matched" and x["turn_id"] == turn_id for x in identity)
                and lifecycle["complete"]
                and session_ids == {tid}
                and lifecycle["session_id"] == tid
                and receipt["observed_image"] == args.image
                and receipt["source_unchanged"]
                and not receipt["unexpected_mcp"]
                and result.stat().st_size > 0
                and receipt["native_tools_completed"] > 0
            )
            receipt["native_cancellation_observed"] = bool(
                receipt.get("interrupt_requested")
                and receipt["native_terminal"]["status"] == "interrupted"
                and not receipt["runtime_state"]["Running"]
            )
            receipt["provider_cancellation_attested"] = False
        else:
            receipt["auth_probe_passed"] = receipt["runtime_exit_code"] == 0
    except Exception as exc:
        receipt["error"] = scrub(str(exc))
        print(type(exc).__name__, scrub(str(exc)))
    finally:
        if process.poll() is None:
            subprocess.run(docker + ["stop", "-t", "2", cid], capture_output=True, timeout=15)
            process.wait(timeout=15)
        selector.close()
        reader.join(timeout=2)
        (args.output / "stderr.log").write_text("".join(err))
        receipt["elapsed_seconds"] = round(time.monotonic() - started, 3)
        receipt["host_auth_cache_unchanged"] = digest(auth_path) == auth_before
        receipt["owned_state_has_auth_file"] = any(state.rglob("auth.json"))
        # Do not write even a credential fragment to evidence.
        receipt["credential_values_found_in_owned_state"] = sum(
            any(v.encode() in p.read_bytes() for v in sensitive)
            for p in state.rglob("*")
            if p.is_file()
        )
        if (
            receipt["owned_state_has_auth_file"]
            or receipt["credential_values_found_in_owned_state"]
        ):
            receipt["complete"] = False
            receipt["credential_boundary_failed"] = True
        with (args.output / "receipt.json").open("x") as handle:
            handle.write(scrub(json.dumps(receipt, indent=2)))
            handle.flush()
            os.fsync(handle.fileno())
        with (args.output / "receipt-ref.json").open("x") as handle:
            json.dump(reference(args.output / "receipt.json", args.output), handle)
            handle.flush()
            os.fsync(handle.fileno())
        subprocess.run(docker + ["rm", cid], capture_output=True, timeout=15, check=True)
        print(
            json.dumps(
                {
                    k: receipt[k]
                    for k in (
                        "complete",
                        "elapsed_seconds",
                        "host_auth_cache_unchanged",
                        "owned_state_has_auth_file",
                        "credential_values_found_in_owned_state",
                    )
                }
            )
        )
    return (
        0
        if receipt.get("complete")
        or receipt.get("auth_probe_passed")
        or receipt.get("native_cancellation_observed")
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
