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

Companion workflows that the same repo should host:
- `citation-validate.yml` — validates `CITATION.cff` against [citation-file-format/cff-converter](https://github.com/citation-file-format/cff-converter-python)
- `codemeta-validate.yml` — validates `codemeta.json` against [codemeta/codemeta-generator](https://codemeta.github.io)

Both follow the same `workflow_call` shape and are intentionally minimal — they exist only to be `uses:`-referenced from consumer repos like `hapax-council`, `hapax-officium`, etc.

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
