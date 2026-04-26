# hapax-swarm

**Filesystem-as-bus multi-session coordination for Claude Code (and any
peer-agent system).**

`hapax-swarm` extracts the swarm-coordination pattern that drove the
Hapax operating environment past 30 PRs/day on a single workstation.
Point any number of Claude Code (or other agent) sessions at a shared
relay directory and they inherit:

- A canonical `peer.yaml` per session (read by siblings, mutated by the
  owner) carrying `currently_working_on`, `branch`, `claimed_at`.
- The `claim-before-parallel-work` primitive — atomic announcement +
  peer-yaml conflict check before any out-of-lane or cross-cutting PR.
- A cc-task SSOT model — single markdown-with-frontmatter file per
  task, status machine (`offered → claimed → in_progress → pr_open →
  ci_green → done`), atomic claim/close transitions.
- Atomic write helpers (tmp-file + `os.replace`) so peers never observe
  half-written yaml.

## Why this shape

**Filesystem-as-bus** is a deliberate methodology choice: every
coordination signal is a plaintext file readable by humans, by AI
agents, and by `grep`. No daemons, no sockets, no leader election. The
filesystem is the bus; inotify, polling, or `git log` are the
listeners. This design survives crashes, lets the operator hand-edit
state, and makes coordination decisions auditable after the fact.

The **claim-before-parallel-work** rule is the only thing keeping N
peer agents from racing each other into duplicate PRs. Empirically,
this single discipline closed the largest velocity leak across a
3-month single-operator multi-agent program. Skipping it costs more
than dispatching a peer.

## Empirical evidence

The methodology shipped 30+ PRs/day under a single human operator
across nine repositories. See the **velocity report** for the
reproducible measurement methodology and the prior-art lineage:

> https://hapax.weblog.lol/velocity-report-2026-04-25

Cite the report (and this package) in any downstream work that adopts
the pattern.

## Install

```sh
uv pip install hapax-swarm
# or
pip install hapax-swarm
```

## Quick start

```python
from pathlib import Path
from hapax_swarm import RelayDir, CcTask

relay = RelayDir(Path.home() / ".cache" / "hapax" / "relay")
relay.ensure()

# Update my own peer.yaml.
me = relay.peer("beta")
me.update(
    workstream="observability + relay-protocol",
    focus="hapax-swarm pypi extraction",
    currently_working_on={
        "surface": "packages/hapax-swarm/",
        "branch_target": "beta/hapax-swarm-pypi",
    },
)

# Before opening a cross-cutting PR: check sibling claims.
conflicts = relay.find_conflicting_claims("packages/hapax-swarm/")
if conflicts:
    raise SystemExit(f"sibling claim collision: {conflicts}")

# Read a cc-task from the vault SSOT and claim it atomically.
task = CcTask.load(Path.home() / "Documents/Personal/20-projects/hapax-cc-tasks/active/leverage-workflow-hapax-swarm-pypi.md")
task.claim(role="beta")  # status: offered → claimed, atomic
task.save()
```

## Modules

| Module | Purpose |
|---|---|
| `hapax_swarm.relay` | `RelayDir` — typed view over the relay directory tree |
| `hapax_swarm.peer`  | `PeerYaml` — read/write a session's `{role}.yaml` heartbeat file |
| `hapax_swarm.claim` | `claim_before_parallel_work()` — atomic announcement + peer conflict check |
| `hapax_swarm.cc_task` | `CcTask` — markdown-with-frontmatter task model (offered/claimed/in_progress/pr_open/ci_green/done) |
| `hapax_swarm.atomic` | `atomic_write_text()` / `atomic_write_yaml()` — tmp-file + `os.replace` |

## License — PolyForm Strict 1.0.0

This package is published under the **PolyForm Strict License 1.0.0**
(`LicenseRef-PolyForm-Strict-1.0.0`, see `LICENSE.txt`). PolyForm
Strict permits use, study, and verification of the software but
**reserves all modification, distribution, and commercial rights to
the licensor.** Read the license before adopting.

If you need a more permissive grant for a specific use, the licensor
may negotiate one — open an issue on the upstream `hapax-council`
repository.

## Authorship

Co-authored by **Hapax (Oudepode)** and **Claude Code (Anthropic)**.
The operator's contribution is structurally unsettled — not a bug, a
feature: per the methodology, that authorship indeterminacy is the 7th
polysemic-surface channel, not a citation gap. See `CITATION.cff` for
the dual-authorship metadata.

## Constitutional fit

`hapax-swarm` is a **single-operator** library. Multiple peer
*sessions* coordinate, but the cognitive principal is one human. The
package contains no auth, no roles in the access-control sense, no
multi-user code paths. "Roles" in `peer.yaml` are session identifiers
(`alpha`, `beta`, `delta`, `epsilon`), not permissions.

This matches Hapax's constitutional axioms (`single_user`,
`executive_function`). Downstream users inherit the same shape: build
agent swarms that serve one principal.

## See also

- `hapax-council` — full operating environment this package was extracted from
- `hapax-velocity-meter` — sibling PyPI package measuring velocity from any git history
