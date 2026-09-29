"""Offline effects at the real Arm A entrypoint; no provider or secret access."""

import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/hapax-glmcp-arm-a"
SUFFIXES = ("request.json", "response.json", "error.json", "meta.json")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_driver():
    loader = importlib.machinery.SourceFileLoader("arm_a_under_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


def reply(**changes):
    data = {
        "id": "offline-response-1",
        "model": "glm-5.3",
        "choices": [{"finish_reason": "stop", "message": {"content": "data only\n"}}],
        "usage": {"prompt_tokens": 31, "completion_tokens": 7},
    }
    data.update(changes)
    return json.dumps(data).encode()


@pytest.fixture
def rig(tmp_path, monkeypatch, request):
    driver = load_driver()
    agents = (ROOT / "config/agent-instructions/AGENTS.md").read_bytes()
    installed = tmp_path / "AGENTS.md"
    installed.write_bytes(agents)
    rows = []
    originals = []
    for index in range(1, 13):
        system = agents.decode() + f"\nHistorical system {index}\n"
        user = f"Historical user {index}: π\n\n"
        prompt = tmp_path / f"input-{index}.json"
        prompt.write_text(json.dumps({"system": system, "user": user}))
        combined = (system + "\n\n" + user).encode()
        rows.append(
            {
                "case": f"c{index:02d}_fixture",
                "source": str(prompt),
                "system_sha256": digest(system.encode()),
                "user_sha256": digest(user.encode()),
                "combined_sha256": digest(combined),
                "combined_bytes": len(combined),
            }
        )
        originals.append((system, user))
    manifest = tmp_path / "inputs.manifest.json"
    manifest.write_text(json.dumps(rows))
    # Synthetic CI exercises downstream contracts with an explicit test-only pin.
    # Substitution and custody tests retain the unmodified production identity.
    if getattr(request, "param", True):
        monkeypatch.setattr(driver, "APPROVED_INPUTS_SHA256", digest(manifest.read_bytes()))
    output = tmp_path / "evidence"
    args = [
        "--execute",
        "--inputs",
        str(manifest),
        "--inputs-sha256",
        digest(manifest.read_bytes()),
        "--agents",
        str(installed),
        "--agents-sha256",
        digest(agents),
        "--output",
        str(output),
    ]

    def fake_secret(entry):
        assert entry == "glmcp/api-key"
        return "offline-credential"

    monkeypatch.setattr(driver.transport, "read_secret", fake_secret)
    calls = []
    responses = [reply()]

    class Opener:
        def open(self, request, *, timeout):
            calls.append(request)
            result = responses[min(len(calls) - 1, len(responses) - 1)]
            if isinstance(result, Exception):
                raise result
            return io.BytesIO(result)

    def build_opener(*handlers):
        assert handlers == (driver.transport.NoRedirectHTTPHandler,)
        return Opener()

    monkeypatch.setattr(driver.transport.urllib.request, "build_opener", build_opener)
    return driver, args, output, calls, responses, originals


def run_observed(rig):
    driver, args, output, *_ = rig
    allowed = {output / "manifest.json"} | {
        output / f"{i:02d}.{suffix}" for i in range(1, 13) for suffix in SUFFIXES
    }
    effects = []
    active = [True]

    def audit(event, values):
        if not active[0]:
            return
        forbidden = event.startswith(("subprocess.", "socket.", "os.exec", "os.spawn"))
        forbidden |= event in {"os.system", "os.remove", "os.rename", "os.link", "os.symlink"}
        if event == "os.mkdir":
            forbidden |= Path(values[0]) != output
        if event == "open" and not isinstance(values[0], int):
            path, mode, flags = values
            writing = flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
            # dir_fd writes are relative to the freshly opened evidence directory.
            target = Path(path) if Path(path).is_absolute() else output / path
            forbidden |= bool(writing and target not in allowed)
        if forbidden:
            effects.append(event)
            raise OSError("offline effect observer refused undeclared effect")

    sys.addaudithook(audit)
    try:
        result = driver.main(args)
    finally:
        active[0] = False
    assert effects == [], effects
    assert set(output.iterdir()) == allowed
    return result


def test_unsafe_response_at_real_entrypoint_is_inert_and_stops(rig):
    _, _, output, calls, responses, _ = rig
    responses[0] = reply(
        choices=[
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": [
                        {"type": "text", "text": "$(touch escaped); `curl https://invalid.test`"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "https://invalid.test/redirect"},
                        },
                    ],
                    "tool_calls": [
                        {
                            "function": {
                                "name": "Agent",
                                "arguments": json.dumps(
                                    {
                                        "delegate": {"tool": "shell", "command": "touch escaped"},
                                        "filename": "../../escaped",
                                        "callback": "https://invalid.test/callback",
                                    }
                                ),
                            }
                        }
                    ],
                },
            }
        ]
    )
    assert run_observed(rig) == 2
    assert len(calls) == 1
    assert (output / "01.response.json").read_bytes() == responses[0]
    assert json.loads((output / "01.meta.json").read_bytes())["status"] == "held"
    assert (output / "02.request.json").read_bytes() == b""


