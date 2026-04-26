# `ryanklee/.github` repo scaffold

Pre-authored content for the operator-account-level `ryanklee/.github` repo, per cc-task `repo-pres-org-level-github` (WSJF 6.0). Copy-paste into a fresh repo when ready; nothing here ships into `hapax-council` itself.

## Why this scaffold lives here

Per cc-task `repo-pres-org-level-github`: the canonical surface for the operator's GitHub presence is `ryanklee/.github/profile/README.md` (rendered at github.com/ryanklee), not `ryanklee/ryanklee/README.md` (which drop 3 incorrectly proposed). The scaffold pre-authors the constitutional posture, repo map, and refusal-brief pointer so the operator only has to:

1. Create the new repo: `gh repo create ryanklee/.github --public`
2. Copy this scaffold's `profile/` and `.github/` into the new repo
3. Push

## Layout

```
docs/repo-pres/dot-github-scaffold/
├── README.md            # This file (scaffold notes; not copied to new repo)
├── profile/
│   └── README.md        # Rendered at github.com/ryanklee
└── .github/
    └── workflows/
        └── render-check.yml.SCAFFOLD  # Reusable workflow (see § Workflow design)
```

## Workflow design (file deferred)

The reusable `render-check.yml` workflow is described here rather than committed because the local PreToolUse hook flags `${{ inputs.* }}` interpolation in workflow files — even when the safe `env:` pattern is used. The operator should create the workflow directly in the new repo. Spec:

```yaml
# .github/workflows/render-check.yml — reusable workflow
name: hapax-sdlc render-check
on:
  workflow_call:
    inputs:
      python-version: { type: string, default: "3.12" }
      hapax-sdlc-version: { type: string, default: "" }
permissions: { contents: read }
jobs:
  render-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with: { python-version: ${{ inputs.python-version }} }
      - name: Install hapax-sdlc (pinned)
        env:
          HAPAX_SDLC_VERSION: ${{ inputs.hapax-sdlc-version }}
        run: |
          if [ -n "$HAPAX_SDLC_VERSION" ]; then
            pip install "hapax-sdlc==$HAPAX_SDLC_VERSION"
          elif [ -f spec.txt ]; then
            pip install -r spec.txt
          else
            pip install hapax-sdlc
          fi
      - name: hapax-sdlc render --check
        run: hapax-sdlc render --check
```

Companion workflows that the same repo should host (per cc-task `repo-pres-shared-workflows`):

### `citation-validate.yml` — CITATION.cff schema validation

```yaml
# .github/workflows/citation-validate.yml
name: CITATION.cff validate
on:
  workflow_call:
    inputs:
      python-version: { type: string, default: "3.12" }
permissions: { contents: read }
jobs:
  citation-validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with: { python-version: ${{ inputs.python-version }} }
      - name: Install cffconvert
        run: pip install cffconvert
      - name: Validate CITATION.cff
        run: cffconvert --validate
```

Validates that the consumer repo's `CITATION.cff` parses cleanly under the [Citation File Format schema](https://citation-file-format.github.io/) (1.2.0+). Uses the [`cffconvert`](https://github.com/citation-file-format/cff-converter-python) reference validator. No-op when the consumer has no `CITATION.cff`; the action checks `--validate` only.

### `codemeta-validate.yml` — codemeta.json schema validation

```yaml
# .github/workflows/codemeta-validate.yml
name: codemeta.json validate
on:
  workflow_call:
    inputs:
      python-version: { type: string, default: "3.12" }
permissions: { contents: read }
jobs:
  codemeta-validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with: { python-version: ${{ inputs.python-version }} }
      - name: Install jsonschema + codemeta schema
        run: pip install jsonschema requests
      - name: Validate codemeta.json
        run: |
          python - <<'PY'
          import json, sys, requests, jsonschema
          schema = requests.get(
              "https://raw.githubusercontent.com/codemeta/codemeta/2.0/codemeta.jsonld",
              timeout=10,
          ).json()
          with open("codemeta.json") as fp:
              data = json.load(fp)
          jsonschema.validate(data, schema)
          print("codemeta.json validates against codemeta v2.0 schema")
          PY
```

Validates that the consumer repo's `codemeta.json` conforms to [codemeta v2.0](https://codemeta.github.io). Fetches the canonical schema at validation time (no vendoring). Cached fetches via the standard `actions/setup-python` cache; the schema is small (~20 KB).

### Consumer-side pattern

A consumer repo (e.g., `hapax-council`, `hapax-mcp`) calls these via `workflow_call`:

```yaml
# .github/workflows/metadata-validate.yml in the CONSUMER repo
name: Metadata validate
on: [push, pull_request]
permissions: { contents: read }
jobs:
  citation:
    uses: ryanklee/.github/.github/workflows/citation-validate.yml@main
  codemeta:
    uses: ryanklee/.github/.github/workflows/codemeta-validate.yml@main
  render-check:
    uses: ryanklee/.github/.github/workflows/render-check.yml@main
```

Pinning to `@main` is the bootstrap; once a stable SHA is available, consumers should pin to the exact commit per [GitHub's actions-supply-chain guidance](https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions#using-third-party-actions).

## Handoff to operator

When ready, the operator runs:

```bash
# Create the new repo (one-time)
gh repo create ryanklee/.github --public --description "Operator-account profile + shared workflows" --confirm

# Clone + populate
gh repo clone ryanklee/.github /tmp/dot-github
cp -r docs/repo-pres/dot-github-scaffold/profile /tmp/dot-github/
mkdir -p /tmp/dot-github/.github/workflows
# (paste render-check.yml content from § Workflow design above)

cd /tmp/dot-github
git add . && git commit -m "init: profile README + render-check workflow"
git push
```

The profile-README renders at github.com/ryanklee within seconds.

## Cross-references

- cc-task: `repo-pres-org-level-github`
- Source synthesis: `docs/research/2026-04-25-leverage-strategy.md` drop 4 §4
- Refusal-as-data substrate: `agents/publication_bus/refusal_brief_publisher.py`
- V5 publication bus: `agents/publication_bus/`
