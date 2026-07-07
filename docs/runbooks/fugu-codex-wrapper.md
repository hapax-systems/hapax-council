# Governed Fugu Codex Wrapper

The governed Sakana Fugu path is `scripts/reins-fugu` or `scripts/reins-fugu-ultra`, which delegates to `scripts/hapax-codex --fugu-profile ...`. It is distinct from any raw `codex-fugu` or direct Codex invocation: the Hapax wrapper pins the Sakana provider, model, endpoint, wire API, local task hooks, secret source, and PATH-resolved `codex` executable before launching Codex.

Raw Codex invocations must not be used as review or task evidence for this path. They do not prove the governed launcher loaded the reviewed profile, refused remote dispatch, rejected `HAPAX_CODEX_BIN_PATH` executable overrides, or kept `SAKANA_API_KEY` inside the local Codex process boundary.

## Required Local Inputs

- `pass:sakana/api-key` must contain the Sakana API key.
- A reviewed Codex model catalog is mandatory. `HAPAX_CODEX_FUGU_MODEL_CATALOG` may override the path; if unset, the wrapper uses `~/.codex/fugu.json`.
- The catalog must be JSON shaped as either a list of model objects or an object with a `models` list. Each model object should expose `slug`, `id`, or `model`; the governed profiles require entries for `fugu` and `fugu-ultra`.

Minimal catalog:

```json
{"models":[{"slug":"fugu"},{"slug":"fugu-ultra"}]}
```

## Rechecks

Run these from the council worktree before treating a Fugu launch as ready:

```bash
scripts/reins-fugu --check
scripts/reins-fugu-ultra --check
scripts/reins-fugu --print-env
```

The check output redacts the secret value, reports `raw_codex_fugu_bypass=false`, reports the PATH-resolved `codex_binary=...`, and exits nonzero with next-action text when the worktree, catalog, pass entry, endpoint, wire API, executable boundary, or hook setup is unsupported. For `--check`, exit code `1` means readiness or Fugu configuration failed, `2` means wrapper syntax/profile, caller passthrough override, or `HAPAX_CODEX_BIN_PATH` executable override was refused, `3` means the selected worktree is unavailable, and `14` means remote dispatch was refused. Exit code `7` means launch-time secret load failure after readiness checks.

Negative boundary rechecks:

```bash
scripts/reins-fugu --check -- --model gpt-5.5
scripts/reins-fugu --fugu-profile fugu-ultra --print-env
REINS_FUGU_PROFILE=fugu-ultra scripts/reins-fugu --print-env
HAPAX_DISPATCH_HOST=appendix scripts/reins-fugu --print-env
DISPATCH_HOST=appendix scripts/reins-fugu --print-env
HAPAX_CODEX_BIN_PATH=/tmp/codex-fugu scripts/reins-fugu --check
HAPAX_CODEX_FUGU_SECRET_ENTRY=github/pat scripts/reins-fugu --check
tmpbin="$(mktemp -d)"; printf '#!/usr/bin/env bash\nexit 1\n' > "$tmpbin/pass"; chmod +x "$tmpbin/pass"; PATH="$tmpbin:$PATH" scripts/reins-fugu --role cx-fugu
```

The explicit profile override, remote-dispatch, executable-override, unsupported secret-entry, and launch-time missing-pass commands must fail without printing secret values. The `REINS_FUGU_PROFILE=...` environment override command should succeed while still printing the pinned shim profile (`fugu` for `scripts/reins-fugu`, `fugu-ultra` for `scripts/reins-fugu-ultra`). The unsupported secret-entry recheck must fail before reading the caller-selected pass entry. The final launch-time command is an exit-code-7 boundary recheck that shadows `pass` with a failing shim while leaving PATH-resolved `codex` behavior otherwise governed.

## Boundary Rules

Fugu mode refuses caller-supplied Codex passthrough arguments. Do not pass `-c`, provider/model flags, remote-control flags, future Codex aliases, or prompt text through the wrapper. Use the governed profile inputs above instead. Fugu mode also refuses `HAPAX_CODEX_BIN_PATH`; expose the supported Codex CLI as `codex` on PATH rather than selecting an executable through environment fallback. The Reins shims also refuse caller `--fugu-profile` overrides so `reins-fugu` and `reins-fugu-ultra` remain pinned entrypoints.

Fugu mode also refuses `HAPAX_DISPATCH_HOST`; pass-backed Sakana credentials are loaded only for the local terminal-none Codex exec. For visible `tmux` or `foot` launches, the outer control process writes a runner that re-enters the wrapper, and the inner local Codex process loads `SAKANA_API_KEY`.
