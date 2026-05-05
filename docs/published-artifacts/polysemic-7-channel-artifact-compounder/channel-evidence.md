---
slug: polysemic-7-channel-artifact-compounder-channel-evidence
title: "Channel evidence for polysemic-7-channel-artifact-compounder"
type: channel-evidence
cc_task: polysemic-7-channel-artifact-compounder
polysemic_audit_acknowledged_terms:
  - compliance
  - governance
  - safety
  - transparency
  - accountability
  - policy
polysemic_audit_acknowledgement_rationale: |
  The evidence note intentionally names every decoder channel and its
  governance role. The channel table is the disambiguation layer.
---
# Channel evidence for polysemic-7-channel-artifact-compounder

## Scope

This note is the channel-by-channel evidence document for the staged
refusal artifact at `docs/published-artifacts/polysemic-7-channel-artifact-compounder/source.md`.
It records repository evidence only. No DOI has been minted and no live
publication service has been touched.

## Evidence matrix

| Channel | Name | Evidence path | Acceptance claim |
|---|---|---|---|
| 1 | visual | `visual-map.svg` | The channel graph is inspectable as a visual artifact. |
| 2 | sonic | `sonic-score.txt` | The artifact carries an executable earcon recipe, not prose about sound only. |
| 3 | linguistic | `source.md` | The refusal brief body states the declined posture. |
| 4 | typographic | `source.md` | The markdown table and repeated channel numerals are part of the artifact form. |
| 5 | structural-form | `metadata.yaml` | The directory partitions source, evidence, metadata, visual, sonic, and attribution surfaces. |
| 6 | marker-as-membership | `metadata.yaml` | The slug and exact channel ids provide a repeatable marker vocabulary. |
| 7 | authorship | `attribution.yaml` | The artifact carries the authorship-indeterminacy stance explicitly. |

## Formula check

The braid vector is:

- `E=6`, `M=4`, `R=8`, `T=5`, `C=6`, `P=0`
- `U=3`
- `braid_polysemic_channels=[1,2,3,4,5,6,7]`
- `forcing_function_window` absent, so urgency is `0`
- `axiomatic_strain=0`

`scripts.braided_value_snapshot_runner.recompute_braid_score` computes
`5.20` with the channels present and `4.50` without them. The difference
is exactly the v1.1 channel bonus: `0.10 * 7 = 0.70`.

## Follow-on owner path

A production publication owner can adopt the staged artifact by passing
`agents.publication_bus.polysemic_7_channel_artifact.PolysemicSevenChannelArtifact`
through the normal refusal-deposit path. The owner must verify operator
authorization before any external DOI mint or public-service fanout.

## Pattern for future 7-channel artifacts

Future artifacts should keep the same minimum shape:

- a pure composer that exposes `body()`, `metadata()`, channel records,
  and RelatedIdentifier edges without network access
- a staged source document with `braid_polysemic_channels` set to all
  seven ids
- a channel evidence note that maps every id to an inspectable surface
- at least one non-textual visual surface and one renderable sonic
  surface, even if the sonic surface is a score rather than audio bytes
- metadata and attribution files that make structural-form,
  marker-as-membership, and authorship channels auditable
- a formula test proving `with_channels - without_channels == 0.70`
