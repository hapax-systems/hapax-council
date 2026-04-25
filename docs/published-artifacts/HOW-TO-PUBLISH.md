# How to Publish — Operator Runbook

**Scope:** Operator-side workflow for rendering V5 audience artifacts
into publish-ready forms (markdown, HTML, eventually PDF) using the
shipped publish pipeline (#1439 + #1445 + #1457).

**Owner:** epsilon (V5 weave wk1 follow-on)
**Companion:** [README.md](README.md) — DOI index lifecycle and
directory shape

---

## Prerequisites

Three pieces of operator state. None require Claude Code; all are
one-time setup unless flagged otherwise.

### 1. Environment variables

Set these in `.envrc` (gitignored), `~/.config/fish/conf.d/hapax.fish`,
or wherever your shell config lives:

```bash
export HAPAX_OPERATOR_NAME="<your formal-context legal name>"
```

This name is interpolated into the V2 byline (operator + Hapax + Claude
Code) and the V4 byline (Hapax-canonical with operator-of-record). It
does NOT appear in source markdown — the pii-guard hook blocks legal
names there. The render pipeline reads from this env at publish time
and never writes it back to source.

**If unset:** the renderer falls back to the placeholder
`"The Operator"` and emits a warning. Useful for testing; not for
public publish-events.

### 2. ORCID iD (optional, for academic surfaces)

For Zenodo / OSF / Crossref publish-events that record per-author
ORCID iDs, store the iD in the password store:

```bash
pass insert orcid/orcid
# enter your NNNN-NNNN-NNNN-NNNN ORCID iD
```

The `shared.orcid.operator_orcid()` helper (#1430) reads from
`pass show orcid/orcid` and degrades gracefully when the key is
missing. Non-formal surfaces (omg.lol weblog, social posts) do not
require an ORCID — they use the operator-referent picker
(Oudepode / The Operator / OTO / Oudepode The Operator) instead.

### 3. Pandoc + (optional) LaTeX

Pandoc is required for HTML render and pre-installed in CI. For
local rendering on Arch:

```bash
pacman -S pandoc                              # required for HTML
pacman -S texlive-xetex texlive-fontsrecommended  # optional, for PDF
```

Pandoc HTML works without LaTeX. Pandoc PDF requires a LaTeX engine
(`xelatex` / `pdflatex`) on PATH.

---

## Render workflow

### Step 1 — Smoke test

Verify the renderer assembles the AttributionBlock for an artifact:

```bash
HAPAX_OPERATOR_NAME="<name>" uv run python scripts/render_constitutional_brief.py \
    docs/audience/constitutional-brief.md
```

Expected output:

```
surface: philarchive
byline: <name>, Hapax, Claude Code
byline_variant: V2
unsettled_variant: V3
unsettled_sentence: Whose voice you are reading is not finally settled — ...
non_engagement_clause: This artifact's distribution surfaces are constrained ...
```

If the output looks wrong (e.g., wrong surface, missing co-authors),
check the artifact's frontmatter `authors` block. The
`SURFACE_DEVIATION_MATRIX` entries live in
`shared/attribution_block.py`.

### Step 2 — Emit publish-ready markdown

```bash
HAPAX_OPERATOR_NAME="<name>" uv run python scripts/render_constitutional_brief.py \
    docs/audience/constitutional-brief.md \
    --emit-md docs/published-artifacts/constitutional-brief/v0.1.0/constitutional-brief.publish.md
```

The output carries:

- title heading (from frontmatter `title`)
- byline line (V0..V5 per matrix)
- italicized unsettled-contribution sentence (V1..V5 per matrix)
- artifact body (frontmatter-stripped, duplicate H1 deduped)
- non-engagement-clause footer (LONG or SHORT per matrix)

No YAML frontmatter is re-emitted. The publish-ready form is for
public consumption; frontmatter is operator-internal.

### Step 3 — Emit HTML (pandoc-native, no LaTeX needed)

```bash
HAPAX_OPERATOR_NAME="<name>" uv run python scripts/render_constitutional_brief.py \
    docs/audience/constitutional-brief.md \
    --emit-html docs/published-artifacts/constitutional-brief/v0.1.0/constitutional-brief.html
```

The HTML is self-contained (`--standalone`); the `<title>` element
matches the frontmatter title.

### Step 4 — Emit PDF (when LaTeX backend is installed)

```bash
pandoc docs/published-artifacts/constitutional-brief/v0.1.0/constitutional-brief.publish.md \
    --pdf-engine=xelatex \
    --output docs/published-artifacts/constitutional-brief/v0.1.0/constitutional-brief.pdf
```

Eisvogel template is optional but recommended for academic
publishing aesthetics:

```bash
# one-time install
mkdir -p ~/.local/share/pandoc/templates/
curl -L https://github.com/Wandmalfarbe/pandoc-latex-template/releases/latest/download/eisvogel.latex \
    > ~/.local/share/pandoc/templates/eisvogel.latex

# then on each render
pandoc <publish.md> --pdf-engine=xelatex --template=eisvogel \
    --output <out.pdf>
```

### Step 5 — Combine modes

Both `--emit-md` and `--emit-html` can be passed in a single
invocation:

```bash
HAPAX_OPERATOR_NAME="<name>" uv run python scripts/render_constitutional_brief.py \
    docs/audience/<artifact>.md \
    --emit-md docs/published-artifacts/<artifact>/v0.1.0/<artifact>.publish.md \
    --emit-html docs/published-artifacts/<artifact>/v0.1.0/<artifact>.html
```

Parent directories are created automatically; both files are
overwritten on each invocation.

---

## Three current V5 lead-with artifacts

| Artifact | Source | DOI subdir |
|---|---|---|
| Constitutional Brief | `docs/audience/constitutional-brief.md` | `docs/published-artifacts/constitutional-brief/v0.1.0/` |
| Aesthetic Library Manifesto | `docs/audience/aesthetic-library-manifesto.md` | `docs/published-artifacts/aesthetic-library-manifesto/v0.1.0/` |
| Self-Censorship as Aesthetic | `docs/audience/self-censorship-aesthetic.md` | `docs/published-artifacts/self-censorship-aesthetic/v0.1.0/` |

Each artifact's frontmatter declares its target surface deviation
matrix entry, byline variant, unsettled variant, and non-engagement
clause form. The renderer reads these declarations; it does not
require manual configuration per artifact.

---

## Operator review checklist

Before any public publish-event:

1. **Run the smoke test** for the artifact (Step 1 above) — confirm
   surface key, byline composition, unsettled sentence, and
   non-engagement clause are correct
2. **Read the publish-ready markdown** — verify title, byline,
   unsettled sentence, body content, non-engagement clause are
   coherent
3. **Render to HTML** — verify the HTML title element matches
   expectations and the body renders without markdown artifacts
4. **(Optional) Render to PDF** if academic surface — verify
   typography and pagination are acceptable for the target surface
5. **Verify polysemic-audit passes** —
   `uv run python scripts/verify-polysemic-audit.py`

---

## What this runbook does NOT do

- **Does not auto-publish.** The publish-bus orchestrator
  (`agents/publish_orchestrator/`) handles surface-specific
  publishing. This runbook produces the substrate the publishers
  consume.
- **Does not commit publish-ready files.** The render output
  carries the operator legal name (per `HAPAX_OPERATOR_NAME` env)
  and would trigger the pii-guard hook if committed without
  acknowledgement. The intended workflow is: render locally to
  `docs/published-artifacts/<artifact>/v0.1.0/`, validate,
  optionally commit (with operator's explicit acknowledgement),
  then trigger the publish-bus for the appropriate surfaces.
- **Does not mint DOIs.** Zenodo DOI minting happens at first
  successful publish-event via the orchestrator's
  `agents.zenodo_publisher` (per V5 weave wk1 PR #1425).

---

## Troubleshooting

### `surface: <key>` shows the wrong matrix entry

The artifact's frontmatter `authors.surface_deviation_matrix_key`
disagrees with the intended target surface. Update the frontmatter
to match a key in `SURFACE_DEVIATION_MATRIX`
(`shared/attribution_block.py`). Common keys: `philarchive`,
`omg_lol_weblog`, `lesswrong`, `bsky`, `mastodon`.

### `byline: The Operator` instead of legal name

`HAPAX_OPERATOR_NAME` env var is unset. Export it.

### Pandoc command not found

Install pandoc (`pacman -S pandoc` on Arch). Pandoc 3.x is the
tested target.

### `--emit-html` returns rc=3

Pandoc is not on PATH. The exit code distinguishes infrastructure
failure (rc=3) from source-error (rc=2) for operator scripts.

### Polysemic-audit fails on a new artifact

Three remediation paths: (1) rewrite the polysemic term to remain
in a single register; (2) add an explicit register-shift sentence
near the term; (3) add the term to
`polysemic_audit_acknowledged_terms` in the artifact's frontmatter
with a rationale. Option (3) is per-artifact, not blanket — see
the brief's frontmatter (`docs/audience/constitutional-brief.md`)
for an example.

---

## References

- Render scaffold: `scripts/render_constitutional_brief.py`
  (#1439, #1445, #1457)
- Byline module: `agents/authoring/byline.py` (#1406)
- Attribution block: `shared/attribution_block.py` (#1413, #1422)
- Polysemic audit: `agents/authoring/polysemic_audit.py` (#1409,
  #1454)
- DOI index: this directory's [README.md](README.md) (#1426)
- V5 weave plan:
  `~/.cache/hapax/relay/inflections/20260425T150858Z-beta-v5-workstream-weave.md`

— epsilon, V5 publish-bus operator-side runbook, 2026-04-25
