"""Tests for the gitea-mcp vs Forgejo verification harness (scripts/forge-mcp-verify).

S2 slice-2 item 4 (task forge-s2-remaining-scope-slice2-20261006): the harness
manages a gitea-mcp container in HTTP mode against a forge base URL and drives
a read-only MCP battery. All transport and docker launching is faked here; the
live shadow run is recorded in lanebus receipts outside pytest.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "forge-mcp-verify"


def _load_module():
    loader = importlib.machinery.SourceFileLoader("forge_mcp_verify", str(SCRIPT))
    spec = importlib.util.spec_from_loader("forge_mcp_verify", loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules["forge_mcp_verify"] = module
    loader.exec_module(module)
    return module


def sse(payload: dict) -> str:
    return f"event: message\ndata: {json.dumps(payload)}\n\n"


class FakeTransport:
    """Serves canned MCP responses per JSON-RPC id / method; records requests."""

    def __init__(self, *, tools=None, tool_results=None, healthy_after=0, echo_token=None):
        self.calls: list[SimpleNamespace] = []
        self.health_attempts = 0
        self.healthy_after = healthy_after
        self.tools = (
            tools
            if tools is not None
            else [
                {"name": "get_me"},
                {"name": "list_pull_requests"},
                {"name": "pull_request_read"},
                {"name": "list_branches"},
                {"name": "list_commits"},
                {"name": "get_file_contents"},
                {"name": "get_gitea_mcp_server_version"},
            ]
        )
        self.tool_results = tool_results or {}
        self.echo_token = echo_token
        self.next_id = 0

    def __call__(self, method: str, url: str, body: str | None = None, headers: dict | None = None):
        self.calls.append(SimpleNamespace(method=method, url=url, body=body, headers=headers or {}))
        if url.endswith("/healthz"):
            self.health_attempts += 1
            if self.health_attempts <= self.healthy_after:
                return 0, ""
            return 200, "ok"
        if method == "POST" and url.endswith("/mcp"):
            request = json.loads(body or "{}")
            rid = request.get("id", 0)
            if request.get("method") == "initialize":
                result = {
                    "serverInfo": {"name": "Gitea MCP Server", "version": "9.9"},
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                }
            elif request.get("method") == "tools/list":
                result = {"tools": self.tools}
            elif request.get("method") == "tools/call":
                name = request["params"]["name"]
                outcome = self.tool_results.get(name, {"ok": True, "text": f"result for {name}"})
                if outcome.get("ok"):
                    result = {
                        "content": [{"type": "text", "text": outcome["text"]}],
                        "isError": False,
                    }
                else:
                    result = {
                        "content": [{"type": "text", "text": outcome["text"]}],
                        "isError": True,
                    }
                if self.echo_token:
                    result["content"][0]["text"] += self.echo_token
            else:
                return 200, sse(
                    {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown"}}
                )
            return 200, sse({"jsonrpc": "2.0", "id": rid, "result": result})
        return 404, ""


class FakeDocker:
    def __init__(self):
        self.argv: list[str] | None = None
        self.env: dict[str, str] | None = None
        self.torn_down = []

    def __call__(self, argv: list[str], env: dict[str, str] | None = None) -> int:
        self.argv = argv
        self.env = env
        return 0


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    module = _load_module()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORGE_TOKEN", "unit-test-token")
    return module


def run_main(harness, transport, docker, argv=None):
    harness.docker_launch = docker
    harness.docker_teardown = lambda name: docker.torn_down.append(name)
    harness.transport_request = transport
    code = harness.main(argv or [])
    report = Path(harness.REPORT_DEFAULT).read_text()
    return code, report, transport, docker


def test_docker_argv_shape(harness):
    argv = harness.docker_argv(
        image="img:1", name="nm", host_port=18775, container_port=8080, base_url="http://f:3000"
    )
    assert argv[0] == "docker"
    assert "run" in argv
    assert "--rm" in argv
    assert "127.0.0.1:18775:8080" in argv
    assert "img:1" in argv
    # image has no ENTRYPOINT: the binary must be passed explicitly
    assert argv[argv.index("img:1") + 1] == "/app/gitea-mcp"
    assert "-t" in argv and argv[argv.index("-t") + 1] == "http"
    assert "-r" in argv
    env_names = {argv[i + 1].split("=", 1)[0] for i, a in enumerate(argv) if a == "-e"}
    assert "GITEA_HOST" in env_names
    assert "GITEA_ACCESS_TOKEN" in env_names  # name-only passthrough, no value
    assert "GITEA_READONLY=true" in argv
    host_env = {
        argv[i + 1].split("=", 1)[0]: argv[i + 1].split("=", 1)[1]
        for i, a in enumerate(argv)
        if a == "-e" and "=" in argv[i + 1]
    }
    assert host_env["GITEA_HOST"] == "http://f:3000"
    assert "GITEA_ACCESS_TOKEN" not in host_env


def test_token_never_in_argv_or_report(harness, monkeypatch):
    token = "sekrit-token-value-xyz"
    monkeypatch.setenv("FORGE_TOKEN", token)
    docker = FakeDocker()
    transport = FakeTransport(echo_token=token)
    code, report, _, _ = run_main(harness, transport, docker)
    assert code == 0
    for element in docker.argv:
        assert token not in element
    # the token must reach the container through the env mapping instead
    assert docker.env["GITEA_ACCESS_TOKEN"] == token
    assert token not in report


def test_sse_and_json_framing(harness):
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
    assert harness.parse_sse(sse(payload)) == payload
    assert harness.parse_sse(json.dumps(payload)) == payload
    assert harness.parse_sse("") is None


def test_initialize_request_shape(harness):
    transport = FakeTransport()
    run_main(harness, transport, FakeDocker())
    init = [
        c
        for c in transport.calls
        if c.method == "POST" and json.loads(c.body)["method"] == "initialize"
    ]
    assert len(init) == 1
    request = json.loads(init[0].body)
    assert request["params"]["clientInfo"]["name"] == "forge-mcp-verify"
    assert "protocolVersion" in request["params"]
    accept = init[0].headers.get("Accept", "")
    assert "text/event-stream" in accept


def test_write_shaped_tools_skipped_not_called(harness):
    tools = [{"name": "get_me"}, {"name": "issue_write"}, {"name": "label_delete"}]
    transport = FakeTransport(tools=tools)
    code, report, _, _ = run_main(harness, transport, FakeDocker())
    called = {
        json.loads(c.body)["params"]["name"]
        for c in transport.calls
        if c.method == "POST" and json.loads(c.body).get("method") == "tools/call"
    }
    assert "issue_write" not in called and "label_delete" not in called
    entries = [json.loads(line) for line in report.splitlines()]
    skipped = [e for e in entries if e.get("status") == "SKIPPED-WRITE"]
    assert {e["tool"] for e in skipped} == {"issue_write", "label_delete"}
    assert code == 0


def test_battery_all_pass_exit_zero(harness):
    transport = FakeTransport()
    code, report, _, docker = run_main(harness, transport, FakeDocker())
    assert code == 0
    entries = [json.loads(line) for line in report.splitlines()]
    calls = [e for e in entries if e.get("kind") == "tool_call" and e.get("probe") is None]
    assert calls and all(e["status"] == "PASS" for e in calls)
    assert any(
        e["kind"] == "initialize" and e["result"]["serverInfo"]["version"] == "9.9" for e in entries
    )
    assert docker.torn_down  # container removed at the end


def test_battery_failure_exit_one(harness):
    transport = FakeTransport(
        tool_results={
            "list_branches": {"ok": False, "text": "branch error"},
        }
    )
    code, report, _, _ = run_main(harness, transport, FakeDocker())
    assert code == 1
    entries = [json.loads(line) for line in report.splitlines()]
    failed = [e for e in entries if e.get("status") == "FAIL"]
    assert len(failed) == 1 and failed[0]["tool"] == "list_branches"
    assert "branch error" in failed[0]["text_head"]


def test_empty_content_counts_as_fail(harness):
    transport = FakeTransport(
        tool_results={
            "get_me": {"ok": True, "text": ""},
        }
    )
    code, report, _, _ = run_main(harness, transport, FakeDocker())
    assert code == 1
    entries = [json.loads(line) for line in report.splitlines()]
    assert any(e.get("tool") == "get_me" and e["status"] == "FAIL" for e in entries)


def test_divergence_probes_recorded_not_counted(harness):
    transport = FakeTransport(
        tool_results={
            "list_org_repos": {"ok": False, "text": "token does not have scope"},
        }
    )
    code, report, _, _ = run_main(harness, transport, FakeDocker())
    assert code == 0
    entries = [json.loads(line) for line in report.splitlines()]
    probes = [e for e in entries if e.get("probe")]
    assert {e["probe"] for e in probes} == {"org_repos", "pulls_disabled_mirror"}
    org = next(e for e in probes if e["probe"] == "org_repos")
    assert org["isError"] is True and "scope" in org["text_head"]


def test_transport_failure_exit_two_with_next_action(harness, monkeypatch, capsys):
    monkeypatch.setattr(harness, "HEALTHZ_TIMEOUT_SECONDS", 0.2)

    def dead(method, url, body=None, headers=None):
        raise harness.TransportError("connection refused")

    harness.docker_launch = lambda argv, env=None: 0
    harness.docker_teardown = lambda name: None
    harness.transport_request = dead
    code = harness.main([])
    assert code == 2
    err = capsys.readouterr().err
    assert "Next action" in err


def test_healthz_retries_warmup_resets(harness):
    transport = FakeTransport()
    real_call = transport.__call__
    resets = {"left": 2}

    def flaky(method, url, body=None, headers=None):
        if url.endswith("/healthz") and resets["left"] > 0:
            resets["left"] -= 1
            raise harness.TransportError("connection reset by peer")
        return real_call(method, url, body, headers)

    harness.docker_launch = lambda argv, env=None: 0
    harness.docker_teardown = lambda name: None
    harness.transport_request = flaky
    code = harness.main([])
    assert code == 0  # resets during warmup must not abort the run


def test_healthz_retries_until_healthy(harness):
    transport = FakeTransport(healthy_after=2)
    code, _, _, _ = run_main(harness, transport, FakeDocker())
    assert code == 0
    assert transport.health_attempts == 3


def test_main_e2e_report_kinds(harness):
    transport = FakeTransport()
    code, report, transport, docker = run_main(harness, transport, FakeDocker())
    assert code == 0
    entries = [json.loads(line) for line in report.splitlines()]
    kinds = [e["kind"] for e in entries]
    assert kinds[0] == "container"
    assert "initialize" in kinds and "tools_list" in kinds
    assert kinds[-1] == "summary"
    summary = entries[-1]
    assert summary["exit_code"] == 0
    assert summary["tools_total"] == len(transport.tools)
    assert docker.argv[0] == "docker"
