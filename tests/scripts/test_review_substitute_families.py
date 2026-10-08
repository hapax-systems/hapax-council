"""Contract, ceiling, outage-mapping and anti-inflation tests for the entitlement substitute
review seats (kimi, featherless, verboo) — review-substitute-families-kimi-featherless-verboo-20261003.

The outage tests assert the wrappers' failure signals are classified by the REAL dispatcher
classifiers (scripts/review_team.is_quota_wall / is_provider_outage / is_reviewer_route_unavailable),
so "so the latch works" is pinned against the consumer, not a mirror.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.review_team as review_team  # noqa: E402
from scripts.hapax_review_family_inflation import (  # noqa: E402
    canonical_family,
    effective_review_family,
    substitute_pin_inflates,
)
from scripts.hapax_review_http_seat import (  # noqa: E402
    http_failure,
    provider_outage,
    quota_wall,
    redact,
    refuse,
)

WRAPPERS = ("hapax-kimi-reviewer", "hapax-featherless-reviewer", "hapax-verboo-reviewer")
_FAKE_KEY = "sk-fake"  # pragma: allowlist secret  (test fixture, not a real key)


def _load(name: str):
    # The wrappers are extensionless executables; load by an explicit source loader.
    loader = importlib.machinery.SourceFileLoader(
        name.replace("-", "_"), str(REPO_ROOT / "scripts" / name)
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- anti-inflation


def test_canonical_family_maps_known_models() -> None:
    assert canonical_family("GLM-5.3") == "glm"
    assert canonical_family("deepseek-ai/DeepSeek-V4-Pro") == "deepseek"
    assert canonical_family("kimi-k3") == "kimi"
    assert canonical_family("qwen3.8-flash-next") == "qwen"
    assert canonical_family("Mistral-Medium-3.5") == "mistral"
    assert canonical_family("something-unknown-9000") is None


def test_featherless_glm_counts_as_glm_not_a_new_family() -> None:
    assert effective_review_family("featherless", "GLM-5.3") == "glm"
    assert effective_review_family("featherless", "qwen3.8-flash-next") == "local"
    assert effective_review_family("featherless", "deepseek-ai/DeepSeek-V4-Pro") == "featherless"
    assert effective_review_family("kimi", "kimi-k3") == "kimi"


def test_substitute_pin_inflates_flags_duplicates_only() -> None:
    assert substitute_pin_inflates("featherless", "GLM-5.3") == "glm"
    assert substitute_pin_inflates("featherless", "qwen-2.5") == "local"
    assert substitute_pin_inflates("featherless", "deepseek-ai/DeepSeek-V4-Pro") is None


def test_registry_substitute_pins_are_distinct() -> None:
    registry = yaml.safe_load((REPO_ROOT / "config/review-lenses/registry.yaml").read_text())
    subs = [f for f in registry["families"] if f.get("substitute") is True and "pinned_model" in f]
    assert {f["family"] for f in subs} >= {"kimi", "featherless", "verboo"}
    pinned_families = [canonical_family(f["pinned_model"]) for f in subs]
    assert None not in pinned_families
    assert len(pinned_families) == len(set(pinned_families))
    for entry in subs:
        inflated = substitute_pin_inflates(entry["family"], entry["pinned_model"])
        assert inflated is None, (
            f"{entry['family']} pin {entry['pinned_model']} inflates as {inflated}"
        )


# --------------------------------------------------------------------------- outage mapping


def test_quota_wall_classifies_as_quota(capsys) -> None:
    code = quota_wall("hapax-kimi-reviewer", 429, "rate limit reached", secret=_FAKE_KEY)
    err = capsys.readouterr().err.strip()
    assert code != 0
    assert review_team.is_quota_wall(err, process_failed=True, model_stdout="")
    # a wall is not misread as a mere route-unavailable or a clean review
    assert not review_team.is_reviewer_route_unavailable(err, process_failed=True, model_stdout="")


def test_provider_outage_classifies_as_outage(capsys) -> None:
    code = provider_outage("hapax-verboo-reviewer", 503, "temporarily overloaded", secret=_FAKE_KEY)
    err = capsys.readouterr().err.strip()
    assert code != 0
    assert review_team.is_provider_outage(err, process_failed=True, model_stdout="")


def test_http_failure_maps_each_status(capsys) -> None:
    cases = [
        (429, review_team.is_quota_wall),
        (500, review_team.is_provider_outage),
        (503, review_team.is_provider_outage),
        (401, review_team.is_reviewer_route_unavailable),
        (403, review_team.is_reviewer_route_unavailable),
    ]
    for status, classifier in cases:
        code = http_failure("hapax-featherless-reviewer", status, "detail", secret=_FAKE_KEY)
        err = capsys.readouterr().err.strip()
        assert code != 0, status
        assert classifier(err, process_failed=True, model_stdout=""), status


def test_refuse_classifies_as_route_unavailable(capsys) -> None:
    refuse("hapax-kimi-reviewer", "no key")
    err = capsys.readouterr().err.strip()
    assert review_team.is_reviewer_route_unavailable(err, process_failed=True, model_stdout="")


def test_a_wall_on_stdout_never_classifies(capsys) -> None:
    # the anti-forge anchor: a wall-looking literal with review output present is NOT a wall.
    quota_wall("hapax-kimi-reviewer", 429, "rate limit reached", secret=_FAKE_KEY)
    err = capsys.readouterr().err.strip()
    assert not review_team.is_quota_wall(err, process_failed=True, model_stdout="a review verdict")


def test_redact_removes_the_key() -> None:
    assert _FAKE_KEY not in redact(f"boom {_FAKE_KEY} trailing", _FAKE_KEY)


# --------------------------------------------------------------------------- kimi guard / parse


def test_kimi_rejects_non_coding_base() -> None:
    kimi = _load("hapax-kimi-reviewer")
    assert kimi.valid_coding_base("https://api.kimi.com/coding")
    assert kimi.valid_coding_base("https://api.kimi.com/coding/")
    assert not kimi.valid_coding_base("https://api.moonshot.ai/anthropic")  # booster/PAYG wallet
    assert not kimi.valid_coding_base("http://api.kimi.com/coding")  # not https
    assert not kimi.valid_coding_base("https://api.kimi.com/v1")  # not the coding plan
    assert not kimi.valid_coding_base("https://api.kimi.com/coding?x=1")  # query smuggling


def test_kimi_anthropic_request_and_extract() -> None:
    kimi = _load("hapax-kimi-reviewer")
    body = kimi.request_body("please review", "kimi-k3")
    assert body["model"] == "kimi-k3"
    assert body["system"] and "blind reviewer" in body["system"].lower()
    assert body["messages"][-1]["role"] == "user"
    assert kimi.extract_text({"content": [{"type": "text", "text": "ok"}]}) == "ok"
    assert kimi.extract_text({"content": []}) is None


# --------------------------------------------------------------------------- wrapper contract


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):  # silence
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length", 0))
        self.rfile.read(length)
        mode = self.server.mode  # type: ignore[attr-defined]
        if mode == "429":
            body = json.dumps({"error": {"message": "rate limit reached"}}).encode()
            self.send_response(429)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            return
        if mode == "500":
            self.send_response(503)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"temporarily overloaded"}')
            return
        if mode == "sse_ok":
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.end_headers()
            for piece in ("```yaml\n", "verdict: accept\n", "```"):
                chunk = {"model": "verboo-coder", "choices": [{"delta": {"content": piece}}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n')
            self.wfile.write(b"data: [DONE]\n\n")
            return
        if mode == "sse_truncate":
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.end_headers()
            chunk = {
                "model": "verboo-coder",
                "choices": [{"delta": {"content": "partial"}, "finish_reason": "length"}],
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            return
        # openai non-stream
        finish = "length" if mode == "truncate" else "stop"
        payload = {
            "model": "deepseek-ai/DeepSeek-V4-Pro",
            "choices": [
                {"message": {"content": "```yaml\nverdict: accept\n```"}, "finish_reason": finish}
            ],
        }
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def mock_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    server.mode = "ok"  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def _run(name: str, prompt: str, extra_env: dict[str, str]) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("HAPAX_")}
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / name)],
        input=prompt,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
    )


def _base(server) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}"


@pytest.mark.parametrize("name", WRAPPERS)
def test_empty_prompt_refuses(name: str) -> None:
    result = _run(name, "   ", {})
    assert result.returncode != 0
    assert "UNSUPPORTED_CLIENT" in result.stderr


@pytest.mark.parametrize("name", WRAPPERS)
def test_over_ceiling_refuses(name: str) -> None:
    # no network: the ceiling check precedes the key read and the HTTP call.
    result = _run(name, "x" * 200_001, {})
    assert result.returncode != 0
    assert "UNSUPPORTED_CLIENT" in result.stderr
    assert "exceeds" in result.stderr


def test_kimi_non_coding_base_refuses_before_any_call() -> None:
    result = _run(
        "hapax-kimi-reviewer",
        "review this",
        {"HAPAX_KIMI_REVIEW_BASE_URL": "https://api.moonshot.ai/anthropic"},
    )
    assert result.returncode != 0
    assert "booster" in result.stderr.lower() or "UNSUPPORTED_CLIENT" in result.stderr


def test_featherless_success(mock_server) -> None:
    mock_server.mode = "ok"
    result = _run(
        "hapax-featherless-reviewer",
        "review this",
        {
            "HAPAX_FEATHERLESS_REVIEW_BASE_URL": _base(mock_server),
            "HAPAX_FEATHERLESS_REVIEW_API_KEY": _FAKE_KEY,
        },
    )
    assert result.returncode == 0, result.stderr
    assert "verdict: accept" in result.stdout
    assert "served_model=deepseek-ai/DeepSeek-V4-Pro" in result.stderr


@pytest.mark.parametrize(
    ("mode", "classifier"),
    [("429", "is_quota_wall"), ("500", "is_provider_outage")],
)
def test_featherless_http_errors_latch(mock_server, mode: str, classifier: str) -> None:
    mock_server.mode = mode
    result = _run(
        "hapax-featherless-reviewer",
        "review this",
        {
            "HAPAX_FEATHERLESS_REVIEW_BASE_URL": _base(mock_server),
            "HAPAX_FEATHERLESS_REVIEW_API_KEY": _FAKE_KEY,
        },
    )
    assert result.returncode != 0
    assert result.stdout.strip() == ""  # anti-forge: no review content on an outage
    check = getattr(review_team, classifier)
    assert check(result.stderr.strip(), process_failed=True, model_stdout="")


def test_featherless_truncation_refuses(mock_server) -> None:
    mock_server.mode = "truncate"
    result = _run(
        "hapax-featherless-reviewer",
        "review this",
        {
            "HAPAX_FEATHERLESS_REVIEW_BASE_URL": _base(mock_server),
            "HAPAX_FEATHERLESS_REVIEW_API_KEY": _FAKE_KEY,
        },
    )
    assert result.returncode != 0
    assert "truncated" in result.stderr


def test_featherless_missing_key_refuses(mock_server) -> None:
    mock_server.mode = "ok"
    result = _run(
        "hapax-featherless-reviewer",
        "review this",
        {"HAPAX_FEATHERLESS_REVIEW_BASE_URL": _base(mock_server), "HOME": "/nonexistent-home-xyz"},
    )
    assert result.returncode != 0
    assert "UNSUPPORTED_CLIENT" in result.stderr


def test_verboo_streamed_success(mock_server) -> None:
    mock_server.mode = "sse_ok"
    result = _run(
        "hapax-verboo-reviewer",
        "review this",
        {
            "HAPAX_VERBOO_REVIEW_BASE_URL": _base(mock_server),
            "HAPAX_VERBOO_REVIEW_API_KEY": _FAKE_KEY,
        },
    )
    assert result.returncode == 0, result.stderr
    assert "verdict: accept" in result.stdout
    assert "served_model=verboo-coder" in result.stderr


def test_verboo_stream_truncation_refuses(mock_server) -> None:
    mock_server.mode = "sse_truncate"
    result = _run(
        "hapax-verboo-reviewer",
        "review this",
        {
            "HAPAX_VERBOO_REVIEW_BASE_URL": _base(mock_server),
            "HAPAX_VERBOO_REVIEW_API_KEY": _FAKE_KEY,
        },
    )
    assert result.returncode != 0
    assert "truncated" in result.stderr


def test_kimi_preserves_the_entire_system_preamble(monkeypatch) -> None:
    kimi = _load("hapax-kimi-reviewer")
    preamble = "You are a blind reviewer.\n\nTools are off.\n\nReturn the bare fence."
    monkeypatch.setattr(kimi, "SEAT_PREAMBLE", preamble, raising=False)
    body = kimi.request_body("  packet\n\nlast paragraph\n", "kimi-for-coding")
    assert body["system"] == preamble
    assert body["messages"] == [{"role": "user", "content": "  packet\n\nlast paragraph\n"}]


@pytest.mark.parametrize("name", WRAPPERS)
def test_unmeasured_ceiling_is_not_described_as_measured(name) -> None:
    result = _run(name, "x" * 200_001, {})
    assert result.returncode != 0
    assert "measured" not in result.stderr


@pytest.mark.parametrize("model", [None, "verboo-coder", "unknown-gpt-proxy", "glm-kimi-mix"])
def test_unknown_or_ambiguous_identity_never_adds_a_family(model) -> None:
    assert effective_review_family("verboo", model) is None


def test_inter_substitute_duplicate_pin_collapses() -> None:
    assert substitute_pin_inflates("verboo", "deepseek-ai/DeepSeek-V4-Pro") == "featherless"
    assert substitute_pin_inflates("featherless", "kimi-k3") == "kimi"
    assert substitute_pin_inflates("kimi", "minimax-m3") == "verboo"


class _WireHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):  # noqa: N802
        self.server.requests.append(
            (self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        )
        self.send_response(self.server.status)
        self.end_headers()
        self.wfile.write(self.server.body)


@pytest.fixture
def wire_server():
    server = HTTPServer(("127.0.0.1", 0), _WireHandler)
    server.requests = []
    server.status = 200
    server.body = b""
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


_WIRE_REPLY = "```yaml\nverdict: accept\nfindings: []\nchecklist: {}\n```"
_WIRE_MODELS = {
    "kimi": "kimi-for-coding",
    "featherless": "deepseek-ai/DeepSeek-V4-Pro",
    "verboo": "minimax-m3",
}
# Intercept transport only in the child test process. Kimi's production URL guard stays on;
# no test-only localhost bypass or production credential resolver is added to the wrapper.
_WIRE_CHILD = """
import runpy, sys, urllib.request
original = urllib.request.urlopen
def local_only(request, **kwargs):
    expected = sys.argv[3]
    assert request.full_url == expected, request.full_url
    local = urllib.request.Request(sys.argv[2], data=request.data,
                                   headers=dict(request.header_items()), method=request.method)
    return original(local, **kwargs)
