# ALPHA-FINDING-1 — Compositor Memory Leak Root Cause

**Date:** 2026-04-13
**Audit phase:** Post-epic audit Phase 3 (robustness + resource leaks)
**Status:** root cause confirmed; fix deferred to a follow-up PR
**Reporter:** post-epic audit session (alpha, post A3 merge)

## TL;DR

The studio compositor process **runs Kokoro TTS inference (PyTorch) in-process**, pulling ~3 GB of CUDA runtime libraries and torch modules into the compositor's address space. Each synthesis pass allocates intermediate tensors that accumulate in the torch allocator, producing the steady **~49 MB/min RSS growth** previously tracked as ALPHA-FINDING-1.

This is both a **leak** and an **architectural violation** — per `CLAUDE.md` § "Key services", TTS lives in `hapax-daimonion`, not in the compositor. The fix is to remove TTS from the compositor process and route synthesis through the daimonion via IPC.

## Live measurement

Pulled from a live main-branch compositor after the post-epic A1+A3 merge, steady-state:

| Metric | t0 (15:38:24) | t1 (15:40:04) | Δ over 100s | Rate |
|---|---|---|---|---|
| VmRSS | 6,407,820 kB | 6,490,456 kB | +82,636 kB | **49 MB/min** |
| RssAnon | 5,565,152 kB | 5,647,888 kB | +82,736 kB | **49 MB/min** |
| VmSize | 25,958,748 kB | 26,308,852 kB | +350,104 kB | 205 MB/min |
| VmData | 10,137,108 kB | 10,525,012 kB | +387,904 kB | 228 MB/min |
| Threads | 112 → 104 | — | — | — |

The **4.7× gap between virtual (228 MB/min) and resident (49 MB/min) growth** is a signature of an allocator that reserves large address ranges and only lazily touches a fraction of them — consistent with PyTorch's caching allocator behavior.

## Root cause stack trace

`sudo py-spy dump --pid $(pgrep -f 'agents.studio_compositor')` on the running compositor showed a live torch forward pass:

```
Thread 2388001 (active): "speak-react"
    _conv_forward (torch/nn/modules/conv.py:371)
    forward (torch/nn/modules/conv.py:375)
    inner (torch/nn/modules/module.py:1830)
    ...
    forward (kokoro/istftnet.py:72)
    forward (kokoro/istftnet.py:319)
    forward (kokoro/istftnet.py:420)
    forward_with_tokens (kokoro/model.py:118)
    forward (kokoro/model.py:133)
    infer (kokoro/pipeline.py:232)
    __call__ (kokoro/pipeline.py:383)
    _synthesize_kokoro (agents/hapax_daimonion/tts.py:58)
    synthesize (agents/hapax_daimonion/tts.py:52)
    _synthesize (agents/studio_compositor/director_loop.py:742)
    _do_speak_and_advance (agents/studio_compositor/director_loop.py:696)
```

Cross-referenced against `/proc/$PID/map_files`: 35 `libtorch*` entries, `libtorch_cuda.so` (921 MB mapped), `libcublasLt` (616 MB), `libcusparse`, `libcublas`, `libcufft`, `libcurand`, `libcusolver`, `libnccl`, `libnvshmem_host`, `libcusparseLt`, `libtriton.so`. A fresh compositor process would not map any of these — they are demand-loaded by the `from agents.hapax_daimonion.tts import TTSManager` line when `_synthesize` is first invoked.

## The offending code

`agents/studio_compositor/director_loop.py:735-742`:

```python
def _synthesize(self, text: str) -> bytes:
    with self._tts_lock:
        if self._tts_manager is None:
            from agents.hapax_daimonion.tts import TTSManager

            self._tts_manager = TTSManager()
            self._tts_manager.preload()
        return self._tts_manager.synthesize(text, "conversation")
```

The `TTSManager()` construction + `.preload()` pulls in Kokoro + torch + the full CUDA linker dependency chain. Every subsequent `.synthesize(text, ...)` call runs a full forward pass inside the compositor process — each adding torch allocator pressure that never fully releases. The `_tts_lock` prevents concurrent synthesis but doesn't bound memory growth per call.

## Why this violates the architecture

`CLAUDE.md` § "Key services":

> `hapax-daimonion` (GPU STT, CPU TTS)

