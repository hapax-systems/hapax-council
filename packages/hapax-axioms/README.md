# hapax-axioms

Single-operator axiom enforcement library. Pre-commit and CI primitives
extracted from the Hapax constitutional substrate, packaged so any
single-operator project can adopt the same governance gates without
re-deriving them.

> **License: PolyForm Strict 1.0.0.** Noncommercial / personal-research
> use only; no redistribution and no derivative works. The full license
> text is in `LICENSE.txt`. See <https://polyformproject.org/licenses/strict/1.0.0>.

The package bundles a frozen snapshot of the five constitution-published
axioms — `single_user`, `executive_function`, `management_governance`,
`interpersonal_transparency`, `corporate_boundary` — along with the T0
regex patterns that gate structural multi-operator scaffolding and
generated-feedback-language code paths. The canonical, evolving source
of truth is the constitution repo:

> **Canonical source:** <https://github.com/hapax-systems/hapax-constitution>

## What this is

A single-operator system has exactly one authorised user, who is also
the developer. That posture rules out — by axiom — auth managers, role
hierarchies, multi-tenant scaffolding, consent layers over
operator-owned data, admin panels, and (for the management domain)
generated feedback or coaching language about identifiable team
members. The axiom set says these things in prose; this library
enforces them at the diff layer.

The same axioms ship across the Hapax stack as YAML in the
`hapax-constitution` repo (`axioms/registry.yaml`) and surface in the
council monorepo through `shared/axiom_*` modules and the
`hooks/scripts/axiom-*.sh` pre-tool / pre-commit hooks. This library
extracts the parts that have a clean reusable shape: the typed axiom +
implication + pattern models, the regex scanner, and a CLI suitable for
wiring into git hooks or CI.

## Install

```bash
uv add hapax-axioms          # uv (recommended)
pip install hapax-axioms     # pip, if you must
```

Requires Python 3.12 or newer.

## Library usage

```python
from hapax_axioms import (
    load_axioms,
    load_patterns,
    scan_text,
    scan_commit_message,
    scan_file,
)

# Inspect the bundled axiom snapshot.
bundle = load_axioms()
for ax in bundle.axioms:
    print(ax.id, ax.weight, ax.scope)

# Scan source code.
violations = scan_file("agents/something.py")
for v in violations:
    print(v.format())
    # [T0] single_user/su-auth-001 (line 17): 'class U.serManager' -- ...

# Scan a commit message body.
msg = open(".git/COMMIT_EDITMSG").read()
hits = scan_commit_message(msg)
if any(v.tier == "T0" for v in hits):
    raise SystemExit(2)
```

`scan_text`, `scan_file`, and `scan_commit_message` accept optional
`tier_filter=` and `axiom_filter=` arguments. `Pattern` and `Axiom`
models are Pydantic v2; they validate the bundled YAML at load time and
are also the schema downstream projects can use to author their own
bundles. Set `HAPAX_AXIOMS_PATH` / `HAPAX_AXIOMS_PATTERNS_PATH` in the
environment, or pass `path=` to the loaders, to point at a project-local
override.

## CLI usage

```bash
hapax-axioms list-axioms                     # print the bundled snapshot
hapax-axioms scan-file path/to/file.py       # one or many files
hapax-axioms scan-commit-msg .git/COMMIT_EDITMSG
```

Exit code is `2` on T0 hit, `1` on argv/IO error, `0` on clean scan.

### As a `commit-msg` git hook

```bash
# .git/hooks/commit-msg
#!/usr/bin/env bash
exec hapax-axioms scan-commit-msg "$1"
```

### As a `pre-commit` framework hook

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: hapax-axioms
        name: hapax-axioms scan
        entry: hapax-axioms scan-file
        language: system
        types: [text]
```

### In CI

```yaml
# .github/workflows/axiom-gate.yml
- name: Axiom gate
  run: |
    git diff --name-only origin/main...HEAD \
      | xargs -r hapax-axioms scan-file
```

## What's covered

The bundled patterns are T0 (block) only — the floor of axiom
enforcement. They cover:

| Axiom | Implications | What gets blocked |
| --- | --- | --- |
| `single_user` | `su-auth-001` | Auth managers, login/logout/register functions, permission-check helpers, auth-library imports |
| `single_user` | `su-feature-001` | Multi-tenant / collaboration / sharing scaffolding |
| `single_user` | `su-privacy-001` | Privacy/consent scaffolding for operator-owned data (note: non-operator data is governed by `interpersonal_transparency` and takes precedence by weight 88) |
| `single_user` | `su-security-001` | RateLimiter / UserQuota / AbusePrevention classes, role/permission token references |
| `single_user` | `su-admin-001` | AdminPanel / AdminDashboard / UserAdmin classes |
| `management_governance` | `mg-boundary-001`, `mg-boundary-002` | Functions or classes that generate feedback language, suggest what to say to a person, or recommend coaching about an individual |

The other constitutional axioms (`executive_function`,
`interpersonal_transparency`, `corporate_boundary`) are not covered by
T0 regex patterns in this bundle — they're enforced upstream through
runtime gates (consent registry, working-mode routing, employer-API
allowlists) and design-review canon. The bundled axiom YAML is included
so callers can reference the canonical text and weights when authoring
project-local rules.

## Refusal-as-data note

When this library blocks a change, the violation message is structured
data (axiom_id, implication_id, tier, matched_text). Downstream projects
are expected to log refusals into their own substrate so the operator
can audit them. The Hapax council does this via `shared/axiom_audit.py`;
this library deliberately ships no logging side-effects of its own.

## Authoring a project-local bundle

You can override either bundle by pointing the env vars at YAML files
that conform to `AxiomBundle` / `PatternBundle`:

```bash
export HAPAX_AXIOMS_PATH=/path/to/my-axioms.yaml
export HAPAX_AXIOMS_PATTERNS_PATH=/path/to/my-patterns.yaml
hapax-axioms scan-file file.py
```

The Pydantic models in `hapax_axioms.models` are the authoritative
schema — see the bundled YAMLs in
`src/hapax_axioms/data/{axioms,patterns}.yaml` for shape examples.

## Provenance

- Axiom bundle: snapshot of `axioms/registry.yaml` from
  <https://github.com/hapax-systems/hapax-constitution> taken on
  `2026-04-25`.
- Pattern bundle: snapshot of
  `hooks/scripts/axiom-patterns.sh` and `axioms/enforcement-patterns.yaml`
  from <https://github.com/hapax-systems/hapax-council> taken on `2026-04-25`.

Both upstreams remain canonical. PRs that change the axiom corpus go to
the constitution repo first; this package republishes a frozen snapshot
on each release.

## Citation

See `CITATION.cff` for BibTeX-equivalent citation metadata. Zenodo DOI
and Software Heritage SWHID land in CITATION.cff at first release tag
— the values currently in the file are placeholders.
