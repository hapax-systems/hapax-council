# Hapax Council agent instructions

`AGENTS.md` is the canonical authored repository instruction file for every native harness.
`CLAUDE.md` is a relative symlink to it for Claude and existing filesystem readers; edit
`AGENTS.md` directly. Do not maintain a second copy. Binding and verification details:
`docs/runbooks/agent-instruction-binding.md`.

Read `~/AGENTS.md` for workspace orientation and `~/.claude/CLAUDE.md` for shared
cross-repo conventions (uv, ruff, testing, git and declared-capability delegation).
Repository-local instructions take precedence over workspace summaries; nested instruction
files apply to their own directories. Global instruction delivery remains a native binding,
not a claim that every harness discovers those files automatically.

Hapax serves a **single sovereign principal**. Interacting with, serving and engaging others
is in scope; those people do not become additional principals. Delegation and service must
not create a second source of authority. The `single_user` axiom identifier remains the
existing registry key; the former prohibition on all auth, roles and collaboration misstated
the operator's intent.

Sister: [vscode](vscode/CLAUDE.md), [hapax-mcp](https://github.com/hapax-systems/hapax-mcp).
Governance: `hapax-constitution` → `hapax-sdlc` package; local axioms in `axioms/registry.yaml`.
Rotation policy: `docs/superpowers/specs/2026-04-13-claude-md-excellence-design.md` applies to
both instruction filenames.

## Architecture

Filesystem-as-bus: agents read/write markdown+YAML on disk; inotify reactive engine cascades work. Three tiers: T1 interactive (Tauri, waybar, VS Code), T2 LLM agents (pydantic-ai via LiteLLM :4000; configured local and cloud engines; verify host-specific runtime bindings before use), T3 deterministic (sync/health/maintenance). Docker Compose 13 containers + systemd user units. New units → `systemd/units/` only. Key chain: hapax-secrets → logos-api(:8051) → tabbyapi(:5000) → hapax-daimonion → studio-compositor. Qdrant `operator-patterns` is dead schema — don't add writers.

## Design Language

Authority: `docs/logos-design-language.md`. No hardcoded hex — use CSS vars/Tailwind. Visual PRs MUST include before/after screenshots via `scripts/compositor-frame-capture.sh`.

## Logos API

`:8051`. `uv run logos-api`. Containers: `docker compose up -d`.

## Obsidian Integration

Vault: `~/Documents/Personal/` (kebab-case, PARA). Plugin `obsidian-hapax/` provides context panel. Goal notes: `type: goal` frontmatter. Agents: `obsidian_sync.py` (6h), `vault_context_writer.py` (15min), `vault_canvas_writer.py`, `sprint_tracker.py` (5min).

## Screwm Aggregate Runtime

Only the Logos/Tauri desktop frontend is intentionally sunsetted and disabled.
Do not revive it as the primary runtime. The aggregate target is
Screwm-native: DarkPlaces/Quake spatial rendering plus Hapax compositor, drift,
and effects capabilities re-homed behind governed contracts. Required ports
include audio reactivity, drift/modulation currency, WGSL node graph parity,
Cairo/ward atlas rendering, image/video classification, audio governance:
ducking, LUFS panic, VAD, and consent egress, layout switching and transition
FSM, director/programme control, temporal/glfeedback effects, recording/HLS
egress, and camera resilience. The `hapax-logos` workspace may still contain
shared visual crates, but the Tauri shell is not the live surface.

## Unified Semantic Recruitment

Single `AffordancePipeline` gates everything. Impingement → embed → cosine vs Qdrant `affordances` → score (similarity+base_level+context_boost+thompson×cost_weight) → governance veto → activate. Thompson sampling Beta(2,1) clamped [1,10]. 6 domains (perception/expression/recall/action/communication/regulation). Imagination produces intent not implementation. Consent gate fail-closed on `consent_required` capabilities. Face privacy at egress layer (#129). Spec: `docs/superpowers/specs/2026-04-02-unified-semantic-recruitment-design.md`.

## Studio Compositor

GStreamer pipeline: cameras → cudacompositor → GL shader chain (12 glfeedback slots) → cairooverlay (wards) → v4l2sink(/dev/video42) + HLS. Layout JSON at `config/compositor-layouts/default.json` + `config/layouts/garage-door.json`. Cairo wards render via `CairoSourceRunner` on background threads; `pip_draw_from_layout()` blits post_fx assignments ON TOP of shaders. Camera mode via `/dev/shm/hapax-compositor/layout-mode.txt` (balanced/packed/sierpinski). Key: `compositor.py`, `cairo_source.py`, `fx_chain.py`, `overlay.py`, `layout.py`. Camera resilience: per-camera sub-pipelines, fallback producers, 5-state FSM, WatchdogSec=60s.

## Reverie Vocabulary Integrity

62 WGSL nodes (60 registered in `agents/shaders/nodes/`), 88 presets, glfeedback Rust plugin. 8 always-on vocab nodes + 52 satellite-recruitable. Full affordance coverage (60/60 registered). Satellites MUST use `sat_` prefix. Two GPU bridge paths: shared 9-dim uniforms + per-node params_buffer. Regression pin: `tests/test_wgsl_node_affordance_coverage.py`.

## Audio Routing — PROTECTED INVARIANTS

**MANDATORY.** Full reference: `docs/audio-topology-reference.md` (single source of truth). The **MOTU UltraLite mk5** is the single analog I/O hub (pinned to the pro-audio profile, 48 kHz); Hapax's TTS voice is modulated by the **Torso S-4** via an **analog hardware insert** (dry send out the mk5, processed wet return back in; the S-4 sits in a `Material=Bypass` scene). The legacy **MPC / Behringer L-12 / Evil Pet** hardware-mixer chain is **RETIRED** (decommissioned 2026-05/06) — music/YT/PC/private sources now mix at the PipeWire loudnorm→tap layer, not in hardware. Golden voice chain: `TTS(hapax-daimonion) → voice-fx → loudnorm → mk5 OUT3/4 (dry send) → Torso S-4 [analog insert] → mk5 IN3/4 (wet return) → voice-wet → livestream-tap → broadcast-master → broadcast-normalized → obs-broadcast-remap → OBS`. mk5 channel map: IN1=Rode operator mic (`pro-input-0:capture_AUX0`, never dropped), IN2=Cortado contact mic (AUX1, quarantine/non-broadcast), IN3/4=S-4 wet return (AUX2/3), OUT3/4=dry send to S-4 (AUX2/3), Phones=AUX10/11 (private/operator monitor), Main=AUX0/1 (monitor, not broadcast). Music plays via `hapax-music-player.service` (yt-dlp → pw-cat → hapax-music-loudnorm), NOT a browser. Default sink must NEVER be a physical/broadcast device (mk5/S-4/M8/Yeti/HDMI/BT). Run `scripts/hapax-audio-routing-check` before/after ANY audio change. REVERT on failure. NEVER bypass the S-4 wet path or the mk5 hub. NEVER target `hapax-livestream-tap` playback from unauthorized sources. NEVER modify `~/.config/pipewire/pipewire.conf.d/` without approval.

## CC Task Tracking

SSOT: `~/Documents/Personal/20-projects/hapax-cc-tasks/`. Commands: `cc-claim <id>`, `cc-close <id> [--pr N]`.
**A task's `pr:` MUST be accompanied by `pr_repo: <owner>/<name>`** — `cc-task-pr-link.sh` writes both
automatically from the PR URL, so hand-written notes are the only ones at risk. A bare number is not a
link: the merge watcher scans one repository and a same-numbered PR elsewhere used to close the wrong
task (measured 2026-08-04, twice). Both closure gates refuse an undeclared, malformed, or foreign
`pr_repo`, and refuse a PR they cannot verify. `HAPAX_PR_MERGE_GATE_OFF=1` closes with **no merge
evidence at all** — it does not pick a repository or check anything, and it says so on stderr; it is
for a genuinely offline operator, not for clearing a block. Recheck: `uv run pytest tests/test_cc_pr_merge_watcher_repo_scope.py tests/scripts/test_cc_claim_pr_merge_gate.py -q`; audit the vault for undeclared links with `rg -l --glob '*.md' '^pr: *"?[0-9]' ~/Documents/Personal/20-projects/hapax-cc-tasks/active | xargs rg --files-without-match '^pr_repo:'` (expect no output). Hook `cc-task-gate.sh` auto-transitions claimed→in_progress. SessionStart shows claimed task + top 5 WSJF.

Multi-session stacks: Claude (`hapax-claude-<role>`, `scripts/hapax-claude`),
Codex (`hapax-codex-cx-<color>`, `scripts/hapax-codex`), Vibe
(`hapax-vibe-vbe-N`, `~/.local/bin/hapax-vibe`), and route-gated Agy adapter
support. Antigrav/Antigravity and legacy `gemini-cli` worker surfaces are
retired and excised as live dispatch platforms, lanes, and route families; do
not use `hapax-antigrav`, Antigrav lanes, or legacy Gemini lanes for SDLC task
ownership. `agy.review.direct` is the live agy CLI review route: it is
read-only, blocked until route-specific quota/resource receipt evidence exists,
and not a methodology-dispatch, cross-runtime, or visible-dev worker lane. A
spawnable Agy dispatch route still requires measured route/resource/governance
receipts and is not listed in `--list-platform-paths` by this wiring slice.
Gemini/Claude/GPT-OSS are engines behind the agy harness, not separate Hapax
capability-family names. Recheck before treating agy/Gemini as live worker
supply: `rg -n "agy.review.direct|Antigrav.*retired|Gemini.*engine|antigrav.interactive.full" CLAUDE.md docs/routing-ontology-reference.md config/platform-capability-registry.json`
must match this file, the routing ontology, and the registry; `scripts/hapax-methodology-dispatch --list-platform-paths | rg -i "antigrav|agy"`
must return no rows because `agy.review.direct` is a review route, not a
PLATFORM_PATHS launcher. Active interactive stacks use tmux control plane +
relay YAML + `--require-ack` sends where supported. Spawn pattern:
`hapax-claude --terminal tmux --role X` then `sleep 8` then
`hapax-claude-send --session X -- "task"`. RTE role: 270s tick, PR drain,
branch hygiene, queue health, never carries workloads. Off-limits for vbe-*:
`axioms/`, `shared/governance/`, `agents/hapax_daimonion/`,
`config/pipewire/`, `CODEOWNERS`, any `AGENTS.md` or `CLAUDE.md`; Antigrav restrictions are
enforced by retired-surface refusal above, not by worker off-limits scope.

## Axiom Governance

| Axiom | Weight | Constraint |
|-------|--------|------------|
| single_user | 100 | Single sovereign principal; serving others must not create another principal |
| executive_function | 95 | Zero-config, errors include next actions |
| corporate_boundary | 90 | Work data in employer systems only |
| interpersonal_transparency | 88 | No persistent state on non-operator without consent |
| management_governance | 85 | LLMs prepare, humans deliver |

Non-formal referents: "The Operator"/"Oudepode"/"OTO" (sticky per utterance via `shared.operator_referent`).

## V5 Publication Bus

55 surfaces, 3 tiers (FULL_AUTO/CONDITIONAL_ENGAGE/REFUSED). Publisher superclass enforces AllowlistGate + legal-name guard + Prometheus counter. SWH attribution pipeline. Cold-contact: citation-graph-only, ≤5/deposit, ≤3/year/candidate.

## Key Modules

`shared/config.py` (model aliases, LiteLLM/Qdrant), `shared/working_mode.py`, `shared/notify.py` (ntfy), `shared/frontmatter.py` (canonical parser), `shared/dimensions.py` (11 dims), `shared/governance/consent.py`, `shared/agent_registry.py`, `shared/telemetry.py` (hapax_span ExitStack pattern — don't refactor).

## IR Perception

3 Pi fleet: Pi-1(.78) ir-desk, Pi-2(.52) ir-room, Pi-6(.74) sync+ir-overhead. YOLOv8n ONNX, 3s cadence. Fusion: any() for person, desk-prefer for gaze, overhead-prefer for hands.

## Hooks

| Hook | Blocks |
|------|--------|
| work-resolution-gate | Edit/Write on feature branch without PR |
| no-stale-branches | Branch creation with unmerged branches; max 20 worktrees |
| pii-guard | PII patterns |
| attribution-entity-check | Product-company misattributions in publication-adjacent files (registry: `config/publication-hardening/known-entities.yaml`) |
| unguarded-cd-guard | Bash where a failed `cd` would run later commands in the wrong directory (analyzer: `hooks/scripts/unguarded_cd_guard.py`; allowed: `set -e` before the cd, full `&&` chains, `cd X \|\| exit`) |

Activation state (2026-05-29; `unguarded-cd-guard.sh` registered for Bash in `~/.claude/settings.json` 2026-06-11 — recheck: `grep -c unguarded-cd-guard ~/.claude/settings.json`; the deployed copy at `~/.cache/hapax/rebuild/worktree/hooks/scripts/` was an untracked fail-open v1 until 2026-06-12, when it was replaced in place with the tracked analyzer pair — after any merge touching these hooks, re-run `hapax-hooks-doctor --check`): `push-gate.sh` remains unwired, but the conditional in-session release gate `pr-release-gate.sh` is registered in `~/.claude/settings.json` for Bash and GitHub MCP PR create/merge paths. It runs the AVSDLC release precheck and the real test-before-push evidence check where the active task requires release evidence. `hook-presence-verify.sh` runs on session start, `visual-audio-evidence-reflex.sh` advises after visual/audio edits, and `subagent-git-safety.sh` runs on SubagentStop. Pre-commit hooks are installed in the current council and constitution clones; new clones still need the one-time bootstrap in `docs/runbooks/pre-commit-bootstrap.md`. `.github/CODEOWNERS` documents governance-protected paths, but required Code Owner review is disabled for this single-user repo because GitHub forbids self-approval. Full verification runbook: `docs/runbooks/claude-code-config-conformance.md`.

## Voice & Research

Voice FX: PipeWire filter-chain presets at `config/pipewire/voice-fx-*.conf`. Research state: `agents/hapax_daimonion/proofs/RESEARCH-STATE.md`. Composition ladder: 10 layers, 7-dim matrix, gate on N-1 complete.

## Session coordination and Codex bindings

- Obsidian is the canonical work-state surface. CC/Codex work items live in `~/Documents/Personal/20-projects/hapax-cc-tasks/`; use `cc-claim` and the active claim files before source mutation.
- Use `uv`, not `pip`. Secrets come from `pass` and `hapax-secrets`; do not copy credential values into code or docs.
- Prefer `scripts/hapax-codex --session cx-<color> --slot <alpha|beta|delta|epsilon>` to launch Codex so hooks, MCP, Obsidian context, and no-ask execution are all active. Without `--cd`, non-primary Codex sessions use Codex-native worktrees named `~/projects/hapax-council--cx-<color>`.
- Use `scripts/hapax-codex-send --session cx-<color> --require-ack -- "message"` for load-bearing parent-to-child instructions. The reliable control plane is tmux (`hapax-codex-cx-<color>`); direct `foot` delivery is a legacy fallback and must not be treated as task receipt unless an ACK is observed.
- Use `scripts/hapax-operator-message --type advisory|query|escalation --subject ...` for child/session-to-operator messages that should appear in the SBCL/CLOG Operator Inbox. Do not use it for work assignment; dispatch still goes through `scripts/hapax-methodology-dispatch`.
- Screen visibility is required for `cx-red` and protected `cx-violet`. Other worker lanes may run headless in tmux if the Obsidian session dashboard (`hapax-cc-tasks/_dashboard/codex-session-health.md`), relay YAML, active claim file, and PR state stay current.
- Respect relay path claims in `~/.cache/hapax/relay/*.yaml` before touching shared areas.
- Respect protected live-session declarations in `~/.cache/hapax/relay/session-protection.md`; a protected `cx-*` lane must not be killed, replaced, relaunched, or reclaimed unless the operator explicitly overrides it.
- Idle Codex sessions must stay on the coordination timer from `HAPAX_IDLE_UPDATE_SECONDS` (default 270): when blocked, waiting, or otherwise not actively producing, check parent/user/relay updates on that cadence and leave a concise relay/status update if the wait continues.
- Existing Claude hook scripts are also the Codex guardrails through `hooks/scripts/codex-hook-adapter.sh`.
- Current Claude Code config-conformance state, hook activation checks, pre-commit bootstrap, CODEOWNERS advisory ownership, and constitution-package follow-up are documented in `docs/runbooks/claude-code-config-conformance.md`.
- **Task claiming is MANDATORY.** You MUST `cc-claim <task_id>` before writing code and close the current task before claiming another. Do not disable or route around the hooks.
- **`cc-task-gate` is an advisory discipline aid, not an enforcement boundary** (operator ruling 2026-09-20). The obligation above is unchanged — claim before you write, and never route around the hook — but do not mistake the mechanism for a control: it fails **open** by design when its substrate is missing (INV-5, "never fail-closed-stuck"), it classifies on command *spelling* so any absolute-path invocation matches no rule, and it does not open script files to see what they write. It catches slips, which is what it is for — **accidents do not evade** — and it does not catch intent, which is acceptable because there is one sovereign principal and no adversary. **Do not build anything that depends on it as a control, and do not "fix" it by normalizing command heads or extending marker lists.** The rule it instantiates: *a check may read an upstream-defined free variable, but may never treat it as identifying.* Irreversible and outward-facing actions — token revocation, spend, outbound messages to real people — are carved out, and their checks **do** block. Note also that the whole personal vault is exempt from scope checking (cognition is always writable), so `mutation_scope_refs` entries under `~/Documents/Personal/` are decorative; shell source is still gated, even inside the vault.
- **One task at a time.** `cc-claim` refuses to claim a new task while the current claim is active (non-terminal). Use `cc-close` first, or follow the governed stale-lease release procedure for a stale claim. After normal closure, admitted `cc-claim` archives any terminal dispatch-only residue to the old task lineage before publishing the next claim. The admitted default path rejects `cc-claim --force`; use the explicit emergency fallback only with operator authorization.
- **Worktree limit: 20 visible session worktrees.** Creating worktrees beyond this is blocked. Codex lanes share this cap with Claude Code sessions.
- A `codex-claim-audit.timer` runs every 4 hours and auto-releases phantom claims (claimed > 6h with no PR). Do not disable this timer.

For multi-session work, Codex lane identities use `cx-<color>` and worktree slots remain `alpha`, `beta`, `delta`, `epsilon` as coordination lanes. Greek slot names are not Codex worktree names; do not default Codex work into legacy Claude-era `hapax-council--delta/epsilon/main-red` paths.

## Review Guidelines

External GitHub App reviewers such as CodeRabbit, Claude, and Codex are advisory unless their output is explicitly ingested through the Hapax review-team contract. Do not treat an external AI review, status check, or summary as authoritative closure evidence by itself.

When reviewing changes in this repository:

- Check that source, runtime, provider-spend, and public-surface mutations are tied to a cc-task with `authority_case`, non-null `parent_spec`, route metadata, and scoped mutation refs.
- Treat review-team quorum, critical findings, and signed acceptance receipts as the authoritative review plane.
- Flag attempts to make Codecov, Semgrep, CodeRabbit, Claude, or Codex a required branch-protection context unless the PR includes a governed task authorizing that gate change and rollback.
- For CI/CD edits, verify merge-queue behavior explicitly: required contexts should remain stable and aggregate, while advisory checks must not wedge queued PRs.
- For secrets and provider credentials, verify values are referenced through GitHub Secrets, `pass`, or `hapax-secrets`; never request plaintext values in files, PR comments, or logs.
- New Hapax repositories must be created under `hapax-systems`, never under
  `ryanklee`. Use `scripts/hapax-github-repo-create` for new repos and
  `scripts/hapax-github-repo-standards-audit.py` to check CI/app baselines.
