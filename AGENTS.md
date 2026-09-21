# Hapax Council agent instructions

`AGENTS.md` is the canonical authored repository instruction file.
`CLAUDE.md -> AGENTS.md` is its relative compatibility alias; edit the target.
Do not reread or maintain an independent alias body. Binding and verification:
`docs/runbooks/agent-instruction-binding.md`.

Shared conventions are authored in `config/agent-instructions/AGENTS.md` and
native global bindings deploy them from one source. If not already delivered,
read `~/.config/hapax/agent-instructions/AGENTS.md`. Read `~/AGENTS.md` for
workspace orientation; repository instructions take precedence over workspace
summaries, and nested instructions apply to their directories. Discovery and
semantic compliance must be observed separately.

Hapax serves a **single sovereign principal**. Serving and engaging other
people is in scope; they do not become additional principals. Delegation and
service preserve authority, consent and scope. Do not revive the old blanket
prohibition on auth, roles or collaboration.

## Domain work

Before changing a domain, read its full scoped instructions in
`docs/runbooks/council-domain-context.md` and the referenced source of truth.
That document retains architecture, audio maps, compositor/recruitment,
publication, hook activation, voice/research and module details. This core
file stays below 10,000 characters for Grok; no native binding may silently
truncate it. Both filenames follow the rotation policy in
`docs/superpowers/specs/2026-04-13-claude-md-excellence-design.md`.

- New systemd units belong in `systemd/units/`. Never add writers to the dead
  Qdrant `operator-patterns` schema. Preserve `hapax_span` ExitStack semantics.
- Design authority: `docs/logos-design-language.md`; use CSS variables/Tailwind,
  not hardcoded hex. Visual PRs require before/after screenshots via
  `scripts/compositor-frame-capture.sh`.
- Only the Logos/Tauri desktop frontend is sunsetted. Do not revive that shell
  as primary. Screwm-native is the aggregate target; preserve the required
  rendering, audio governance, drift, transition, recording and camera ports
  enumerated in the domain reference. Shared visual crates remain usable.
- Recruitment goes through the single `AffordancePipeline`; consent-required
  capabilities fail closed, face privacy applies at egress. Imagination
  produces intent, not implementation. Shader satellites use `sat_` prefixes;
  preserve `tests/test_wgsl_node_affordance_coverage.py` coverage.
- **Audio is protected.** Read `docs/audio-topology-reference.md` before any
  audio work. Run `scripts/hapax-audio-routing-check` before and after changes;
  revert on failure. Never bypass the Torso S-4 wet insert or MOTU mk5 hub.
  MPC/L-12/Evil Pet are retired. Never drop the Rode operator mic; Cortado is
  quarantined/non-broadcast. Never make a physical/broadcast device the default
  sink, target `hapax-livestream-tap` playback from unauthorized sources, or
  modify `~/.config/pipewire/pipewire.conf.d/` without authority. Music uses
  `hapax-music-player.service`, not a browser.
- Publication uses the publisher superclass's AllowlistGate, legal-name guard,
  attribution and counter. Cold contact is citation-graph-only: at most five
  per deposit and three per year per candidate. Observe the declared surface's
  FULL_AUTO/CONDITIONAL_ENGAGE/REFUSED tier.

## Work authority and coordination

Obsidian is the canonical work-state surface:
`~/Documents/Personal/20-projects/hapax-cc-tasks/`. Use real
`cc-claim <task_id>` before governed mutation, one active task at a time, and
`cc-close <id> [--pr N]` at completion. Do not hand-write claim markers, disable
hooks, or route around refusals. Close the current task before claiming another;
use the governed stale-lease procedure when necessary. Admitted `cc-claim`
archives terminal dispatch residue to the predecessor lineage. Its normal path
rejects `--force`; emergency fallback requires explicit operator authorization.

Every task `pr:` needs `pr_repo: <owner>/<name>`. Use `cc-task-pr-link.sh` to
write both from the URL. A bare number can close a task against an unrelated
repository's PR. Closure requires verified matching repository evidence.
`HAPAX_PR_MERGE_GATE_OFF=1` produces no merge evidence; it is an explicit
operator offline procedure, not a way to clear a block. Verification:
`tests/test_cc_pr_merge_watcher_repo_scope.py` and
`tests/scripts/test_cc_claim_pr_merge_gate.py`.

**`cc-task-gate` is an advisory discipline aid, not an enforcement boundary**
(operator ruling 2026-09-20). Claiming remains mandatory. It fails open when
its substrate is missing (INV-5), classifies command spelling, and does not
inspect script contents. It catches slips; **accidents do not evade**. Do not
build a control on it or “fix” it by normalizing command heads or extending
marker lists. A check may read an upstream-defined free variable but may not
treat it as identifying. Irreversible/outward actions—token revocation, spend,
messages to real people—have blocking checks. The personal vault is exempt
from scope checking because cognition is always writable; vault
`mutation_scope_refs` do not enforce scope. Shell source remains gated there.

