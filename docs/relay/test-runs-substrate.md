# Test-runs substrate (`~/.cache/hapax/relay/test-runs/`)

Per cc-task `full-test-output-substrate`. Long or full-suite test runs need
to be auditable across sessions — not as fragile terminal scrollback, but
as a durable on-disk path a handoff can cite.

## The wrapper

```sh
scripts/run-with-test-substrate.sh [--label SLUG] -- <cmd> [args...]
```

Drop-in around any command. Captures everything to a substrate directory
under `~/.cache/hapax/relay/test-runs/<iso-timestamp>-<short-cwd>[-<label>]/`
and exits with the wrapped command's exit code.

## Layout

Each substrate directory contains:

| File                  | Contents                                               |
|-----------------------|--------------------------------------------------------|
| `cmd`                 | The exact argv (one per line)                          |
| `cwd`                 | Absolute working directory at invocation               |
| `git_head`            | `git rev-parse HEAD` (if cwd is a git tree)            |
| `git_branch`          | `git rev-parse --abbrev-ref HEAD`                      |
| `git_dirty.txt`       | `git status --short` snapshot (empty if clean)         |
| `stdout.log`          | Captured stdout                                        |
| `stderr.log`          | Captured stderr                                        |
| `exit_code`           | Numeric exit code                                      |
| `start_time`          | ISO 8601 UTC                                           |
| `end_time`            | ISO 8601 UTC                                           |
| `pytest_lastfailed`   | Snapshot of `.pytest_cache/v/cache/lastfailed` if any  |
| `env.txt`             | HAPAX_*, CLAUDE_*, USER, HOME, PATH, PWD only          |

Override the substrate root with `HAPAX_TEST_SUBSTRATE_ROOT` (used by tests).

## Hygiene for handoffs

When closing a session that ran a long test suite, paste the substrate path
into the handoff doc instead of the test output itself:

```markdown
> Last full test run: `~/.cache/hapax/relay/test-runs/20260501T050000Z-hapax-council-pre-merge-pr1952/`
> Exit: see `exit_code`. Failing tests: see `pytest_lastfailed`.
```

A receiving session can then `cat` the substrate files directly without
parsing terminal scrollback.

## Examples

```sh
# Wrap pytest:
scripts/run-with-test-substrate.sh --label pre-pr1952 -- uv run pytest tests/shared -q

# Wrap a build:
scripts/run-with-test-substrate.sh --label rebuild-logos -- pnpm tauri build

# Wrap an arbitrary script:
scripts/run-with-test-substrate.sh -- ./scripts/audit-audio-topology.sh
```
