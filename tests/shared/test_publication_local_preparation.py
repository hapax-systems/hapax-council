"""Exercise real local writers and their later, separately admitted egress."""

from importlib import import_module
from pathlib import Path
from unittest.mock import Mock

import pytest

from agents.publication_bus.publisher_kit import AllowlistGate, PublisherPayload, PublisherResult
from tests.publication_admission_fixtures import install_publication_admission

LOCAL_PUBLISHERS = (
    ("agents.marketing.refusal_annex_publisher", "RefusalAnnexPublisher"),
    ("agents.publication_bus.github_sponsors_publisher", "GitHubSponsorsPublisher"),
    ("agents.publication_bus.liberapay_publisher", "LiberapayPublisher"),
    ("agents.publication_bus.stripe_payment_link_publisher", "StripePaymentLinkPublisher"),
    ("agents.publication_bus.ko_fi_publisher", "KoFiPublisher"),
    ("agents.publication_bus.patreon_publisher", "PatreonPublisher"),
    ("agents.publication_bus.buy_me_a_coffee_publisher", "BuyMeACoffeePublisher"),
    ("agents.publication_bus.open_collective_publisher", "OpenCollectivePublisher"),
    ("agents.publication_bus.mercury_publisher", "MercuryPublisher"),
    ("agents.publication_bus.modern_treasury_publisher", "ModernTreasuryPublisher"),
    ("agents.publication_bus.treasury_prime_publisher", "TreasuryPrimePublisher"),
)


@pytest.fixture(autouse=True)
def isolated_effects(monkeypatch, tmp_path):
    monkeypatch.delenv("HAPAX_PUBLICATION_TASK_ID", raising=False)
    monkeypatch.setenv("HAPAX_ROUTE_DECISION_LEDGER", str(tmp_path / "absent.jsonl"))
    monkeypatch.setenv("HAPAX_PUBLICATION_LOG_PATH", str(tmp_path / "witness.jsonl"))
    monkeypatch.setenv("HAPAX_REFUSALS_LOG_PATH", str(tmp_path / "refusals.jsonl"))
    monkeypatch.setenv("HAPAX_OPERATOR_NAME", "Synthetic Private Name")
    monkeypatch.setattr(
        "requests.sessions.Session.request",
        lambda *a, **kw: pytest.fail("local preparation attempted HTTP"),
    )


def local_case(module, name, monkeypatch, tmp_path):
    cls = getattr(import_module(module), name)
    target = next(iter(cls.allowlist.permitted))
    monkeypatch.setattr(cls, "allowlist", AllowlistGate(cls.surface_name, frozenset({target})))
    return cls(output_dir=tmp_path / "prepared"), PublisherPayload(
        target=target, text="A bounded local record.", metadata={"raw_payload_sha256": "a" * 64}
    )


@pytest.mark.parametrize("module,name", LOCAL_PUBLISHERS)
def test_local_preparation_needs_no_public_route(module, name, monkeypatch, tmp_path):
    publisher, payload = local_case(module, name, monkeypatch, tmp_path)
    result = publisher.publish(payload)
    assert result.ok, result.detail
    assert result.route_resource_admission is None
    assert Path(result.detail).read_text() == payload.text
    witness = (tmp_path / "witness.jsonl").read_text()
    assert publisher.surface_name in witness


@pytest.mark.parametrize("module,name", LOCAL_PUBLISHERS)
@pytest.mark.parametrize("violation", ["allowlist", "legal_name"])
def test_local_preparation_keeps_content_guards(module, name, violation, monkeypatch, tmp_path):
    publisher, payload = local_case(module, name, monkeypatch, tmp_path)
    payload = PublisherPayload(
        target="not-admitted" if violation == "allowlist" else payload.target,
        text="Synthetic Private Name" if violation == "legal_name" else payload.text,
    )
    result = publisher.publish(payload)
    assert result.refused
    assert (
        "allowlist" in result.detail if violation == "allowlist" else "legal-name" in result.detail
    )
    assert not (tmp_path / "prepared").exists()


def test_replacing_local_writer_with_transport_requires_admission(monkeypatch, tmp_path):
    from agents.marketing.refusal_annex_publisher import RefusalAnnexPublisher

    transport = Mock(return_value=PublisherResult(ok=True))

    class TransportPublisher(RefusalAnnexPublisher):
        _emit = transport

    monkeypatch.setattr(
        TransportPublisher, "allowlist", AllowlistGate("marketing-refusal-annex", frozenset({"ok"}))
    )
    result = TransportPublisher(output_dir=tmp_path).publish(
        PublisherPayload(target="ok", text="Clean content.", metadata={"local_preparation": True})
    )
    assert result.refused
    assert result.route_resource_admission["allowed"] is False
    transport.assert_not_called()


def test_prepared_annex_still_requires_route_at_remote_publisher(monkeypatch, tmp_path):
    from agents.publication_bus.omg_weblog_publisher import OmgLolWeblogPublisher

    publisher, payload = local_case(*LOCAL_PUBLISHERS[0], monkeypatch, tmp_path)
    prepared = publisher.publish(payload)
    assert prepared.ok
    text = Path(prepared.detail).read_text()
    client = Mock()
    client.enabled = True
    client.set_entry.return_value = {"url": "https://example.invalid/prepared"}
    remote = OmgLolWeblogPublisher(client=client, address="synthetic")
    monkeypatch.setattr(
        remote, "allowlist", AllowlistGate(remote.surface_name, frozenset({"prepared"}))
    )
    outgoing = PublisherPayload(target="prepared", text=text, metadata={"local_preparation": True})
    denied = remote.publish(outgoing)
    assert denied.refused
    client.set_entry.assert_not_called()
    install_publication_admission(monkeypatch, tmp_path, surfaces=[remote.surface_name])
    admitted = remote.publish(outgoing)
    assert admitted.ok, admitted.detail
    client.set_entry.assert_called_once()