TTS is explicitly a daimonion concern. The compositor is supposed to be a GStreamer + Cairo render shell. Running Kokoro in the compositor process:

1. **Doubles the VRAM/RAM footprint** — both daimonion and the compositor hold a Kokoro model in memory.
2. **Couples separation of concerns** — changes to the daimonion TTS path now have to consider compositor process implications.
3. **Produces the leak** — torch's caching allocator accumulates arena space across forward passes in a process that's otherwise long-lived and never unloads.
4. **Adds 3 GB+ of driver libraries** to the compositor's mapped file set, slowing process startup and pushing disk cache eviction.

## Fix options

### Option A — delegate to daimonion via HTTP (recommended)

`hapax-daimonion` already owns TTS. Expose a synthesize endpoint on its internal API, have `director_loop._synthesize` call it, return PCM as bytes. Zero torch in the compositor.

**Risk:** daimonion's TTS path is hot and shared with the CPAL voice loop. Adding a second caller needs a queue bound and cancellation semantics.

**Scope:** 2–4 hours.

### Option B — delegate via /dev/shm request/response

Write `{text, id}` to `/dev/shm/hapax-daimonion/tts-requests/{id}.json`, poll for `/dev/shm/hapax-daimonion/tts-responses/{id}.pcm`. File-based queue matches the existing hapax filesystem-as-bus convention.

**Risk:** latency vs HTTP, atomic write discipline.

**Scope:** 3–5 hours.

### Option C — strip the in-process TTS entirely; compositor speaks via existing impingement path

The director loop can write a `{modality: "auditory", text, slot}` impingement to `/dev/shm/hapax-dmn/impingements.jsonl`; the daimonion's CPAL loop already picks these up and speaks them. Removes the synchronous PCM handoff in favor of the existing unified semantic recruitment path.

**Risk:** the director loop needs the completion timing to sequence slot advances; impingement path is fire-and-forget.

**Scope:** 4–8 hours (requires completion callback or polled status).

### Non-options

- **"Tune the torch allocator"** — slaps a bandaid on the architectural violation. The leak would still accumulate, just slower, and the 3 GB of mapped libraries would stay.
- **"Restart the compositor periodically"** — a systemd `MemoryMax=6G` already bounds it. The right fix is to not load torch.

## Recommendation

**Option A** for minimum disruption. The daimonion already has a FastAPI app; adding a synthesize endpoint is a one-file change on the daimonion side and a one-function change on the compositor side. The existing `TTSManager.preload()` + `synthesize()` API is already serialized by a lock, so single-caller semantics on the wire are a natural fit.

## Follow-up ticket

**Title:** `fix(compositor): ALPHA-FINDING-1 — remove in-process TTS, delegate to daimonion`

**Scope:**
- Add `POST /api/tts/synthesize` (or equivalent) to hapax-daimonion's FastAPI app.
- Rewrite `director_loop._synthesize` to call the endpoint and return the PCM bytes.
- Drop the `self._tts_manager` field and the lazy-import block.
- Verify post-deploy that (a) the compositor's mapped file list no longer includes `libtorch*`, (b) RSS stabilizes in the 1.5–2 GB range instead of climbing to 6+, (c) `speak-react` still produces audible output at parity latency.

**Owner:** next alpha session.

## State of the post-epic audit

With this finding published, the audit closes:

- Phase 1 (completion verification) — shipped with PR #749.
- Phase 2 (correctness + invariants) — 4 of 6 follow-ups fixed in PR #749; 2 deferred.
- Phase 3 (robustness + ALPHA-FINDING-1) — **this document**. Root cause confirmed; fix deferred to a dedicated PR because the wire between daimonion and compositor is cross-service work.
- Phase 4 (edge cases) — 10 tests shipped in PR #749.
- Phase 5 (dead code + missed opportunities) — report shipped in PR #749; five follow-up tickets filed.
- Phase 6 (retirement handoff) — `docs/superpowers/handoff/2026-04-13-alpha-post-epic-audit-retirement.md` shipped.

The operator's two live asks — four-quadrant default layout and reverie-inside-Logos — are resolved and live-verified. The remaining six follow-up tickets from the Phase 5 report plus this ALPHA-FINDING-1 ticket form the inherited backlog for the next alpha session.
