# LRR Phase 9 integration pre-flight — chat_queues, chat_signals, inference_budget

**Date:** 2026-04-14
**Author:** delta (beta role)
**Scope:** Reviews the three LRR Phase 9 modules that shipped
library-only in PR #798 and will be wired into the director
loop hot path when Phase 8 integration lands. Asks: are there
perf or correctness gotchas that should be caught before the
integration PR goes in flight?
**Register:** scientific, neutral
**Status:** investigation only — four concrete fix-candidates,
each one-function-scope. No code ships from this drop

## Headline

**Four fix-candidates.**

1. **`ResearchRelevantQueue.push` calls the embedder
   synchronously** (`chat_queues.py:172`). Under a real
   embedder (production plan: `nomic-embed-text` via the
   Ollama CPU pipeline at ~10–20 ms/call), pushing at
   100 chat msgs/sec consumes 1–2 seconds of CPU per
   wall-clock second — the queue can't keep up. Becomes a
   live chokepoint under any meaningful chat volume. **Fix
   cost: M** — batch push or async embedding worker.
2. **`StructuralSignalQueue.push` calls `prune()` on every
   push** (`chat_queues.py:238`). `prune()` rebuilds the
   list via list comprehension — O(n) per call. Under
   sustained high chat volume this is O(n²) amortized; at
   1 000 msgs/sec with a 60 s window (~60 k messages), each
   push costs ~60 k comparisons. Not a problem at typical
   Twitch volumes (10–100 msg/s) but a viral-stream burst
   could surface it. **Fix cost: S** — use a `deque` with
   `popleft`-while-stale instead of rebuilding.
3. **`chat_signals._shannon_entropy` uses Python's built-in
   `hash()` on tuples** (`chat_signals.py:120`). Python
   enables hash randomization by default — the seed
   differs per interpreter process. **Two runs of the same
   data produce different entropy values.** For a stimmung
   consumer reading this across process restarts, the
   non-determinism is a correctness bug disguised as
   noise. **Fix cost: S** — replace `hash(tuple(...))`
   with `hashlib.blake2s(bytes_of(vec), digest_size=1)`.
4. **`InferenceBudgetAllocator.reserve` invokes `warn_fn`
   inside the lock** (`inference_budget.py:171-177`). If
   `warn_fn` does I/O (HTTP ntfy, log write, metric
   publish), it blocks every concurrent `reserve`, every
   `remaining` query, and every `snapshot` call until the
   I/O returns. Fires only once per interval — rare but
   high-impact when it does. **Fix cost: S** — set the
   `warned_this_interval` flag inside the lock, release,
   then call `warn_fn` outside.

Plus three minor-grade nits documented in § 5 that are
hygiene, not perf.

## 1. `ResearchRelevantQueue` — synchronous embedding

```python
# chat_queues.py:166-182 (abbreviated)
def push(self, message: ChatMessage, *, now: float | None = None) -> None:
    if message.classification.tier != ChatTier.T5_RESEARCH_RELEVANT:
        raise ValueError(...)
    if message.embedding is None:
        embedding = tuple(self.embedder(message.text))   # ← synchronous
        message = ChatMessage(..., embedding=embedding)
    self._items.append(message)
    if len(self._items) > self.capacity:
        self._evict_lowest(now=now or time.time())
```

**Why this matters:**

- The production embedder (per module docstring §2) is
  `nomic-embed-text` via the existing Ollama CPU pipeline.
  Nomic-embed is a 137 M param model running on CPU —
  typical latency 10–20 ms/call.
- Chat volume scenarios:
  - **Idle stream (1–5 msg/s, ~10 % T5):** ≤ 1 push/s, 20 ms
    of work/sec, fine.
  - **Active stream (10–30 msg/s, ~10 % T5):** 1–3 pushes/s,
    20–60 ms/sec. Fine.
  - **Viral stream (100–300 msg/s, ~10 % T5):** 10–30
    pushes/s, 200–600 ms/sec. Becomes noticeable.
  - **Chat raid (1 000 msg/s, ~15 % T5 because injection
    patterns bloom):** 150 pushes/s, **3 000 ms/sec = queue
    cannot keep up**, pushes block the chat feed thread.

