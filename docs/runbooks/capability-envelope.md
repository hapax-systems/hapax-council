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

Recheck: `HAPAX_ENVELOPE_REQUIRE_BWRAP=1 uv run pytest tests/capability_envelope/test_envelope.py -q -k "refused or carrier"`.

## Audit on a real harness (canary C10)

`shared.capability_envelope.sentinel.OpenWatch` records inotify open events on sentinel files. It needs no privilege,
and it sees opens through bind mounts. What the model says it saw is complementary evidence only.

`scripts/capability-envelope-import-audit` is the rerunnable witness.
- It builds a sentinel world.
- It launches the harness the way its reviewer wrapper does, against a mirror of the home (the operator's own files
  are **read as the harness would read them, and never changed** — the baseline's root is read-only and the mirrored
  home is the only writable place), and then again inside the envelope.
- It exits 0 when the enveloped run imported nothing **and** the baseline control witnessed an import on a run that
  completed, 1 on a leak, and 64 when it refuses. **Anything that leaves the observation incomplete is 2
  (inconclusive), never 0:** the enveloped run did not complete; the baseline control witnessed nothing
  (`clean-no-control` — a run whose control proved nothing is not evidence); the baseline itself failed, so its
  coverage of the sentinels is unknown; or the watch queue **overflowed**, which means the kernel dropped events and
  an open can be missing from the record.
- It refuses when a binary or credential is missing, and never copies a credential or a config that carries one:
  opencode's declared config drops secret-named fields, and kimi's is rebuilt from an allowlist.
- Vibe runs only on the Team allowance; GLM is not offered while its dispatch is on hold.

```bash
TMPDIR=/store-fast/tmp uv run python scripts/capability-envelope-import-audit --harness claude --out /tmp/claude.json
# harnesses: agy claude codex grok kimi muse opencode vibe
```

Every row below is backed by a stored report, and claims only what that report shows. All eight harnesses the audit
supports are measured; seven are `clean` and codex was re-run clean on 2026-09-28 after its subscription wall ended
(its 2026-09-26 run is kept as the `inconclusive` predecessor).

| harness | report | sha256 (first 16) | recheck |
|---|---|---|---|
| claude | `frame/harness-import-scrub-20260925/measure/audit-claude.json` (`clean`, 20260925T104357Z) | `42122d5a8793fa82` | `TMPDIR=/store-fast/tmp uv run python scripts/capability-envelope-import-audit --harness claude --out /tmp/claude.json` |
| vibe | `frame/harness-import-scrub-20260925/measure/audit-vibe.json` (`clean`, 20260925T104411Z) | `3ee6d4bdb04098c4` | `TMPDIR=/store-fast/tmp uv run python scripts/capability-envelope-import-audit --harness vibe --out /tmp/vibe.json` |
| muse | `frame/harness-import-scrub-20260925/measure/audit-muse.json` (`clean`, 20260925T104432Z) | `737789c66b091ac0` | `TMPDIR=/store-fast/tmp uv run python scripts/capability-envelope-import-audit --harness muse --out /tmp/muse.json` |
| opencode | `frame/harness-import-scrub-20260925/measure/audit-opencode.json` (`clean`, 20260926T004840Z) | `43826dbd4a755c2f` | `TMPDIR=/store-fast/tmp uv run python scripts/capability-envelope-import-audit --harness opencode --out /tmp/opencode.json` |
| grok | `frame/harness-import-scrub-20260925/measure/audit-grok.json` (`clean`, 20260926T004855Z) | `77957d7a9c2896d0` | `TMPDIR=/store-fast/tmp uv run python scripts/capability-envelope-import-audit --harness grok --out /tmp/grok.json` |
| agy | `frame/harness-import-scrub-20260925/measure/audit-agy.json` (`clean`, 20260926T004926Z) | `b74ed3b587554532` | `TMPDIR=/store-fast/tmp uv run python scripts/capability-envelope-import-audit --harness agy --out /tmp/agy.json` |
| kimi | `frame/harness-import-scrub-20260925/measure/audit-kimi.json` (`clean`, 20260926T004945Z) | `8880b76ce076cfea` | `TMPDIR=/store-fast/tmp uv run python scripts/capability-envelope-import-audit --harness kimi --out /tmp/kimi.json` |
| codex | `frame/harness-import-scrub-20260925/measure/codex-import-audit-20260928T022438Z.json` (`clean`, 20260928T022438Z) | `4e8abdd89cbe9649` | `TMPDIR=/store-fast/tmp uv run python scripts/capability-envelope-import-audit --harness codex --out /tmp/codex.json` |

