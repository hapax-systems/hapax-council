# Capability envelope: declared imports, default off

`shared/capability_envelope` runs a harness (Claude Code, Codex, agy, grok, kimi, Vibe, opencode, Muse) so that
nothing reaches the job unless its declaration names it. That rules out:
- instruction-file walk-up (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, …);
- user or project memory;
- MCP autoload;
- project hooks and settings;
- the host environment.

Review, panel, witness and benchmark runs use it so that "independent" families really are independent. Fabric
capability jobs use the same declaration.

Design: `frame/capability-dispatch-fabric-placement-20260925/DESIGN.md` v1.3 §3.2a and canary C10.

## Use

```python
from pathlib import Path
from shared.capability_envelope import EnvelopeDeclaration, UnitSection, render

decl = EnvelopeDeclaration(
    harness="claude",
    argv=("/usr/bin/true",),                # synthetic source-render example; no provider
    billing_surface="api",                 # declaration only; never spend authority
    unit=UnitSection(memory_high=67108864, memory_max=134217728,
                     memory_swap_max=0, runtime_max_sec=60),
)
rendered = render(decl, run_root=Path("fresh-run"))  # must not exist: a job home is never reused
record = rendered.facts                          # declaration and argv sha256, masked paths
```

This first slice of #5055 carries the existing declaration's unit/channel fields and the T2 renderer.
Limits are mandatory and validated here; T2 alone does not enforce the outer unit's memory or time ceilings.
`channels` names read-only mounts or Unix sockets under `/channels/<name>`. Network endpoints refuse until
an admitted egress gate exists. Subscription invocations refuse until onboarding/admission qualifies their
complete argv/config/env/credential shape; changing the declaration to API is not a repair or spend approval.

## What the carrier does (T2, bubblewrap), and how to recheck each claim

Each claim below names the test that witnesses it, and every cell carries the whole command — no shorthand to
expand. `HAPAX_ENVELOPE_REQUIRE_BWRAP=1` makes a sandbox that cannot be built fail the test instead of skipping it.

| claim | recheck |
|---|---|
| **Allowlist root.** `/usr`, the `/bin`-style links and a short list of `/etc` files, all read-only. The host root and the operator's home are never bound whole | `HAPAX_ENVELOPE_REQUIRE_BWRAP=1 uv run pytest tests/capability_envelope/test_envelope.py -q -k "never_exposes_root or ancestor_agents_md"` |
| **A fresh read-only job home** at `/home/job` under a create-once run root. It holds only generated config (Claude: `settings.json` with the declared hooks; `.claude.json` with the declared MCP servers), declared files and credentials | `HAPAX_ENVELOPE_REQUIRE_BWRAP=1 uv run pytest tests/capability_envelope/test_envelope.py -q -k "fresh_per_run or hook_matcher or declared_home_file"` |
| **Credentials** are file binds: read-only unless `writable=True` (for refresh by rename). Their values never appear in the argv or the run facts | `HAPAX_ENVELOPE_REQUIRE_BWRAP=1 uv run pytest tests/capability_envelope/test_envelope.py -q -k credential` |
| **The checkout** is at `/work`, read-only unless `workdir_writable`. Every name in `MASKED_NAMES` is covered by an empty read-only file, or an empty read-only tmpfs for a directory, unless declared — wherever the walk meets it, `.git` included. A masked-named symlink is covered at its **resolved target**, wherever that target lives, never at the link itself (bwrap refuses to mount over a symlink destination); a symlink that leaves the checkout is refused | `HAPAX_ENVELOPE_REQUIRE_BWRAP=1 uv run pytest tests/capability_envelope/test_envelope.py -q -k "masked or symlink or workdir or dot_git"` |
| **The environment** is cleared (`--clearenv`), then given a fixed base, the harness config variables and the declared `env` | `HAPAX_ENVELOPE_REQUIRE_BWRAP=1 uv run pytest tests/capability_envelope/test_envelope.py -q -k "environment or declared_env"` |
| **No undeclared import reaches the job**, and a declared governance hook still fires. The control run shows the same probe reaches every sentinel without the envelope | `HAPAX_ENVELOPE_REQUIRE_BWRAP=1 uv run pytest tests/capability_envelope/test_envelope.py -q -k "undeclared or control or governance_hook"` |

## Refusals (each narrows; the message names the next action)

- A missing unit section; incomplete, non-integer or out-of-range limits; `memory_high > memory_max`;
  an OOM policy other than `kill` or restart policy other than `no`.
- Subscription execution without qualification of the complete invocation, including `--bare`, unknown flags,
  shells and otherwise innocuous executable names. A short flag blacklist cannot establish billing safety.
- Duplicate channels, missing source bindings, endpoint fields on mount/Unix channels, non-socket Unix sources,
  whole-root/home sources, or network endpoints without an admitted egress gate.
- Overrides of `HOME`, XDG config/data/state/cache roots or the harness's config environment variables.
- An `env` key that looks like a credential. Env values appear in the carrier argv, so use a `CredentialBind` file.
- Hooks or MCP servers for a harness whose config format the renderer does not yet render (today, anything but
  Claude).
- A checkout symlink with an instruction or config name that points outside the checkout. Inside the job it could
  resolve to any file the job can see, such as a bound credential.
- A run root that already exists.
- **At run time:** `EnvelopeCarrierError` when bubblewrap is missing or fails. A consumer maps it to an outage, never
  to an unenveloped run.

Recheck: `HAPAX_ENVELOPE_REQUIRE_BWRAP=1 uv run pytest tests/capability_envelope/test_envelope.py -q -k "refused or carrier"`.

## Not covered here

- **Network egress:** T2 renders a private network namespace. Admitted network egress awaits the fabric's R9 gate.
- **Outer-unit enforcement, T1/T3 rendering and carrier conformance:** subsequent slices of #5055, carried by
  `capability-fabric-envelope-carrier-split-carry-20261011`. Exact generated-home inventory, rendered channel
  comparison, launch binding and the full mutation harness remain in that stack. This slice is source only;
  no runtime containment, independent acceptance or activation is claimed.

## Tests

```bash
uv run python tests/capability_envelope/run_source_checks.py              # source only; C10 explicitly skipped
uv run pytest tests/capability_envelope -q                                   # skips where bwrap cannot run
HAPAX_ENVELOPE_REQUIRE_BWRAP=1 uv run pytest tests/capability_envelope -q    # fails instead of skipping
```

The runtime tests need bubblewrap with unprivileged user namespaces. The required CI job
`capability-envelope-containment` (in `.github/workflows/ci.yml`, part of `all-green`) does three things:
- installs bubblewrap;
- lifts the runner's AppArmor user-namespace restriction;
- runs the suite with `HAPAX_ENVELOPE_REQUIRE_BWRAP=1`.

So CI cannot pass by skipping. `tests/ci/test_capability_envelope_ci.py` pins that job.
