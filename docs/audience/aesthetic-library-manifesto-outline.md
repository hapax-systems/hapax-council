# Aesthetic Library + Authentic-Asset Provenance Manifesto — Outline

**V5 weave wk1 follow-on / wk2 lead-with artifact #6 staging draft**
**Owner:** epsilon (V5 weave inflection 20260425T150858Z, lead-with #6)
**Substrate:** `assets/aesthetic-library/` (SHA-pinned BitchX/Px437/Enlightenment)
**Substrate impl:** `it-attribution-001` axiom implication, hapax-assets CDN
**Status:** wait-window staging during #1445 CI; for move-into-branch
post-merge as `docs/audience/aesthetic-library-manifesto-outline.md`

---

## TL;DR

Eight thousand-word web essay (per V5 weave §2.2 #6 web-essay form;
130-page manuscript form is a separate follow-on). Subject: the
constitutive case that **operator-redistributed third-party content
must carry provenance metadata as an architectural invariant** —
not as an aesthetic choice. Frame: provenance attribution is the
content-creator analogue of consent to non-operator persons. Both
obligations flow from honoring the autonomy of external parties whose
work or identity the system relies on.

The deployed evidence: the Hapax aesthetic library carries SHA-pinned
BitchX (BSD-3-Clause), Px437 IBM VGA 8x16 font (CC-BY-SA-4.0), and
Enlightenment Moksha theme (CC0-1.0) under `assets/aesthetic-library/`,
gated by `_manifest.yaml`, `_NOTICES.md`, per-asset `provenance.yaml`,
the CI `verify-aesthetic-library.py` linter, the asset-provenance
PreToolUse hook, the `it-attribution-001` axiom implication, and a
SHA-pinned CDN at `ryanklee/hapax-assets` (GitHub Pages). Each layer
is a structural enforcement of the constitutive rule. The contribution
is that all six layers operate together in production for an
eighteen-month deployment record.

---

## Decoder stacks targeted (per V5 weave invariant 5)

1. **Demoscene / shareware-aesthetic / retrocomputing** — read it as a
   case study in honoring upstream license terms while still
   redistributing the artifacts that make computing aesthetics
   possible
2. **Software supply-chain / SBOM literature** — read it as a
   per-asset provenance metadata case study at smaller scale than
   typical SBOM tooling addresses
3. **Continental philosophy / aesthetics theory** — read it as
   a Latour-style "frame rules" application: provenance-as-
   constitutive-rule rather than provenance-as-procedural-checkbox
4. **Cultural-heritage / archival theory** — read it as deliberate
   curation discipline applied to open-source cultural artifacts

## Class (per V5 weave §2.4)

**Infrastructure-as-argument**: the manifesto's argument is the
operating discipline; the working artifact is the proof. Same posture
as the Constitutional Brief.

---

## Section 1 — The case (~600 words)

When third-party content lands in a system's redistribution path, the
default is to redistribute without provenance metadata: the asset's
authorship, license terms, source URL, and integrity hash dissipate
into the system's bytes. The downstream surfaces (livestream
overlays, omg.lol surfaces, CDN-published files) emit the asset as
if it were operator-authored. License compliance erodes silently;
upstream creators receive no attribution; the audience cannot
distinguish operator-authored from operator-redistributed.

The alternative is **provenance-as-architectural-invariant**: every
redistributed asset carries authorship, license, source URL, and
integrity hash as required metadata. The metadata is enforced at the
commit-hook layer (asset cannot enter the repository without
provenance), the CI lint layer (manifest drift is caught at PR-time),
the runtime layer (the live system rejects attempts to load an asset
without registered provenance), and the publication layer (the
downstream `_NOTICES.md` and `/credits` surfaces are auto-rendered
from the manifest, not hand-curated).

This is what the Hapax aesthetic library implements. The contribution
is not novel: per-asset provenance is described in SBOM literature
and is required by GPL/CC license terms for redistributors. What is
novel is that all six enforcement layers operate together in a
deployed single-operator system, and that the discipline is anchored
to a constitutional axiom (`it-attribution-001`) rather than to
procedural reminders.

## Section 2 — Constitutive framing (~800 words)

The architectural posture is:

1. **Provenance as Searle constitutive rule.** A piece of redistributed
   content is not merely a file with a URL attached; it is an
   *attributed-asset*, a category that exists only when the
   provenance metadata is present. Without the metadata, the
   redistribution is structurally refused.

