# Repository instruction binding

Author repository instructions in `AGENTS.md`. The root `CLAUDE.md` is a relative
symlink to `AGENTS.md`, not a second policy document. Edit the target directly.
Keep native-specific guidance explicit inside the canonical document where it
changes how a capability works.

The symlink is deliberate: estate filesystem readers of `CLAUDE.md` must continue
to receive the instruction body. A file containing only `@AGENTS.md` works for
Claude's import loader, but those readers would see only the import directive.
Git-blob readers must read `AGENTS.md`: `git show HEAD:CLAUDE.md` returns the link
target name, not the target body. The monthly audit handles this explicitly.

Claude documents this binding, including deduplication and instruction-load hook
behavior: [Claude memory documentation](https://code.claude.com/docs/en/memory#share-one-file-with-other-coding-tools).
It also works when direct AGENTS discovery is unavailable or a CLAUDE file takes
precedence. There is no need to enable a new plugin setting for this migration.

This binding targets the estate's Linux checkouts and Linux containers. Preserve
symlinks when building an image or copying the source. On Windows without Git
symlink support, use a native `@AGENTS.md` import and adapt raw readers; do not
claim that a plain-text link target is an equivalent checkout. Existing nested
instruction files and global bindings retain their own scopes.

## Verification and limits

- Confirm `readlink CLAUDE.md` is `AGENTS.md` and both filesystem reads return the
  same bytes. A Git checkout must preserve mode `120000` for the alias.
- Run the focused instruction-binding, governance-path, launcher and rotation
  tests. Rotation discovery, pre-commit selection and CI must cover both names.
- Exercise the installed native loader where available, including a nested cwd
  and its actual trust configuration. Retain version, configuration, discovered
  paths and content evidence. Do not change repository trust merely to get a pass.
- Check a fresh Claude session's instruction-load evidence before treating the
  binding as observed there. Existing sessions can retain old context until a
  fresh load. A successful filesystem check is not a measured Claude session.

Instruction delivery is not semantic compliance. An agent restating a rule is
not evidence it followed it, and filename agreement does not establish equivalent
precedence, trust, imports, context budgets, hooks or tool authority across engines.
Future containerization must declare those bindings alongside state and service
access; an image alone does not freeze the resulting capability.

The wider variation-reduction assessment and implementation receipts are in the
operator's vault at `30-areas/hapax/frame/harness-variation-reduction-agents-md-assessment-20260920.md`.
