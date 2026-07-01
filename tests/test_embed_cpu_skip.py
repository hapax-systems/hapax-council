"""Fix A: CPU-embed models (nomic-embed-cpu) NEVER interact with the GPU semaphore.

A CPU embed (Ollama ``size_vram:0``) contends for no GPU VRAM, so it must BYPASS the
GPU-VRAM coordinator (``gpu_slot``'s ``fcntl.flock``) entirely — not merely block-non-block
on it. ``block=False`` would still couple the CPU embed to GPU state (acquire when free,
SKIP when saturated), which is the residual classification bug. The bypass makes a CPU
embed never acquire, block, or skip on a GPU flock — full decoupling of CPU perception
from GPU load. This is the per-call equivalent of the proven ``HAPAX_GPU_SEM_NONBLOCK``
mechanism, so every CPU embedder in the fleet (~30 callers, incl. rag-ingest + the
segment-prep producer) is robust by construction, not just the ones that set the env.

Background: py-spy + /proc/locks (2026-06-22) showed the producer deadlocked as the 5th
waiter on ``slot.0`` behind unrelated GPU-resident daemons, for VRAM its CPU embed never
touched. Self-contained per council test conventions (``unittest.mock`` only).
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from shared.config import EMBEDDING_MODEL, EXPECTED_EMBED_DIMENSIONS, embed, embed_batch

_VEC = [0.1] * EXPECTED_EMBED_DIMENSIONS


def _slot_spy() -> tuple[dict, object]:
    """Spy on gpu_slot: captures the ``block`` kwarg + call count, runs the body slot-less."""
    captured: dict = {"block": "NOT_CALLED", "count": 0}

    @contextmanager
    def _spy(block: bool = True):
        captured["block"] = block
        captured["count"] += 1
        yield

    return captured, _spy


def _mock_client() -> MagicMock:
    mc = MagicMock()
    mc.embed.return_value = {"embeddings": [_VEC]}
    return mc


def test_default_embedding_model_is_cpu() -> None:
    # The fleet default is the CPU model — so the default embed path must bypass the slot.
    assert EMBEDDING_MODEL == "nomic-embed-cpu"


def test_embed_cpu_model_bypasses_gpu_slot() -> None:
    captured, spy = _slot_spy()
    with (
        patch("shared.gpu_semaphore.gpu_slot", spy),
        patch("shared.config._get_ollama_client", return_value=_mock_client()),
    ):
        vec = embed("text", model="nomic-embed-cpu")
    assert captured["count"] == 0  # CPU model → gpu_slot never called (fully bypassed)
    assert vec == _VEC  # ...and the embed still ran + returned a vector


def test_embed_default_model_bypasses_gpu_slot() -> None:
    captured, spy = _slot_spy()
    with (
        patch("shared.gpu_semaphore.gpu_slot", spy),
        patch("shared.config._get_ollama_client", return_value=_mock_client()),
    ):
        embed("text")  # defaults to EMBEDDING_MODEL = nomic-embed-cpu
    assert captured["count"] == 0


def test_embed_gpu_model_acquires_gpu_slot() -> None:
    # A GPU-resident embed model must still acquire the slot (it genuinely contends for VRAM).
    captured, spy = _slot_spy()
    with (
        patch("shared.gpu_semaphore.gpu_slot", spy),
        patch("shared.config._get_ollama_client", return_value=_mock_client()),
    ):
        embed("text", model="nomic-embed-text")  # the GPU variant (size_vram > 0)
    assert captured["count"] == 1
    assert captured["block"] is True


def test_embed_gpu_model_respects_block_gpu_false() -> None:
    # An explicit block_gpu=False on a GPU model still reaches gpu_slot (non-blocking).
    captured, spy = _slot_spy()
    with (
        patch("shared.gpu_semaphore.gpu_slot", spy),
        patch("shared.config._get_ollama_client", return_value=_mock_client()),
    ):
        embed("text", model="nomic-embed-text", block_gpu=False)
    assert captured["count"] == 1
    assert captured["block"] is False


def test_embed_batch_cpu_model_bypasses_gpu_slot() -> None:
    captured, spy = _slot_spy()
    with (
        patch("shared.gpu_semaphore.gpu_slot", spy),
        patch("shared.config._get_ollama_client", return_value=_mock_client()),
    ):
        embed_batch(["a"], model="nomic-embed-cpu")
    assert captured["count"] == 0


def test_embed_batch_gpu_model_acquires_gpu_slot() -> None:
    captured, spy = _slot_spy()
    with (
        patch("shared.gpu_semaphore.gpu_slot", spy),
        patch("shared.config._get_ollama_client", return_value=_mock_client()),
    ):
        embed_batch(["a"], model="nomic-embed-text")
    assert captured["count"] == 1
    assert captured["block"] is True


def test_explicit_block_gpu_true_irrelevant_for_cpu_model() -> None:
    # block_gpu=True must NOT make a CPU model acquire the slot — the model check wins
    # (a CPU embed cannot contend for VRAM, so blocking is never correct for it).
    captured, spy = _slot_spy()
    with (
        patch("shared.gpu_semaphore.gpu_slot", spy),
        patch("shared.config._get_ollama_client", return_value=_mock_client()),
    ):
        embed("text", model="nomic-embed-cpu", block_gpu=True)
    assert captured["count"] == 0