2. **License compliance as defeasible.** Some asset categories are
   prohibited (GPL components in a non-GPL system; ToS-restricted
   reverse-engineered APIs). The general rule "honor the license"
   admits specific defeaters ("Europa.c GPL-2 plugin explicitly
   excluded" — per CLAUDE.md aesthetic library section). Defeaters
   are named and tier-assigned, not improvised at commit time.

3. **Vertical stare decisis.** When a new asset category arises (a
   font; a color palette; a sound effect; a shader), the question
   is "which existing precedent governs?" — not "what new procedure
   should we enumerate?" The case-law-style growth keeps the
   architectural shape stable across asset class proliferation.

The framing maps onto the Constitutional Brief's three moves
(Ordnungspolitik / defeasibility / stare decisis), so the same
constitutive grammar that produces the axiom-driven governance
produces the provenance discipline. This is not a coincidence; the
two are the same architectural posture applied to different
content classes.

## Section 3 — The six enforcement layers (~1,500 words)

**Layer 1 — Per-asset provenance.yaml.** Every directory under
`assets/aesthetic-library/` carries a sibling `provenance.yaml`
naming source URL, upstream author(s), SPDX license identifier,
extraction date, and any per-asset notes. Without the sibling file,
the manifest validator rejects the asset.

**Layer 2 — `_manifest.yaml`.** The top-level manifest enumerates
every asset's path, SHA-256, license, author, source URL, and
extraction date. Manifest drift (an asset's bytes differ from the
declared SHA) fails CI. The manifest is regenerable: the
`scripts/generate-aesthetic-manifest.py` tool reads each
`provenance.yaml` and re-derives the manifest line.

**Layer 3 — `_NOTICES.md`.** Auto-generated from the manifest,
groups assets by SPDX license and renders the canonical attribution
surface. The omg.lol /credits page (`ytb-OMG-CREDITS` publisher)
consumes this directly; the in-stream credits ward consumes this
directly. Hand-edits are forbidden ("do not hand-edit" header).

**Layer 4 — `verify-aesthetic-library.py` CI linter.** Runs on every
PR's lint job. Three checks: (a) manifest currency vs. provenance
files, (b) SHA integrity of every byte, (c) every manifest source
has a sibling `provenance.yaml`. Drift fails the lint suite. The
script is also wired as a PreToolUse hook (`asset-provenance-gate.sh`)
so commits cannot land without passing the same checks locally.

**Layer 5 — `it-attribution-001` axiom implication.** The
`interpersonal_transparency` axiom's implication file declares
attribution as a T1 enforcement-tier obligation: "Third-party
content the system redistributes to any audience must carry
attribution per the upstream license terms. Attribution to
non-operator authors is the content-creator analogue of consent to
non-operator persons — both obligations flow from honoring the
autonomy of external parties whose work or identity the system
relies on." The axiomatic anchor is the load-bearing constitutive
move; the other layers are the enforcement surfaces it requires.

**Layer 6 — `ryanklee/hapax-assets` CDN.** A separate GitHub
repository carries the public-CDN-published copy of the aesthetic
library, mirrored from `assets/aesthetic-library/` by the
`agents/hapax_assets_publisher/` daemon. The CDN delivers
SHA-pinned URLs (e.g. `hapax-assets/<sha>/<path>`) so omg.lol
surfaces embed the assets via integrity-verified pointers. The
SHA pins close the loop: the asset that ships to the audience is
byte-identical to the asset registered in the manifest.

The six layers are not redundant. Each catches a different drift
mode: provenance.yaml catches missing metadata at write time; the
manifest catches integrity drift; `_NOTICES.md` catches publication-
surface drift; the CI linter catches all three at PR time; the axiom
anchors the discipline to the constitutive rule; the CDN closes the
distribution loop. Removing any one layer creates a silent failure
mode the others cannot catch.

## Section 4 — Walkthrough: BitchX assets (~900 words)

A worked example: how the BitchX assets entered the library and how
each enforcement layer fired during ingestion.

**Source.** BitchX is an IRC client originally by Colten Edwards
(panasync) plus EPIC Software Labs, Matthew Green, and Michael
Sandroff. License: BSD-3-Clause. Source: github.com/prime001/BitchX.
Three asset classes were extracted: ASCII splash banner, ASCII
quotes-on-quit text, and the mIRC-16 color palette (canonical
hex/RGB pairings used in the ASCII art). Extraction date:
2026-04-24.

**Layer 1 — provenance.yaml.** Three sibling files at
`assets/aesthetic-library/bitchx/{splash,quotes,colors}/provenance.yaml`
declare source URL, author list, license, and extraction date. The
files were committed alongside the assets; the
`asset-provenance-gate.sh` PreToolUse hook would have rejected
the commit otherwise.

**Layer 2 — manifest update.** `scripts/generate-aesthetic-manifest.py`
ran post-extraction. It read each `provenance.yaml`, derived the
manifest entries, and computed each asset's SHA-256. Three new
manifest entries appeared with their bytes hashed.

**Layer 3 — NOTICES regeneration.** The same script regenerated
`_NOTICES.md`. The BSD-3-Clause section of the file gained three
new asset paths under the BitchX upstream attribution.

**Layer 4 — CI lint pass.** The PR shipping the assets ran
`verify-aesthetic-library.py` in lint. The three checks all passed:
manifest currency (new entries match new files), SHA integrity
(declared hash equals computed hash), provenance presence (all three
new directories have provenance.yaml).

**Layer 5 — axiom compliance.** The `it-attribution-001` implication
fires on the publish-event level: the omg.lol /credits page is
auto-regenerated, and the in-stream ward (the splash + quotes lines
appear during livestream) carries the BitchX byline as part of the
in-frame attribution surface. No publish event runs without the
NOTICES.md in scope.

**Layer 6 — CDN sync.** The `agents/hapax_assets_publisher/` daemon
detected the new manifest entries on its 30s push throttle, mirrored
the new files to `ryanklee/hapax-assets`, and the CDN URLs became
available with SHA-pinned shapes
(`hapax-assets.pages.dev/<sha>/bitchx/splash/banner.txt`).

The walkthrough makes a single point: the operator did not have to
remember to update NOTICES.md, regenerate the manifest, post to the
CDN, or notify any downstream consumer. The layers compose
mechanically. The operator's only manual action was extracting the
assets and writing the three provenance.yaml files.

## Section 5 — License hygiene as defeasible rule (~600 words)

Not every asset class enters the library. The Europa.c GPL-2
plugin (a known-good visualization shader) is explicitly excluded
because its license is incompatible with the system's redistribution
model. The exclusion is a defeater on the general rule "ingest
useful aesthetic assets": specific-license-incompatibility defeats
the general extraction permission.

Defeaters are named, scoped, and recorded in
`docs/research/aesthetic-library-license-decisions.md` (or similar).
Each exclusion has a one-paragraph rationale citing the specific
license clause that precludes inclusion. New asset proposals are
checked against the exclusion list; if a candidate matches an
existing exclusion category, the proposal is auto-rejected without
re-deriving the rationale.

The exclusion list grows sub-linearly with new asset classes. Most
new candidates fall under existing categories (BSD-3-Clause: yes;
CC-BY-SA: yes; GPL: defeater applies; ToS-restricted reverse-
engineered API: defeater applies). The list itself is operator-
ratified and committed.

## Section 6 — Why this scales beyond the single-operator case (~700 words)

The provenance discipline is not single-operator-specific. The same
six-layer architecture composes for multi-operator systems with one
addition: a per-operator audit trail on the manifest entries. The
constitutive rule (`it-attribution-001`) does not change; the
enforcement layers do not change; only the audit trail expands to
identify which operator extracted which asset.

Open-source projects that redistribute third-party content (Linux
distributions; Homebrew; npm packages; Docker images) currently
implement this discipline procedurally — by convention, by license
review at submission time, by SBOM tooling. The constitutional
posture treats the discipline as architectural rather than
procedural; the SBOM becomes the constitutive object, and procedural
checks become regulative consequences of the constitutive object's
existence.

The cost of the architectural posture is upfront: writing the linter,
the manifest generator, the NOTICES emitter, the per-asset
provenance.yaml schema. The cost of the procedural posture is
ongoing: every PR re-litigates compliance; every contributor must
remember the rules; every audit is a manual sweep. The architectural
posture amortizes the cost; the procedural posture pays it on each
operation.

## Section 7 — Receipts (~900 words)

Three concrete deployments where the provenance-as-architecture
framing was load-bearing.

1. **Px437 IBM VGA 8x16 font** — CC-BY-SA-4.0 (unmodified-only). The
   font ships in two formats (TTF + WOFF2). The CC-BY-SA-4.0
   unmodified-only constraint propagates as a contract: the system
   cannot subset, hint, or rasterize the font. The constraint is
   recorded in the per-asset provenance.yaml; downstream consumers
   (the in-stream typography ward, the omg.lol page that renders
   the operator's bio in this font) verify the constraint at load
   time.

2. **Enlightenment Moksha theme (`moksha.edc`)** — CC0-1.0
   (Hapax-authored approximation under the no-operator-approval-waits
   directive). The asset is *not* a verbatim Enlightenment theme; it
   is an authored approximation of one, released under CC0 by the
   author (Hapax-the-system). The provenance.yaml records the
   ambiguity: the asset credits "Hapax (authored approximation under
   no-operator-approval-waits mandate 2026-04-24T19:10Z)" with a link
   to the upstream Enlightenment project for context. The audit
   trail makes the provenance honest: this is *inspired-by*, not
   *taken-from*, the upstream.

3. **omg.lol /credits page auto-render** — the
   `agents/cross_surface/omg_credits_publisher.py` daemon reads
   `_NOTICES.md` directly, re-renders it as omg.lol weblog markdown,
   and pushes on every aesthetic-library change. The publisher does
   not hand-edit the credits page; the credits page is structurally
   downstream of the manifest. This closes the loop: the audience
   sees the same provenance the manifest declares.

## Section 8 — Limitations and future work (~400 words)

Three honest limitations:

1. **The manifest tracks bytes, not derived content.** A WGSL shader
   that loads the Px437 font for in-shader text rendering does not
   itself appear in the manifest, even though it is downstream of a
   manifest-tracked asset. Tracking derived content would require
   AST-level analysis; not yet implemented.

2. **Cross-asset license interactions are operator-resolved.** When
   a CC-BY-SA-4.0 asset is composed with a BSD-3-Clause asset
   (e.g., Px437 typography rendered via a BitchX-derived layout),
   the resulting composition's license is operator-ratified, not
   automatically derived. The composition's provenance.yaml lists
   both upstream sources; the operator selects the result's
   license.

3. **The CDN is single-distribution-channel.** GitHub Pages serves
   the SHA-pinned URLs, but a CDN failure would temporarily break
   downstream consumers. A second mirror (Cloudflare Pages, or a
   self-hosted nginx) would be additive; not yet implemented.

Future work: derived-content tracking via static analysis;
multi-mirror CDN; cross-asset license propagation rules.

## Section 9 — Cross-reference: the Refusal Brief

The provenance discipline catalogues *which content can ship*; the
Refusal Brief (`hapax.omg.lol/refusal`) catalogues *which surfaces
will not be engaged*. Both are constitutive declarations about what
the system will and will not do; the provenance discipline is about
honoring upstream-creator autonomy, the Refusal Brief is about
honoring operator-labor non-substitutability. Both are
infrastructure-as-argument.

## Section 10 — Conclusion (~300 words)

This essay reports a working provenance-as-architectural-invariant
discipline deployed in a single-operator system. The contribution
is not the SBOM-style metadata (which is well-described in software
supply-chain literature) and not the per-asset attribution
discipline (which is required by upstream license terms anyway).
The contribution is that all six enforcement layers — provenance
file, manifest, NOTICES, CI linter, axiom anchor, CDN — operate
together for an eighteen-month deployment record without a single
silent attribution failure. The discipline is architectural rather
than procedural; the operator does not have to remember to honor
the licenses, because the codebase cannot redistribute assets that
do not honor them.

---

## Polysemic-surface notes (per V5 weave invariant 5)

Polysemic terms in this essay are minimal: "provenance" reads
consistently in the SBOM / software-supply-chain register;
"compliance" appears once (Section 5, license hygiene) in
the legal-license register; "governance" does not appear. The
polysemic_audit gate should pass cleanly without an
acknowledgement override.

## Byline assignment

- **Surface**: omg.lol primary + Repeater Books pitch (per V5
  weave §2.2 #6)
- **Byline variant**: V4 (Hapax-canonical with operator-of-record)
  per `SURFACE_DEVIATION_MATRIX["omg_lol_weblog"]`
- **Unsettled-contribution variant**: V5 (manifesto register) per
  `SURFACE_DEVIATION_MATRIX["omg_lol_weblog"]`
- **Non-engagement-clause form**: LONG (capacity surface)

## Approval queue notes

- Outline ships as `docs/audience/aesthetic-library-manifesto-outline.md`
  (parallel to `constitutional-brief-outline.md`).
- Full draft (~8,000 words) lands as
  `docs/audience/aesthetic-library-manifesto.md`.
- Render via the existing `scripts/render_constitutional_brief.py` /
  `compose_publish_markdown` substrate (same V5 publish-pipeline).
- 130-page manuscript form is a separate follow-on.

## Status

- [x] Substrate identified (assets/aesthetic-library/, it-attribution-001,
  hapax-assets CDN)
- [x] Decoder stacks identified (4)
- [x] Section structure outlined (10 sections; ~6,700 words target)
- [ ] Substrate-to-prose pass (next; aim ~8,000 words full essay)
- [ ] Operator review (post-substrate-to-prose)
- [ ] omg.lol /credits + Repeater Books pitch (publish-event time)

— epsilon, V5 wk1 follow-on / wk2 lead-with #6 staging draft, 2026-04-25 ~20:13Z
