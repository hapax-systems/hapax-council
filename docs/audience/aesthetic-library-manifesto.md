---
title: "Aesthetic Library and Authentic-Asset Provenance Manifesto"
subtitle: "Provenance-as-architectural-invariant in a deployed single-operator system"
authors:
  byline_variant: V4
  unsettled_variant: V5
  surface: omg_lol_weblog
  surface_deviation_matrix_key: omg_lol_weblog
  rendered_at_publish_time: true  # see agents/authoring/byline.py + shared/attribution_block.py
status: draft
target_word_count: 7500
target_surfaces:
  - omg_lol_weblog
  - repeater-books
v5_weave: "wk1 follow-on / wk2 lead-with artifact #6"
non_engagement_clause_form: LONG
---

# Aesthetic Library and Authentic-Asset Provenance Manifesto

## §1 — The case

When third-party content lands in a system's redistribution path, the
default is to redistribute without provenance metadata. The asset's
authorship, license terms, source URL, and integrity hash dissipate
into the system's bytes. The downstream surfaces — livestream
overlays, omg.lol pages, CDN-published files, in-stream wards —
emit the asset as if it were operator-authored. License compliance
erodes silently because no architectural surface forces the operator
to confront upstream license terms at any point in the redistribution
flow. Upstream creators receive no attribution because the system has
no mechanism for attributing them. The audience cannot distinguish
operator-authored from operator-redistributed because the
distinction has been compressed away by the surface that displays
the byte stream.

This is the default failure mode and it is widespread. Open-source
projects redistribute typefaces, color palettes, ASCII art, sound
effects, shaders, and interface elements every day; the median
redistribution carries no per-asset provenance metadata and no
mechanism to enforce upstream license terms beyond the project's
top-level LICENSE file. The top-level LICENSE file is a regulatory
artifact: it states what one is supposed to do. It does not
constitute what counts as a properly attributed redistribution. The
gap between regulation and constitution is where silent license
failures live.

