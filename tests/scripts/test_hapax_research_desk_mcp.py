"""Transport, auth and end-to-end tests for the research desk MCP server.

The auth edge is tested by driving the real ASGI app with a recording ``send``:
there is no HTTP client between the assertion and the code, so a 401 here is the
bytes the connector would receive. The end-to-end test is the one the task row
requires before any connector is registered — a real uvicorn on an ephemeral port,
spoken to by the official MCP Streamable-HTTP client.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.machinery
import importlib.util
import json
import socket
import threading
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from shared import research_desk_ledger as ledger_mod
from shared.research_desk import ResearchDeskConfig

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "hapax-research-desk-mcp"


def _load_module() -> types.ModuleType:
    loader = importlib.machinery.SourceFileLoader("hapax_research_desk_mcp", str(_SCRIPT_PATH))
    spec = importlib.util.spec_from_loader("hapax_research_desk_mcp", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


desk_mcp = _load_module()

KEY = "test-key-with-enough-entropy-0123456789"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def config(tmp_path: Path) -> ResearchDeskConfig:
    vault = tmp_path / "vault"
    (vault / "20-projects" / "hapax-cc-tasks" / "active").mkdir(parents=True)
    (vault / "30-areas" / "hapax" / "lanebus" / "cx-blue").mkdir(parents=True)
    return ResearchDeskConfig(
        vault_root=vault, state_root=tmp_path / "state", delivery_lane="cx-blue"
    )


@pytest.fixture
def ledger_path(tmp_path: Path) -> Path:
    return tmp_path / "ledger.jsonl"


def seed_request(config: ResearchDeskConfig, request_id: str, *, status: str = "offered") -> Path:
    path = config.requests_dir / f"{request_id}.md"
    path.write_text(
        "\n".join(
            [
                "---",
                "type: cc-task",
                f"task_id: {request_id}",
                f'title: "{request_id}"',
                "kind: research_request",
                "route_family: perplexity-desk",
                f"status: {status}",
                "priority: p1",
                'question: "Which EU implementing acts landed this quarter?"',
                "---",
                "",
                "Brief body.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


class Recorder:
    """A recording ASGI ``send``."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def __call__(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    @property
    def status(self) -> int | None:
        for message in self.messages:
            if message["type"] == "http.response.start":
                return int(message["status"])
        return None

    @property
    def headers(self) -> dict[bytes, bytes]:
        for message in self.messages:
            if message["type"] == "http.response.start":
                return {key.lower(): value for key, value in message["headers"]}
        return {}

    def json_body(self) -> Any:
        blob = b"".join(
            message.get("body", b"")
            for message in self.messages
            if message["type"] == "http.response.body"
        )
        return json.loads(blob)


async def _noop_receive() -> dict[str, Any]:
    return {"type": "http.request", "body": b"", "more_body": False}


def http_scope(path: str, headers: list[tuple[bytes, bytes]] | None = None) -> dict[str, Any]:
    return {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": headers or [],
        "client": (LOOPBACK, 51234),
    }


# --------------------------------------------------------------------------- #
# Credential handling
# --------------------------------------------------------------------------- #


def _canonical_secret_stub(home: Path, body: str) -> None:
    path = home / ".local" / "bin" / "hapax-secret"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def test_loopback_guard_refuses_a_public_bind() -> None:
    assert desk_mcp._require_loopback(LOOPBACK) == LOOPBACK
    with pytest.raises(desk_mcp.DeskStartupError) as exc:
        desk_mcp._require_loopback("0" + ".0.0.0")  # noqa: S104 — the refusal is the point
    assert "tailnet" in str(exc.value)


