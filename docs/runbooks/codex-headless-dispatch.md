# Codex Headless Dispatch

`scripts/hapax-codex-headless` is the governed `codex exec` launcher for `cx-*`
lanes. It must not create or repair remote worktrees until the local dispatch has
passed the task/claim gate and the single-live-lane PID guard.

Remote appendix dispatch uses this order:

1. validate the session name, relay state, local worktree, hook adapter, task/claim,
   and live PID guard;
2. bootstrap the default remote session worktree if it is missing and
   `HAPAX_CODEX_CREATE_WORKTREE=1`;
3. run remote preflight for required directories, hook adapter, `python3`, and
   `codex`;
4. execute `codex exec` on the remote host.

Default worktrees are constructive: if `$HOME/projects/hapax-council--<cx-session>`
is missing on the dispatch host, the launcher may create it from the remote primary
council checkout using branch `codex/<cx-session>`.

Explicit workdirs are not constructive. If `HAPAX_CODEX_HEADLESS_WORKDIR` is set,
that exact path must already exist locally and remotely. A missing explicit path
fails closed; unset the variable or create the path deliberately before retrying.

Remote bootstrap failures print the failing branch and a next action. Check:

- target worktree path;
- remote primary council checkout;
- `git` on the dispatch host;
- `HAPAX_CODEX_CREATE_WORKTREE`;
- `HAPAX_CODEX_WORKTREE_BASE` if a non-default base was requested.
