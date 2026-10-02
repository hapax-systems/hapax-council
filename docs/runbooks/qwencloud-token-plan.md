# Token Plan listed-client support

Task `qwencloud-entitlement-activation-20260914`, CASE-CAPACITY-ROUTING-001;
parent `frame/coordination-20260904/FUGU-EFFECTIVE-USE-20260911.md`, current
2026-10-02 continuation. Source stays in held draft #4977. Independent review,
acceptance, installed readback and applicable live admission remain separate.
The task-id argument records provenance; it is not admission.

## Binding and account evidence

The historical `scripts/hapax-qwencloud-claude` filename launches OpenCode.
Alibaba's [listed-client guide](https://www.alibabacloud.com/help/en/model-studio/opencode)
pins `@ai-sdk/anthropic` to Singapore's
`https://token-plan.ap-southeast-1.maas.aliyuncs.com/apps/anthropic/v1`.
The explicit Personal catalogue is pinned in `MODELS`; `auto` is excluded.
The [Personal catalogue](https://www.alibabacloud.com/help/en/model-studio/token-plan-personal-overview)
and guide were rechecked 2026-10-02. No model-list HTTP probe is used.

Current credential: FileStore `alibaba-cloud/plan-api-key`. `qwencloud/apikey`
remains an explicit legacy smoke selector, never a useful-work retry or another
inferred subscription. The last account dashboard (2026-09-30) showed Personal
Token Plan Pro, Singapore, and term end `2026-10-03 11:00`. Its timezone,
renewal, current Credits and provider-served identity remain unobserved.
Client tokens do not measure Credits. No backend/LiteLLM route, direct model
HTTP call, polling, PAYG fallback or top-up is part of this binding.

BACKED source prior art: closed-unmerged [#4630](https://github.com/hapax-systems/hapax-council/pull/4630),
head `7e01a658541d949fef5852658c8ec47dab0aa233`, supplied the isolated launcher
and runtime credential pattern. Historical smoke success is not current
account evidence or useful-work acceptance.

## Source interface and measured live blocker

`--check --task TASK` is keyless. Existing `--smoke` produces a fixed synthetic
answer only and still requires external admission. The useful interface is:

```bash
uv run --no-sync python scripts/hapax-qwencloud-claude \
  --task qwencloud-entitlement-activation-20260914 \
  --negative-tests public-source.json --output cases.json --timeout 600
```

**Useful execution currently refuses before credential retrieval.** Native
OpenCode 1.17.4 made three loopback requests in the offline HTTP-503 fixture,
even with `maxRetries: 0`; its session retry layer owns further attempts.
The single-attempt requirement therefore has no measured supported binding.
`require_single_attempt` refuses until that boundary is repaired and verified;
there is no production bypass option or approved version inferred from a string.
Tests inject a synthetic single-attempt client in process only.

Separately, the installed envelope renderer refuses credential environment
transport because values enter its argv. Its file-bind alternative is
incompatible with this task's memory-only credential contract. Do not rename
the environment key to evade its heuristic, persist the key, bypass the carrier,
or invent `opencode.headless.flash` admission. Repair requires the existing
carrier/interface owner's governed compatible binding. No live useful call is
claimed while either predicate remains.

## Input, instructions and output

Input is a UTF-8 JSON array of 1–6 objects, at most 32,768 bytes total. Each has
exactly `url`, `sha256`, and `text`. URLs identify public Council `shared/`,
`scripts/`, `tests/` or `docs/` files at a full Git commit; the text hash must
match. The submitting admitted caller must verify public provenance against
those URLs: matching self-supplied bytes and hashes alone proves no publication.
The wrapper never follows a URL or reads a workspace recursively.

Useful configuration includes the exact authored global and repository
`AGENTS.md` bodies from the source/release tree in the agent prompt, with a
receipt hash. A standalone copied script lacking those files refuses. This
preserves explicit canonical delivery; it does not prove semantic uptake or
replace the existing instruction-ingestion admission boundary.

The fixed job requests six negative cases: wrong endpoint, wrong model/budget,
unauthorized imports, missing attempted ledger row, partial/empty response,
and invalid artifact. Every case requires input/precondition, refusal,
transport count and persisted evidence. These are support proposals for the
existing direct API and panel-consumer work, never acceptance or adoption.

The client configuration caps output at 8,192 tokens, disables tools, title,
summary and compaction, and uses a finite process group (maximum 600 seconds).
Native offline request capture verified `max_tokens=8192`, zero tools, exact
requested model and canonical instruction bytes. The success fixture made one
request and yielded six validated cases; the failure fixture exposed retries.

Only one completed text answer with exactly the six typed cases can be written.
Empty, truncated, error, malformed, over-budget or secret-bearing answers fail.
The artifact is create-once, mode 0600, file-fsynced and hashed; receipts contain
measurements/hashes, not raw client events. Semantic quality still needs review.
Raw stdout/stderr remain in memory. Client home/XDG state stays in tmpfs and the
whole child group is killed before cleanup. Ambient auth, proxy and config are
not inherited. Endpoint/model escape knobs refuse; failures never select a new
key, model or billing surface.

## Verification

```bash
uv run --no-sync ruff check scripts/hapax-qwencloud-claude tests/scripts/test_hapax_qwencloud_claude.py
bwrap --unshare-net --bind / / --dev /dev --proc /proc \
  uv run --no-sync pytest tests/scripts/test_hapax_qwencloud_claude.py -q
```

Executable fixtures use synthetic credentials. Mutation evidence retains the
unsafe break, red test, exact-byte restoration and green test. Native loopback
fixtures have no provider egress. Durable results and remaining account/use
unknowns belong in the existing entitlement-utilization vault record. Preserve
failed specimens and the predecessor head; no installation or task closure is
implied by passing author tests.
