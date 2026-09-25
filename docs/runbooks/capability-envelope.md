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

## What the carrier does (T2, bubblewrap)

- **Allowlist root.** `/usr`, the `/bin`-style links and a short list of `/etc` files, all read-only. The host root
  and the operator's home are never bound whole.
- **A fresh job home** at `/home/job` under the run root. It holds only generated config (Claude: `settings.json` with
  the declared hooks; `.claude.json` with the declared MCP servers), declared files and credentials.
- **The checkout** is at `/work`. Every name in `MASKED_NAMES` is covered by an empty read-only file, or an empty
  tmpfs for a directory, unless it is declared.
- **The environment** is cleared (`--clearenv`), then given a fixed base, the harness config variables and the
  declared `env`.

## Refusals (each narrows; the message names the next action)

- `--bare` without `billing_surface="api"`. Claude's bare mode does not read `CLAUDE_CODE_OAUTH_TOKEN`, so it would
  switch billing implicitly.
- An `env` key that looks like a credential. Env values appear in the carrier argv, so use a `CredentialBind` file.
- Hooks or MCP servers for a harness whose config format the renderer does not yet render (today, anything but
  Claude).
- A run root that already exists.

## Audit (canary C10)

`shared.capability_envelope.sentinel.OpenWatch` records inotify open events on sentinel files. It needs no privilege,
and it sees opens through bind mounts. Plant sentinels wherever a harness could import from, run the job inside the
watch, and fail on any open. What the model says it saw is complementary evidence only.

Measured results, and the per-harness baseline, are in the vault at
`frame/harness-import-scrub-20260925/HARNESS-IMPORTS.md`.

## Not covered here

- **Network egress:** shared with the host (the fabric's R9 gate).
- **Memory and time ceilings, and the T1 and T3 carriers:** row `capability-fabric-envelope-unit-and-oci-carrier-20260925`.

## Tests

```bash
uv run pytest tests/capability_envelope -q
```

The runtime tests need bubblewrap with unprivileged user namespaces. Where that is missing (for example, Ubuntu CI
runners with AppArmor's userns restriction), they skip with that reason. The render-time refusals and argv checks
run everywhere.