def test_final_wire_exact_inputs_single_agents_identity_and_fixed_paths(rig, monkeypatch):
    driver, _, output, calls, responses, originals = rig
    for name in ("MODEL", "BASE_URL", "PAYG_FALLBACK", "SECRET_ENTRY", "THINKING"):
        monkeypatch.setenv("HAPAX_GLMCP_REVIEW_" + name, "poisoned")
    responses[0] = reply(
        choices=[
            {
                "finish_reason": "stop",
                "message": {
                    "content": "$(touch escaped); `curl https://invalid.test`; ../../escaped\n"
                    '{"tool_calls":[{"function":{"name":"Agent"}}]}',
                },
            }
        ]
    )
    assert run_observed(rig) == 0
    assert len(calls) == 12
    agents = (ROOT / "config/agent-instructions/AGENTS.md").read_text()
    for index, (request, (system, user)) in enumerate(zip(calls, originals, strict=True), 1):
        wire = (output / f"{index:02d}.request.json").read_bytes()
        assert wire == request.data
        assert request.full_url == "https://api.z.ai/api/coding/paas/v4/chat/completions"
        assert request.get_method() == "POST"
        assert request.get_header("Authorization") == "Bearer offline-credential"
        assert json.loads(wire) == {
            "model": "glm-5.3",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "thinking": {"type": "enabled"},
            "reasoning_effort": "max",
            "max_tokens": 32768,
        }
        assert system.count(agents) == 1
        meta = json.loads((output / f"{index:02d}.meta.json").read_bytes())
        assert meta["response"]["model"] == "glm-5.3"
        assert meta["response"]["id"] == "offline-response-1"
        assert meta["response"]["finish_reason"] == "stop"
        assert meta["response"]["usage"] == {"prompt_tokens": 31, "completion_tokens": 7}
        assert meta["agents_sha256"] == digest(agents.encode())
        assert meta["request_sha256"] == digest(wire)
        assert meta["response_sha256"] == digest(responses[0])
        assert meta["status"] == "recorded"
        assert meta["duration_seconds"] >= 0
    manifest = json.loads((output / "manifest.json").read_bytes())
    assert manifest["native_instruction_loading"] is False
    assert manifest["secret_binding"] == "filestore:glmcp/api-key"  # pragma: allowlist secret
    assert set(manifest["files"]) == {p.name for p in output.iterdir()} - {"manifest.json"}
    assert all("offline-credential" not in p.read_text() for p in output.iterdir())
    assert driver.transport.DEFAULT_MODEL == "glm-5.2"  # unused reviewer default


