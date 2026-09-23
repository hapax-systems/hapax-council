"""Test ConsentGatedReader wiring in conversation pipeline."""

import asyncio
import importlib
import logging
import threading
import time
from dataclasses import asdict
from unittest.mock import AsyncMock, Mock

import pytest

from shared.governance import consent
from tests.shared.synthetic_custody import CONTRACT, OLD_PRINCIPAL, PRINCIPAL


def test_pipeline_calls_filter_tool_result():
    """Conversation pipeline must call consent_reader.filter_tool_result."""
    source = open("agents/hapax_daimonion/conversation_pipeline.py").read()
    assert "filter_tool_result" in source, (
        "conversation_pipeline must call consent_reader.filter_tool_result for tool results"
    )


def _pipeline(reader, content):
    from agents.hapax_daimonion.conversation_pipeline import ConversationPipeline

    pipeline = ConversationPipeline.__new__(ConversationPipeline)
    pipeline._bridge_engine = None
    pipeline._consent_reader = reader
    pipeline._tool_recruitment_gate = None
    pipeline.messages = []
    pipeline.tool_handlers = {"search_documents": lambda _: content}
    pipeline._emit = Mock()
    pipeline._generate_and_speak = AsyncMock()
    return pipeline


def _registry():
    return consent.ConsentRegistry(
        _contracts={
            CONTRACT: consent.ConsentContract(
                CONTRACT, ("operator", PRINCIPAL), frozenset({"audio"})
            )
        }
    )


async def _retrieve(pipeline):
    await pipeline._handle_tool_calls(
        [{"id": "synthetic-call", "name": "search_documents", "arguments": "{}"}], ""
    )
    pipeline._generate_and_speak.assert_awaited_once()
    return pipeline.messages[-1]["content"]


@pytest.mark.parametrize(
    "module_name", ["shared.governance.consent_reader", "agents._governance.consent_reader"]
)
@pytest.mark.parametrize("scope", ["audio", "document"])
async def test_complete_retrieval_gates_predecessor(
    module_name, scope, synthetic_custody, tmp_path, caplog
):
    module = importlib.import_module(module_name)
    registry = consent.ConsentRegistry(
        _contracts={
            CONTRACT: consent.ConsentContract(CONTRACT, ("operator", PRINCIPAL), frozenset({scope}))
        }
    )
    reader = module.ConsentGatedReader(registry, frozenset({"operator"}), tmp_path / "reader.jsonl")
    caplog.set_level(logging.INFO)
    predecessor = await _retrieve(_pipeline(reader, f"Notes about {OLD_PRINCIPAL}."))
    canonical = await _retrieve(_pipeline(reader, f"Notes about {PRINCIPAL}."))
    if scope == "audio":
        assert predecessor == canonical == "Notes about someone."
    else:
        assert predecessor == f"Notes about {OLD_PRINCIPAL}."
        assert canonical == f"Notes about {PRINCIPAL}."
    assert len(reader.decisions) == 2
    assert reader.decisions[0].degradation_level == (2 if scope == "audio" else 1)
    assert await _retrieve(_pipeline(reader, "No people mentioned.")) == "No people mentioned."
    assert len(reader.decisions) == 2
    assert OLD_PRINCIPAL not in (tmp_path / "reader.jsonl").read_text()
    assert OLD_PRINCIPAL not in caplog.text
    if scope == "audio":
        assert OLD_PRINCIPAL not in repr([asdict(d) for d in reader.decisions])
    assert all(d.person_ids == (PRINCIPAL,) for d in reader.decisions)


@pytest.mark.parametrize(
    "module_name", ["shared.governance.consent_reader", "agents._governance.consent_reader"]
)
async def test_retrieval_keeps_loop_responsive_with_one_snapshot(
    module_name, synthetic_custody, monkeypatch
):
    module = importlib.import_module(module_name)
    reader = module.ConsentGatedReader(_registry(), frozenset({"operator"}))
    pipeline = _pipeline(
        reader, f"Notes about {OLD_PRINCIPAL} and {PRINCIPAL} and another@example.test."
    )
    original = consent._read_compatibility_document
    entered = threading.Event()
    finished = threading.Event()
    calls = 0

    def slow_read():
        nonlocal calls
        calls += 1
        entered.set()
        time.sleep(0.2)
        raw = original()
        finished.set()
        return raw

    monkeypatch.setattr(consent, "_read_compatibility_document", slow_read)

    async def heartbeat():
        while not entered.is_set():
            await asyncio.sleep(0.001)
        assert not finished.is_set(), "custody read blocked the event loop"

    result, _ = await asyncio.gather(_retrieve(pipeline), heartbeat())
    assert OLD_PRINCIPAL not in result
    assert calls == 1


async def test_pipeline_start_offloads_reload(synthetic_custody, monkeypatch):
    module = importlib.import_module("agents._governance.consent_reader")
    from agents.hapax_daimonion.conversation_pipeline import ConversationPipeline

    registry = _registry()
    monkeypatch.setattr(module, "load_contracts", lambda: registry)
    reader = module.ConsentGatedReader(registry, frozenset({"operator"}))
    pipeline = _pipeline(reader, "")
    pipeline._experiment_flags = {}
    pipeline.system_prompt = "synthetic system"
    pipeline.buffer = None
    pipeline._open_audio_output = Mock()
    pipeline._prewarm_llm = AsyncMock()
    main_thread = threading.get_ident()
    original = consent._read_compatibility_document
    reads = []

    def checked_read():
        reads.append(threading.get_ident())
        assert reads[-1] != main_thread
        return original()

    monkeypatch.setattr(consent, "_read_compatibility_document", checked_read)
    await ConversationPipeline.start(pipeline)
    await asyncio.sleep(0)
    assert len(reads) == 1


async def test_pipeline_worker_inherits_existing_snapshot(synthetic_custody, monkeypatch):
    module = importlib.import_module("agents._governance.consent_reader")
    pipeline = _pipeline(
        module.ConsentGatedReader(_registry(), frozenset({"operator"})),
        f"Notes about {OLD_PRINCIPAL}.",
    )
    with consent.estate_identity_operation():

        def forbid_reload():
            raise AssertionError("nested operation loaded another snapshot")

        monkeypatch.setattr(consent, "_read_compatibility_document", forbid_reload)
        assert await _retrieve(pipeline) == "Notes about someone."
