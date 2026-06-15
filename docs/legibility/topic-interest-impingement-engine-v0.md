# Topic Interest Impingement Engine v0

## Contract

The topic-interest engine treats interestingness as systemic impingement
pressure. It does not produce weblog suggestions, segment suggestions, operator
todo lists, publication verdicts, or schedule decisions.

Inputs are structured observations from chronicle, research registry, tasks,
reviews, programme boundaries, source observations, platform aggregates, or
external references. Outputs are auditable decisions that may carry an existing
`Impingement` and, when gates permit, an optional `ContentSourceObservation` for
the existing content-candidate daemon.

## Why This Shape

Research on interestingness and exploratory data analysis treats insight value
as multidimensional: novelty, surprise, relevance, diversity, presentation, and
peculiarity must be separated. Topic Detection and Tracking, first-story
detection, and topic-conditioned novelty detection treat stream novelty as a
history-conditioned problem, not as string search. Horizon scanning treats weak
signals as material for preparedness and investigation, not predictions.
Contextual bandits and Thompson sampling supply a controlled exploration model.
Human-in-the-loop research supports explicit human control points, while
alert-fatigue literature requires tiering, deduplication, and noninterruptive
defaults.

Local Hapax architecture already matches this: `shared/impingement.py` is the
universal activation currency, `shared/exploration.py` models curiosity and
exploration pressure, `shared/content_candidate_discovery.py` stops at candidate
emission, and `shared/content_programme_scheduler_policy.py` keeps public,
private, refusal, correction, and programme routes gated.

## Score Vector

The engine scores:

- `novelty`
- `surprise`
- `relevance`
- `evidence_density`
- `trajectory`
- `public_value`
- `research_value`
- `actionability`
- `staleness`
- `rights_privacy_risk`
- `claim_risk`
- `duplicate_pressure`
- `operator_cost`

The scalar score is only a routing projection. It is not truth, publication
authority, or programme authority.

## Action Meanings

- `ignore`: no output.
- `watch`: preserve the decision without recruitment pressure.
- `research_more`: emit research pressure only.
- `frame_candidate`: emit systemic framing/programme pressure.
- `emit_content_observation`: also emit a content-source observation.
- `operator_question`: interrupt only for high-value unresolved authority.
- `refusal_candidate`: recruit refusal/correction work.

## Gates

Content-source observation emission requires evidence refs, provenance refs,
freshness TTL, low rights/privacy risk, low claim risk, actionability, and
publication relevance. Current-event and trend material is downgraded to
`dry_run`; popularity and trend pressure never become truth warrant.

Programme and segment systems consume impingement pressure as a soft prior. The
pressure must not reduce the candidate set, schedule a segment, or bypass
public/live/audio/witness gates.

## Research Sources

- Interestingness Measures for Exploratory Data Analysis:
  https://www.cse.uoi.gr/~pvassil/publications/2024_ADBIS/ADBIS24.pdf
- NIST Topic Detection and Tracking overview:
  https://www.nist.gov/publications/topic-detection-and-tracking-evaluation-overview
- Topic-conditioned Novelty Detection:
  https://www.cs.cmu.edu/~jgc/publication/Topic_Conditioned_Novelty_Detection_ACM_2002.pdf
- Horizon scanning and foresight methods:
  https://www.ncbi.nlm.nih.gov/books/NBK556423/
- Empirical evaluation of Thompson sampling:
  https://papers.nips.cc/paper_files/paper/2011/file/e53a0a2978c28872a4505bdb51db06dc-Paper.pdf
- Human-in-the-loop machine learning:
  https://link.springer.com/article/10.1007/s10462-022-10246-w
- AHRQ alert fatigue primer:
  https://psnet.ahrq.gov/primer/alert-fatigue