@pytest.mark.parametrize(
    "response",
    [
        reply(model=None),
        reply(model="glm-5.2"),
        reply(model=" glm-5.3 "),
        reply(id=None),
        reply(id=""),
        b"not json",
        b"[]",
        reply(choices=[]),
        reply(choices=[None]),
        reply(choices=[{"finish_reason": "length", "message": {"content": "truncated"}}]),
        reply(choices=[{"finish_reason": "stop", "message": {"content": [], "tool_calls": []}}]),
        reply(
            choices=[
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": "mixed",
                        "tool_calls": [{"function": {"name": "Write"}}],
                    },
                }
            ]
        ),
        reply(
            choices=[
                {
                    "finish_reason": "stop",
                    "message": {"content": "legacy", "function_call": {"name": "shell"}},
                }
            ]
        ),
        reply(choices=[{"finish_reason": "stop", "message": {"content": ""}}]),
        TimeoutError("offline-credential"),
        urllib.error.URLError("offline-credential"),
    ],
)
def test_refusals_stop_future_cases_and_preserve(rig, response, capsys):
    _, _, output, calls, responses, _ = rig
    responses[0] = response
    assert run_observed(rig) == 2
    assert len(calls) == 1
    if isinstance(response, bytes):
        assert (output / "01.response.json").read_bytes() == response
    assert json.loads((output / "01.meta.json").read_bytes())["status"] == "held"
    assert (output / "02.request.json").read_bytes() == b""
    assert all("offline-credential" not in p.read_text() for p in output.iterdir())
    diagnostic = capsys.readouterr().err
    assert "Arm A case 01 held:" in diagnostic
    assert "offline-credential" not in diagnostic


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308, 401, 429, 500])
def test_http_refusal_never_retries_redirects_or_uses_payg(rig, status):
    _, _, output, calls, responses, _ = rig
    responses[0] = urllib.error.HTTPError(
        "https://api.z.ai/api/coding/paas/v4/chat/completions",
        status,
        "offline-credential",
        {"Location": "https://invalid.test/steal"},
        io.BytesIO(b'{"error":{"code":"1308"}}'),
    )
    assert run_observed(rig) == 2
    assert len(calls) == 1
    assert json.loads((output / "01.meta.json").read_bytes())["http_status"] == status
    assert (output / "01.response.json").read_bytes() == b'{"error":{"code":"1308"}}'


def test_redacts_credential_echo_without_continuing(rig):
    _, _, output, calls, responses, _ = rig
    responses[0] = reply(id="offline-credential")
    assert run_observed(rig) == 2
    assert len(calls) == 1
    assert b"<credential-redacted>" in (output / "01.response.json").read_bytes()
    assert all("offline-credential" not in p.read_text() for p in output.iterdir())


@pytest.mark.parametrize("rig", [False], indirect=True)
def test_substituted_manifest_with_matching_caller_hash_is_refused(rig, monkeypatch):
    driver, _, output, calls, *_ = rig
    secrets = []
    monkeypatch.setattr(
        driver.transport, "read_secret", lambda entry: secrets.append(entry) or "offline-credential"
    )
    # All twelve synthetic cases and the caller's hash agree. Production must
    # still refuse this replacement before credential lookup or transport.
    assert run_observed(rig) == 2
    assert calls == secrets == []
    assert json.loads((output / "01.meta.json").read_bytes()) == {
        "status": "held",
        "request_issued": False,
    }
    assert (output / "01.request.json").read_bytes() == b""


@pytest.mark.parametrize("target", ["manifest", "case"])
def test_invalid_input_json_is_recorded_hold(rig, monkeypatch, target):
    driver, args, output, calls, *_ = rig
    manifest = Path(args[args.index("--inputs") + 1])
    path = (
        manifest if target == "manifest" else Path(json.loads(manifest.read_bytes())[0]["source"])
    )
    path.write_bytes(b"not json")
    if target == "manifest":
        args[args.index("--inputs-sha256") + 1] = digest(manifest.read_bytes())
        monkeypatch.setattr(driver, "APPROVED_INPUTS_SHA256", digest(manifest.read_bytes()))
    secrets = []
    monkeypatch.setattr(driver.transport, "read_secret", lambda entry: secrets.append(entry))
    assert run_observed(rig) == 2
    assert calls == secrets == []
    assert json.loads((output / "01.error.json").read_bytes())["kind"] == "JSONDecodeError"
    assert json.loads((output / "01.meta.json").read_bytes())["request_issued"] is False


