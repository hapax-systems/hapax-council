---
title: "Legal-Posture Registry - Whistleblower Subtree"
type: legal-research
created: 2026-06-30
authority_case: CASE-SDLC-REFORM-001
parent_request: REQ-20260628-mdlc-tax-legal-posture-registry
parent_spec: hapax-council/docs/superpowers/specs/2026-05-30-sdlc-frictionless-self-direction-design.md
cc_task: 20260628-registry-phase4-whistleblower-subtree
tags: [legal-registry, g2, whistleblower, monetization, governance]
status: active
---

# Legal-Posture Registry - Whistleblower Subtree

This note records the phase 4 research basis for the `whistleblower` rows in
`docs/monetization/legal-posture-registry.yaml`.

## Gate Conclusion

All phase 4 rows remain `DARK`. The cited authorities show viable statutory
programs and procedural routes, but they do not create Hapax clearance. A row
can move to `PARTIAL` or `LIT` only after counsel has approved the concrete fact
pattern, source acquisition, privilege/confidentiality posture, filing route,
and operator signature.

## Encoded Rules

### Original Information And Public Sources

SEC award eligibility turns on voluntary original information provided to the
Commission in the required form and manner. Rule 21F-4 requires independent
knowledge or independent analysis, and excludes information derived exclusively
from judicial/administrative hearings, government reports/audits/investigations,
or news media unless the claimant is a source. Rule 21F-9 requires SEC Form TCR
or another SEC-designated submission route, plus a penalty-of-perjury
declaration.

CFTC rules are parallel for this registry's purposes: the claimant submits
information on Form TCR, the information must be original, and public-source-only
information does not clear the original-information screen without qualifying
source status or independent analysis.

The False Claims Act has a separate public-disclosure bar. A court dismisses a
qui tam claim based on substantially the same allegations or transactions
already publicly disclosed in specified federal proceedings, reports, audits,
investigations, or news media unless the Government opposes dismissal or the
relator is an original source.

IRS whistleblower claims require Form 211 and specific, timely, credible
information. IRS materials also flag taint, privilege, ethical, and
representative-status issues, so this row remains DARK until counsel screens any
candidate submission.

### File To Government First

The registry encodes a frozen workflow rule: the first external action for any
monetized whistleblower path is counsel intake or a government/court procedure.
For SEC and CFTC this means Form TCR or an agency-designated route. For IRS this
means Form 211. For FCA qui tam this means a counsel-controlled complaint filed
under seal and served on the Government, not the defendant.

No target contact, warning, demand, settlement request, private bounty request,
press leak, or public leverage step is cleared before that government-first
route. This is stricter than any single program's procedure because it protects
eligibility, seal/privilege posture, and the extortion boundary.

### Digital Realty Citation Cleanup

Digital Realty Trust, Inc. v. Somers is not an award-eligibility or
original-information citation. It is an anti-retaliation holding: Dodd-Frank's
anti-retaliation remedy is limited to individuals who reported securities-law
information to the SEC in the manner required by the statute/rules. Use it only
for anti-retaliation posture, and only after counsel checks the actual reporting
sequence and employment facts.

### Extortion Tripwire

18 U.S.C. 873 makes it a federal offense to demand or receive money or another
thing of value under a threat of informing, or as consideration for not
informing, against a violation of U.S. law. Related exposure can arise under 18
U.S.C. 875(d) for interstate extortionate threats to property or reputation and
under 18 U.S.C. 1951 when commerce is affected. The only potentially cleared
monetization channel is a statutory award program after the required
government/court route.

## Source Authorities

- SEC: 15 U.S.C. 78u-6; 17 CFR 240.21F-2 through 240.21F-11; especially
  Rule 21F-4(b) and Rule 21F-9:
  https://www.ecfr.gov/current/title-17/chapter-II/part-240/subject-group-ECFR821bdfb7bc8017f
- Digital Realty: Digital Realty Trust, Inc. v. Somers, 583 U.S. 149 (2018):
  https://supreme.justia.com/cases/federal/us/583/16-1276/
- CFTC: 7 U.S.C. 26; 17 CFR part 165; CFTC Whistleblower Program materials:
  https://www.ecfr.gov/current/title-17/chapter-I/part-165 and
  https://www.whistleblower.gov/
- IRS: 26 U.S.C. 7623; 26 CFR 301.7623-1; IRS Form 211 guidance; IRM 25.2.2:
  https://www.ecfr.gov/current/title-26/chapter-I/subchapter-F/part-301/subpart-ECFRb6a8144588833b0/subject-group-ECFRab8d8de6db79758/section-301.7623-1,
  https://www.irs.gov/help/submit-a-whistleblower-claim-for-award, and
  https://www.irs.gov/irm/part25/irm_25-002-002
- FCA: 31 U.S.C. 3730(b)(2), 3730(d), and 3730(e)(4); DOJ Justice Manual
  4-4.110:
  https://www.law.cornell.edu/uscode/text/31/3730 and
  https://www.justice.gov/jm/jm-4-4000-commercial-litigation
- Extortion boundary: 18 U.S.C. 873, 18 U.S.C. 875(d), and 18 U.S.C. 1951:
  https://www.law.cornell.edu/uscode/text/18/873,
  https://www.law.cornell.edu/uscode/text/18/875, and
  https://www.law.cornell.edu/uscode/text/18/1951

## Recheck Commands

Registry contract:

```bash
uv run python - <<'PY'
from pathlib import Path
import yaml

registry = Path("docs/monetization/legal-posture-registry.yaml")
data = yaml.safe_load(registry.read_text())
rows = data["rows"]
keys = [(row["surface"], row["venue"], row["instrument"]) for row in rows]
phase4 = [
    row for row in rows
    if row.get("source_task") == "20260628-registry-phase4-whistleblower-subtree"
]

assert len(keys) == len(set(keys)), "duplicate registry tuple"
assert len(phase4) == 7, f"expected 7 phase-four rows, got {len(phase4)}"
assert {row["surface"] for row in phase4} == {"whistleblower"}
assert all(row["g2_verdict"] == "DARK" for row in phase4)
assert all(row["operator_signed"] is False for row in phase4)
assert any(row["instrument"] == "file_to_government_first" for row in phase4)
assert any(row["instrument"] == "extortion_boundary" for row in phase4)
for row in phase4:
    citation = row.get("citation", "")
    if row["instrument"] != "sec_anti_retaliation":
        assert "Digital Realty" not in citation, row["instrument"]
print(f"whistleblower registry recheck OK: total={len(rows)} phase4={len(phase4)}")
PY
```

## Registry Implications

Every concrete whistleblower workflow must resolve these blockers before any
non-DARK verdict:

- Counsel approves the exact source, facts, privilege/taint posture, and filing
  path.
- The operator signs the registry row after counsel review.
- The row records a filing route and receipt policy that does not store secrets,
  privileged material, or target-sensitive facts in the registry.
- Public-source-only information is rejected unless counsel confirms original
  source status or independent analysis that materially adds to public facts.
- Digital Realty is not cited for bounty eligibility.
- Any communication that could be understood as "pay or I report/publish" is
  rejected before drafting.