**Fix options (ordered by invasiveness):**

- **Option A (minimal change)**: accept a batch push API —
  `push_batch(messages)` embeds all texts in a single
  Ollama call. Ollama's embeddings endpoint accepts
  `prompt: [str, str, …]` and runs them as a batch. For
  a batch of 50, latency is ~100–300 ms total instead of
  50 × 20 ms = 1 000 ms serialized. Worthwhile for chat
  bursts.
- **Option B (async worker)**: push stores the raw
  message immediately with `embedding=None`, an internal
  worker thread pulls unembedded messages and computes
  their embeddings in the background. Eviction uses only
  already-embedded messages, with a configurable floor on
  embedding delay before a message becomes eligible for
  eviction consideration.
- **Option C (pre-classify embedding)**: change the
  contract so the classifier produces the embedding as
  part of its T5 decision. The classifier already has
  the text; embedding once at the classifier is the same
  cost as embedding at the queue, but removes the queue's
  push-time branch entirely. Cleanest but requires
  updating `chat_classifier.py` and its callers.

**Recommendation:** Option A for the Phase 8 integration
(minimal diff), consider Option C for Phase 9 v2 which
already plans to touch the classifier for the small-model
tier.

## 2. `StructuralSignalQueue` — O(n²) prune pattern

```python
# chat_queues.py:233-243
def push(self, message: ChatMessage) -> None:
    if message.classification.tier != ChatTier.T4_STRUCTURAL_SIGNAL:
        raise ValueError(...)
    self.prune(now=message.ts)        # ← O(n) every push
    self._items.append(message)

def prune(self, *, now: float) -> None:
    cutoff = now - self.window_seconds
    self._items = [m for m in self._items if m.ts >= cutoff]
```

**Why this matters:**

Current shape: each push rebuilds the list. At N items in
the window, each push is O(N). Over K pushes, total work
is O(K × N). If K grows with N (which it does — sustained
chat rate keeps the window full), total work is O(N²).

Numbers:

| chat rate | window size | work / push | work / sec |
|---|---|---|---|
| 10 msg/s | ~600 | 600 cmps | 6 000 cmps/s |
| 100 msg/s | ~6 000 | 6 000 cmps | 600 000 cmps/s |
| 1 000 msg/s | ~60 000 | 60 000 cmps | 60 M cmps/s |

60 M integer comparisons/sec is fast in C, meaningful in
Python. At 1 000 msg/s, the prune alone chews ~400 ms of
CPU time per wall-clock second (Python list comprehension
runs ~150 M ops/sec on a modern core). Close to saturating
one core on the viral-stream path.

**Fix (one-function scope):**

```python
from collections import deque

@dataclass
class StructuralSignalQueue:
    window_seconds: float = 60.0
    _items: deque[ChatMessage] = field(default_factory=deque)

    def push(self, message: ChatMessage) -> None:
        if message.classification.tier != ChatTier.T4_STRUCTURAL_SIGNAL:
            raise ValueError(...)
        cutoff = message.ts - self.window_seconds
        while self._items and self._items[0].ts < cutoff:
            self._items.popleft()
        self._items.append(message)

    def prune(self, *, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._items and self._items[0].ts < cutoff:
            self._items.popleft()
```

`deque.popleft` is O(1); each stale message is evicted
exactly once across all pushes. Total work drops to O(N +
K), not O(N × K).

**Only matters under high chat volume.** If Bundle 9's
typical operating point is ≤ 30 msg/s, this is
premature optimization. Flag for alpha to decide — if the
Phase 9 target is "cope with a chat raid," ship the fix;
if it's "typical streaming chat," don't.

## 3. `chat_signals._shannon_entropy` — non-deterministic hash

