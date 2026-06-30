---
title: "Data-Exhaust Legal Posture Research"
type: legal-research
created: 2026-06-30
authority_case: CASE-SDLC-REFORM-001
parent_request: REQ-20260628-mdlc-tax-legal-posture-registry
parent_spec: hapax-council/docs/superpowers/specs/2026-05-30-sdlc-frictionless-self-direction-design.md
cc_task: 20260628-registry-phase6-data-exhaust-subtree
tags: [legal-registry, data-exhaust, b2b, deidentification, biometric, padfaa]
status: active
---

# Data-Exhaust Legal Posture Research

This is non-attorney registry research, not legal advice. The registry rows stay
`DARK` until the operator signs a narrower legal/ethical authority. The work here
separates plausible non-biometric package candidates from held biometric,
reidentifiable, data-broker, and struck tiers.

## Method

- Reviewed the phase-0 legal-posture schema and encoded rows into
  `docs/monetization/legal-posture-registry.yaml`.
- Used official or regulator sources where available, reviewed on 2026-06-30.
- Treated deidentification as a prerequisite artifact, not as legal clearance.
- Treated biometric, health-adjacent, reidentifiable, non-operator, and struck
  data as held unless a later authority case proves a lawful and ethical route.

## Source Findings

### BIPA: Illinois Biometric Data

Illinois BIPA defines biometric identifiers to include retina or iris scans,
fingerprints, voiceprints, and scans of hand or face geometry, and defines
biometric information as information based on a biometric identifier used to
identify an individual. Section 15 requires written notice, purpose and retention
disclosure, and written release before collection or obtaining. Section 15(c)
bars selling, leasing, trading, or otherwise profiting from a person's or
customer's biometric identifier or biometric information.

Registry effect: `US-IL / biometric_identifier_or_information` remains `DARK`.

Sources:
- 740 ILCS 14/10 definitions:
  https://www.ilga.gov/documents/legislation/ilcs/documents/074000140k10.htm
- 740 ILCS 14/15 retention, notice, release, sale/profit, disclosure:
  https://www.ilga.gov/documents/legislation/ilcs/documents/074000140K15.htm

### CUBI: Texas Biometric Identifiers

Texas CUBI covers commercial capture or possession of biometric identifiers such
as retina or iris scans, fingerprints, voiceprints, or records of hand or face
geometry. The Texas Attorney General summarizes the statute as requiring notice
and consent before capture, restricting sale, lease, or disclosure, requiring
reasonable care, and requiring destruction within the statutory timeframe.

Registry effect: `US-TX / biometric_identifier` remains `DARK`.

Sources:
- Texas Attorney General CUBI overview:
  https://www.texasattorneygeneral.gov/consumer-protection/file-consumer-complaint/consumer-privacy-rights/biometric-identifier-act
- Tex. Bus. & Com. Code §503.001:
  https://statutes.capitol.texas.gov/Docs/BC/htm/BC.503.htm

### WA-MHMD: Washington Health, Biometric, And Vital-Sign Data

Washington's My Health My Data Act is broader than classical biometric statutes.
Consumer health data includes, among other categories, bodily functions, vital
signs, symptoms, biometric data, genetic data, and precise location information
that could reasonably indicate health-service activity. RCW 19.373.030 restricts
collection and sharing without specified-purpose consent. RCW 19.373.070 makes
sale or offer to sell consumer health data unlawful without separate valid
authorization and retention of authorization records.

Registry effect: `US-WA / consumer_health_or_biometric_data` remains `DARK`.

Source:
- Chapter 19.373 RCW:
  https://app.leg.wa.gov/RCW/default.aspx?cite=19.373&full=true

### PADFAA And Data-Broker Concerns

PADFAA, codified at 15 USC Chapter 123, prohibits a data broker from making
personally identifiable sensitive data of a United States individual available to
a foreign adversary country or controlled entity. The data-broker definition is
tied to valuable-consideration transfer of data of U.S. individuals that the
entity did not collect directly from those individuals to a non-service-provider.
Sensitive data categories include precise geolocation, biometric and genetic
information, private communications, credentials, private media, online activity
over time, protected-class data, minor data, and military-status data.

