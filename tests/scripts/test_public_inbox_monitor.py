"""Synthetic metadata fixtures only; no live mailbox or foreign bodies."""

import json
from pathlib import Path

import httpx
import pytest

from scripts import public_inbox_monitor as monitor


def test_missing_published_route_fails_even_with_other_enabled_routes():
    published = {"contact@hapaxresearch.com": ["https://hapaxresearch.com/contact/"]}
    routes = {address: "forward" for address in monitor.KNOWN_INBOXES}
    routes[monitor.WORKER_RECIPIENT] = "worker"
    assert monitor.check_routes(routes, published) == []
    del routes["contact@hapaxresearch.com"]
    assert "missing enabled route: contact@hapaxresearch.com" in monitor.check_routes(
        routes, published
    )
    routes["contact@hapaxresearch.com"] = "forward"
    del routes["rlk@hapaxresearch.com"]
    assert "missing enabled route: rlk@hapaxresearch.com" in monitor.check_routes(routes, published)
    routes["rlk@hapaxresearch.com"] = "forward"
    published["new@hapaxresearch.com"] = ["https://hapaxresearch.com/contact/"]
    assert "missing enabled route: new@hapaxresearch.com" in monitor.check_routes(routes, published)
    del published["new@hapaxresearch.com"]
    routes[monitor.WORKER_RECIPIENT] = "forward"
    assert "HAN intake must use worker route" in monitor.check_routes(routes, published)


def test_public_crawl_finds_footer_and_org_address(monkeypatch):
    pages = {
        "https://hapaxresearch.com/": '<a href="/contact/">Contact</a>',
        "https://hapaxresearch.com/contact/": "<footer>contact@hapaxresearch.com</footer>",
        "https://raw.githubusercontent.com/org/profile.md": "hrl-han@hapaxresearch.com",
    }
    roots = ("https://hapaxresearch.com/", "https://raw.githubusercontent.com/org/profile.md")
    assert monitor.published_addresses(pages.__getitem__, roots) == {
        "contact@hapaxresearch.com": ["https://hapaxresearch.com/contact/"],
        "hrl-han@hapaxresearch.com": ["https://raw.githubusercontent.com/org/profile.md"],
    }
    del pages["https://hapaxresearch.com/contact/"]
    with pytest.raises(monitor.MonitorError, match="unavailable"):
        monitor.published_addresses(pages.__getitem__, roots)


def test_active_site_roots_include_newly_published_zone(monkeypatch):
    import socket

    def lookup(domain, _port):
        if domain in {"hapaxresearch.com", "hapaxromanum.com"}:
            return [("fixture",)]
        raise socket.gaierror(socket.EAI_NONAME, "synthetic absent DNS")

    monkeypatch.setattr(monitor.socket, "getaddrinfo", lookup)
    assert monitor.active_site_roots() == (
        "https://hapaxresearch.com/",
        "https://hapaxromanum.com/",
    )


def test_cloudflare_enumerates_every_zone_and_refuses_unknown_rules(monkeypatch):
    monkeypatch.setattr(monitor, "_secret", lambda _name: "fixture")
    zones = [{"id": str(i), "name": name} for i, name in enumerate(sorted(monitor.DOMAINS))]
    rule = {
        "enabled": True,
        "matchers": [{"type": "literal", "field": "to", "value": "contact@hapaxresearch.com"}],
        "actions": [{"type": "forward", "value": ["private@example.invalid"]}],
    }
    state = {"zones": zones, "rule": rule}

    def handler(request):
        if request.url.path == "/client/v4/zones":
            rows = state["zones"]
        elif request.url.path.endswith("/email/routing"):
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "result": state.get("settings", {"enabled": True, "status": "ready"}),
                },
            )
        elif request.url.path.endswith("/email/routing/rules") and "/zones/1/" in request.url.path:
            rows = [state["rule"]]
        else:
            rows = []
        return httpx.Response(
            200, json={"success": True, "result": rows, "result_info": {"total_pages": 1}}
        )

    client = httpx.Client
    monkeypatch.setattr(
        monitor.httpx, "Client", lambda **kw: client(transport=httpx.MockTransport(handler), **kw)
    )
    assert monitor.cloudflare_routes() == {"contact@hapaxresearch.com": "forward"}
    state["settings"] = {"enabled": False, "status": "unconfigured"}
    with pytest.raises(monitor.MonitorError, match="unready"):
        monitor.cloudflare_routes()
    state.pop("settings")
    state["zones"] = zones[:-1]
    with pytest.raises(monitor.MonitorError, match="incomplete"):
        monitor.cloudflare_routes()
    state["zones"] = zones
    state["rule"] = {**rule, "matchers": [{"type": "all"}]}
    with pytest.raises(monitor.MonitorError, match="matcher"):
        monitor.cloudflare_routes()


