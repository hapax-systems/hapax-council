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
from shared.capability_envelope import CredentialBind, DeclaredHook, EnvelopeDeclaration, execute, render

decl = EnvelopeDeclaration(
    harness="claude",
    argv=(str(claude_exe), "-p", "--model", model),
    binaries=(claude_package_dir,),
    credentials=(CredentialBind(source=Path.home() / ".claude/.credentials.json",
                                target=".claude/.credentials.json"),),
    hooks=(DeclaredHook(name="gate", event="PreToolUse", script=gate_script),),  # optional
    workdir=checkout,                      # optional; mounted read-only at /work
    declared_work_files=("AGENTS.md",),    # optional; everything else in MASKED_NAMES is covered
    spool=spool_dir,                       # optional; the job's only writable output, at /spool
)
rendered = render(decl, run_root=fresh_dir)    # fresh_dir must not exist: a job home is never reused
result = execute(rendered, stdin=prompt, timeout=600)
record = rendered.facts                          # declaration and argv sha256, masked paths
```

## What the carrier does (T2, bubblewrap), and how to recheck each claim

Each claim below names the test that witnesses it. `R` stands for
`HAPAX_ENVELOPE_REQUIRE_BWRAP=1 uv run pytest tests/capability_envelope/test_envelope.py -q -k`. With that variable
set, a sandbox that cannot be built fails the test instead of skipping it.

| claim | recheck |
|---|---|
| **Allowlist root.** `/usr`, the `/bin`-style links and a short list of `/etc` files, all read-only. The host root and the operator's home are never bound whole | `R "never_exposes_root or ancestor_agents_md"` |
| **A fresh job home** at `/home/job` under a create-once run root. It holds only generated config (Claude: `settings.json` with the declared hooks; `.claude.json` with the declared MCP servers), declared files and credentials | `R "fresh_per_run or hook_matcher or declared_home_file"` |
| **Credentials** are file binds: read-only unless `writable=True` (for refresh by rename). Their values never appear in the argv or the run facts | `R credential` |
| **The checkout** is at `/work`, read-only unless `workdir_writable`. Every name in `MASKED_NAMES` is covered by an empty read-only file, or an empty tmpfs for a directory, unless declared. A symlink with such a name is masked at its in-checkout target; one that leaves the checkout is refused | `R "masked or symlink or workdir"` |
| **The environment** is cleared (`--clearenv`), then given a fixed base, the harness config variables and the declared `env` | `R "environment or declared_env"` |
| **No undeclared import reaches the job**, and a declared governance hook still fires. The control run shows the same probe reaches every sentinel without the envelope | `R "undeclared or control or governance_hook"` |

## Refusals (each narrows; the message names the next action)

- `--bare` without `billing_surface="api"`. Claude's bare mode does not read `CLAUDE_CODE_OAUTH_TOKEN`, so it would
  switch billing implicitly.
- An `env` key that looks like a credential. Env values appear in the carrier argv, so use a `CredentialBind` file.
- Hooks or MCP servers for a harness whose config format the renderer does not yet render (today, anything but
  Claude).
- A checkout symlink with an instruction or config name that points outside the checkout. Inside the job it could
  resolve to any file the job can see, such as a bound credential.
- A run root that already exists.
- **At run time:** `EnvelopeCarrierError` when bubblewrap is missing or fails. A consumer maps it to an outage, never
  to an unenveloped run.

Recheck: `R "refused or carrier"`.

## Audit on a real harness (canary C10)

`shared.capability_envelope.sentinel.OpenWatch` records inotify open events on sentinel files. It needs no privilege,
and it sees opens through bind mounts. What the model says it saw is complementary evidence only.

`scripts/capability-envelope-import-audit` is the rerunnable witness.
- It builds a sentinel world.
- It launches the harness the way its reviewer wrapper does, against a mirror of the home (the operator's own files
  are neither read nor changed), and then again inside the envelope.
- It exits 0 when the enveloped run imported nothing and 1 on a leak.
- Vibe runs only on the Team allowance.

```bash
TMPDIR=/store-fast/tmp uv run python scripts/capability-envelope-import-audit --harness claude --out /tmp/claude.json
```

Last run: 2026-09-25 ~10:50Z on appendix. The reports are in the vault at
`frame/harness-import-scrub-20260925/measure/audit-*.json`.

| harness | baseline launch (origin/main wrapper argv) imported | enveloped |
|---|---|---|
| Claude Code 2.1.281 (`-p`, tools off) | ancestor and checkout `CLAUDE.md`, `CLAUDE.local.md`, `.claude/CLAUDE.md`, user `CLAUDE.md` and rules, a skill, both settings files, user and project hooks **run**, user and project MCP servers **started** | nothing: `clean` |
| Mistral Vibe (the `hapax-vibe-reviewer` argv) | `~/.vibe/AGENTS.md`, and it reached the model | nothing: `clean` |
| Meta Muse 1.4.0 (the `hapax-muse-reviewer` argv) | `~/.config/muse/AGENTS.md`, and it reached the model | nothing: `clean` |

Codex, agy, grok and kimi are inventoried in ENCOUNTERED-MACHINERY M153; opencode is not yet measured. The full
table is in the vault at `frame/harness-import-scrub-20260925/HARNESS-IMPORTS.md`.

## Not covered here

- **Network egress:** shared with the host (the fabric's R9 gate).
- **Memory and time ceilings, and the T1 and T3 carriers:** row `capability-fabric-envelope-unit-and-oci-carrier-20260925`.

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

**Mutation check:** the same job runs `scripts/capability-envelope-mutation-check`.
- It breaks each envelope invariant in a temporary copy of the package: a mask, a refusal, a read-only bind, the
  cleared environment, and so on.
- It fails unless every mutation turns `tests/capability_envelope` red and the unmutated copy stays green.
- `tests/scripts/test_capability_envelope_mutation_check.py` checks, in every suite, that each mutation still applies.

```bash
HAPAX_ENVELOPE_REQUIRE_BWRAP=1 uv run python scripts/capability-envelope-mutation-check   # prints "ALL KILLED"
```