Use `uv`, not `pip`. Reference secrets through the declared `hapax-secret` /
FileStore or credential binding; never place values in source, docs, logs or PRs.
Respect relay path claims under `~/.cache/hapax/relay/` and protected-session
rules in `session-protection.md`. Never replace, kill or reclaim a protected
lane without operator override. Refresh progress/relay state; idle workers
check updates on `HAPAX_IDLE_UPDATE_SECONDS` (default 270 seconds).

Native Agent/Task subagents and dispatching plugins remain retired. Compose
admitted, declared capabilities with quota/authority/measurement bindings.
Do not infer admission from the presence of a CLI or from model names.
Antigrav/Antigravity and legacy gemini-cli worker lanes are retired; do not use
`hapax-antigrav` or Gemini lanes for SDLC ownership. `agy.review.direct` is a
read-only review route, gated on route-specific evidence, not a visible-dev or
methodology worker lane. Gemini/Claude/GPT-OSS behind agy are engines, not
capability families. Before dispatch, reconcile
`config/platform-capability-registry.json`, `docs/routing-ontology-reference.md`
and `scripts/hapax-methodology-dispatch --list-platform-paths`.

Interactive stacks use tmux control plane and relay YAML: Claude
`hapax-claude-<role>`, Codex `hapax-codex-cx-<color>`, Vibe `hapax-vibe-vbe-N`.
Require ACK for load-bearing sends where supported; terminal visibility alone
is not receipt. RTE handles PR drain, branch and queue health on its 270-second
tick and never carries workloads. Auxiliary vbe-* lanes may not mutate
`axioms/`, `shared/governance/`, `agents/hapax_daimonion/`, `config/pipewire/`,
`CODEOWNERS`, or any `AGENTS.md` / `CLAUDE.md` without appropriate authority.

## Codex native additions

- Launch with `scripts/hapax-codex --session cx-<color> --slot
  <alpha|beta|delta|epsilon>` so configured hooks, MCP and context are active.
  Without `--cd`, non-primary worktrees are `~/projects/hapax-council--cx-<color>`.
  Greek slots are coordination lanes, never default worktree names. Do not
  migrate to Claude-era delta/epsilon/main-red paths implicitly.
- Use `scripts/hapax-codex-send --session cx-<color> --require-ack -- "message"`.
  tmux is the reliable control plane; direct foot delivery is a legacy fallback
  and does not prove receipt without ACK.
- `scripts/hapax-operator-message --type advisory|query|escalation --subject ...`
  delivers operator-facing notices to the SBCL/CLOG inbox. Work assignment
  still uses `scripts/hapax-methodology-dispatch`.
- `cx-red` and protected `cx-violet` require screen visibility. Other lanes may
  be headless if the Obsidian session dashboard, relay, claim and PR stay current.
- The Codex adapter is `hooks/scripts/codex-hook-adapter.sh`. Verify actual
  hook activation with `hapax-hooks-doctor --check` after related changes;
  configuration and historical observations are not current activation proof.
- At most 20 visible session worktrees, shared with Claude lanes. Do not disable
  `codex-claim-audit.timer` (four-hour audit, stale phantom claims >6h without PR).

## Governance and review

Governance derives from `hapax-constitution` / `hapax-sdlc` and
`axioms/registry.yaml`: one sovereign principal (100); zero-configuration and
next-action errors (95); employer data stays in employer systems (90);
no persistent state about another person without consent (88). The management
domain axiom (85) says LLMs prepare, humans deliver; preserve its declared
`scope: domain` / `domain: management` rather than applying it to every
communication. Operator referents use `shared/operator_referent`.

Review source, runtime, provider-spend and public-surface mutations against the
active task's `authority_case`, non-null `parent_spec`, route metadata and
scoped `mutation_scope_refs`. Independent
review-team quorum, critical-finding disposition and signed acceptance are the
review plane. GitHub App reviewers and their summaries are advisory unless
explicitly ingested there. Do not turn Codecov, Semgrep, CodeRabbit, Claude or
Codex into required checks without governed authority and rollback. CI changes
must preserve stable aggregate required contexts and working merge queues.

Ownership exclusions include both instruction filenames. Code Owner reviews
are advisory in this single-principal repository; do not infer self-approval
requirements. Bootstrap new clones using `docs/runbooks/pre-commit-bootstrap.md`;
configuration verification is in `docs/runbooks/claude-code-config-conformance.md`.
Create new repositories under `hapax-systems`, never `ryanklee`, using
`scripts/hapax-github-repo-create`; check baselines with
`scripts/hapax-github-repo-standards-audit.py`.
