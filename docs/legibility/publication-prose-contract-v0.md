# Publication Prose Contract v0

Authority: `publication-bus-prose-contract-hardening-20260611`

Design: `DESIGN-PUBLICATION-BUS-PROSE-CONTRACT-HARDENING-20260611`

Status: minted

This contract defines the prose floor for publication-bus output. It applies
before public fanout, surface dispatch, or any receipt that treats generated
publication text as releasable.

## Evidence Basis

Local evidence:

- `shared/publication_hardening/gate.py` already treats lint errors as reject
  decisions, and rejects cannot be operator-overridden.
- `shared/anti_personification_linter.py` already encodes the Phase 7
  non-anthropomorphic discriminator for inner-life and human-host framing.
- `.vale/styles/Hapax/BannedTerms.yml` already bans generic marketing and jargon
  terms for file-backed publication material.
- `docs/superpowers/specs/2026-05-06-nonanthropomorphic-segment-prep-framework-stack.md`
  defines source consequence, argument audit, visible action, and
  non-anthropomorphic segment language.
- `docs/methodology/avsdlc-authority-case.md` requires standards provenance,
  evidence gates, and release blocks when quality evidence is missing or stale.
- `docs/isaps/visibility-engine-egress-safety-gate-isap-2026-05-20.md` requires
  dry-run, classification, pass/hold/reject receipts, and replay safety before
  rolling autonomous egress.
- `hapax-legibility-evidence-claim-audience-schemas-2026-06-11.md` requires
  claim records to bind to evidence records, audience scope, public-safe status,
  and currentness windows.
- `llm-agent-failure-taxonomy-2026-06-11.md` found that prose-only guidance does
  not self-repair, while gates and construction controls close defect classes.

External evidence:

- Digital.gov plain-language guidance favors audience fit, clear structure,
  active wording, and testing with real readers:
  `https://digital.gov/guides/plain-language/writing` and
  `https://digital.gov/guides/plain-language/test`.
- Nielsen Norman Group reports that concise, scannable, objective web writing
  improves usability, while promotional wording reduces reader performance and
  trust: `https://www.nngroup.com/articles/concise-scannable-and-objective-how-to-write-for-the-web/`.
- A 2025 JMIR review of 1,241 plain-language summaries found that many research
  summaries still contain readability and jargon defects:
  `https://www.jmir.org/2025/1/e50862`.
- AI-trust and anthropomorphic-AI studies show that human-like framing can shift
  trust, reliance, and perceived agency in ways that must be controlled for
  public-facing system descriptions:
  `https://doi.org/10.5465/annals.2018.0057`,
  `https://doi.org/10.1609/aies.v7i1.31613`, and
  `https://doi.org/10.1145/3630106.3659040`.
- Studies of AI-assisted verification show that output acceptance depends on
  user review cost and evidence access, so publication claims must carry enough
  source context for checking: `https://arxiv.org/abs/2212.06823`.

## Contract

Generated publication prose must satisfy all of these conditions:

- Claim binding: each substantive claim cites a current evidence record or
  explicitly scopes itself as hypothesis, design intent, or dated observation.
- Audience scope: public-targeted prose uses public-safe evidence and does not
  expose private runtime state, private operator state, secrets, or consent-bound
  material.
- Formal register: prose uses research-publication diction, not creator-channel,
  sales, hype, or hollow affirmation language.
- Non-anthropomorphic register: prose describes operations, interfaces,
  evidence, failure modes, and readback. It does not attribute inner life,
  desire, feeling, preference, belief, taste, or human-host qualities to Hapax or
  to a component.
- Surface fit: the text obeys the surface contract, canonical URL contract,
  privacy class, rate limit, and replay/idempotency constraints for the target
  surface.
- Egress decision: lint errors reject. Holds require current review evidence.
  Rejects cannot be operator-overridden.

## Enforced v0 Slice

The v0 implementation pins the prose portion of the contract in
`shared/publication_hardening/lint.py`:

- generated-text lint mirrors the local Vale banned-register list;
- generated-text lint rejects emoji, repeated exclamation, creator openers,
  creator calls to action, promotional superlatives, and hollow affirmation;
- generated-text lint wraps anti-personification findings as
  `Hapax.NonAnthropomorphicRegister` errors;
- file-backed lint applies the same publication register checks before Vale;
- `PublicationHardeningGate` rejects generated artifacts with these errors when
  no `source_path` exists.

## Release Floor

This contract is not satisfied by a prose instruction alone. A release needs:

- unit tests for formal-register rejection;
- unit tests for non-anthropomorphic rejection;
- gate tests proving generated body text rejects without a source file;
- no public egress, service restart, credential check, or DOI/DataCite/ORCID
  mutation as part of this slice;
- a PR review gate before any merge.
