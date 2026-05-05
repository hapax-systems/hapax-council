# Anthropic Claude for Open Source submission packet

**Task:** `leverage-vector-anthropic-cco-submit`
**Status:** Ready for operator review; not submitted
**Verified:** 2026-05-05
**Official form:** `https://claude.com/contact-sales/claude-for-oss`
**Terms:** `https://www.anthropic.com/claude-for-oss-terms`
**State file:** `~/hapax-state/applications/anthropic-cco-2026.yaml`

## Source snapshot

- The current Claude for Open Source page says applications are reviewed on a
  rolling basis, up to 10,000 contributors are accepted, and approved applicants
  receive an activation link for the subscription period.
- The stated benefit is six months of Claude Max 20x.
- The maintainer track is for a primary maintainer or core team member of a
  public GitHub repo with 5,000+ stars or 1M+ monthly NPM downloads, with
  commits, releases, or PR reviews in the last three months.
- The same page invites applicants outside those thresholds to apply if they
  maintain something the ecosystem quietly depends on and can explain it.
- The Terms page states that submitting an application agrees to the program
  terms; the application period expires on June 30, 2026 unless extended; each
  eligible person may receive only one subscription.
- The embedded HubSpot form currently uses portal ID `23987127` and form ID
  `64c4f246-3bd4-4d55-ba2b-0c2e52b4a8f2`.

## Form fields

Operator-only fields:

- `firstname` - first name, required.
- `lastname` - last name, required.
- `email` - existing Claude account email if applicable, required.

Public/prefill fields:

- `github_profile` - `ryanklee`, required; operator may replace with the exact
  desired GitHub handle or profile URL.
- `repository_url` - `https://github.com/ryanklee/hapax-council`, optional.
- `message__oss` - use the "Other info" text below, optional.

Hidden UTM fields are present in the form definition but should be left to the
official page unless the operator has a specific campaign value.

## Other info

Hapax applies under the discretionary ecosystem-impact track. It is a
single-operator, publicly inspectable research infrastructure stack for
externalized executive function: concurrent Claude Code/Codex sessions
coordinate through filesystem-as-bus work state, reactive rules, and Obsidian
task ledgers rather than a central coordinator. The council repo and sister
repos document a reproducible architecture with roughly 200 agents, a local
LLM/API/runtime substrate, a voice daemon, a studio compositor, and a
5-axiom constitutional governance layer. The public value is not a conventional
high-star package; it is a research instrument for agentic software engineering
and human-AI operating systems.

Claude is structurally central to Hapax. The project uses Claude for sustained
multi-session software work, governance drafting, research synthesis, refusal
analysis, and publication-bus preparation. The repo records the operating
method rather than merely consuming model output: cc-task notes, relay YAML,
PRs, and research drops make the coordination substrate auditable. A recent
18-hour sample recorded 30 PRs/day, 137 commits/day, about 33,500 LOC churn/day,
and a sustained research-drop cadence; those numbers are used as evidence for
the substrate claim, not as a vanity metric.

The strongest fit with Anthropic's research posture is the refusal-as-data and
citation-graph layer. Hapax publishes refused or deferred engagements as
first-class artifacts with DataCite RelatedIdentifier edges, so abstentions,
constraints, and policy boundaries become citable evidence rather than private
absence. That directly supports the operator's research-instrument positioning:
Hapax treats its own operational limits, constitutional commitments, and
submission outcomes as part of the public evidence graph. If this application
is rejected, the rejection will be recorded in the same state file and can feed
the refusal-brief publication path.

The application is intentionally transparent about licensing. The runtime repos
use the in-repo license matrix, including PolyForm Strict for single-operator
runtime code, MIT for the MCP bridge, and CC BY-NC-ND for the constitution and
research/specification surfaces. The request is therefore for support of a
public research and infrastructure project with open inspectability and
citable artifacts, not a claim that every runtime component is permissively
licensed.

Grant use would extend the current Claude routing budget for sustained
multi-session work and accelerate the planned public research outputs:
velocity/reproducibility reporting, MSR-style dataset packaging, Anthropic
Constitutional AI comparison, and DataCite/ORCID citation-graph publication
surfaces.

## Operator checklist

- Review or edit the "Other info" text above.
- Confirm first name, last name, and Claude account email.
- Confirm GitHub handle/profile and repository URL.
- Read the Claude for Open Source Terms and decide whether to submit.
- If submitted, record the confirmation/outcome in
  `~/hapax-state/applications/anthropic-cco-2026.yaml`.
- If rejected or intentionally not submitted, record that operator-authored
  decision in the same state file before closing the task.