Registry effect: first-party operator-only telemetry may need a different
analysis from brokered or third-party data, but any buyer path needs
data-broker, sensitive-data, and foreign-adversary-control screening before it
can move beyond `DARK`.

Sources:
- 15 USC Chapter 123:
  https://uscode.house.gov/view.xhtml?edition=prelim&path=%2Fprelim%40title15%2Fchapter123
- FTC PADFAA page:
  https://www.ftc.gov/legal-library/browse/statutes/protecting-americans-data-foreign-adversaries-act-2024-padfaa

### Deidentification Standard

HIPAA's deidentification rule is useful as an analog, not as a general license.
45 CFR §164.514 says health information is deidentified when it does not identify
an individual and there is no reasonable basis to believe it can be used to
identify an individual. HHS OCR guidance describes the two HIPAA methods:
Expert Determination and Safe Harbor. For Hapax data exhaust, the analogous
minimum package artifact should be expert-determination-style: documented
methods, retained results, field minimization, and buyer-context reidentification
risk analysis.

Registry effect: `deidentified_aggregate_operational_telemetry` remains `DARK`
until the deidentification artifact, buyer contract, and operator signature
exist.

Sources:
- 45 CFR §164.514:
  https://www.ecfr.gov/current/title-45/subtitle-A/subchapter-C/part-164/subpart-E/section-164.514
- HHS OCR deidentification guidance:
  https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html

### FTC Data-Broker Enforcement Signal

The FTC's X-Mode/Outlogic matter is not a registry clearance source, but it is a
relevant enforcement signal: sensitive location data sale, weak downstream-use
controls, and purportedly non-anonymous mobile identifiers are high-risk. This
supports the registry's red line against precise location, raw device
identifiers, reidentifiable data, and buyer-side reidentification.

Source:
- FTC X-Mode/Outlogic announcement:
  https://www.ftc.gov/news-events/news/press-releases/2024/01/ftc-order-prohibits-data-broker-x-mode-social-outlogic-selling-sensitive-location-data

## Encoded Tiers

| Tier | Registry instrument | Verdict | Disposition |
|---|---|---|---|
| Non-biometric first-party operational telemetry | `non_biometric_operational_telemetry` | `DARK` | Candidate first tranche only after inventory, minimization, buyer-screening, and operator signature. |
| Deidentified aggregate operational telemetry | `deidentified_aggregate_operational_telemetry` | `DARK` | Candidate only after expert-determination-style artifact and no-reidentification terms. |
| Biometric or biometric-derived data | `biometric_or_biometric_derived_data` plus state rows | `DARK` | Held until separate legal/ethical authority. |
| Data-broker sensitive personal data transfer | `data_broker_sensitive_personal_data_transfer` | `DARK` | Held until buyer and sensitive-data analysis proves no PADFAA/state-broker issue. |
| Reidentifiable or sensitive personal data | `reidentifiable_or_sensitive_personal_data` | `DARK` | Held. No raw private data, precise location, credentials, private communications, or linkable personal data in offers or samples. |
| Struck or non-operator person data | `struck_or_non_operator_person_data` | `DARK` | Held by policy. Requires a new authority case, not package refinement. |

## Buyer-Screening Minimum For Any Later Non-DARK Row

Any later upgrade for non-biometric/deidentified tiers needs, at minimum:

- Buyer is sophisticated/institutional and screened for foreign-adversary
  control.
- Contract prohibits surveillance misuse, reidentification, onward sale,
  marginalized extraction, employment/credit/insurance eligibility use, and
  person-targeting.
- Package exposes only metadata and aggregate claims until contract acceptance.
- No biometric, health, precise-location, credential, private-communication,
  secret-value, non-operator person, or struck data leaves the system.
- Reidentification risk review accounts for buyer-side joins, not just the
  dataset in isolation.