```python
# chat_signals.py:108-131 (abbreviated)
def _shannon_entropy(vectors: list[tuple[float, ...]]) -> float:
    if not vectors:
        return 0.0
    buckets: dict[int, int] = {}
    for vec in vectors:
        idx = hash(tuple(round(v, 4) for v in vec)) % 8   # ← seed-randomized
        buckets[idx] = buckets.get(idx, 0) + 1
    total = sum(buckets.values())
    if total == 0:
        return 0.0
    entropy = 0.0
    for count in buckets.values():
        if count == 0:
            continue
        p = count / total
        entropy -= p * math.log2(p)
    return entropy
```

**The bug:** Python's built-in `hash()` on tuples uses a
per-process random seed (`PYTHONHASHSEED`), enabled by
default since Python 3.3 for DoS resistance. Two
consecutive runs of the compositor — after a rebuild,
after a restart, after `hapax-rebuild-services` cycles —
produce **different bucket assignments** for the same
vectors → different Shannon entropy values.

**Downstream effect:** `chat_entropy` flows into
`audience_engagement` which flows into stimmung.
`audience_engagement` is used in Bundle 9 §2.5's formula
and reads into per-cycle stream reactivity. A stimmung
dimension that silently drifts across process restarts
isn't noise — it's a mis-attribution source that any
downstream correlation analysis will trip on.

**Fix:**

```python
import hashlib
# ...
for vec in vectors:
    # Deterministic byte-level hash: round to 4 decimals, encode as
    # fixed-width bytes, blake2s digest, mod 8.
    key = bytes.fromhex("".join(f"{round(v, 4):+.4f}".encode().hex() for v in vec))
    idx = hashlib.blake2s(key, digest_size=1).digest()[0] % 8
    buckets[idx] = buckets.get(idx, 0) + 1
```

Or use a simpler deterministic path: quantize each float
to an int bucket (e.g. `int(v * 1000)`), stringify, hash
with `hashlib`.

**Test impact:** any existing test that asserts a
specific entropy value was passing by accident — the
PYTHONHASHSEED is stable within a single test run. The
fix will produce a different (stable) value and tests
will need new fixture values.

## 4. `InferenceBudgetAllocator.reserve` — `warn_fn` inside lock

```python
# inference_budget.py:152-177 (abbreviated)
def reserve(self, tier: InferenceTier, tokens: int) -> None:
    if tokens < 0:
        raise ValueError(...)
    with self._lock:
        state = self._tiers[tier]
        self._maybe_refresh(state)
        if tokens > state.remaining:
            raise BudgetExhausted(...)
        state.tokens_consumed += tokens
        if (
            not state.warned_this_interval
            and state.consumed_fraction >= state.config.warn_fraction
            and self._warn_fn is not None
        ):
            state.warned_this_interval = True
            self._warn_fn(tier, state.consumed_fraction)   # ← inside lock
```

**Problem:** the warn callback fires inside the lock. If
`warn_fn` does I/O (HTTP POST to ntfy, log write, Prometheus
metric publish, Langfuse trace), every other concurrent
`reserve` / `remaining` / `consumed_fraction` / `snapshot`
call blocks until the I/O returns.

The warn fires **once per tier per refresh interval** — so
this is a rare, once-per-hour event per tier. When it
fires, it's probably at a moment of high concurrency
(the tier is busy enough to hit 80 %, which means many
callers are trying to reserve). Timing is adversarial.

**Fix:**

```python
def reserve(self, tier: InferenceTier, tokens: int) -> None:
    if tokens < 0:
        raise ValueError(...)
    warn_payload: tuple[InferenceTier, float] | None = None
    with self._lock:
        state = self._tiers[tier]
        self._maybe_refresh(state)
        if tokens > state.remaining:
            raise BudgetExhausted(...)
        state.tokens_consumed += tokens
        if (
            not state.warned_this_interval
            and state.consumed_fraction >= state.config.warn_fraction
            and self._warn_fn is not None
        ):
            state.warned_this_interval = True
            warn_payload = (tier, state.consumed_fraction)
    if warn_payload is not None:
        self._warn_fn(*warn_payload)
```

