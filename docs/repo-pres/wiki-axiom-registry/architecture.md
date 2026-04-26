# Wiki-as-Axiom-Registry — `hapax-constitution` only

**cc-task:** `repo-pres-wiki-axiom-registry` (WSJF 3.6)
**Composed:** 2026-04-26
**Target repo:** `hapax-constitution` (this scaffold lives in council; the actual wiki content is operator-applied to hapax-constitution)

## Premise

GitHub Wiki defaults are noisy: most repos enable Wiki and produce no content, leaving an orphan tab in the navbar. Hapax's policy is to disable Wiki everywhere except `hapax-constitution`, where it is repurposed as the **axiom registry surface** — the canonical reading view of the constitution's axioms + implications + canons.

The `axioms/` directory in `hapax-constitution` is the source-of-truth (`registry.yaml` + per-axiom `implications/` markdown + `contracts/` artifacts). The wiki is a derived view: each axiom gets one wiki page, each implication gets one, each canon gets one. The wiki pages are auto-rendered from the source markdown by a CI workflow on push to `main`.

## Why GitHub Wiki specifically

- Wiki has its own `clone`-able git repo (`<repo>.wiki.git`) — automation can push generated content without polluting the constitution repo's main branch
- Wiki pages get a separate URL space (`github.com/ryanklee/hapax-constitution/wiki/<slug>`) that's stable + cite-able
- Wiki search is its own surface — separate from code search; useful when a reader is hunting for an axiom by content rather than by name
- Wiki pages render markdown identically to repo READMEs but support inter-page wikilinks (`[[axiom-single-user]]`) which the source markdown doesn't

## Page taxonomy (proposed)

```
hapax-constitution.wiki/
├── Home.md                              # Index: 5 axioms + implication count + canon count
├── axiom-single-user.md                 # weight=100; each axiom is a top-level page
├── axiom-executive-function.md          # weight=95
├── axiom-corporate-boundary.md          # weight=90
├── axiom-interpersonal-transparency.md  # weight=88
├── axiom-management-governance.md       # weight=85
├── implication-<axiom>-<slug>.md × N    # one per implication entry in implications/
├── canon-<slug>.md × N                  # one per canon entry
├── contract-<slug>.md × N               # one per consent contract
└── _Sidebar.md                          # auto-generated nav by axiom-weight
```

Slugs follow the `axiom-<name>` / `implication-<axiom>-<name>` pattern so cross-references in source can be resolved by string-rewrite at render time.

## Render workflow (lives in hapax-constitution)

```yaml
# .github/workflows/render-wiki.yml — CI workflow in hapax-constitution
name: Render axiom-registry wiki
on:
  push:
    branches: [main]
    paths:
      - "axioms/**"
permissions:
  contents: write  # for the wiki push
jobs:
  render:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-python@v6
        with: { python-version: "3.12" }
      - name: Install hapax-axioms (rendered surface)
        run: pip install hapax-axioms  # depends on leverage-workflow-hapax-axioms-pypi cc-task
      - name: Render axiom registry to wiki Markdown
        run: hapax-axioms render-wiki --output /tmp/wiki-pages
      - name: Push to wiki
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          git clone "https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.wiki.git" /tmp/wiki
          cp /tmp/wiki-pages/*.md /tmp/wiki/
          cd /tmp/wiki
          git add -A
          if git diff --cached --quiet; then
            echo "no wiki changes"
          else
            git -c user.name="hapax-bot" -c user.email="noreply@anthropic.com" commit -m "render: axiom registry from main@$(echo $GITHUB_SHA | head -c 7)"
            git push
          fi
```

Render command (`hapax-axioms render-wiki`) is part of the same `hapax-axioms` PyPI package the AAIF donation depends on (`leverage-workflow-hapax-axioms-pypi` cc-task). Reads the `axioms/` directory, applies the slug rules, emits flat Markdown for the wiki tree.

## Anti-pattern guard

Wiki is enabled on no other repo. The hapax-council CODEOWNERS + repo-settings guard (still pending — `repo-pres-issues` cc-task) should include:

```yaml
repos:
  - hapax-council:    { wiki: false }
  - hapax-officium:   { wiki: false }
  - hapax-watch:      { wiki: false }
  - hapax-phone:      { wiki: false }
  - hapax-mcp:        { wiki: false }
  - distro-work:      { wiki: false }
  - hapax-constitution: { wiki: true }   # axiom-registry surface
```

`gh repo edit ... --enable-wiki=false` enforces it via API; CI lints check the desired state.

## Operator handoff

When ready, in the hapax-constitution repo:

1. Enable wiki on hapax-constitution: `gh repo edit ryanklee/hapax-constitution --enable-wiki`
2. Initialise wiki with a placeholder Home page (one-time, via web UI)
3. Drop in the render workflow at `.github/workflows/render-wiki.yml` (per § Render workflow above)
4. Tag the first commit that touches `axioms/` to trigger the workflow + populate the wiki tree

The render workflow is idempotent — it diffs before pushing, so re-runs are no-ops if axioms/ hasn't changed.

## Disable wiki on the other 6 repos (separate operator-action queue item)

```bash
for repo in hapax-council hapax-officium hapax-watch hapax-phone hapax-mcp distro-work; do
  gh repo edit "ryanklee/$repo" --enable-wiki=false
done
```

This is a one-shot operator command; can also be wrapped in a script when `repo-pres-issues` cc-task ships its repo-settings management surface.

## Constitutional posture

- `single_user`: Wiki on hapax-constitution makes axioms cite-able; Wiki off everywhere else avoids surface-creep.
- `feedback_full_automation_or_no_engagement`: render workflow is fully automated; no manual wiki-edits.
- `interpersonal_transparency`: wiki contains only the constitutional substrate, no operator-personal content.

## Cross-references

- Axiom registry source: `axioms/registry.yaml` (in hapax-constitution)
- PyPI package dependency: `leverage-workflow-hapax-axioms-pypi` cc-task
- Repo-settings management: `repo-pres-issues` cc-task (parent dependency)
- Org-level `.github` scaffold (parallel surface): `docs/repo-pres/dot-github-scaffold/` (PRs #1669, #1682)

— alpha