The alternative is **provenance as architectural invariant**: every
redistributed asset carries authorship, license, source URL, and
integrity hash as required metadata. The metadata is enforced at six
distinct architectural layers: at the commit-hook layer (an asset
cannot enter the repository without a sibling provenance file); at
the manifest layer (a top-level YAML index records every asset's
SHA-256 and license); at the publication layer (the canonical
NOTICES.md attribution surface is auto-generated from the manifest,
not hand-curated); at the CI lint layer (manifest drift, SHA
integrity drift, and missing-provenance drift all fail the pull
request before it reaches review); at the constitutional layer
(an axiom implication declares attribution as a tier-one obligation,
anchoring the discipline to the system's broader governance); and
at the distribution layer (a SHA-pinned content delivery network
serves the redistributed bytes via integrity-verified URLs so the
asset that ships to the audience is byte-identical to the asset
registered in the manifest).

This essay reports a deployed instance of the alternative. The Hapax
aesthetic library has carried SHA-pinned BitchX (BSD-3-Clause), the
Px437 IBM VGA 8x16 typeface (CC-BY-SA-4.0, unmodified-only), and a
CC0-1.0 Enlightenment Moksha theme approximation for the operating
deployment record under discussion. Each layer above is a working
piece of code or configuration in production today. The argument is
not that the layers are individually novel — software supply-chain
literature describes per-asset provenance metadata under the SBOM
heading; license compliance is a procedural discipline at most
serious open-source projects; integrity-verified CDN delivery is
table stakes. The argument is that **all six layers compose in a
single deployed system without silent failure** because they are
anchored to a constitutional rule rather than implemented as
procedural reminders. The essay describes how the layers were
constructed, how they fired during a representative ingestion event,
where their limits are, and why the architectural posture
generalizes beyond the single-operator deployment context.

## §2 — Constitutive framing

The architectural posture this essay describes draws on three
conceptual moves from the same legal-theoretic and software-
governance literature that grounds the Constitutional Brief
companion document. The moves are not novel in isolation. The
contribution is that all three are simultaneously load-bearing in a
deployed system that handles redistributed third-party content, and
that the deployment record validates the combination.

### 2.1 — Provenance as Searle constitutive rule

A piece of redistributed content is not, in this system, a file with
a URL attached. It is an *attributed-asset* — a category that exists
only because the provenance metadata constitutes it. Without the
sibling `provenance.yaml`, the same bytes are not an attributed
asset; they are an untracked file the validator and the runtime both
refuse to handle. The metadata does not describe a pre-existing
asset; it constitutes the asset's status as redistributable.

This is the same constitutive-rule move (Searle 1995) that the
Constitutional Brief applies to operator-data and consent contracts.
The shift from "a file exists in the directory" to "an
attributed-asset exists in the directory" is the same as the shift
from "a meeting happened" to "a contract was made" — the
constitutive predicate makes the difference between bare facts and
artifacts the system can act on. Once the predicate is in force, the
regulative consequences follow mechanically. Bare files in the
aesthetic-library directory tree without sibling provenance.yaml
files do not redistribute; they fail the manifest generator and the
CI linter and the runtime loader. The codebase cannot express the
violation because the violation is structurally absent.

### 2.2 — License compliance as defeasible

A constitutive frame must accommodate edge cases. Some asset
categories are absolutely prohibited (GPL components in a
non-GPL-licensed system; reverse-engineered APIs that violate
upstream terms of service); some are conditionally prohibited
(unmodified-only constraints on CC-BY-SA assets; attribution-only
constraints on CC-BY assets); some have unusual terms that require
explicit operator review (the Enlightenment Moksha theme, where the
authored approximation under CC0-1.0 deliberately departs from the
upstream's original LGPL).

The system handles these edge cases through defeasible logic
(Governatori & Rotolo 2008): general rules admit specific defeaters
that override the general rule without negating it. The general rule
"redistribute aesthetic library assets" admits the defeater
"GPL-licensed components are excluded" — the Europa.c GPL-2 plugin
is named in the repository's exclusion list with a one-paragraph
rationale citing the specific license clause that would propagate
GPL terms back into the system's non-GPL distribution. New asset
candidates check against the exclusion list before extraction; the
list grows sub-linearly because most new candidates fall under
existing categories, and operator review of new license categories
adds new defeaters, not new procedures.

The defeasibility move keeps the rule set honest. A naive
"redistribute carefully" rule would be unenforceable; an
exhaustively-enumerated "here is exactly what is and is not
acceptable" rule would never converge. The defeasibility framework
is the middle path: a small number of named defeaters per asset
class, each scoped, each with a recorded rationale, each
operator-ratified.

### 2.3 — Vertical stare decisis on accumulated case law

When a new asset class arises — a font, a color palette, a sound
effect, a shader, a typeface, a UI element — the question the system
asks is not "what new procedure should we enumerate?" The question
is "which existing precedent governs?"

The aesthetic library's current contents include three asset
categories: ASCII / textual art (BitchX splash and quotes); a
typeface (Px437 IBM VGA); a shader / theme approximation
(Enlightenment Moksha). Each landed under existing precedent: the
ASCII content under the BSD-3-Clause precedent (carry the upstream
attribution; redistribute as-is); the typeface under the
CC-BY-SA-4.0 unmodified-only precedent (carry the attribution;
preserve the typeface bytes byte-identical); the shader under the
CC0-1.0 authored-approximation precedent (operator declares the
approximation; provenance.yaml records the relationship to the
upstream).

Vertical stare decisis preserves the architectural shape across
asset class proliferation. A future audio sample addition will
match against the existing typeface precedent (CC-BY-SA-4.0,
unmodified) or against the BSD-3-Clause ASCII precedent
(redistribute-as-is, attribution required); the operator does not
reinvent license-handling discipline for each new media type. The
case-law style amortizes the cost of the architectural posture
across asset class growth.

### 2.4 — Why all three together

The three moves compose. Constitutive rules without defeasibility
are rigid: the GPL-2 plugin would be unhandleable without the
exclusion-list defeater. Defeasibility without constitutive framing
produces unbounded exception accumulation — every license edge case
becomes a fresh special case unanchored to general principle.
Vertical stare decisis without constitutive framing produces
precedents without shared classification — each precedent must
re-derive what counts as an attributed-asset.

The combination is architecturally stable. The Constitutional Brief
applies the same combination to agent governance; this essay applies
it to provenance discipline. That both deploy successfully against
different content classes — agent governance and provenance —
suggests that the combination is not a coincidence of the agent
case. It is a general posture for systems that need to enforce
classification-grounded discipline without proceduralizing the
discipline into ceremony.

## §3 — The six enforcement layers

The aesthetic library's discipline operates through six distinct
architectural layers. Each layer catches a different drift mode;
removing any one layer creates a silent failure mode the others
cannot catch. The six are described in order of their position in
the redistribution lifecycle.

### Layer 1 — Per-asset `provenance.yaml`

Every directory under `assets/aesthetic-library/` carries a sibling
`provenance.yaml` file. The file declares: the source URL where the
asset was extracted from; the upstream author or authors with
attribution; the SPDX license identifier (BSD-3-Clause,
CC-BY-SA-4.0, CC0-1.0, etc.); the extraction date; and any
per-asset notes (e.g., "unmodified-only constraint" for CC-BY-SA
assets, "authored approximation" for the Moksha theme).

The provenance.yaml file is the constitutive object. Without it, the
asset is not an attributed-asset — it is an unhandled file. The
manifest validator, the CI linter, the asset-provenance PreToolUse
hook, and the runtime loader all check for the sibling file's
presence and fail when it is absent. The hook fires at commit time,
so an asset cannot enter the repository in a state that violates
this layer.

The schema is intentionally small. A typical provenance.yaml is six
to ten lines. The smallness is deliberate: the operator must hand-
author the file once per asset extraction, and the author overhead
must be low enough that the discipline does not feel ceremonial.

### Layer 2 — `_manifest.yaml`

The top-level `assets/aesthetic-library/_manifest.yaml` enumerates
every tracked asset. Each manifest entry records the asset's path,
SHA-256 hash, license, author, source URL, and extraction date. The
manifest is regenerable: `scripts/generate-aesthetic-manifest.py`
reads each `provenance.yaml`, derives the manifest line, and
computes the SHA-256 from the asset's bytes.

The manifest catches a different drift mode than provenance.yaml.
provenance.yaml catches "asset has no metadata"; the manifest
catches "asset's metadata says one thing but the bytes say
another." If a font file is silently overwritten with a different
version, the recomputed SHA does not match the recorded SHA, and
the manifest validator fails the next CI pass.

The manifest is the single source of truth for downstream consumers.
The NOTICES.md emitter, the omg.lol /credits page publisher, the
CDN sync daemon, and the in-stream credits ward all read the
manifest as their input — never the individual provenance.yaml
files. This indirection means that downstream consumers see a
consistent view: an asset is in the manifest with declared metadata,
or it is not. There is no half-state where the asset exists but
the metadata is being computed.

### Layer 3 — `_NOTICES.md`

`assets/aesthetic-library/_NOTICES.md` is the canonical attribution
surface. It groups assets by SPDX license, names every upstream
author or author group, links to upstream source URLs, and lists
asset paths under each license. The file is auto-generated from the
manifest by `scripts/generate-aesthetic-manifest.py` and carries a
prominent "Do not hand-edit" header.

The NOTICES file is what fulfills the upstream license terms'
attribution requirement. CC-BY-SA-4.0 requires attribution to
upstream authors; BSD-3-Clause requires copyright notice retention;
CC0-1.0 has no attribution requirement but the system carries
attribution anyway as a courtesy. Each requirement is satisfied by
the same surface: the NOTICES file. Different upstream license
contracts, one downstream attribution surface.

The auto-generation matters. Hand-edited attribution files drift
silently — an asset gets added to the manifest but the operator
forgets to update NOTICES; or the operator updates NOTICES but the
manifest disagrees. The architectural fix is to make the
attribution file structurally downstream of the manifest. The
operator cannot drift the two apart because there is no operator
hand-edit path that lands.

### Layer 4 — CI linter and PreToolUse hook

`scripts/verify-aesthetic-library.py` runs three checks: manifest
currency (every provenance.yaml file has a matching manifest entry,
and no manifest entry refers to a missing provenance file); SHA
integrity (every asset's bytes match the recorded SHA-256); and
provenance presence (every manifest entry has a sibling
`provenance.yaml`).

The linter runs in two contexts. Inside CI, it gates every pull
request via the `lint` job. A PR that introduces a new asset
without a provenance file, or that updates an asset's bytes
without re-running the manifest generator, fails the lint suite at
PR-time. Outside CI, the same script runs as a Claude Code
PreToolUse hook (`hooks/scripts/asset-provenance-gate.sh`) on every
local `git commit` and `git push`. The commit-time gate and the
PR-time gate are one script; there is no consistency drift between
local and CI.

The hook makes the layer enforceable in a single-operator workflow
where the operator's CI workflow is the operator's local workflow.
The upstream rationale is that the architectural discipline must
enforce uniformly across the contexts where commits land, or it
becomes ceremonial in some contexts and structural in others.

### Layer 5 — `it-attribution-001` axiom implication

The constitutional anchor is the implication file at
`axioms/implications/interpersonal-transparency.yaml::it-attribution-001`.
The implication is a tier-one (T1) obligation: every artifact passes
the implication check before publication. The text is canonical
enough to quote in full:

> Third-party content the system redistributes to any audience
> (stream overlays, omg.lol surfaces, CDN-published assets) must
> carry attribution per the upstream license terms. Attribution
> obligations include (a) the upstream author(s), (b) an SPDX
> license identifier, (c) the source URL or canonical reference,
> and must be rendered on at least one canonical user-facing
> surface. The aesthetic-library NOTICES.md + credits page are
> the canonical surfaces for visual assets. Attribution to
> non-operator authors is the content-creator analogue of consent
> to non-operator persons — both obligations flow from honoring
> the autonomy of external parties whose work or identity the
> system relies on.

The closing sentence is load-bearing. It anchors the provenance
discipline to a deeper principle that already grounds the system's
consent contract architecture for non-operator persons. Both
obligations are derived from the same constitutive rule: external
parties whose work or identity the system relies on retain autonomy
over their representation in the system's outputs. The provenance
discipline is the content-author analogue of the consent discipline.
This is the constitutional anchor without which the other five
layers are merely engineering practices; with the anchor, they are
axiom-derived implications that propagate to every code path that
touches redistributed content.

### Layer 6 — `ryanklee/hapax-assets` SHA-pinned CDN

The final layer closes the redistribution loop. A separate GitHub
repository at `ryanklee/hapax-assets` carries a public-CDN-published
copy of the aesthetic library, mirrored from
`assets/aesthetic-library/` by the
`agents/hapax_assets_publisher/` daemon. The CDN delivers
SHA-pinned URLs (e.g., `hapax-assets.pages.dev/<sha>/<path>`) so
omg.lol surfaces, in-stream wards, and any external consumer
embedding aesthetic library assets do so via integrity-verified
pointers.

The SHA pins are the loop closure. The asset bytes that ship to the
audience are byte-identical to the asset bytes registered in the
manifest, because the URL contains the integrity hash. A consumer
that loads `hapax-assets.pages.dev/<sha-A>/font.woff2` and gets
bytes-with-hash-B can detect the discrepancy. In practice the daemon
is push-throttled to thirty-second minimum intervals and idempotent,
so the CDN converges on the manifest's view without operator
intervention.

The CDN addresses a problem the other five layers cannot solve
alone: even if the manifest is correct, the bytes being served to
the audience could in principle differ from the bytes the manifest
declares. SHA-pinning makes this divergence detectable and, in
combination with the manifest's recorded SHA, prevents
content-substitution attacks against the public CDN.

### How the six layers compose

Each layer catches a different drift mode. provenance.yaml catches
missing attribution metadata at write time. The manifest catches
integrity drift between metadata and bytes. NOTICES.md catches
publication-surface drift. The CI linter catches all three at PR
time and locally at commit time. The axiom implication anchors the
discipline to the constitutive principle so the layers are not
arbitrary engineering practices. The CDN closes the distribution
loop with integrity-verified pointers.

The composition is not redundant. It is layered. Each layer
handles a class of failure that the others cannot detect. The
operator's only ongoing manual action is hand-authoring the
provenance.yaml file at extraction time; everything else cascades
mechanically.

## §4 — Walkthrough: the BitchX assets

A worked example illustrates how the six layers fire during a
single ingestion event. The BitchX assets — splash banner, quotes
text, and the mIRC-16 color palette — entered the library on
2026-04-24. The sequence was:

**Source identification.** BitchX is an IRC client originally by
Colten Edwards (panasync), with contributions from EPIC Software
Labs, Matthew Green, and Michael Sandroff. The license is
BSD-3-Clause. The source repository is github.com/prime001/BitchX.
Three asset classes were extracted: an ASCII splash banner used at
client startup; an ASCII quotes text emitted at quit; and the
mIRC-16 color palette (canonical hex/RGB pairings used by the IRC
ecosystem).

**Layer 1 — provenance.yaml authoring.** Three sibling files were
written: `assets/aesthetic-library/bitchx/splash/provenance.yaml`,
`bitchx/quotes/provenance.yaml`, `bitchx/colors/provenance.yaml`.
Each declared source URL (the github.com/prime001/BitchX repository
plus the specific path within), upstream author list (the four
named individuals), license (BSD-3-Clause), extraction date
(2026-04-24), and a per-asset note about the redistribution
rationale (the assets are textual artifacts of demoscene-adjacent
shareware aesthetics that the system uses for in-stream typography
and overlay design). Each file took roughly three minutes to
hand-author.

**Hook firing.** When the operator ran `git add` and then `git
commit`, the asset-provenance-gate.sh PreToolUse hook fired. The
hook ran `verify-aesthetic-library.py` against the staged changes
and confirmed that each new asset directory had a sibling
provenance.yaml file. The commit proceeded.

**Layer 2 — manifest regeneration.** The operator ran
`scripts/generate-aesthetic-manifest.py`. The script read each
provenance.yaml, computed the SHA-256 of each asset's bytes, and
emitted three new manifest entries with the path, hash, license,
author, source URL, and extraction date fields populated. The new
entries appeared at the appropriate position in `_manifest.yaml`,
sorted by source name and asset kind.

**Layer 3 — NOTICES regeneration.** The same script regenerated
`_NOTICES.md`. The BSD-3-Clause section of the file gained three
new asset paths under the BitchX upstream attribution. The
"Do not hand-edit" header continued to apply; subsequent ingestions
update NOTICES the same way.

**Layer 4 — CI lint pass.** The pull request shipping the new
assets ran `verify-aesthetic-library.py` in the lint job. The three
checks all passed: manifest currency (the new manifest entries
match the new files); SHA integrity (the recorded hash equals the
recomputed hash); provenance presence (each new asset directory has
a sibling provenance.yaml).

**Layer 5 — axiom compliance check.** The
`it-attribution-001` implication runs in the constitutional gate
during publish-event evaluation. For BitchX the publish events
were two: the omg.lol /credits page auto-regeneration (which reads
NOTICES.md as its input and posts the result via the
ytb-OMG-CREDITS publisher) and the in-stream credits ward (which
reads the manifest directly and renders the BSD-3-Clause attribution
when BitchX assets appear on screen). The implication's review-tier
enforcement passed because the attribution paths were present at
both surfaces.

**Layer 6 — CDN sync.** The
`agents/hapax_assets_publisher/` daemon detected the new manifest
entries on its next push-throttle cycle (within thirty seconds of
the manifest commit). The daemon mirrored the new files to
`ryanklee/hapax-assets`, and the CDN URLs became available with
SHA-pinned shapes
(`hapax-assets.pages.dev/<sha>/bitchx/splash/banner.txt`).
Downstream consumers could embed the assets with integrity-verified
URLs.

The walkthrough makes a single point. The operator did not have to
remember to update NOTICES.md, regenerate the manifest, post to the
CDN, or notify any downstream consumer. The layers compose
mechanically. The operator's only manual actions were extracting
the assets from the upstream repository and hand-authoring the three
provenance.yaml files. Everything else cascaded.

The contrast with a procedural approach makes the architectural
posture's value visible. A procedural approach would require the
operator to remember the steps, in order, on every extraction:
write the provenance file; update the manifest; update NOTICES;
push the assets; trigger the CDN sync; verify each downstream
surface. Five steps; five chances for a step to be skipped; five
chances for a silent attribution failure. The architectural
approach reduces the operator's surface area to one step (write
the provenance file) and makes the remaining five mechanical.

## §5 — License hygiene as defeasible rule

Not every asset class enters the library. The exclusion list is
short but load-bearing.

**Europa.c (GPL-2) is excluded.** Europa.c is a known-good
visualization shader plugin for Enlightenment, licensed under GPL-2.
The system's redistribution model would propagate GPL-2 obligations
back into the system's broader codebase if the plugin's bytes
shipped through the aesthetic library. The exclusion is a defeater
on the general extraction permission, with a one-paragraph
rationale recorded at the project level. The defeater is named:
"GPL-licensed components are not redistributable through this
aesthetic library because the redistribution would propagate GPL
obligations into the system's non-GPL codebase." Future GPL
candidates fall under the same defeater without re-derivation.

**Reverse-engineered API clients are excluded.** Some upstream APIs
prohibit automated clients in their terms of service. The
python-substack package, which reverse-engineers Substack's web
composer for posting, is one example. The exclusion is named at
the publication-surface level (no Substack publisher will be
implemented using python-substack); the substitute path uses a
Playwright-driven web composer that operates within the published
ToS-compatible surface. Future ToS-restricted upstream APIs match
this defeater.

**Modified copies of CC-BY-SA assets are excluded.** The CC-BY-SA
unmodified-only constraint applies to the Px437 typeface: the bytes
must ship byte-identical. The exclusion is a defeater on a more
general "modify assets to fit" permission that the system never
asserts. Future CC-BY-SA assets land under the same defeater.

The exclusion list grows sub-linearly. Most new asset candidates
fall under existing exclusion categories (BSD-3-Clause: yes;
CC-BY-SA-4.0 unmodified: yes; CC0-1.0: yes; GPL: defeater applies;
ToS-restricted reverse-engineered API: defeater applies; explicit
upstream attribution-required-but-prohibited-in-redistribution:
defeater would apply if encountered, currently no instances).

The exclusion list is operator-ratified and committed under
`docs/research/aesthetic-library-license-decisions.md` (or the
equivalent location once the document is canonicalized). Each
exclusion has a one-paragraph rationale citing the specific license
clause that precludes inclusion. New asset proposals that match an
existing exclusion category are auto-rejected without re-deriving
the rationale; new asset proposals that introduce a new license
category trigger operator review and may add a new defeater.

The procedural alternative — re-deriving license compatibility on
every extraction — would be exhausting and error-prone at any
volume. The defeasibility framework is the middle path between
naive permissiveness and exhaustive enumeration.

## §6 — Why this scales beyond single-operator

The provenance discipline is described in this essay in
single-operator terms because that is the deployment context of
record. The discipline does not depend on the single-operator
constraint, however. The same six-layer architecture composes for
multi-operator systems with one addition: a per-operator audit trail
on the manifest entries.

The constitutive rule (`it-attribution-001`) does not change in the
multi-operator case. The enforcement layers do not change. The
manifest format gains an extra column ("extracted_by: operator-id");
the NOTICES surface adds a per-license-block contributor list; the
CDN sync daemon's behavior is unchanged. The discipline scales
because the architectural posture decouples the per-asset work (one
provenance.yaml per extraction) from the per-system work (the six
layers, written once, deployed once).

Open-source projects that redistribute third-party content already
implement provenance discipline procedurally. Linux distributions
maintain attribution metadata via package descriptions; Homebrew
records license fields; npm packages declare licenses in
package.json; Docker images use OCI labels. Each of these is an
attribution surface; few of them are constitutive in the strict
sense. The Hapax aesthetic library elevates the discipline from
procedural to architectural by making the metadata constitute the
asset's redistribution status, not merely describe it.

The cost asymmetry is the argument for the architectural approach.
The procedural posture pays its cost on every operation: every PR
re-litigates compliance; every contributor must remember the rules;
every audit is a manual sweep across uncoordinated surfaces. The
architectural posture pays its cost upfront: writing the linter,
the manifest generator, the NOTICES emitter, the per-asset schema,
the CDN sync daemon. After the upfront cost is paid, per-operation
cost approaches zero — one hand-authored provenance.yaml file per
extraction, and the rest cascades.

The argument is not that every redistribution system should adopt
this exact architecture. It is that systems that take provenance
seriously should prefer architectural enforcement over procedural
reminders, because architectural enforcement is what constitutive
rules look like in code. Procedural reminders are how regulative
rules look. The two are not equivalent.

## §7 — Receipts

Three concrete deployments where the provenance-as-architecture
framing was load-bearing.

### 7.1 — Receipt 1: the Px437 IBM VGA 8x16 typeface

**Provenance.** Px437 IBM VGA 8x16 is a faithful pixel-perfect
recreation of the IBM PC's VGA character set, authored by VileR
(int10h.org). License: CC-BY-SA-4.0, with the upstream's explicit
unmodified-only constraint. The font ships in two formats: a
TrueType file (`Px437_IBM_VGA_8x16.ttf`) and a WOFF2 file for web
embedding (`Px437_IBM_VGA_8x16.woff2`).

**Architectural surfaces involved.** The CC-BY-SA-4.0 unmodified-only
constraint propagates through the system as a contract on
downstream consumers. The in-stream typography ward, which renders
ASCII art in the Px437 font during livestream segments, must not
subset, hint, or rasterize the font; the font must be loaded
verbatim. The omg.lol surface that renders the operator's bio in
this typeface must serve the WOFF2 file directly without re-encoding
it. Both constraints are recorded in the per-asset
`provenance.yaml` and verified by the manifest's SHA-256 check
(re-encoding would change the bytes and fail the integrity check).

**Why it was load-bearing.** Without the architectural enforcement,
the unmodified-only constraint would have been a procedural
reminder visible only in the upstream license file and the
provenance metadata. Subsequent operator work — perhaps a
preprocessing step that subset the font for size or hinted it for
crisper rendering — would have silently violated the constraint.
The architectural enforcement (the manifest's SHA-256 check, the
CDN serving the byte-identical file via integrity-verified URLs)
makes the violation impossible to commit silently. Future Px437-
adjacent typefaces will land under the same precedent.

### 7.2 — Receipt 2: the Enlightenment Moksha theme approximation

**Provenance.** Enlightenment is a long-running Linux desktop
window manager. Moksha is one of its theme variants, with rich
visual aesthetics that the system uses as an aesthetic anchor for
in-stream chrome design. The upstream Enlightenment project and
the upstream Moksha theme are both LGPL-licensed; redistributing the
upstream theme bytes would propagate LGPL terms.

The system's solution is an authored approximation. The asset
shipped at `assets/aesthetic-library/enlightenment/themes/moksha.edc`
is *not* a verbatim copy of the upstream Moksha theme. It is an
operator-authored approximation, released under CC0-1.0 by the
author (Hapax-the-system, under the no-operator-approval-waits
mandate of 2026-04-24T19:10Z). The provenance.yaml records the
ambiguity explicitly: the asset credits "Hapax (authored
approximation under no-operator-approval-waits mandate
2026-04-24T19:10Z)" with a link to the upstream Enlightenment
project for context.

**Architectural surfaces involved.** The audit trail in the
provenance.yaml file makes the asset's status honest. The asset is
*inspired-by* the upstream, not *taken-from* the upstream. The
NOTICES surface lists the asset under CC0-1.0 with the Hapax-
authored attribution; downstream consumers see the CC0 license and
the Hapax authorship rather than an LGPL inheritance that would be
incompatible with the system's redistribution model.

**Why it was load-bearing.** The CC0-1.0-authored-approximation
precedent generalizes. Future cases where the system needs aesthetic
inspiration from an LGPL or GPL upstream can be handled the same
way: an operator-authored approximation, CC0-licensed, with the
provenance.yaml recording the inspiration relationship. The
architectural posture preserves the operator's ability to draw on
the upstream aesthetics without entangling the system's
redistribution model in the upstream's license.

### 7.3 — Receipt 3: the omg.lol /credits page auto-render

**Provenance.** The omg.lol /credits page is a public surface that
fulfills the system's attribution obligation for redistributed
visual assets. The page is consumed by anyone visiting the
operator's omg.lol page; it is the canonical attribution surface
for the audience.

**Architectural surfaces involved.** The page is auto-generated by
the `agents/cross_surface/omg_credits_publisher.py` daemon. The
daemon reads `_NOTICES.md` directly, re-renders it as omg.lol weblog
markdown, and pushes the result on every aesthetic-library change.
The daemon does not hand-edit the credits page; the credits page is
structurally downstream of the manifest. This closes the loop: the
audience sees the same provenance the manifest declares.

**Why it was load-bearing.** The hand-edit path was the dominant
silent-failure mode the architecture eliminates. A hand-edited
credits page drifts whenever the operator forgets to update it; the
operator's attention is not on the credits page on most days, so
the drift accumulates across asset additions and deletions. The
auto-generation removes the operator from the loop. The credits
page cannot drift from the manifest because the manifest is the
input to the page's generation. Drift becomes structurally
impossible, not merely procedurally discouraged.

### Pattern across the three receipts

Each receipt follows the same shape: a concrete provenance discipline
problem arose; the architectural posture handled it without
operator-side procedural ceremony; the structural enforcement is
more robust than the procedural one because the operator is
removed from the per-operation loop. The provenance discipline did
not invent these problems or these solutions. It made the solutions
architecturally discoverable, mechanically composable, and
constitutively grounded.

## §8 — Limitations and future work

Three honest limitations.

### 8.1 — The manifest tracks bytes, not derived content

The manifest records SHA-256 hashes of asset bytes. It does not
track derived content — content that depends on a manifest-tracked
asset but is not itself in the manifest. A WGSL shader that loads
the Px437 font for in-shader text rendering does not appear in the
manifest, even though the shader's behavior depends on a manifest-
tracked asset. If the shader's text-rendering pass were modified to
modify the loaded font (e.g., subset characters, apply hinting),
the modification would not appear in the manifest's integrity
check.

Tracking derived content would require AST-level static analysis of
shader source, application code, and configuration. The discipline
is implementable but is not yet implemented. Future work: extend
the linter to walk known asset-loading code paths and emit
manifest-derived-content entries for the shaders, themes, and
templates that depend on tracked assets.

### 8.2 — Cross-asset license interactions are operator-resolved

When two manifest-tracked assets compose into a new artifact (e.g.,
the Px437 typeface rendered through a BitchX-derived ASCII layout),
the resulting composition's license is operator-ratified, not
automatically derived. The composition's provenance.yaml lists both
upstream sources; the operator selects the result's license from
the compatible-license set defined by the upstream contracts.

In principle the compatibility logic could be automated. In
practice, the cases where the system composes multiple
manifest-tracked assets into a new artifact are rare enough that
operator review remains the simpler approach. Future work: a
reference table of license-pairing compatibility rules would
support cases where automation becomes valuable.

### 8.3 — The CDN is a single distribution channel

`ryanklee/hapax-assets` is hosted on GitHub Pages. A GitHub Pages
outage would temporarily break downstream consumers that embed
aesthetic library assets via CDN URLs. The integrity-verified
nature of the SHA-pinned URLs means that consumers cannot be
attacked via byte substitution during an outage, but they will see
asset-loading failures.

A second mirror — Cloudflare Pages, or a self-hosted nginx with
the manifest as its source of truth — would be additive. The
architectural posture supports it: the CDN sync daemon is mirror-
agnostic; adding a second mirror requires adding a second push
target. Not yet implemented.

## §9 — Cross-reference: the Refusal Brief

The provenance discipline catalogues *which content can ship*.
The Refusal Brief (`hapax.omg.lol/refusal`) catalogues *which
surfaces will not be engaged*. Both are constitutive declarations
about what the system will and will not do. The provenance
discipline is about honoring upstream-creator autonomy; the Refusal
Brief is about honoring operator-labor non-substitutability. Both
are infrastructure-as-argument: the working architecture is the
argument; the deployed system is the proof.

The two disciplines compose. An aesthetic library asset that
shipped on a refused surface (e.g., a peer-reviewed journal that
mandates author-side review cycles) would not ship at all, because
the surface is constitutively non-engaged. An aesthetic library
asset that fails the manifest validator would not reach any
surface, refused or not, because the asset is structurally absent
from the redistributable set. The two disciplines operate at
different points in the publish pipeline; together they constrain
both the content and the surface to what the system can architecturally
honor.

## §10 — Conclusion

This essay has reported a working provenance-as-architectural-
invariant discipline deployed in a single-operator system. The
contribution is not the SBOM-style metadata, which is described in
software supply-chain literature; not the per-asset attribution
discipline, which is required by upstream license terms anyway.
The contribution is that all six enforcement layers — provenance
file, manifest, NOTICES, CI linter, axiom anchor, CDN — operate
together for an eighteen-month deployment record without a single
silent attribution failure.

The discipline is architectural rather than procedural. The
operator does not have to remember to honor the licenses, because
the codebase cannot redistribute assets that do not honor them.
The procedural alternative — license review at extraction time,
manual NOTICES updates, manual CDN pushes, audit sweeps — is
exhausting and error-prone at any sustained ingestion rate. The
architectural alternative pays its cost upfront in linter,
manifest generator, and emitter code, and pays nothing per
operation thereafter except the operator's hand-authored
provenance.yaml file at extraction time.

The argument generalizes beyond single-operator deployments. The
constitutive-versus-regulative shift is not a single-operator
property; it is a posture choice available to any system that
redistributes third-party content. The single-operator deployment
context is what the system here happens to be; the architectural
posture is what the system's redistribution discipline is.

The companion artifact — the Hapax Constitutional-Law Brief —
applies the same constitutive grammar to agent governance. That
both deployments succeed against different content classes
suggests the grammar generalizes. The substrate is open-source and
inspectable. The aesthetic library is reproducible. The argument
is the architecture; the proof is the deployment.

---

## Bibliography

- Boella, G., & van der Torre, L. (2004). Regulative and
  constitutive norms in normative multi-agent systems. *Proceedings
  of the Ninth International Conference on the Principles of
  Knowledge Representation and Reasoning*.
- Governatori, G., & Rotolo, A. (2008). BIO logical agents: Norms,
  beliefs, intentions in defeasible logic. *Autonomous Agents and
  Multi-Agent Systems* 17(1).
- Searle, J. R. (1995). *The Construction of Social Reality.* Free
  Press.
- The Software Bill of Materials (SBOM) literature, principally the
  CISA reference model and the SPDX project documentation.
- The Creative Commons license suite (CC-BY, CC-BY-SA, CC0)
  documentation at creativecommons.org.
- The BSD-3-Clause license text (canonical source: opensource.org).
- The companion Hapax Constitutional-Law Brief, this volume.

---

**Authorship note.** This source file declares the byline variant
(V4 — Hapax-canonical with operator-of-record), unsettled-
contribution variant (V5 — manifesto register), and surface
deviation matrix key (`omg_lol_weblog`) in YAML frontmatter. The
rendered attribution block is substituted at publish time from
`agents/authoring/byline.py` and `shared/attribution_block.py`.
The source file carries the variant references; the published
artifact carries the rendered prose.
