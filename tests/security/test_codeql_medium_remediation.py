from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from logos.api.routes import chronicle, consent, studio, vault

SECRET_TOKEN = "secret-stack-token"


def _json(response) -> dict:
    return json.loads(response.body.decode("utf-8"))


def test_obsidian_sections_use_attribute_context_escaping() -> None:
    source = Path("obsidian-hapax/src/sections.ts").read_text(encoding="utf-8")

    assert 'data-action="${attr(action)}"' in source
    assert "hapax-stance-${attr(stance)}" in source
    assert 'data-action="${esc(action)}"' not in source
    assert "hapax-stance-${esc(stance)}" not in source


def test_conversation_helpers_strip_emoji_without_regex_ranges() -> None:
    from agents.hapax_daimonion.conversation_helpers import _strip_emoji

    assert _strip_emoji(f"hello {chr(0x1F600)} operator") == "hello  operator"
    source = Path("agents/hapax_daimonion/conversation_helpers.py").read_text(encoding="utf-8")
    assert "\\U0001f600-\\U0001f64f" not in source


def test_chat_monitor_tokenizer_strips_emoji_without_regex_ranges() -> None:
    script_path = Path("scripts/chat-monitor.py")
    spec = importlib.util.spec_from_file_location("chat_monitor_codeql_medium", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["chat_monitor_codeql_medium"] = module
    spec.loader.exec_module(module)

    assert module.tokenize_chat(f"HELLO{chr(0x1F600)} wooorld") == ["hello", "wooorld"]
    assert "\\U0001f600-\\U0001f64f" not in script_path.read_text(encoding="utf-8")


def test_vault_related_notes_failure_uses_generic_public_error(monkeypatch) -> None:
    def boom(_query: str, _limit: int) -> list[dict]:
        raise RuntimeError(SECRET_TOKEN)

    monkeypatch.setattr(vault, "_search_related", boom)

    response = asyncio.run(vault.get_related_notes("query", 5))
    payload = _json(response)

    assert payload == {"results": [], "error": "related notes search failed"}
    assert SECRET_TOKEN not in response.body.decode("utf-8")


def test_chronicle_validation_errors_do_not_echo_exception_text() -> None:
    response = asyncio.run(chronicle.chronicle_query(since="-not-a-duration"))
    payload = _json(response)

    assert payload == {"error": "invalid since parameter"}
    assert "not-a-duration" not in response.body.decode("utf-8")


def test_consent_contract_errors_are_generic(monkeypatch) -> None:
    import logos._governance as governance

    def boom():
        raise RuntimeError(SECRET_TOKEN)

    monkeypatch.setattr(governance, "load_contracts", boom)

    payload = asyncio.run(consent.list_contracts())

    assert payload == {
        "contracts": [],
        "active_count": 0,
        "error": "contract list unavailable",
    }


def test_consent_coverage_errors_are_generic(monkeypatch) -> None:
    import logos.api.routes._config as route_config

    def boom():
        raise RuntimeError(SECRET_TOKEN)

    monkeypatch.setattr(route_config, "get_qdrant", boom)

    payload = asyncio.run(consent.consent_coverage())

    assert payload == {"error": "consent coverage unavailable"}


def test_precedent_timeline_errors_are_generic(monkeypatch) -> None:
    import logos.api.routes._config as route_config

    def boom():
        raise RuntimeError(SECRET_TOKEN)

    monkeypatch.setattr(route_config, "get_qdrant", boom)

    payload = asyncio.run(consent.precedent_timeline())

    assert payload == {
        "error": "precedent timeline unavailable",
        "total_precedents": 0,
        "precedents": [],
    }


def test_studio_resolver_errors_are_generic(monkeypatch) -> None:
    def boom():
        raise RuntimeError(SECRET_TOKEN)

    monkeypatch.setitem(
        sys.modules,
        "shared.livestream_egress_state",
        SimpleNamespace(resolve_livestream_egress_state=boom),
    )

    payload = studio._resolve_egress_state_json()

    assert payload["evidence"][0]["summary"] == "egress resolver failed"
    assert SECRET_TOKEN not in json.dumps(payload)


def test_studio_audio_safety_errors_are_generic(monkeypatch) -> None:
    def boom():
        raise RuntimeError(SECRET_TOKEN)

    monkeypatch.setitem(
        sys.modules,
        "shared.broadcast_audio_health",
        SimpleNamespace(read_broadcast_audio_health_state=boom),
    )

    payload = studio._resolve_audio_safe_for_broadcast_json()

    reason = payload["audio_safe_for_broadcast"]["blocking_reasons"][0]
    assert reason["message"] == "audio safety state resolver failed"
    assert SECRET_TOKEN not in json.dumps(payload)


def test_studio_layout_write_error_is_generic(monkeypatch) -> None:
    class BrokenPath:
        parent: BrokenPath

        def __init__(self, _value: str) -> None:
            self.parent = self

        def mkdir(self, *args, **kwargs) -> None:
            raise OSError(SECRET_TOKEN)

    monkeypatch.setattr(studio, "Path", BrokenPath)

    response = asyncio.run(studio.set_layout_mode(studio.LayoutModeRequest(mode="balanced")))
    payload = _json(response)

    assert payload == {"error": "write failed"}
    assert SECRET_TOKEN not in response.body.decode("utf-8")
