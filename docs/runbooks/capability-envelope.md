# Capability envelope: declared imports, default off

`shared/capability_envelope` renders one declared execution surface into T1/T2/T3 carriers.
The existing T2 executor remains the only implemented execution path. Subscription shapes
without complete billing qualification refuse; API rendering does not authorize spend.
The scrub carrier excludes undeclared imports at the documented filesystem boundaries:
- instruction-file walk-up (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, …);
- user or project memory;
- MCP autoload;
- project hooks and settings;
- the host environment.

Review, panel, witness and benchmark runs use it so that "independent" families really are independent. Fabric
capability jobs use the same declaration.

Design: `frame/capability-dispatch-fabric-placement-20260925/DESIGN.md` v1.3 §3.2a and canary C10.

## Use

The following is a source-rendering example using a synthetic command and an explicit
API billing declaration. It performs no launch or provider call. Actual subscription
harness commands remain held until the existing onboarding owner supplies a qualification
binding the complete argv/config/env/credential shape through execution admission.
Neither an API label nor a rendered artifact authorizes spend.

```python
from pathlib import Path
from shared.capability_envelope import EnvelopeDeclaration, UnitSection, render

decl = EnvelopeDeclaration(
    harness="claude",
    argv=("/usr/bin/true",),
    billing_surface="api",  # Explicit synthetic fixture, not a billing fallback.
    unit=UnitSection(memory_high=536870912, memory_max=1073741824,
                     memory_swap_max=0, runtime_max_sec=600),
)
rendered = render(decl, run_root=Path("fresh-run"), carrier="t1")
record = rendered.facts  # Source rendering only; fresh-run must not exist.
```

## What the carrier does (T2, bubblewrap), and how to recheck each claim

Each claim below names the test that witnesses it, and every cell carries the whole command — no shorthand to
expand. `HAPAX_ENVELOPE_REQUIRE_BWRAP=1` makes a sandbox that cannot be built fail the test instead of skipping it.

| claim | recheck |
|---|---|
| **Allowlist root.** `/usr`, the `/bin`-style links and a short list of `/etc` files, all read-only. The host root and the operator's home are never bound whole | `HAPAX_ENVELOPE_REQUIRE_BWRAP=1 uv run pytest tests/capability_envelope/test_envelope.py -q -k "never_exposes_root or ancestor_agents_md"` |
| **A fresh job home** at `/home/job` under a create-once run root. It holds only generated config (Claude: `settings.json` with the declared hooks; `.claude.json` with the declared MCP servers), declared files and credentials | `HAPAX_ENVELOPE_REQUIRE_BWRAP=1 uv run pytest tests/capability_envelope/test_envelope.py -q -k "fresh_per_run or hook_matcher or declared_home_file"` |
| **Credentials** are file binds: read-only unless `writable=True` (for refresh by rename). Their values never appear in the argv or the run facts | `HAPAX_ENVELOPE_REQUIRE_BWRAP=1 uv run pytest tests/capability_envelope/test_envelope.py -q -k credential` |
| **The checkout** is at `/work`, read-only unless `workdir_writable`. Every name in `MASKED_NAMES` is covered by an empty read-only file, or an empty tmpfs for a directory, unless declared — wherever the walk meets it, `.git` included. A masked-named symlink is covered at its **resolved target**, wherever that target lives, never at the link itself (bwrap refuses to mount over a symlink destination); a symlink that leaves the checkout is refused | `HAPAX_ENVELOPE_REQUIRE_BWRAP=1 uv run pytest tests/capability_envelope/test_envelope.py -q -k "masked or symlink or workdir or dot_git"` |
| **The environment** is cleared (`--clearenv`), then given a fixed base, the harness config variables and the declared `env` | `HAPAX_ENVELOPE_REQUIRE_BWRAP=1 uv run pytest tests/capability_envelope/test_envelope.py -q -k "environment or declared_env"` |
| **No undeclared import reaches the job**, and a declared governance hook still fires. The control run shows the same probe reaches every sentinel without the envelope | `HAPAX_ENVELOPE_REQUIRE_BWRAP=1 uv run pytest tests/capability_envelope/test_envelope.py -q -k "undeclared or control or governance_hook"` |

## Refusals (each narrows; the message names the next action)

- Any unqualified subscription invocation, including `--bare`, unknown flags, configuration overrides and
  shell wrappers. Complete execution-shape qualification remains with the existing harness onboarding owner;
  changing the billing label is not a remedy or spend authorization.
- Missing/nonpositive unit bounds, MemoryHigh above MemoryMax, or a restart policy other than `no`.
- Duplicate/missing channel bindings, a Unix channel whose source is not a socket, whole-root/home channels,
  network channels without an admitted egress gate, or reserved config environment overrides.
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

- **Network egress:** private network namespaces; network endpoint declarations refuse until an admitted
  egress gate exists. Declared Unix socket endpoints are explicit read-only mounts.
- **Memory and time ceilings:** the declaration must supply finite unit limits. T1 renders them as
  `systemd-run --user` properties; T3 returns the same required outer-unit properties alongside a rootless
  OCI 1.2.1 spec. Bare T2 carries these facts but does not enforce cgroup limits.
- **Activation:** this source implementation executes only T2. T1/T3 launch refuses before consuming
  the dispatch message until independent acceptance and governed executor admission. ID enrolment,
  image qualification, recursive read-only support and runtime C1–C10 remain separate holds.
- **Conformance:** all required isolation flags/namespaces must occur exactly once; additions, removals,
  host namespace paths and contradictory settings refuse. Generated home contents must match the exact
  generated files and declared empty mountpoints, including directories. No-follow descriptor reads
  reject symlinks, changed contents, new entries and concurrent replacements during readback. This
  observes render/pre-dispatch state; it does not freeze host files after return. The launcher must retain
  exclusive bundle custody through activation; this source check is not a live containment witness.

## Tests

```bash
uv run pytest tests/capability_envelope -q                                   # skips where bwrap cannot run
HAPAX_ENVELOPE_REQUIRE_BWRAP=1 uv run pytest tests/capability_envelope -q    # fails instead of skipping
```

The runtime tests need bubblewrap with unprivileged user namespaces. The required CI job
`capability-envelope-containment` (in `.github/workflows/ci.yml`, part of `all-green`) does three things:
- installs bubblewrap;
- lifts the runner's AppArmor user-namespace restriction;
- runs the suite with `HAPAX_ENVELOPE_REQUIRE_BWRAP=1`.

So CI cannot pass by skipping. `tests/ci/test_capability_envelope_ci.py` pins that job.
