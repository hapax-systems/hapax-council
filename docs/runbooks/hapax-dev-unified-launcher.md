# hapax-dev — unified visible-session launcher

`scripts/hapax-dev` is the operator's one front door for **visible** sessions
across the admitted Claude and Codex visible-dev runtimes. Vibe remains an
admitted coding runtime through `hapax-vibe`, not through this visible-dev
launcher. You no longer need to remember per-platform launch particulars
(`--role` vs `--session`, which lane is free, `--terminal tmux`, identity export):

```bash
hapax-dev claude      # visible claude session, auto non-conflicting identity
hapax-dev codex       # visible codex session
```

…and all the right things happen: a **fresh, unique `HAPAX_SESSION_ID`** plus a
**free interactive identity distinct from the headless reform fleet**, then a
dispatch to the existing per-platform spawner. Because each launch gets a unique
explicit identity, the session is guaranteed non-conflicting — spin up a
parallel stream (e.g. audio) that never collides with the headless fleet.

It does **not** reimplement launch logic. Identity export, governance wiring,
the tmux spawn, and the runtime exec all stay in `hapax-claude` /
`hapax-codex`. `hapax-dev` only (a) picks a free identity,
(b) refuses collisions by construction, (c) guarantees a fresh session id, and
(d) handles visibility (attach / window / detach).

`antigrav` / `antigravity` is retired as a live dispatch platform, lane, route
family, and supply leaf. `hapax-dev agy`, `hapax-dev antigrav`, and
`hapax-dev antigravity` still fail closed in this dev launcher because there is
no `hapax-dev` Agy session path; Agy's methodology adapter support is live but
spawnable dispatch still requires a measured route with fresh
route/resource/governance receipts.

Recheck the admitted governed route set with:

```bash
uv run python scripts/hapax-methodology-dispatch --list-platform-paths
uv run pytest tests/scripts/test_hapax_dev.py -q
```

## Identities (interactive pools, distinct from the supervised fleet)

| Platform | Spawner | Interactive pool | tmux session |
|----------|---------|------------------|--------------|
| `claude` | `hapax-claude` | `dev`, `dev2`, `dev3`, … | `hapax-claude-<name>` |
| `codex`  | `hapax-codex`  | `cx-blue`, `cx-green`, `cx-cyan`, … | `hapax-codex-<name>` |

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
  Claim-cache writers must also keep the matching
  `~/.cache/hapax/cc-claim-epoch-<name>` sidecar in step, including
  session-keyed variants. The sidecar is written before the claim cache and
  stores `<epoch> <task_id>` so terminal checks can age unassigned claim-stamp
  drift without trusting claim-file mtime.
  Recheck a lane's sidecar contract with:
  `for f in ~/.cache/hapax/cc-active-task-<name>*; do k=${f##*/cc-active-task-}; printf '%s -> %s :: ' "$f" "$(head -n1 "$f")"; head -n1 ~/.cache/hapax/cc-claim-epoch-"$k"; done`.
  Emergency-only bypass: set `HAPAX_CLAIM_EPOCH_CHECK_BYPASS=1` only while
  repairing a sidecar writer; unset it after recreating the matching
  `cc-claim-epoch-*` files. The bypass does not override reassignment,
  closed-note, or merged-PR terminal states.
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
- **Workdir**: defaults to the current directory. Note that `codex`
  writes workspace rule files (`AGENTS.md`) into the workdir — pass
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
