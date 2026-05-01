# P-9 Mutation Nightly — Triage Policy

**Status:** Normative for the targets enumerated in §1.
**cc-task:** `p9-mutation-nightly` (WSJF 4.5, closed 2026-05-01).
**Workflow:** `.github/workflows/p9-mutation-nightly.yml`.
**Source:** `~/.cache/hapax/relay/research/2026-04-26-absence-bugs-synthesis-for-beta.md` §92.

This document governs the bounded mutation-testing pass that runs at 03:00 UTC daily against high-leverage governance modules. It exists so the survivor counts the workflow ntfy's are interpretable — what counts as "expected", what counts as "regression", and what to do about either.

## 1. Target packages

The first cycle scope is intentionally narrow:

| Package | LOC | Modules | Tests |
|---|---|---|---|
| `agents/refused_lifecycle/` | ~1.3k | 9 | `tests/agents/refused_lifecycle/` |
| `agents/publication_bus/` | ~4.5k | 25 | `tests/agents/publication_bus/` |

Rationale for selection:

- **Both are governance-load-bearing.** `refused_lifecycle` runs the constitutional-watcher daemons that probe whether refusal-briefs can be lifted. `publication_bus` is the single keystone publisher abstraction (PUB-P0-B per V5 weave §2.1). Bugs in either propagate to refusal correctness and publication rights — exactly the kind of code where "tests pass" should mean more than "lines covered".
- **Both have substantive existing test suites.** Mutation testing only produces signal when the target has tests for mutmut to challenge. Modules with stub-only or smoke-only tests trivially pass mutation tests because there are no assertions to defeat.
- **Both are bounded.** mutmut runtime scales as O(mutations × test_runtime). Combined ~5.8k LOC fits inside a 90-min CI budget; `shared/` (~109k LOC) does not.

`shared/` is deliberately **out of scope** for the first rollout. Re-evaluate after the first month of survivor-trend data lands. If targeting `shared/` becomes necessary, split into per-subpackage parallel jobs rather than running the whole tree in one job.

## 2. Failure thresholds

The workflow runs **continue-on-error: true** and ntfy's the survivor count rather than failing the build. This is intentional:

- The first cycle has no baseline. Any survivor count above zero is informational, not actionable, until the operator decides what's tolerable.
- Mutation testing produces some unavoidable survivors (e.g., logging-only branches, `__repr__` formatting, performance hot-paths where a faster but still-correct mutation is allowed). Those are **expected survivors**, not bugs.
- Threshold-gating belongs in a follow-up PR after the first month of trend data establishes a defensible baseline.

The phase-2 follow-up (deferred) should:

1. Pin the per-target baseline survivor count (`refused_lifecycle: N1`, `publication_bus: N2`) in this doc.
2. Flip the workflow to fail when `survivors > baseline + tolerance`. Suggested tolerance: `max(2, ceil(baseline * 0.10))`.
3. Annotate each expected-survivor mutation with a `# pragma: no mutate` comment in the source so the baseline drops to "reviewed expected" rather than "untriaged".

## 3. Triage steps when a survivor count rises

When the ntfy lands with `total > prior_run`, follow this sequence:

1. **Open the artifact.** Download `p9-mutation-nightly-reports` from the workflow run. The HTML report (`html/index.html`) lists every mutation by file + line + status, with the source diff.

2. **Bucket each new survivor into one of three categories:**

   - **Real test gap.** The mutation changed observable behavior but no test caught it. Action: write a focused test that fails on the mutation. Re-run the workflow manually (`workflow_dispatch`) to verify the test now kills the mutant.

   - **Equivalent mutation.** The mutation is semantically equivalent to the original (e.g., `range(0, n)` ↔ `range(n)`). Action: add `# pragma: no mutate` to the source line, or move the mutation to a `# noqa` block. Document the rationale in the commit message.

   - **Acceptable variance.** The mutation changes behavior in a way that's not worth testing (logging text, debug-only branches, performance-sensitive paths where multiple correct implementations exist). Action: same as equivalent — annotate with `# pragma: no mutate` + commit-message rationale.

3. **Commit the triage in a focused PR.** Tag with `mutation-nightly-triage` so the history is greppable. PR description should include:
   - The workflow run URL where the survivors first appeared.
   - One-line classification per survivor.
   - The new survivor count after triage.

4. **Update §2 baseline.** Once the new count is the new normal, bump the baseline in this doc (when phase-2 threshold-gating ships).

## 4. Local invocation

The workflow installs `mutmut>=3.2,<4.0`. To reproduce locally:

```bash
uv pip install "mutmut>=3.2,<4.0"
LITELLM_BASE_URL=http://0.0.0.0:1 \
QDRANT_URL=http://0.0.0.0:1 \
OLLAMA_HOST=http://0.0.0.0:1 \
OTEL_SDK_DISABLED=true \
LANGFUSE_HOST=http://0.0.0.0:1 \
uv run mutmut run \
  --paths-to-mutate agents/refused_lifecycle \
  --runner "uv run pytest -x -q tests/agents/refused_lifecycle/"

uv run mutmut results
uv run mutmut html  # → html/index.html
```

For a single mutation's diff:

```bash
uv run mutmut show <id>
```

For a single mutation's test run (debug):

```bash
uv run mutmut apply <id>      # apply the mutation to source
uv run pytest tests/...       # run tests against mutated source
git checkout -- <file>        # revert
```

## 5. Why mutmut

`mutmut` is the Python-ecosystem standard for offline mutation testing. Alternatives considered:

- **cosmic-ray** — broader operator coverage but markedly slower; the LOC-runtime tradeoff doesn't hold for nightly cadence.
- **mutpy** — older, less maintained.
- **CI-integrated mutation services (e.g., Stryker for JS)** — no Python equivalent in our stack.

The choice can be revisited if the cycle reveals mutmut's coverage is insufficient for the governance load-bearing modules; for now its operator catalogue (arithmetic, comparison, boundary, conditional) is well-aligned with the categories of bug that generate-and-run-with-incomplete-tests would miss.

## 6. Cross-references

- Workflow: `.github/workflows/p9-mutation-nightly.yml`
- Closed cc-task vault note: `~/Documents/Personal/20-projects/hapax-cc-tasks/closed/p9-mutation-nightly.md`
- Earlier design context (mutation testing as a generated-test quality gate): `docs/plans/2026-03-12-self-improving-systems-design.md` §"Quality gate"
- Sibling nightly workflow pattern: `.github/workflows/homage-vr-nightly.yml`
