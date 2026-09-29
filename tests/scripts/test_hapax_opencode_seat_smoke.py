import hashlib
import http.client
import importlib.machinery
import importlib.util
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

SHARED = b"# Shared instructions\nKeep scope narrow.\n"
SCRIPT = Path(__file__).resolve().parents[2] / "scripts/hapax-opencode-seat-smoke"


@pytest.fixture
def smoke():
    loader = importlib.machinery.SourceFileLoader("smoke", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def observation(smoke):
    now = datetime(2026, 9, 29, 5, tzinfo=UTC)
    balance = {
        "capacity_id": "featherless.prepaid.available",
        "quantity": 1000000000,
        "unit": "nano_usd",
        "label": "observed",
        "source": "https://api.featherless.ai/credits/balance",
        "observed_at": now.isoformat(),
        "measurement_fresh_until": (now + timedelta(seconds=60)).isoformat(),
        "details": {"auto_topup": "off", "billing_mode": "prepaid"},
    }
    return now, balance


def request(smoke):
    return {
        "model": smoke.MODEL,
        "messages": [
            {"role": "system", "content": SHARED.decode()},
            {"role": "user", "content": smoke.PROMPT},
        ],
        "max_tokens": 128,
        "stream": True,
        "stream_options": {"include_usage": True},
    }


@pytest.mark.parametrize("args", [[], ["--check"]])
def test_entry_requires_runtime_evidence(smoke, capsys, args, monkeypatch):
    monkeypatch.delenv("HAPAX_AGENT_ROLE", raising=False)
    assert smoke.main(args) == 2
    assert "runtime_admission_pending" in capsys.readouterr().err


@pytest.mark.parametrize(
    "fault,value",
    [
        ("age", 61),
        ("label", "operator-reported"),
        ("topup", "on"),
        ("topup", "unknown"),
        ("topup", None),
    ],
)
def test_entitlement_refused(smoke, observation, fault, value):
    now, balance = observation
    if fault == "age":
        now += timedelta(seconds=value)
    elif fault == "label":
        balance["label"] = value
    else:
        balance["details"]["auto_topup"] = value
    with pytest.raises(smoke.Refusal):
        smoke.verify_entitlement(balance, now)


def test_alternate_credentials_rejected(smoke, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-only")
    root = tmp_path / "smoke"
    root.mkdir()
    environment = smoke.isolated_environment(root)
    assert "OPENAI_API_KEY" not in environment
    environment["OPENAI_API_KEY"] = "fixture-only"  # pragma: allowlist secret
    with pytest.raises(smoke.Refusal, match="unexpected_child_environment"):
        smoke.verify_environment(root, environment)


def test_user_body_is_not_system_delivery(smoke):
    body = request(smoke)
    body["messages"][0]["role"] = "user"
    guard = smoke.RequestGuard(SHARED, 128, 16384)
    with pytest.raises(smoke.Refusal, match="exact_shared_body_missing"):
        guard.take(json.dumps(body).encode())


@pytest.mark.parametrize(
    "key,value", [("model", "other"), ("max_tokens", 129), ("tools", [{}]), ("padding", 17000)]
)
def test_unsafe_request_refused(smoke, key, value):
    body = request(smoke)
    if key != "padding":
        body[key] = value
    guard = smoke.RequestGuard(SHARED, 128, 16384)
    with pytest.raises(smoke.Refusal):
        guard.take(json.dumps(body).encode() + (b" " * value if key == "padding" else b""))


def test_message_and_session_args_refused(smoke, monkeypatch):
    monkeypatch.setattr(smoke, "runtime_plan", lambda *_a: {})
    monkeypatch.setattr(smoke, "run_smoke", lambda *_a: pytest.fail("unverified target reached"))
    for flag in ("--message-target", "--session", "--continue"):
        with pytest.raises(SystemExit) as refused:
            smoke.main([flag, "hapax-codex-seat"])
        assert refused.value.code == 2


def response(smoke):
    return {
        "id": "fixture-response",
        "model": smoke.MODEL,
        "choices": [
            {"index": 0, "delta": {"content": "HAPAX_OPENCODE_SMOKE_OK"}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
    }


def wire(chunk):
    return ("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode()


@pytest.mark.parametrize("fault", ["truncated", "length", "tools", "over_budget", "no_usage"])
def test_bad_provider_response_refused(smoke, fault):
    bad = response(smoke)
    if fault == "length":
        bad["choices"][0]["finish_reason"] = "length"
    elif fault == "tools":
        bad["choices"][0]["delta"]["tool_calls"] = [{}]
    elif fault == "over_budget":
        bad["usage"]["completion_tokens"] = 129
        bad["usage"]["total_tokens"] = 139
    elif fault == "no_usage":
        del bad["usage"]
    raw = wire(bad)
    if fault == "truncated":
        raw = raw.replace(b"data: [DONE]", b"")
    with pytest.raises(smoke.Refusal):
        smoke.verify_response(raw, 128)


@pytest.mark.parametrize("flag", ["runtime_mutation_authorized", "release_authorized"])
def test_runtime_authority_required(smoke, tmp_path, monkeypatch, flag):
    import shared.dispatcher_policy as policy

    marker = tmp_path / ".cache/hapax/cc-active-task-cx-fixture"
    marker.parent.mkdir(parents=True)
    marker.write_text("fixture-task")
    note = tmp_path / "Documents/Personal/20-projects/hapax-cc-tasks/active/fixture-task.md"
    note.parent.mkdir(parents=True)
    text = (
        "---\ntask_id: fixture-task\nassigned_to: cx-fixture\nstatus: claimed\n"
        "authority_case: CASE-SDLC-REFORM-001\nparent_spec: fixture\n"
        "runtime_mutation_authorized: true\nrelease_authorized: true\n"
        f"mutation_scope_refs: ['{tmp_path}/.cache/hapax/opencode-seat-smoke']\n---\n"
    )
    note.write_text(text.replace(f"{flag}: true", f"{flag}: false"))
    monkeypatch.setattr(
        policy, "load_dispatch_policy_sources", lambda **_k: pytest.fail("policy reached")
    )
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: pytest.fail("secret/process reached"))
    with pytest.raises(smoke.Refusal, match="runtime_authority_missing"):
        smoke.runtime_plan(tmp_path, {"HAPAX_AGENT_ROLE": "cx-fixture"})


def test_native_prefix_and_spent_failure(smoke):
    raw = request(smoke)
    raw["messages"][0]["content"] = (
        "Native system prefix\nInstructions from AGENTS.md\n" + SHARED.decode()
    )
    guard = smoke.RequestGuard(SHARED, 128, 16384)
    wire = json.dumps(raw).encode()
    assert guard.take(wire) == wire
    with pytest.raises(smoke.Refusal):
        guard.take(wire)
    guard = smoke.RequestGuard(SHARED, 128, 16384)
    with pytest.raises(smoke.Refusal):
        guard.take(b"{}")
    with pytest.raises(smoke.Refusal, match="request_ceiling_exhausted"):
        guard.take(json.dumps(raw).encode())


@pytest.mark.parametrize("fault", [None, "config", "helper", "tools", "body", "identity", "retry"])
def test_isolated_runner_boundary(smoke, tmp_path, monkeypatch, fault):
    """Real local HTTP bridge and files; fake native process, secret and provider."""
    plan = {
        "task_id": "fixture",
        "output_base": tmp_path / "runs",
        "binary": tmp_path / "native",
        "shared": SHARED,
    }
    calls = []
    monkeypatch.setattr(smoke, "runtime_plan", lambda *_a: plan)
    plan["measurement"] = {}
    monkeypatch.setattr(smoke, "verify_entitlement", lambda *_a: 1000000000)
    monkeypatch.setattr(smoke.shutil, "which", lambda _name: "/fixture/bwrap")

    def provider(method, _path, _key, raw=None):
        calls.append(method)
        if method == "GET":
            return b'{"currency":"usd","available_nano_usd":"1000000000"}'
        assert json.loads(raw)["model"] == smoke.MODEL
        value = response(smoke)
        if fault == "identity":
            value["model"] = "another"
        return wire(value)

    def process(command, **_kwargs):
        if command[0] == "hapax-secret":
            return subprocess.CompletedProcess(command, 0, "fixture-key\n")
        assert "--clearenv" in command and "--new-session" in command
        env = {command[i + 1]: command[i + 2] for i, arg in enumerate(command) if arg == "--setenv"}
        root = Path(env["HOME"]).parent
        config = json.loads((root / "config/opencode/opencode.json").read_text())
        endpoint = config["provider"]["featherless"]["options"]["baseURL"]
        bridge_key = env["HAPAX_FEATHERLESS_API_KEY"]
        assert bridge_key != "fixture-key" and "OPENAI_API_KEY" not in env
        if command[-2:] == ["debug", "config"]:
            config["provider"]["featherless"]["options"]["apiKey"] = bridge_key
            config["permission"] = {"*": "allow" if fault == "config" else "deny"}
            if fault == "helper":
                config["small_model"] = "openai/helper"
            if fault == "tools":
                config["tools"] = {"bash": True, "edit": True}
            for agent in config["agent"].values():
                agent.update(options={}, permission={})
            config.update(
                {
                    "$schema": "https://opencode.ai/config.json",
                    "mode": {},
                    "command": {},
                    "username": "unknown",
                }
            )
            return subprocess.CompletedProcess(command, 0, json.dumps(config).encode())
        body = request(smoke)
        if fault == "body":
            body["messages"][0]["content"] = "self-report only"
        connection = http.client.HTTPConnection(
            "127.0.0.1", int(endpoint.split(":")[2].split("/")[0]), timeout=5
        )
        for _ in range(2 if fault == "retry" else 1):
            connection.request(
                "POST",
                "/v1/chat/completions",
                json.dumps(body),
                {"Authorization": "Bearer " + bridge_key},
            )
            result = connection.getresponse()
            result.read()
            connection.close()
            if result.status != 200:
                return subprocess.CompletedProcess(command, 1, b"")
        return subprocess.CompletedProcess(
            command, 0, b'{"type":"text","part":{"text":"HAPAX_OPENCODE_SMOKE_OK"}}\n'
        )

    monkeypatch.setattr(smoke, "_provider", provider)
    monkeypatch.setattr(smoke.subprocess, "run", process)
    if fault:
        with pytest.raises(smoke.Refusal):
            smoke.run_smoke(plan, tmp_path, {})
    else:
        assert smoke.run_smoke(plan, tmp_path, {})["route_admitted_by_smoke"] is False
    assert calls.count("POST") == (0 if fault in {"config", "helper", "tools", "body"} else 1)


def test_current_shared_binding(smoke, tmp_path):
    shared = tmp_path / ".config/hapax/agent-instructions/AGENTS.md"
    active = (
        tmp_path / ".cache/hapax/source-activation/worktree/config/agent-instructions/AGENTS.md"
    )
    for path in (shared, active):
        path.parent.mkdir(parents=True)
        path.write_bytes(SHARED)
    receipt = {
        "observation": "filesystem_readback",
        "files": [
            {
                "binding": "shared",
                "path": str(shared),
                "bytes": len(SHARED),
                "sha256": hashlib.sha256(SHARED).hexdigest(),
            }
        ],
    }
    (shared.parent / "current.json").write_text(json.dumps(receipt))
    assert smoke.verify_shared(tmp_path) == SHARED
    active.write_text("stale")
    with pytest.raises(smoke.Refusal):
        smoke.verify_shared(tmp_path)
