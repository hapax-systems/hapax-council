# Unused-Function Gate

`scripts/check-unused-functions.py` runs `vulture` as a prevention gate for new
dead callable definitions. It intentionally checks only callable-level findings
(`function`, `method`, `class`, `property`) and only when the reported definition
line is newly added in the staged diff or PR diff.

This avoids turning the existing legacy vulture inventory into a blanket
baseline. Current repo sweeps produce thousands of low-confidence findings,
mostly dynamic APIs, Pydantic fields, and older callable debt. The gate's job is
to keep that inventory from growing.

## Local Use

```bash
uv run python scripts/check-unused-functions.py --staged
uv run python scripts/check-unused-functions.py --base-ref origin/main
uv run python scripts/check-unused-functions.py --all
```

`--all` is for audits only; it is expected to report legacy findings until those
surfaces are retired or explicitly wired.

## Dynamic Entrypoints

Prefer one of these fixes, in order:

1. Delete the callable if it is genuinely unused.
2. Add the missing static call path if the callable should be used.
3. Add a narrow reference to `scripts/vulture_whitelist.py` only when the
   callable is invoked dynamically by a framework, subprocess entrypoint, import
   string, plugin registry, or similar path that vulture cannot see.

Do not add ordinary dead code to the whitelist. The whitelist is not a baseline.