Lock is released before the callback. Same semantics, no
blocking. Same fix pattern applies to any future callback
hook added to this class.

## 5. Minor hygiene nits (not fix-ship-worthy individually)

- **`chat_signals._count_unique_author_hashes` re-hashes
  handles** (`chat_signals.py:239`). ChatMessage already
  carries the raw handle; the signals aggregator hashes it
  anew on every `compute_signals` call. `chat_attack_log`
  separately hashes the same handles for its own rate-
  limit dict. If `ChatMessage` carried a pre-computed
  `author_hash: str` field, both paths would share the
  hash and neither would need to repeat it. Cost savings
  trivial, but the duplication is a smell.
- **`chat_signals.write_shm` calls `os.fsync`** on a tmpfs
  file (`chat_signals.py:227`). `fsync` on tmpfs is a
  no-op kernel-side but costs a syscall. `os.replace` on
  tmpfs is already atomic per inode; no fsync is needed.
  Remove the `fsync` call.
- **`chat_signals.write_shm` also calls `mkdir(parents=True,
  exist_ok=True)` on every write** (line 216). Same pattern
  I flagged in `chat_attack_log._append` (drop #11). Move
  to `__init__` — one syscall instead of one-per-write.

Bundle these three into one housekeeping commit when
alpha next touches the files.

## 6. What's not in scope for this drop

- The `chat_attack_log` minor nits already covered in the
  audio path baseline review (persistent file handle,
  mkdir move). Unchanged.
- The `chat_classifier` review from earlier — all checks
  pass, no concerns.
- Phase 9 item 6 (close handoff doc) — pure documentation,
  no code.
- Wire-up questions that depend on Phase 8 design (where
  does `InferenceBudgetAllocator` get constructed? which
  tier does `director_loop._call_activity_llm` use? how
  does the `warn_fn` route through ntfy vs Prometheus?).
  Those are design calls, not perf calls.

## 7. Follow-ups

Ordered by ratio (severity × ease):

1. **Finding 4** (warn_fn inside lock) — S effort,
   prevents adversarial blocking. One-line fix.
2. **Finding 3** (non-deterministic entropy) — S effort,
   correctness fix. Replaces one line + test fixtures.
3. **Finding 2** (deque-based StructuralSignalQueue) — S
   effort, only matters at high chat volume. Ship if
   Phase 9's target is "robust under chat raid."
4. **Finding 1** (async/batch embedding) — M effort,
   defer to Phase 8 wire-up PR so the right caller
   pattern is chosen with the rest of the integration.
5. **Minor hygiene nits § 5** — bundle into one
   housekeeping commit when alpha touches the files.

All of these are **pre-emptive**. The modules are
library-only right now and none of the findings are
live bugs. Shipping them before the Phase 8 integration
lands saves alpha debugging time — especially finding 3,
which would show up as "mysterious stimmung drift" and
be a nightmare to root-cause after the fact.

## 8. References

- `agents/studio_compositor/chat_queues.py:166-210` —
  ResearchRelevantQueue push + scoring
- `agents/studio_compositor/chat_queues.py:233-247` —
  StructuralSignalQueue prune + window
- `agents/studio_compositor/chat_signals.py:108-131` —
  `_shannon_entropy`
- `agents/studio_compositor/chat_signals.py:214-233` —
  `write_shm` fsync + mkdir
- `agents/studio_compositor/chat_signals.py:236-240` —
  `_count_unique_author_hashes`
- `shared/inference_budget.py:152-177` — `reserve` +
  warn_fn path
- Alpha retirement handoff (PR #800,
  `docs/superpowers/handoff/2026-04-14-alpha-continuation-retirement.md`)
  for the Phase 8 integration scope and deferrals
