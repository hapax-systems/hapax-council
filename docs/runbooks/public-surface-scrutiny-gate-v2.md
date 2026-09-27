---
title: "Public Surface Scrutiny Gate V2"
date: 2026-05-13
authority_case: REQ-20260513-token-capital-public-surface-regate-v2
status: runbook
mutation_surface: source_docs
---

# Public Surface Scrutiny Gate V2

Run this gate before publishing weblog or `hapax.omg.lol` copy.

```bash
uv run python scripts/github-public-surface-reconcile.py
uv run python scripts/publication-freshness-audit.py --fail-on-blockers
uv run python scripts/check-public-surface-claims.py --warnings-fail \
  --token-claim-report docs/research/evidence/2026-05-13-token-capital-claim-regate-v2.json \
  --source-reconciliation docs/research/evidence/2026-05-13-public-surface-source-of-truth-reconciliation.json \
  --publication-freshness-state ~/hapax-state/publication/freshness-state.json
```

For PR release authorization when the PR itself adds a required public file
that is not yet visible on GitHub default-branch readback, derive the freshness
state without `--fail-on-blockers`, then run the claim gate in normal live mode:

```bash
uv run python scripts/github-public-surface-reconcile.py
uv run python scripts/publication-freshness-audit.py
uv run python scripts/check-public-surface-claims.py --warnings-fail \
  --publication-freshness-state ~/hapax-state/publication/freshness-state.json
```

The claim gate performs its own fresh GitHub public-surface reconcile by default
before deriving required freshness witnesses. The committed
`docs/repo-pres/github-public-surface-live-state-reconcile.json` is an evidence
snapshot and offline shape fixture, not the release trust root.
`--skip-live-github-public-surface-refresh`, custom
`--github-public-surface-report`, and explicit
`--required-publication-freshness-surface-id` arguments are diagnostic/test-only
paths; with `--warnings-fail`, offline diagnostic mode cannot authorize release.
If a locally supplied required file removes only the `release_authorized` block,
the gate exits cleanly with an `info` finding and still requires post-merge
readback before any `public_current` claim.

Default targets are:

- `agents/omg_web_builder/static/index.html`
- `docs/publication-drafts`

Exit codes:

- `0`: no blocking findings.
- `1`: public copy violates the deterministic claim ceiling, the current source
  reconciliation has unreconciled live items, or publication freshness has
  public-current blockers.
- `2`: a required machine-readable receipt is missing or malformed.

The gate consumes the Token Capital claim re-gate receipt, the public-surface
source-of-truth reconciliation receipt, and the publication freshness snapshot
from `scripts/publication-freshness-audit.py`. It is not a replacement for
legal, privacy, entity, citation, or operator override review.

## Built site pages (R8 register carriage)

The registry names the *sources*. A built public-site output is a second,
separate surface: R8's spec call-out for the site's `verify-dist`. The gate
scans built pages by block units — a `<li>` or `<blockquote>` holding `<p>`s
yields the paragraphs, not one merged unit — and runs the register carriage
lint (`Hapax.RegisterCarriage`, the six devices of the HACA-C §Register
amendment) over them beside `Hapax.FormalRegister`.

The canonical, reproducible invocation over a built output is:

```bash
uv run python scripts/check-public-surface-claims.py --warnings-fail \
  --built-site-dir "$HOME/projects/hrl-portal/dist"
```

`--built-site-dir` is repeatable and is named explicitly, so naming a directory
that is missing fails loudly rather than scanning nothing. A host that holds the
site checkout may instead export the default:

```bash
export HAPAX_PUBLIC_SITE_DIST="$HOME/projects/hrl-portal/dist"   # pathsep-separated
```

An env-provided directory is included only when it exists, so a host without the
site checkout is not a false failure. The site repo's own `scripts/verify-dist.mjs`
owns its dist pins; this gate is the source-side check that reads the same built
pages. The register findings are `warning` level (over-inclusive by design; every
hit is disposed fix / keep-with-reason / carry), so add `--warnings-fail` on the
release path to make them block.

The parser is chosen by file extension (`.html`/`.htm` are HTML; everything else
is text). It is deliberately *not* chosen by content: a Markdown draft that
mentions `<p>` must still be read as text, or its paragraphs are skipped and the
gate passes it silently.
