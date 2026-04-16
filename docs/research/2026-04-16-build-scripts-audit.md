---
title: build scripts + Makefile audit
date: 2026-04-16
queue_item: '314'
epic: lrr
phase: substrate-scenario-2
status: catalog
---

# Build scripts + Makefile audit

## Makefile

No `Makefile` at repo root.

## pyproject.toml build system

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.metadata]
```

## uv scripts + tool invocations (dev workflow)

```
[tool.pytest.ini_options]
```

## Repo-root shell build scripts


## scripts/build*

- `scripts/build_demo_kb.py`
- `scripts/install-claude-code.sh`
- `scripts/install-compositor-layout.sh`