urllib.request.urlopen = local_only
runpy.run_path(sys.argv[1], run_name="__main__")
"""


def _wire_run(server, family, *, prompt="packet", model=None):
    module = _load(f"hapax-{family}-reviewer")
    endpoint = module.DEFAULT_BASE_URL + (
        "/v1/messages" if family == "kimi" else "/chat/completions"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("HAPAX_")}
    env[f"HAPAX_{family.upper()}_REVIEW_API_KEY"] = _FAKE_KEY
    if model:
        env[f"HAPAX_{family.upper()}_REVIEW_MODEL"] = model
    return subprocess.run(
        [
            sys.executable,
            "-c",
            _WIRE_CHILD,
            str(REPO_ROOT / "scripts" / f"hapax-{family}-reviewer"),
            _base(server),
            endpoint,
        ],
        input=prompt,
        text=True,
        capture_output=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=10,
    )


def _wire_body(family, mode="ok", *, model=None):
    model = model or _WIRE_MODELS[family]
    if mode == "bad_json":
        return b"data: {broken\n\n" if family == "verboo" else b"{broken"
    if mode == "bad_shape":
        return b"data: []\n\n" if family == "verboo" else b"[]"
    finish = {"ok": "stop", "partial": "error", "missing_finish": None}.get(mode, "stop")
    content = 42 if mode == "bad_content" else _WIRE_REPLY
    if family == "kimi":
        return json.dumps(
            {
                "model": model,
                "stop_reason": "end_turn" if finish == "stop" else finish,
                "content": [{"type": "text", "text": content}],
            }
        ).encode()
    if family == "featherless":
        return json.dumps(
            {
                "model": model,
                "choices": [{"message": {"content": content}, "finish_reason": finish}],
            }
        ).encode()
    chunk = {"model": model, "choices": [{"delta": {"content": content}, "finish_reason": finish}]}
    data = f"data: {json.dumps(chunk)}\n\n".encode()
    if mode == "drift":
        data += b'data: {"model":"glm-5.3","choices":[]}\n\n'
    if mode == "late_error":
        data += b'data: {"error":{"message":"failed"}}\n\n'
    if mode != "eof":
        data += b"data: [DONE]\n\n"
    return data


@pytest.mark.parametrize("family", _WIRE_MODELS)
def test_wrapper_process_success_keeps_prompt_and_observed_model(wire_server, family):
    from shared.review_seat_wrapper import SEAT_PREAMBLE

    wire_server.body = _wire_body(family)
    result = _wire_run(wire_server, family, prompt="  packet\n\nend\n", model="requested-alias")
    assert result.returncode == 0, result.stderr
    assert result.stdout == _WIRE_REPLY
    assert f"served_model={_WIRE_MODELS[family]}" in result.stderr
    assert "pinned_model=requested-alias" in result.stderr
    assert len(wire_server.requests) == 1
    body = wire_server.requests[0][1]
    assert "tools" not in body and "response_format" not in body
    if family == "kimi":
        assert body["system"] == SEAT_PREAMBLE
    else:
        assert body["messages"][0]["content"] == SEAT_PREAMBLE
        assert body["stream"] is (family == "verboo")
    assert body["messages"][-1]["content"] == "  packet\n\nend\n"


@pytest.mark.parametrize("family", _WIRE_MODELS)
@pytest.mark.parametrize("status,classifier", [(429, "is_quota_wall"), (503, "is_provider_outage")])
def test_wrapper_process_outage_latches_once(wire_server, family, status, classifier):
    wire_server.status = status
    wire_server.body = json.dumps({"error": _FAKE_KEY}).encode()
    result = _wire_run(wire_server, family)
    assert result.returncode != 0 and result.stdout == ""
    assert _FAKE_KEY not in result.stderr
    check = getattr(review_team, classifier)
    assert check(result.stderr, process_failed=True, model_stdout=result.stdout)
    assert not check(result.stderr, process_failed=True, model_stdout="forged review")
    assert len(wire_server.requests) == 1


@pytest.mark.parametrize("family", _WIRE_MODELS)
@pytest.mark.parametrize(
    "mode", ["bad_json", "bad_shape", "bad_content", "partial", "missing_finish"]
)
def test_wrapper_process_invalid_payload_is_never_a_review(wire_server, family, mode):
    wire_server.body = _wire_body(family, mode)
    result = _wire_run(wire_server, family)
    assert result.returncode != 0 and result.stdout == ""
    assert "Traceback" not in result.stderr
    assert "unreachable" not in result.stderr
    assert review_team.is_reviewer_route_unavailable(
        result.stderr, process_failed=True, model_stdout=""
    )
    assert len(wire_server.requests) == 1


@pytest.mark.parametrize("mode", ["eof", "drift", "late_error"])
def test_verboo_incomplete_or_inconsistent_stream_refuses(wire_server, mode):
    wire_server.body = _wire_body("verboo", mode)
    result = _wire_run(wire_server, "verboo")
    assert result.returncode != 0 and result.stdout == ""
    assert "UNSUPPORTED_CLIENT" in result.stderr


@pytest.mark.parametrize("family", _WIRE_MODELS)
def test_wrapper_ceiling_refuses_before_transport(wire_server, family):
    wire_server.body = _wire_body(family)
    module = _load(f"hapax-{family}-reviewer")
    result = _wire_run(wire_server, family, prompt="é" * (module.MAX_PROMPT_BYTES // 2))
    assert result.returncode != 0 and result.stdout == ""
    assert "ceiling" in result.stderr
    assert wire_server.requests == []


@pytest.mark.parametrize("family", _WIRE_MODELS)
def test_ceiling_counts_whitespace_that_is_sent_to_provider(wire_server, family):
    wire_server.body = _wire_body(family)
    result = _wire_run(wire_server, family, prompt="packet" + " " * 200_001)
    assert result.returncode != 0 and result.stdout == ""
    assert "ceiling" in result.stderr
    assert wire_server.requests == []


@pytest.mark.parametrize(
    "family,status,detail",
    [
        ("kimi", 403, "You have reached your weekly (7-day) usage limit"),
        ("featherless", 402, "Prepaid balance exhausted"),
        ("verboo", 403, "Invalid API key"),
    ],
)
def test_subscription_wall_is_distinct_from_auth_failure(wire_server, family, status, detail):
    wire_server.status = status
    wire_server.body = json.dumps({"error": {"message": detail}}).encode()
    result = _wire_run(wire_server, family)
    assert result.returncode != 0 and result.stdout == ""
    classifier = (
        review_team.is_reviewer_route_unavailable
        if family == "verboo"
        else review_team.is_quota_wall
    )
    assert classifier(result.stderr, process_failed=True, model_stdout="")