def test_key_load_refuses_when_hapax_secret_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _canonical_secret_stub(tmp_path, "#!/bin/sh\nexit 3\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(desk_mcp.DeskStartupError) as exc:
        desk_mcp.load_connector_key()
    assert "exited 3" in str(exc.value)


def test_key_load_refuses_a_short_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _canonical_secret_stub(tmp_path, "#!/bin/sh\necho short\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(desk_mcp.DeskStartupError) as exc:
        desk_mcp.load_connector_key()
    assert "entropy" in str(exc.value)


def test_key_load_refuses_when_hapax_secret_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/nonexistent")
    with pytest.raises(desk_mcp.DeskStartupError) as exc:
        desk_mcp.load_connector_key()
    assert "hapax-secret --where" in str(exc.value)


def test_key_load_reads_the_filestore_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _canonical_secret_stub(tmp_path, f"#!/bin/sh\nprintf '%s\\n' '{KEY}'\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert desk_mcp.load_connector_key() == KEY


def test_hapax_secret_override_is_ignored_and_cannot_bypass_filestore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Red-first pin for #4674's critical: the environment cannot choose the secret binary.

    A hostile unit environment may set HAPAX_SECRET to a one-line stub. The desk must still
    invoke the canonical `~/.local/bin/hapax-secret`; this test replaces that canonical path
    only in a temporary HOME and proves the override is ignored by making the override succeed
    while the canonical path refuses.
    """

    override = tmp_path / "override-secret"
    override.write_text(f"#!/bin/sh\nprintf '%s\\n' '{KEY}'\n", encoding="utf-8")
    override.chmod(0o755)
    canonical = tmp_path / ".local" / "bin" / "hapax-secret"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
    canonical.chmod(0o755)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HAPAX_SECRET", str(override))
    with pytest.raises(desk_mcp.DeskStartupError) as exc:
        desk_mcp.load_connector_key()
    assert "exited 7" in str(exc.value)


# --------------------------------------------------------------------------- #
# Header parsing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ([(b"authorization", b"Bearer abc123")], "abc123"),
        ([(b"Authorization", b"bearer abc123")], "abc123"),
        ([(b"x-api-key", b"abc123")], "abc123"),
        ([(b"authorization", b"Basic abc123")], ""),
        ([], ""),
    ],
)
def test_presented_key_reads_both_accepted_spellings(
    headers: list[tuple[bytes, bytes]], expected: str
) -> None:
    assert desk_mcp.presented_key(http_scope("/mcp", headers)) == expected


# --------------------------------------------------------------------------- #
# Auth edge
# --------------------------------------------------------------------------- #


class _Sentinel:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        self.calls += 1
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})


async def test_unauthenticated_call_is_refused_with_a_next_action() -> None:
    inner = _Sentinel()
    app = desk_mcp.build_app(inner, key=KEY)
    recorder = Recorder()
    await app(http_scope("/mcp"), _noop_receive, recorder)

    assert recorder.status == 401
    assert recorder.headers[b"www-authenticate"].startswith(b"Bearer")
    payload = recorder.json_body()
    assert payload["reason_code"] == "unauthorized"
    assert "Authorization: Bearer" in payload["next_action"]
    assert inner.calls == 0


async def test_wrong_key_is_refused_and_the_refusal_never_echoes_a_key() -> None:
    inner = _Sentinel()
    app = desk_mcp.build_app(inner, key=KEY)
    recorder = Recorder()
    await app(
        http_scope("/mcp", [(b"authorization", b"Bearer wrong-key")]), _noop_receive, recorder
    )

    assert recorder.status == 401
    blob = json.dumps(recorder.json_body())
    assert KEY not in blob
    assert "wrong-key" not in blob
    assert inner.calls == 0


async def test_correct_key_reaches_the_mcp_app() -> None:
    inner = _Sentinel()
    app = desk_mcp.build_app(inner, key=KEY)
    recorder = Recorder()
    await app(
        http_scope("/mcp", [(b"authorization", f"Bearer {KEY}".encode())]), _noop_receive, recorder
    )
    assert recorder.status == 204
    assert inner.calls == 1


async def test_x_api_key_spelling_also_authenticates() -> None:
    inner = _Sentinel()
    app = desk_mcp.build_app(inner, key=KEY)
    recorder = Recorder()
    await app(http_scope("/mcp", [(b"x-api-key", KEY.encode())]), _noop_receive, recorder)
    assert recorder.status == 204
    assert inner.calls == 1


async def test_health_is_reachable_without_a_key_and_leaks_nothing() -> None:
    inner = _Sentinel()
    app = desk_mcp.build_app(inner, key=KEY)
    recorder = Recorder()
    await app(http_scope(desk_mcp.HEALTH_PATH), _noop_receive, recorder)

    assert recorder.status == 200
    payload = recorder.json_body()
    assert payload == {"ok": True, "service": "hapax-research-desk"}
    assert inner.calls == 0


async def test_websocket_upgrade_is_refused_in_the_protocols_own_vocabulary() -> None:
    inner = _Sentinel()
    app = desk_mcp.build_app(inner, key=KEY)
    recorder = Recorder()
    await app({"type": "websocket", "path": "/mcp", "headers": []}, _noop_receive, recorder)
    assert recorder.messages == [{"type": "websocket.close", "code": 1008}]
    assert inner.calls == 0


async def test_lifespan_passes_through_untouched() -> None:
    seen: list[str] = []

    async def inner(scope: dict[str, Any], receive: Any, send: Any) -> None:
        seen.append(scope["type"])

    app = desk_mcp.build_app(inner, key=KEY)
    await app({"type": "lifespan"}, _noop_receive, Recorder())
    assert seen == ["lifespan"]


# --------------------------------------------------------------------------- #
# Tools + ledger
# --------------------------------------------------------------------------- #


async def _call_tool(server: Any, name: str, arguments: dict[str, Any]) -> Any:
    result = await server.call_tool(name, arguments)
    content = result[0] if isinstance(result, tuple) else result
    text = content[0].text if hasattr(content[0], "text") else content[0]["text"]
    return json.loads(text)


async def test_tools_write_one_ledger_row_per_call_and_never_the_key(
    config: ResearchDeskConfig, ledger_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_request(config, "req-ledger")
    server = desk_mcp.build_server(config, ledger_path=ledger_path)
    token = desk_mcp._CALLER_IP.set(LOOPBACK)
    try:
        listed = await _call_tool(server, "list_open_research_requests", {"limit": 5})
        fetched = await _call_tool(server, "fetch_request", {"request_id": "req-ledger"})
        delivered = await _call_tool(
            server,
            "deliver_result",
            {
                "request_id": "req-ledger",
                "markdown": "The answer.",
                "citations": ["https://example.org/a"],
                "model_notes": "sonar",
            },
        )
    finally:
        desk_mcp._CALLER_IP.reset(token)

    assert listed["count"] == 1
    assert fetched["request_id"] == "req-ledger"
    assert delivered["ok"] is True

    rows = ledger_mod.read_records(ledger_path).records
    assert [row["tool"] for row in rows] == [
        "list_open_research_requests",
        "fetch_request",
        "deliver_result",
    ]
    assert [row["outcome"] for row in rows] == ["ok", "ok", "ok"]
    assert rows[-1]["receipt_id"] == delivered["receipt_id"]
    assert all(row["caller_ip"] == LOOPBACK for row in rows)
    blob = json.dumps(rows)
    assert KEY not in blob
    assert "authorization" not in blob.lower()


async def test_a_refused_tool_call_is_still_a_ledger_row(
    config: ResearchDeskConfig, ledger_path: Path
) -> None:
    server = desk_mcp.build_server(config, ledger_path=ledger_path)
    payload = await _call_tool(server, "fetch_request", {"request_id": "../escape"})
    assert payload["ok"] is False
    assert payload["reason_code"] == "request_id_invalid"
    assert payload["next_action"]

    (row,) = ledger_mod.read_records(ledger_path).records
    assert row["outcome"] == "refused"
    assert row["reason_code"] == "request_id_invalid"


async def test_duplicate_delivery_is_ledgered_as_duplicate(
    config: ResearchDeskConfig, ledger_path: Path
) -> None:
    seed_request(config, "req-dup")
    server = desk_mcp.build_server(config, ledger_path=ledger_path)
    first = await _call_tool(server, "deliver_result", {"request_id": "req-dup", "markdown": "one"})
    second = await _call_tool(
        server, "deliver_result", {"request_id": "req-dup", "markdown": "two"}
    )

    assert second["duplicate"] is True
    assert second["receipt_id"] == first["receipt_id"]
    outcomes = [row["outcome"] for row in ledger_mod.read_records(ledger_path).records]
    assert outcomes == ["ok", "duplicate"]
    assert len(list(config.lanebus_dir.glob("*.md"))) == 1


# --------------------------------------------------------------------------- #
# Live end-to-end over real HTTP with the official MCP client
# --------------------------------------------------------------------------- #


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind((LOOPBACK, 0))
        return int(sock.getsockname()[1])


@contextlib.contextmanager
def _serving(app: Any, port: int) -> Iterator[None]:
    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(app, host=LOOPBACK, port=port, log_level="warning", lifespan="on")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if server.started:
                break
            threading.Event().wait(0.05)
        else:  # pragma: no cover - a server that never starts fails the test below
            raise RuntimeError("uvicorn did not start")
        yield
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_live_end_to_end_over_streamable_http(
    config: ResearchDeskConfig, ledger_path: Path
) -> None:
    """The gate the task row names: a real MCP client, over real HTTP, through the auth edge."""
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    seed_request(config, "req-live")
    server = desk_mcp.build_server(config, ledger_path=ledger_path)
    app = desk_mcp.build_app(server.streamable_http_app(), key=KEY)
    port = _free_port()
    url = f"http://{LOOPBACK}:{port}{desk_mcp.MCP_PATH}"

    async def drive() -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {KEY}"}
        async with httpx.AsyncClient(headers=headers, timeout=30) as http_client:
            async with streamable_http_client(url, http_client=http_client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    listed = await session.call_tool("list_open_research_requests", {"limit": 5})
                    fetched = await session.call_tool("fetch_request", {"request_id": "req-live"})
                    delivered = await session.call_tool(
                        "deliver_result",
                        {
                            "request_id": "req-live",
                            "markdown": "# Answer\n\nMeasured over HTTP.",
                            "citations": [{"url": "https://example.org/x", "title": "X"}],
                            "model_notes": "live e2e",
                        },
                    )

                    def _payload(result: Any, label: str) -> Any:
                        text = result.content[0].text
                        try:
                            return json.loads(text)
                        except json.JSONDecodeError as exc:  # pragma: no cover - diagnostic
                            raise AssertionError(
                                f"{label} did not return JSON (isError={result.isError}): {text!r}"
                            ) from exc

                    return {
                        "tools": sorted(tool.name for tool in tools.tools),
                        "listed": _payload(listed, "list_open_research_requests"),
                        "fetched": _payload(fetched, "fetch_request"),
                        "delivered": _payload(delivered, "deliver_result"),
                    }

    with _serving(app, port):
        out = asyncio.run(drive())

    assert out["tools"] == ["deliver_result", "fetch_request", "list_open_research_requests"]
    assert out["listed"]["count"] == 1
    assert out["fetched"]["question"].startswith("Which EU")
    assert out["delivered"]["ok"] is True

    drops = list(config.lanebus_dir.glob("*.md"))
    assert len(drops) == 1
    assert "Measured over HTTP." in drops[0].read_text(encoding="utf-8")

    rows = ledger_mod.read_records(ledger_path).records
    assert [row["tool"] for row in rows] == [
        "list_open_research_requests",
        "fetch_request",
        "deliver_result",
    ]
    assert all(row["caller_ip"] == LOOPBACK for row in rows)


def test_live_call_without_the_key_is_refused_at_the_edge(
    config: ResearchDeskConfig, ledger_path: Path
) -> None:
    import httpx

    server = desk_mcp.build_server(config, ledger_path=ledger_path)
    app = desk_mcp.build_app(server.streamable_http_app(), key=KEY)
    port = _free_port()

    with _serving(app, port):
        health = httpx.get(f"http://{LOOPBACK}:{port}{desk_mcp.HEALTH_PATH}", timeout=10)
        unauthenticated = httpx.post(
            f"http://{LOOPBACK}:{port}{desk_mcp.MCP_PATH}",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Accept": "application/json, text/event-stream"},
            timeout=10,
        )

    assert health.status_code == 200
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["reason_code"] == "unauthorized"
    assert ledger_mod.read_records(ledger_path).records == [], (
        "an unauthenticated call never reaches a tool"
    )


# --------------------------------------------------------------------------- #
# Host allowlist — the finding the loopback tests could not see
# --------------------------------------------------------------------------- #


def test_transport_security_keeps_rebinding_protection_on_and_names_the_public_host() -> None:
    """Measured 2026-09-16: the first live call through the tailnet host returned 421.

    FastMCP defaults DNS-rebinding protection ON with an EMPTY allowlist, so every
    ``Host`` is rejected — including the hostname we published. Every loopback test
    passed while the public endpoint was unusable. The fix is an allowlist, never a
    disable, and this pins both halves.
    """
    settings = desk_mcp.transport_security("desk.example.org", 8790)
    assert settings.enable_dns_rebinding_protection is True
    # `.count(...) == 1` rather than `in`: exact-membership is the stronger assertion,
    # and CodeQL's py/incomplete-url-substring-sanitization heuristic reads `"host" in x`
    # as a substring check on a URL even when x is a list.
    assert settings.allowed_hosts.count("desk.example.org") == 1
    assert settings.allowed_hosts.count("{LOOPBACK}:8790") == 1
    assert settings.allowed_hosts.count("*") == 0


def test_tailnet_host_defaults_to_local_mode_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HAPAX_RESEARCH_DESK_TAILNET_HOST", raising=False)
    assert desk_mcp.public_host() == desk_mcp.DEFAULT_TAILNET_HOST
    monkeypatch.setenv("HAPAX_RESEARCH_DESK_TAILNET_HOST", " desk.other.test ")
    assert desk_mcp.public_host() == "desk.other.test"


def test_forwarded_client_addresses_are_believed_only_from_loopback() -> None:
    """the tailnet binding reaches the origin over loopback and forwards the real caller.

    ``proxy_headers`` is what makes the ledger's ``caller_ip`` the actual client
    rather than a constant {LOOPBACK}; ``forwarded_allow_ips`` is what stops anything
    else from asserting an address. Widening either is a trust change, so both are
    pinned here rather than left to a library default.
    """
    kwargs = desk_mcp.uvicorn_kwargs(LOOPBACK, 8790)
    assert kwargs["proxy_headers"] is True
    assert kwargs["forwarded_allow_ips"] == LOOPBACK
    assert kwargs["host"] == LOOPBACK


def _post_with_host(port: int, host_header: str, key: str) -> Any:
    import httpx

    return httpx.post(
        f"http://{LOOPBACK}:{port}{desk_mcp.MCP_PATH}",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "1"},
            },
        },
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json, text/event-stream",
            "Host": host_header,
        },
        timeout=15,
    )


def test_the_published_host_header_is_served_and_an_unknown_one_is_not(
    config: ResearchDeskConfig, ledger_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HAPAX_RESEARCH_DESK_TAILNET_HOST", "desk.example.test")
    # Plain-JSON responses here: the Host check runs before any body is produced, and
    # reading an SSE stream with a one-shot client makes the assertion about chunked
    # teardown rather than about the allowlist.
    monkeypatch.setenv("HAPAX_RESEARCH_DESK_JSON_RESPONSE", "1")
    server = desk_mcp.build_server(config, ledger_path=ledger_path)
    app = desk_mcp.build_app(server.streamable_http_app(), key=KEY)
    port = _free_port()

    with _serving(app, port):
        published = _post_with_host(port, "desk.example.test", KEY)
        unknown = _post_with_host(port, "evil.example.test", KEY)

    assert published.status_code == 200, published.text
    assert unknown.status_code == 421, unknown.text


# --------------------------------------------------------------------------- #
# Review findings, 2026-09-16
# --------------------------------------------------------------------------- #


def test_no_environment_variable_can_substitute_for_the_filestore_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The credential has exactly one source, and it is the FileStore.

    An earlier draft accepted ``HAPAX_RESEARCH_DESK_KEY_FOR_TESTS`` ahead of the
    ``hapax-secret`` call and ahead of the length floor, so anything able to set the
    unit environment could have replaced the bearer credential of a publicly tunnelled
    server with a one-character key. It was deleted rather than guarded: naming a
    variable "for tests" is not a machine-checkable precondition, and a fallback that
    makes the process accept MORE than the primary is unsound by construction.

    This test is the pin. It sets every plausible spelling and asserts the FileStore
    value still wins.
    """
    _canonical_secret_stub(tmp_path, f"#!/bin/sh\nprintf '%s\\n' '{KEY}'\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in (
        "HAPAX_RESEARCH_DESK_KEY_FOR_TESTS",
        "HAPAX_RESEARCH_DESK_KEY",
        "RESEARCH_DESK_CONNECTOR_KEY",
    ):
        monkeypatch.setenv(name, "x")

    assert desk_mcp.load_connector_key() == KEY


def test_key_load_refuses_when_hapax_secret_hangs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _canonical_secret_stub(tmp_path, "#!/bin/sh\nsleep 30\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(desk_mcp.subprocess, "run", _raise_timeout)

    with pytest.raises(desk_mcp.DeskStartupError) as exc:
        desk_mcp.load_connector_key()
    assert "hapax-secret --where" in str(exc.value)


def _raise_timeout(*args: Any, **kwargs: Any) -> Any:
    import subprocess

    raise subprocess.TimeoutExpired(cmd="hapax-secret", timeout=15.0)


def test_the_host_allowlist_covers_the_published_name_with_and_without_a_port() -> None:
    """A client or proxy that spells the default port sends a different Host string.

    Rejecting `desk.example.org:443` would be the same 421 this server already paid
    for once, so both spellings are allowed — the hostname is the boundary, not the
    port, because nothing reaches the origin except through the loopback bind.
    """
    settings = desk_mcp.transport_security("desk.example.org", 8790)
    assert settings.allowed_hosts.count("desk.example.org") == 1
    assert settings.allowed_hosts.count("desk.example.org:443") == 1
    assert settings.allowed_hosts.count("desk.example.org:*") == 1
    assert settings.allowed_hosts.count("*") == 0
    assert settings.enable_dns_rebinding_protection is True


def test_the_allowlist_follows_a_non_default_port() -> None:
    settings = desk_mcp.transport_security("desk.example.org", 9999)
    assert settings.allowed_hosts.count("{LOOPBACK}:9999") == 1
    assert settings.allowed_hosts.count("{LOOPBACK}:8790") == 0


def test_build_server_uses_the_resolved_bind_not_the_defaults(
    config: ResearchDeskConfig, ledger_path: Path
) -> None:
    """A server whose transport settings describe a different socket than it listens
    on is the shape that produced the 421."""
    server = desk_mcp.build_server(config, ledger_path=ledger_path, host=LOOPBACK, port=9391)
    assert server.settings.port == 9391
    assert server.settings.host == LOOPBACK
    assert server.settings.transport_security is not None
    assert server.settings.transport_security.allowed_hosts.count("{LOOPBACK}:9391") == 1
