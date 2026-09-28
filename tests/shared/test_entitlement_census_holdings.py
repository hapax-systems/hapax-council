"""Spend-free transport and names-only holdings in the staged census producer."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import shared.entitlement_census as census
from shared.entitlement_census import (
    HostBinding,
    SecretLeakError,
    SecretRegister,
    collect_holdings,
    holdings_command,
    parse_holdings,
)

NOW = datetime(2026, 9, 28, tzinfo=UTC)


def test_numeric_facts_reject_nonfinite_values_without_name_errors():
    assert census._number(2.5) == 2.5
    assert census._number(float("inf")) is None
    assert census._safe_fact(2.5) == 2.5
    assert census._safe_fact(float("nan")) is None


def test_secret_register_rejects_resolved_values_and_secret_shapes():
    register = SecretRegister()
    register.remember("fixture-credential-value")
    with pytest.raises(SecretLeakError, match="nothing was written"):
        register.require_clean("provider echoed fixture-credential-value", label="view")
    pem_prefix = "-----BEGIN "
    pem_type = "PRIVATE" + " KEY-----"
    with pytest.raises(SecretLeakError):
        register.require_clean(pem_prefix + pem_type, label="view")
    register.require_clean("names and counts only", label="view")


def test_remote_holdings_are_batch_bound_and_names_only():
    binding = HostBinding(host_id="podium", transport="ssh_batch", target="podium.example")
    argv = holdings_command(binding, login_files=[".config/login.json"], harness_bins=["codex"])
    assert argv[:4] == ["ssh", "-o", "BatchMode=yes", "-o"]
    assert "-f" not in argv and "podium.example" in argv
    row = parse_holdings(
        "podium",
        "F\tprovider-token\nP\tother/key\nL\t.config/login.json\t1790553600\nB\tcodex\n",
        now=NOW,
    )
    assert row.filestore_names == ("provider-token",)
    assert row.pass_names == ("other/key",)
    assert row.harness_bins == ("codex",)
    assert ".config/login.json" in row.login_files
    assert "fixture-credential-value" not in repr(row)


def test_unreachable_host_is_explicit_and_never_absent():
    binding = HostBinding(host_id="podium", transport="ssh_batch", target="podium.example")
    seen = []

    def run(argv, **kwargs):
        seen.append((argv, kwargs))
        return SimpleNamespace(returncode=255, stdout="")

    row = collect_holdings(binding, login_files=[], harness_bins=[], now=NOW, run=run)
    assert seen and row.reachable is False and row.error == "exit_255"
    assert row.observed_at is None


def test_transport_builds_get_without_body_and_refuses_redirect(monkeypatch):
    requests = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, _):
            return b"{}"

    def open_request(request, *, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(census._OPENER, "open", open_request)
    assert (
        census.default_http_get(
            "https://example.test/usage", {"Authorization": "fixture"}, 1
        ).status
        == 200
    )
    request, timeout = requests[0]
    assert request.get_method() == "GET" and request.data is None and timeout == 1
    assert (
        census._RefuseRedirects().redirect_request(
            request, None, 302, "move", {}, "https://other.test/"
        )
        is None
    )