@pytest.mark.parametrize("kind", ["manifest", "system", "user", "combined", "agents", "duplicate"])
def test_preflight_mismatch_stops_before_secret_and_transport(rig, kind, monkeypatch):
    driver, args, _, calls, _, _ = rig
    manifest = Path(args[args.index("--inputs") + 1])
    rows = json.loads(manifest.read_bytes())
    if kind == "manifest":
        manifest.write_bytes(manifest.read_bytes() + b" ")
    elif kind == "agents":
        Path(args[args.index("--agents") + 1]).write_bytes(b"stale instructions")
    else:
        prompt = Path(rows[0]["source"])
        data = json.loads(prompt.read_bytes())
        if kind in {"system", "user"}:
            data[kind] = data[kind].rstrip()
        elif kind == "combined":
            rows[0]["combined_bytes"] -= 1
        elif kind == "duplicate":
            data["user"] += data["system"]
            rows[0]["user_sha256"] = digest(data["user"].encode())
            combined = (data["system"] + "\n\n" + data["user"]).encode()
            rows[0]["combined_bytes"] = len(combined)
            rows[0]["combined_sha256"] = digest(combined)
        prompt.write_text(json.dumps(data))
        manifest.write_text(json.dumps(rows))
        args[args.index("--inputs-sha256") + 1] = digest(manifest.read_bytes())
        monkeypatch.setattr(driver, "APPROVED_INPUTS_SHA256", digest(manifest.read_bytes()))
    secrets = []
    monkeypatch.setattr(driver.transport, "read_secret", lambda entry: secrets.append(entry))
    assert run_observed(rig) == 2
    assert calls == secrets == []


def test_truncation_at_final_serializer_is_captured_and_stops(rig, monkeypatch):
    driver, _, output, calls, _, _ = rig
    original = driver.encode

    def truncate(value):
        if isinstance(value, dict) and "messages" in value:
            return original(value)[:-9]
        return original(value)

    monkeypatch.setattr(driver, "encode", truncate)
    assert run_observed(rig) == 2
    assert calls == []
    with pytest.raises(json.JSONDecodeError):
        json.loads((output / "01.request.json").read_bytes())


def test_spent_attempt_and_symlink_are_preserved(rig):
    driver, args, output, calls, *_ = rig
    assert run_observed(rig) == 0
    before = {
        p.name: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in output.iterdir()
    }
    assert driver.main(args) == 2
    alias = output.parent / "alias"
    alias.symlink_to(output, target_is_directory=True)
    args[-1] = str(alias)
    assert driver.main(args) == 2
    assert len(calls) == 12
    assert before == {
        p.name: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in output.iterdir()
    }


def test_real_redirect_handler_stops_at_first_response(rig, monkeypatch):
    import email.message
    import urllib.request
    import urllib.response

    driver, _, output, calls, *_ = rig
    # Restore the real opener factory replaced by rig; only HTTPS I/O is fake.
    real_factory = _REAL_BUILD_OPENER

    class LocalHTTPS(urllib.request.HTTPSHandler):
        def https_open(self, request):
            calls.append(request)
            headers = email.message.Message()
            headers["Location"] = "https://invalid.test/steal"
            response = urllib.response.addinfourl(
                io.BytesIO(b"redirect body"), headers, request.full_url, 302
            )
            response.msg = "Found"
            return response

    monkeypatch.setattr(
        driver.transport.urllib.request,
        "build_opener",
        lambda *handlers: real_factory(*handlers, LocalHTTPS()),
    )
    monkeypatch.setattr(driver.transport.urllib.request, "_opener", None)
    assert run_observed(rig) == 2
    assert len(calls) == 1
    assert (output / "01.response.json").read_bytes() == b"redirect body"


_REAL_BUILD_OPENER = __import__("urllib.request", fromlist=["build_opener"]).build_opener


@pytest.mark.contract
@pytest.mark.parametrize("rig", [False], indirect=True)
def test_original_twelve_inputs_at_transport(rig, monkeypatch):
    _, args, _, _, _, originals = rig
    binding = os.environ.get("HAPAX_ARM_A_ORIGINAL_INPUTS")
    assert binding, (
        "Custody gate requires HAPAX_ARM_A_ORIGINAL_INPUTS; synthetic CI is insufficient"
    )
    path = Path(binding)
    args[args.index("--inputs") + 1] = str(path)
    args[args.index("--inputs-sha256") + 1] = digest(path.read_bytes())
    originals[:] = [
        (p["system"], p["user"])
        for row in json.loads(path.read_bytes())
        for p in [json.loads(Path(row["source"]).read_bytes())]
    ]
    test_final_wire_exact_inputs_single_agents_identity_and_fixed_paths(rig, monkeypatch)
