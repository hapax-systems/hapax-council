# CC Task Vault Shape Smoke

Use this smoke when recovery, handoff, or coordination work depends on the real
cc-task vault being structurally sane before lanes are relaunched or reassigned.

Run it after:

- task note migrations or bulk edits under `hapax-cc-tasks`
- `cc-claim`, `cc-close`, or dashboard generation changes
- recovery from interrupted parent-to-child sends
- suspected drift between active, closed, refused, and dashboard notes
- handoff work where a stale or malformed task note would block session flow

Command:

```bash
uv run python scripts/check-cc-task-vault-shape.py
```

The script defaults to the real vault at
`~/Documents/Personal/20-projects/hapax-cc-tasks`. It only reads task and
dashboard notes. It does not rewrite frontmatter, move files, regenerate
dashboards, or update relay state.

The default mode fails on structural errors and prints warnings for legacy or
known-cleanup status drift that should be reconciled but does not need to block
all recovery work. Use strict mode when the handoff requires a clean vault:

```bash
uv run python scripts/check-cc-task-vault-shape.py --strict
```

For diagnostic output that can be attached to a relay note or PR:

```bash
uv run python scripts/check-cc-task-vault-shape.py --json
```

The smoke fails on missing required directories, malformed task frontmatter,
duplicate task IDs across `active`, `closed`, and `refused`, missing required
frontmatter for each collection, unknown task statuses, invalid refused
automation status, collection fields that are not YAML lists, and missing
dashboard notes or markers required for coordination queries. Strict mode also
fails on warnings, including terminal task statuses still present in `active`.

If it fails during recovery or handoff, treat the output as a read-only
diagnostic first. Record the exact failing note and check in the task relay or
claim note before deciding whether a targeted vault repair is in scope.
