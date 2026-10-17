"""Local TLS fixtures only: DNS and the numeric connection are intercepted together."""

import hashlib
import importlib.machinery
import importlib.util
import ipaddress
import json
import socket
import ssl
import threading
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from shared.dispatcher_policy import build_route_authority_receipt, write_route_authority_receipt
from shared.platform_capability_receipts import PlatformCapabilityReceipt

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/hapax-primary-source-fetch"
PUBLIC_IP = "93.184.216.34"  # pragma: allowlist secret
NONPUBLIC_IPS = [
    "fec0::1",
    "feff::1",
    "::ffff:10.0.0.1",
    "::ffff:127.0.0.1",
    "2002:a00:1::",
    "2002:7f00:1::",
    "64:ff9b::a00:1",
    "2001:0:808:808:0:ffff:f5ff:fffe",
    "2001:0:a00:1:0:ffff:f6f6:f6f6",
]


@pytest.fixture
def rig(tmp_path, monkeypatch):
    assert SCRIPT.is_file(), "the enforcing fetch path is absent"
    loader = importlib.machinery.SourceFileLoader("primary_source_fetch", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    now = datetime.now(UTC)
    env = SimpleNamespace(
        module=module,
        now=now,
        requests=[],
        connections=[],
        dns={},
        responses={},
        after_request=lambda: None,
        root=tmp_path,
        sequence=0,
        production_gate=module.require_first_exposure,
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "local fetch fixture")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("arxiv.org"), x509.DNSName("github.com")]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            env.requests.append((self.path, dict(self.headers)))
            status, headers, body = env.responses.get(self.path, (200, {}, b"source"))
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            if "Content-Length" not in headers and "Transfer-Encoding" not in headers:
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            env.after_request()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(cert_path, key_path)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    real_connect, real_resolve = socket.create_connection, socket.getaddrinfo

    def resolve(host, port, *args, **kwargs):
        if host == "127.0.0.1":
            return real_resolve(host, port, *args, **kwargs)
        assert host in {"arxiv.org", "github.com", "deepmind.google"}, "unexpected DNS request"
        return [
            (
                socket.AF_INET6 if ":" in ip else socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                (ip, port),
            )
            for ip in env.dns.get(host, [PUBLIC_IP])
        ]

    def connect(address, *args, **kwargs):
        env.connections.append(address)
        assert address == (PUBLIC_IP, 443), "unsafe or unpinned connection attempted"
        return real_connect(server.server_address, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(socket, "create_connection", connect)
    context = ssl.create_default_context(cafile=str(cert_path))
    monkeypatch.setattr(module.ssl, "create_default_context", lambda: context)
    monkeypatch.setattr(module, "require_first_exposure", lambda: None)
    monkeypatch.setattr(module, "now_utc", lambda: env.now)
    env.registry = tmp_path / "registry.json"
    env.registry.write_bytes((ROOT / "config/platform-capability-registry.json").read_bytes())
    monkeypatch.setattr(module, "PLATFORM_CAPABILITY_REGISTRY", env.registry)
    env.ledger = tmp_path / "quota.json"
    ledger = json.loads((ROOT / "config/quota-spend-ledger-fixtures.json").read_text())
    ledger["quota_snapshots"] = [
        {
            "snapshot_id": "quota-fetch-fixture",
            "captured_at": now.isoformat(),
            "fresh_until": (now + timedelta(minutes=5)).isoformat(),
            "route_id": "codex.headless.full",
            "provider": "openai-codex-subscription",
            "capacity_pool": "subscription_quota",
            "subscription_quota_state": "fresh",
            "evidence_refs": ["fixture:local-fetch-quota"],
            "operator_visible_reason": "local fixture",
        }
    ]
    env.ledger.write_text(json.dumps(ledger))
    monkeypatch.setenv("HAPAX_QUOTA_SPEND_LEDGER_LIVE", str(env.ledger))
    monkeypatch.setenv("HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR", str(tmp_path / "receipts"))
    monkeypatch.setenv("HTTPS_PROXY", "http://user:secret@127.0.0.1:9")  # pragma: allowlist secret
    try:
        yield env
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def receipt(rig, **changes):
    rig.sequence += 1
    binding = rig.module.load_binding()
    kwargs = dict(
        receipt_type="read_only_fetch",
        route_id=binding.carrier_route_id,
        task_ids=["fetch-task"],
        receipt_id=f"fetch-fixture-{rig.sequence}",
        issued_at=rig.now,
        stale_after="1h",
        evidence_refs=["candidate-binding-sha256:" + rig.module.binding_sha256(binding)],
    )
    return write_route_authority_receipt(
        build_route_authority_receipt(**(kwargs | changes)), receipt_dir=rig.root / "receipts"
    )


def run(rig, urls=None, receipt_path=None):
    return rig.module.fetch(
        "fetch-task", receipt_path or receipt(rig), urls or ["https://arxiv.org/paper"]
    )


def bound(rig, **changes):
    payload = json.loads(rig.registry.read_text())
    row = next(
        x
        for x in payload["omitted_capability_shapes"]
        if x["shape_id"] == "research.external_primary_source_fetch"
    )
    row["candidate_binding"].update(changes)
    rig.registry.write_text(json.dumps(payload))


def stopped(rig, reason, **kwargs):
    with pytest.raises(rig.module.FetchStop, match=reason):
        run(rig, **kwargs)


def failure_manifest(rig, reason):
    directory = rig.root / "receipts" / "fetch-runs" / f"fetch-fixture-{rig.sequence}"
    raw = (directory / "run.json").read_bytes()
    result = json.loads(raw)
    observation = PlatformCapabilityReceipt.model_validate_json(
        (directory / "observation.json").read_text()
    )
    assert result["stop_reason"] == reason and result["execution_authorized"] is False
    assert observation.tool_state[0].available is False
    assert (
        observation.tool_state[0].evidence_ref
        == "artifact-sha256:" + hashlib.sha256(raw).hexdigest()
    )
    return result, directory


@pytest.mark.parametrize("ip", NONPUBLIC_IPS)
def test_initial_nonpublic_endpoint_stops_before_connection(rig, ip):
    rig.dns["arxiv.org"] = [ip]
    stopped(rig, "unsafe_endpoint")
    assert rig.requests == rig.connections == []
    result, _ = failure_manifest(rig, "unsafe_endpoint")
    assert result["gets"] == result["downloaded_bytes"] == 0


@pytest.mark.parametrize("ip", NONPUBLIC_IPS)
def test_redirect_rejects_nonpublic_in_mixed_dns_answers(rig, ip):
    rig.responses["/paper"] = (302, {"Location": "https://github.com/source"}, b"")
    rig.dns["github.com"] = [PUBLIC_IP, ip]
    stopped(rig, "unsafe_endpoint")
    assert rig.connections == [(PUBLIC_IP, 443)]
    assert [path for path, _ in rig.requests] == ["/paper"]
    result, _ = failure_manifest(rig, "unsafe_endpoint")
    assert result["gets"] == 1 and result["downloaded_bytes"] == 0


@pytest.mark.parametrize("ip", [PUBLIC_IP, "2606:4700:4700::1111"])
def test_public_dns_answers_remain_usable(rig, ip):
    rig.dns["arxiv.org"] = [ip]
    assert rig.module.public_address("arxiv.org") == ip
    assert rig.connections == rig.requests == []


@pytest.mark.parametrize(
    "encoded",
    [
        "::ffff:10.0.0.1",
        "2002:a00:1::",
        "64:ff9b::a00:1",
        "2001:0:808:808:0:ffff:f5ff:fffe",
        "2001:0:a00:1:0:ffff:f6f6:f6f6",
    ],
)
def test_embedded_private_ipv4_stops_when_outer_address_is_global(rig, monkeypatch, encoded):
    # The inner check must survive differences in outer-address classification.
    class GlobalOuter(ipaddress.IPv6Address):
        is_global = property(lambda self: True)
        is_private = property(lambda self: False)
        is_reserved = property(lambda self: False)

    real_parse = ipaddress.ip_address
    monkeypatch.setattr(
        rig.module.ipaddress,
        "ip_address",
        lambda value: GlobalOuter(value) if value == encoded else real_parse(value),
    )
    rig.dns["arxiv.org"] = [PUBLIC_IP, encoded]
    stopped(rig, "unsafe_endpoint")
    assert rig.requests == rig.connections == []
    result, _ = failure_manifest(rig, "unsafe_endpoint")
    assert result["gets"] == 0 and result["documents"] == []


@pytest.mark.parametrize("header", ["WWW-Authenticate", "Proxy-Authenticate"])
def test_authentication_header_stops_even_on_success_status(rig, header):
    rig.responses["/paper"] = (200, {header: "Basic realm=fixture"}, b"must not read")
    stopped(rig, "unexpected_authentication")
    assert rig.connections == [(PUBLIC_IP, 443)] and len(rig.requests) == 1
    result, directory = failure_manifest(rig, "unexpected_authentication")
    assert result["downloaded_bytes"] == 0 and result["documents"] == []
    assert list(directory.glob("*.body")) == []


def test_redirect_without_location_stops_before_another_request(rig):
    rig.responses["/paper"] = (302, {}, b"")
    stopped(rig, "unsafe_endpoint")
    assert rig.connections == [(PUBLIC_IP, 443)] and len(rig.requests) == 1
    result, _ = failure_manifest(rig, "unsafe_endpoint")
    assert result["gets"] == 1 and result["documents"] == []


def test_empty_dns_answer_stops_before_connection(rig):
    rig.dns["arxiv.org"] = []
    stopped(rig, "unsafe_endpoint")
    assert rig.requests == rig.connections == []
    result, _ = failure_manifest(rig, "unsafe_endpoint")
    assert result["gets"] == 0 and result["documents"] == []


def test_truncated_body_retains_incomplete_bytes_and_failure(rig):
    rig.responses["/paper"] = (200, {"Content-Length": "20"}, b"partial")
    stopped(rig, "failed_admission")
    assert rig.connections == [(PUBLIC_IP, 443)] and len(rig.requests) == 1
    result, directory = failure_manifest(rig, "failed_admission")
    assert result["downloaded_bytes"] == 7
    assert len(result["documents"]) == 1
    document = result["documents"][0]
    assert document["complete"] is False and document["bytes"] == 7
    assert document["sha256"] == hashlib.sha256(b"partial").hexdigest()
    assert (directory / document["body"]).read_bytes() == b"partial"


def test_production_entry_stays_closed_even_with_matching_receipt(rig, monkeypatch):
    monkeypatch.setattr(rig.module, "require_first_exposure", rig.production_gate)
    stopped(rig, "failed_admission")
    assert rig.requests == rig.connections == []


@pytest.mark.parametrize(
    "changes",
    [
        {"receipt_type": "quality_equivalence", "quality_floors": ["frontier_required"]},
        {"task_ids": ["other-task"]},
        {"evidence_refs": ["candidate-binding-sha256:" + "0" * 64]},
        {"issued_at": datetime(2000, 1, 1, tzinfo=UTC)},
    ],
)
def test_receipt_failure_precedes_dns_and_io(rig, changes):
    stopped(rig, "failed_admission", receipt_path=receipt(rig, **changes))
    assert rig.requests == rig.connections == []


@pytest.mark.parametrize(
    "ip",
    [
        "10.0.0.1",
        "127.0.0.1",
        "169.254.169.254",  # pragma: allowlist secret
        "::1",
        "fe80::1",
        "::ffff:127.0.0.1",
        "224.0.0.1",  # pragma: allowlist secret
    ],
)
def test_redirect_rechecks_every_resolved_address(rig, ip):
    rig.responses["/paper"] = (302, {"Location": "https://github.com/source"}, b"")
    rig.dns["github.com"] = [PUBLIC_IP, ip]
    stopped(rig, "unsafe_endpoint")
    assert len(rig.requests) == len(rig.connections) == 1


@pytest.mark.parametrize(
    "target",
    [
        "http://github.com/source",
        "https://github.com:444/source",
        "https://elsewhere.test/source",
        "https://user:secret@github.com/source",  # pragma: allowlist secret
        "https://github.com/source?token=secret",
        "https://github.com/source#secret",
        "https://github.com/a b",
        "https://github.com/a\x00b",
    ],
)
def test_redirect_url_constraints_precede_dns(rig, target):
    rig.responses["/paper"] = (302, {"Location": target}, b"")
    stopped(rig, "unsafe_endpoint")
    assert len(rig.requests) == len(rig.connections) == 1


@pytest.mark.parametrize(
    "status,headers,reason",
    [
        (401, {}, "unexpected_authentication"),
        (407, {}, "unexpected_authentication"),
        (302, {"Location": "https://github.com/login"}, "unexpected_authentication"),
        (302, {"Location": "/%6cogin"}, "unexpected_authentication"),
        (402, {}, "unknown_billing"),
    ],
)
def test_auth_and_billing_challenges_stop(rig, status, headers, reason):
    rig.responses["/paper"] = (status, headers, b"no read")
    stopped(rig, reason)
    assert len(rig.requests) == 1


def test_document_bound_stops_before_next_document(rig):
    bound(rig, max_documents=1)
    stopped(rig, "bound_exhausted", urls=["https://arxiv.org/one", "https://arxiv.org/two"])
    assert [p for p, _ in rig.requests] == ["/one"]


def test_get_bound_counts_redirects(rig):
    bound(rig, max_gets=2)
    rig.responses["/paper"] = (302, {"Location": "/paper"}, b"")

    # A broken request guard reaches a finite third response, never an endless test loop.
    def finish_after_two():
        if len(rig.requests) >= 2:
            rig.responses["/paper"] = (200, {}, b"source")

    rig.after_request = finish_after_two
    stopped(rig, "bound_exhausted")
    assert len(rig.requests) == 2


@pytest.mark.parametrize(
    "headers,body",
    [({}, b"123456"), ({"Transfer-Encoding": "chunked"}, b"6\r\n123456\r\n0\r\n\r\n")],
)
def test_stream_byte_bound_handles_known_and_unknown_length(rig, headers, body):
    bound(rig, max_download_bytes=5)
    rig.responses["/paper"] = (200, headers, body)
    stopped(rig, "bound_exhausted")
    assert sum(p.stat().st_size for p in rig.root.rglob("*.body")) == (5 if headers else 0)


def test_exact_known_byte_bound_is_usable(rig):
    bound(rig, max_download_bytes=6)
    path = run(rig).parent / "run.json"
    assert json.loads(path.read_text())["downloaded_bytes"] == 6


def test_tls_still_checks_the_original_hostname(rig):
    stopped(rig, "failed_admission", urls=["https://deepmind.google/source"])
    assert rig.requests == [] and len(rig.connections) == 1


@pytest.mark.parametrize(
    "floor", [ssl.TLSVersion.TLSv1, ssl.TLSVersion.TLSv1_1, ssl.TLSVersion.MINIMUM_SUPPORTED]
)
def test_production_transport_refuses_a_context_below_tls12(rig, floor):
    context = rig.module.PinnedHTTPS("arxiv.org", PUBLIC_IP)._context
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2
    with (
        pytest.warns(DeprecationWarning)
        if floor in (ssl.TLSVersion.TLSv1, ssl.TLSVersion.TLSv1_1)
        else nullcontext()
    ):
        context.minimum_version = floor
    with pytest.raises(rig.module.FetchStop, match="failed_admission"):
        rig.module.PinnedHTTPS("arxiv.org", PUBLIC_IP)
    assert rig.requests == rig.connections == []


def test_initial_endpoint_is_checked_before_connection(rig):
    rig.dns["arxiv.org"] = ["127.0.0.1"]
    stopped(rig, "unsafe_endpoint")
    assert rig.requests == rig.connections == []


def test_total_bytes_are_shared_across_documents(rig):
    bound(rig, max_download_bytes=8)
    stopped(rig, "bound_exhausted", urls=["https://arxiv.org/one", "https://arxiv.org/two"])
    assert sum(p.stat().st_size for p in rig.root.rglob("*.body")) == 6


@pytest.mark.parametrize(
    "damage", ["missing", "malformed", "expired", "future", "no_expiry", "wrong_route"]
)
def test_quota_admission_fails_closed(rig, damage):
    if damage == "missing":
        rig.ledger.unlink()
    elif damage == "malformed":
        rig.ledger.write_text("{}")
    else:
        payload = json.loads(rig.ledger.read_text())
        snapshot = payload["quota_snapshots"][0]
        if damage == "expired":
            snapshot["captured_at"] = (rig.now - timedelta(hours=2)).isoformat()
            snapshot["fresh_until"] = (rig.now - timedelta(hours=1)).isoformat()
        elif damage == "future":
            snapshot["captured_at"] = (rig.now + timedelta(minutes=1)).isoformat()
        elif damage == "no_expiry":
            snapshot.pop("fresh_until")
        else:
            snapshot["route_id"] = "claude.headless.full"
        rig.ledger.write_text(json.dumps(payload))
    stopped(rig, "failed_admission")
    assert rig.requests == rig.connections == []


def test_admission_is_rechecked_before_body_read(rig):
    rig.after_request = lambda: rig.ledger.unlink()
    stopped(rig, "failed_admission")
    assert sum(p.stat().st_size for p in rig.root.rglob("*.body")) == 0


def test_success_retains_receipt_link_hashes_and_no_credentials(rig):
    rig.responses["/paper"] = (
        302,
        {"Location": "https://github.com/source", "Set-Cookie": "secret=bad"},
        b"",
    )
    path = run(rig)
    observation = PlatformCapabilityReceipt.model_validate_json(path.read_text())
    manifest = (path.parent / "run.json").read_bytes()
    result = json.loads(manifest)
    assert observation.load_sets == {}
    assert observation.tool_state[0].available is False
    assert (
        observation.tool_state[0].evidence_ref
        == "artifact-sha256:" + hashlib.sha256(manifest).hexdigest()
    )
    assert result["task_id"] == "fetch-task" and result["gets"] == 2
    assert result["downloaded_bytes"] == 6 and result["stop_reason"] is None
    assert result["execution_authorized"] is False
    assert result["authority_receipt_ref"].endswith(":fetch-fixture-1")
    assert result["requests"] == [
        {"url": "https://arxiv.org/paper", "address": PUBLIC_IP, "status": 302},
        {"url": "https://github.com/source", "address": PUBLIC_IP, "status": 200},
    ]
    assert result["documents"][0]["sha256"] == hashlib.sha256(b"source").hexdigest()
    assert result["documents"][0]["url"] == "https://github.com/source"
    assert all(h["Host"] in {"arxiv.org", "github.com"} for _, h in rig.requests)
    assert all(
        not {k.lower() for k in h} & {"cookie", "authorization", "proxy-authorization"}
        for _, h in rig.requests
    )
    assert rig.connections == [(PUBLIC_IP, 443)] * 2


def test_receipt_cannot_be_replayed_to_reset_bounds(rig):
    authority = receipt(rig)
    first = run(rig, receipt_path=authority)
    original = first.read_bytes()
    stopped(rig, "failed_admission", receipt_path=authority)
    assert len(rig.requests) == 1 and first.read_bytes() == original
