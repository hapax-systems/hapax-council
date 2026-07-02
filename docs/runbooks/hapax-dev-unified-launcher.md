# hapax-dev — unified visible-session launcher

`scripts/hapax-dev` is the operator's one front door for **visible** sessions
across the three coding runtimes. You no longer need to remember per-platform
launch particulars (`--role` vs `--session`, which lane is free, `--terminal
tmux`, identity export):

```bash
hapax-dev claude      # visible claude session, auto non-conflicting identity
hapax-dev codex       # visible codex session
hapax-dev agy         # visible agy CLI session
```

…and all the right things happen: a **fresh, unique `HAPAX_SESSION_ID`** plus a
**free interactive identity distinct from the headless reform fleet**, then a
dispatch to the existing per-platform spawner. Because each launch gets a unique
explicit identity, the session is guaranteed non-conflicting — spin up a
parallel stream (e.g. audio) that never collides with the headless fleet.

It does **not** reimplement launch logic. Identity export, governance wiring,
the tmux spawn, and the runtime exec all stay in `hapax-claude` /
`hapax-codex` / `hapax-agy`. `hapax-dev` only (a) picks a free identity,
(b) refuses collisions by construction, (c) guarantees a fresh session id, and
(d) handles visibility (attach / window / detach).

`hapax-agy` is currently the canonical entrypoint shim over the legacy
`hapax-antigrav` implementation. That implementation filename is retained only
until `cc-task-agy-wrapper-legacy-antigrav-surface-excision-20260630` lands.

## Identities (interactive pools, distinct from the supervised fleet)

| Platform | Spawner | Interactive pool | tmux session |
|----------|---------|------------------|--------------|
| `claude` | `hapax-claude` | `dev`, `dev2`, `dev3`, … | `hapax-claude-<name>` |
| `codex`  | `hapax-codex`  | `cx-blue`, `cx-green`, `cx-cyan`, … | `hapax-codex-<name>` |
| `agy` | `hapax-agy` | `agy`, `agy-2`, … | `hapax-agy-<name>` |

`antigrav` is deprecated. `hapax-dev antigrav` refuses with a migration message; use
`hapax-dev agy` or an explicit `agy-*` identity.

Recheck:

```bash
HAPAX_DEV_DRY_RUN=1 scripts/hapax-dev agy --dry-run
HAPAX_DEV_DRY_RUN=1 HAPAX_DEV_FAKE_LIVE_TMUX=hapax-agy-agy scripts/hapax-dev attach agy
HAPAX_DEV_DRY_RUN=1 scripts/hapax-dev antigrav --dry-run
```

The first command must resolve an `agy` / `agy-*` identity through `hapax-agy`;
the attach command must use exact tmux targeting (`-t =hapax-agy-agy`); the
deprecated-platform command must exit non-zero with
`deprecated platform 'antigrav'; use 'agy'`.

- **Why a `dev` pool for claude?** The greek roles `alpha..theta` are the
  *supervised headless reform fleet* — `hapax-lane-supervisor` auto-respawns them
  and the dispatcher hands them governed tasks. An interactive operator session
  must never land there. The non-greek `dev` pool is reserved for operators and
  is invisible to the supervisor/dispatcher. (See `hapax-claude`'s dev-pool
  extension below.) `codex` reserves `cx-red` (primary) and `cx-violet`
  (protected); the interactive pool is the remaining colors.
- **Auto-selection** (name omitted) picks the **lowest free** pool slot. A slot
  is *free* only when there is no live tmux session **and** no active claim file
  (`~/.cache/hapax/cc-active-task-<name>`, including session-keyed variants)
  **and** no fresh headless-output heartbeat
  (`~/.cache/hapax/claude-headless/<name>/output.jsonl`). The claim/heartbeat
  checks mean a headless lane that holds a claim *without* a tmux session is
  still correctly seen as busy.
- **Explicit name** is honored as-is. A *free* greek claude role may be used
  **only** when named explicitly (`hapax-dev claude zeta`).
- **Collisions are refused**: if the resolved name is already live, no second
  session is launched — the `tmux attach …` command is printed and the exit code
  is non-zero.

## Commands & flags

```text
hapax-dev <platform> [name] [flags] [-- spawner-args]
hapax-dev ls | list            table of live sessions + free pool slots
hapax-dev attach <name>        attach to an existing session
hapax-dev help                 usage + the live/free table

flags:
  --window      open a new terminal window attached to the session
  --detach      spawn but do not attach; print the attach command
  --cd DIR      workdir for the session (default: $PWD)
  --dry-run     print the resolution plan; do not spawn or attach
  --            forward all remaining args verbatim to the spawner
```

- **Visibility default** is *attach in the current terminal* — launching is
  operator-initiated, so attaching is wanted, and no unsolicited GUI window is
  opened. Use `--window` for a new terminal window; `--detach` to start without
  attaching.
- **Pass-through**: everything after `--` reaches the underlying spawner, e.g.
  `hapax-dev claude audio -- --task my-task "kick off prompt"`.
- **Workdir**: defaults to the current directory. Note that `codex` and `agy`
  write workspace rule files (`AGENTS.md`, `.agents/`) into the workdir — pass
  `--cd <scratch-dir>` if you want to keep the current repo clean. (A dedicated
  `hapax-council--dev` git worktree is intentionally *not* auto-created: the
  visible-worktree cap is already saturated — see
  [worktree-cap-policy.md](worktree-cap-policy.md). Identity, not a worktree, is
  what guarantees non-collision.)

### Examples

```bash
hapax-dev claude                     # lowest free dev slot, attach here
hapax-dev claude dev3 --detach       # named slot, leave detached
hapax-dev codex --window             # new color, in a new window
hapax-dev agy -- --no-claim          # forward a spawner flag
hapax-dev ls                         # what's live, what's free
hapax-dev attach dev                 # re-attach to a running dev session
```

## Install / PATH

`hapax-dev` follows the standard `scripts/hapax-*` deployment path. On the next
**post-merge deploy** (`scripts/hapax-post-merge-deploy`) it is symlinked into
`~/.local/bin/` automatically — the same mechanism that puts `hapax-claude` and
`hapax-codex` on PATH:

```text
~/.local/bin/hapax-dev → ~/.cache/hapax/source-activation/worktree/scripts/hapax-dev
```

Manual fallback (if you want it on PATH before the deploy runs):

```bash
ln -sfv "$HOME/.cache/hapax/source-activation/worktree/scripts/hapax-dev" \
        "$HOME/.local/bin/hapax-dev"
```

## hapax-claude dev-pool extension

`hapax-dev claude` relies on a small, additive extension to `hapax-claude`:

- `dev` / `dev<N>` are accepted as roles (the greek `alpha..theta` validation
  and worktree mapping are unchanged).
- A `dev*` lane defaults its worktree to the invoking `$PWD` (`hapax-dev` always
  passes `--cd` explicitly; this is the standalone fallback).
- A `dev*` lane is **operator-interactive** and therefore exempt from the
  mandatory cc-task binding that governs the headless greek lanes — the operator
  drives it in person. Greek lanes still require a task or `--readonly`.

## Testing

`tests/scripts/test_hapax_dev.py` exercises the resolver hermetically via
`--dry-run` and the `HAPAX_DEV_*` test hooks (no real sessions are launched),
plus the `hapax-claude` dev-pool extension with stub `claude`/`tmux` binaries.
Run it with:

```bash
uv run pytest tests/scripts/test_hapax_dev.py -q
shellcheck scripts/hapax-dev
```