class Request:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class FakeGmail:
    def __init__(self):
        self.calls = []
        self.history_pages = []
        self.messages_by_id = {}

    def users(self):
        return self

    def history(self):
        return self

    def messages(self):
        return self

    def getProfile(self, **kwargs):
        self.calls.append(("profile", kwargs))
        return Request({"historyId": "100"})

    def list(self, **kwargs):
        self.calls.append(("history", kwargs))
        return Request(self.history_pages.pop(0))

    def get(self, **kwargs):
        self.calls.append(("message", kwargs))
        return Request(self.messages_by_id[kwargs["id"]])


def _page(mid):
    return {"historyId": "101", "history": [{"messagesAdded": [{"message": {"id": mid}}]}]}


def _message(recipient):
    return {
        "id": "fixture",
        "payload": {"headers": [{"name": "To", "value": recipient}]},
        "snippet": "FOREIGN_BODY_SENTINEL_DO_NOT_SURFACE",
    }


def test_gmail_watcher_persists_pending_before_alert_and_retries(tmp_path):
    state = tmp_path / "private" / "state.json"
    service = FakeGmail()
    routes = {"contact@hapaxresearch.com": "forward", "hrl-han@hapaxresearch.com": "worker"}
    assert monitor.watch_gmail(service, routes, state, lambda *_a, **_k: True) == 0
    assert service.calls == [("profile", {"userId": "me", "fields": "historyId"})]
    service.history_pages = [_page("m1")]
    service.messages_by_id["m1"] = _message("contact@hapaxresearch.com")
    notices = []

    def fail_once(title, text, **kwargs):
        notices.append((title, text, kwargs, json.loads(state.read_text())))
        return len(notices) > 1

    with pytest.raises(monitor.MonitorError, match="pending ID retained"):
        monitor.watch_gmail(service, routes, state, fail_once)
    assert json.loads(state.read_text()) == {"history_id": "101", "pending_ids": ["m1"]}
    service.history_pages = [{"historyId": "101"}]
    assert monitor.watch_gmail(service, routes, state, fail_once) == 1
    assert json.loads(state.read_text()) == {"history_id": "101", "pending_ids": []}
    assert all("FOREIGN_BODY_SENTINEL" not in repr(x) for x in notices)
    assert notices[0][3]["pending_ids"] == ["m1"]
    assert all(
        call[1].get("format") == "metadata" and call[1].get("fields") == "id,payload/headers"
        for call in service.calls
        if call[0] == "message"
    )


def test_gmail_watcher_ignores_personal_mail_and_does_not_read_body(tmp_path):
    state = tmp_path / "private" / "state.json"
    service = FakeGmail()
    routes = {"contact@hapaxresearch.com": "forward"}
    monitor.watch_gmail(service, routes, state, lambda *_a, **_k: True)
    service.history_pages = [_page("personal")]
    service.messages_by_id["personal"] = _message("private@example.invalid")
    assert (
        monitor.watch_gmail(
            service, routes, state, lambda *_a, **_k: pytest.fail("unexpected alert")
        )
        == 0
    )
    assert json.loads(state.read_text())["pending_ids"] == []


def test_ntfy_requires_acceptance_and_uses_same_topic(monkeypatch):
    seen = []
    status = {"code": 503}
    monkeypatch.delenv("NTFY_BASE_URL", raising=False)
    assert not monitor.send_public_notification("test", "synthetic")
    monkeypatch.setenv("NTFY_BASE_URL", "http://ntfy.example.invalid:8090")

    def handler(request):
        seen.append(request)
        return httpx.Response(status["code"])

    client = httpx.Client
    monkeypatch.setattr(
        monitor.httpx, "Client", lambda **kw: client(transport=httpx.MockTransport(handler), **kw)
    )
    assert not monitor.send_public_notification("test", "New mail to contact@hapaxresearch.com")
    status["code"] = 200
    assert monitor.send_public_notification("test", "New mail to contact@hapaxresearch.com")
    assert json.loads(seen[-1].content) == {
        "topic": "hapax-han-mail",
        "title": "test",
        "message": "New mail to contact@hapaxresearch.com",
        "priority": 4,
        "tags": ["mail"],
    }


def test_single_kv_puller_is_pinned_to_appendix():
    root = Path(__file__).resolve().parents[2]
    unit = (root / "systemd/units/han-mail-pull.service").read_text()
    assert "ConditionHost=hapax-appendix" in unit
    assert (
        "ConditionHost=hapax-podium"
        in (root / "systemd/units/public-inbox-watch.service").read_text()
    )