One harness is inventoried rather than measured by this script: GLM, whose dispatch is on hold. No row here asserts
anything about it.

| harness | baseline launch imported (by the audit's inotify watch) | enveloped |
|---|---|---|
| Claude Code 2.1.281 (`-p`, tools off) | ancestor and checkout `CLAUDE.md`, `CLAUDE.local.md`, `.claude/CLAUDE.md`, user `CLAUDE.md` and rules, a skill, both settings files, user and project hooks **run**, user and project MCP servers **started** | nothing: `clean` |
| Mistral Vibe (the `hapax-vibe-reviewer` argv) | `~/.vibe/AGENTS.md`, and it reached the model | nothing: `clean` |
| Meta Muse 1.4.0 (the `hapax-muse-reviewer` argv) | `~/.config/muse/AGENTS.md`, and it reached the model | nothing: `clean` |
| opencode (local model, $0) | `~/.config/opencode/AGENTS.md`, ancestor and checkout `AGENTS.md`, checkout `CLAUDE.md` and `CLAUDE.local.md` | nothing: `clean` |
| grok CLI (`--single`) | `~/.grok/AGENTS.md` | nothing: `clean` |
| agy (Gemini, `-p`) | `~/.gemini/GEMINI.md`, checkout `AGENTS.md` | nothing: `clean` |
| kimi (K3, `-p`) | `~/.kimi-code/AGENTS.md`, a user skill, checkout `AGENTS.md` | nothing: `clean` |
| codex (`exec`) | `~/.codex/AGENTS.md`, checkout `AGENTS.md` | nothing: `clean` (2026-09-28 rerun; the 2026-09-26 run is `inconclusive` — the subscription was walled) |

The full table is in the vault at `frame/harness-import-scrub-20260925/HARNESS-IMPORTS.md`.

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

**Mutation check:** the same job runs `scripts/capability-envelope-mutation-check` **with `HAPAX_ENVELOPE_REQUIRE_BWRAP=1`** — a mutation check whose own carrier cannot start is a skip, not a pass.
- It breaks each envelope invariant in a temporary copy of the package: a mask, a refusal, a read-only bind, the
  cleared environment, and so on.
- It fails unless every mutation turns `tests/capability_envelope` red and the unmutated copy stays green.
- `tests/scripts/test_capability_envelope_mutation_check.py` checks, in every suite, that each mutation still applies,
  and runs `check()`/`main()` against a fixture repository (killed, survived, not-applied, the exit code and the
  report).
- **Sizing, measured 2026-09-28** (review of #4837, glm-1): one `tests/capability_envelope` run with
  `HAPAX_ENVELOPE_REQUIRE_BWRAP=1` took **15 s** on appendix, and the check runs one baseline plus one run per
  mutation — 25 runs, about **6 minutes** — against the job's `timeout-minutes: 15`. Re-measure before adding
  mutations in bulk or raising the cap.
- **Runtime cost and credentials of the audit itself** (glm-1's minor): each run launches the harness twice (baseline
  and enveloped) and takes roughly 20–60 s per harness; it needs the harness's own binary on `PATH` or in the
  `HAPAX_*_BIN` variable, and its credential (`~/.claude/.credentials.json`, `~/.vibe/.env` on the Team allowance,
  `~/.config/muse/auth.json`, `~/.codex/auth.json`, `~/.kimi-code/{credentials,device_id}`, grep/grok's
  `~/.grok/auth.json`, agy's token files, and a local model for opencode). A missing binary or credential refuses
  (exit 64) rather than running wide.

```bash
HAPAX_ENVELOPE_REQUIRE_BWRAP=1 uv run python scripts/capability-envelope-mutation-check   # prints "ALL KILLED"
```
