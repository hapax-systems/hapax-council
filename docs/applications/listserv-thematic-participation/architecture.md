# Public-Archive Listserv Participation — Architecture

**cc-task:** `leverage-mktg-listserv-thematic-participation` (WSJF 3.5)
**Composed:** 2026-04-26

## Premise

Public-archive listservs (empyre, sc-users-archive, MSR working-group lists, etc.) are addressable + crawler-reachable surfaces where Hapax-relevant work can be cited into existing cross-disciplinary conversations. The constraint is strict: **publish-only, never reply-thread.** Direct outreach is REFUSED per `cold_contact/candidate_registry.py` (no email/telephone fields by design); listserv posting that is reply-shaped reintroduces the same dynamic.

The daemon-tractable pattern: post one-off citation-graph contributions to relevant threads as topic-relevant new threads (NOT as Re: replies), with a clear stance: "this Hapax artifact is potentially relevant to the discussion at <archive URL>; here's the cite-able resource". Then stop. The listserv archive becomes the citation-graph node.

## Candidate listservs (substrate-fit)

| Listserv | Audience | Substrate fit | Posting cadence |
|---|---|---|---|
| **empyre** | New media + critical-theory researchers | Refusal-as-data + operator-referent policy + Oudepode framing | ≤1 post/quarter |
| **sc-users-archive** | SuperCollider audio-research community | Studio compositor + livestream-as-research-instrument | ≤1 post/quarter |
| **MSR working-group lists** | Mining-software-repositories researchers | MSR 2026 dataset paper substrate (PR #1686) | ≤1 post/year (announcement only) |
| **arxiv-cs-HC subscribers** (open list) | HCI researchers | Velocity findings + multi-session coordination | ≤1 post/year |
| **AI safety mailing lists** (LessWrong-adjacent, FLI) | AI safety researchers | Constitutional governance + refusal-as-data | ≤1 post/quarter |

## Constraints (encoded as the publisher contract)

The daemon-tractable publisher MUST enforce:

1. **No reply-thread**: every post is a new thread. The composer never reads the listserv archive's existing threads to thread-reply. If a thread exists about a Hapax-adjacent topic, the post is "Hapax has shipped a related artifact" — a citation-graph touch, not a discussion contribution.

2. **No subscription-state**: Hapax does not subscribe + read the listserv. Posts originate from a write-only mailbox; replies (if any) route to a quarantine inbox monitored by `mail-monitor` and surfaced as candidate refusal-briefs (most replies will be off-topic / spam / disagreements that the operator does not engage with).

3. **One artifact per post**: each post references exactly one shipped Zenodo deposit + arXiv preprint pair. No bundled "here are 5 things". Forces posts to be high-signal.

4. **Cadence cap**: per-listserv cadence (per § Candidate listservs above). Mass-posting trips the cold-contact-graph anti-pattern.

5. **Refusal-as-data on rejection**: if a listserv moderator rejects the post, the rejection becomes a refusal brief with a stable slug for citation-graph cross-reference.

## Composer shape

```python
# agents/marketing/listserv_publisher.py — sketch
class ListservPublisher(PublisherKit.PublisherBase):
    slug: ClassVar[str] = "marketing-listserv-thematic"
    tier: ClassVar[Tier] = Tier.CONDITIONAL_ENGAGE  # operator approves the per-post target

    requires_legal_name: ClassVar[bool] = False  # post is operator-non-formal

    def _emit(self, artifact: PreprintArtifact, target: ListservTarget) -> str:
        # Compose the body via:
        # 1. Title: "{artifact.title} — preprint + dataset"
        # 2. Body: 2-3 paragraphs from artifact.abstract + the 4
        #    sanctioned operator referents only (per project_operator_
        #    referent_policy)
        # 3. Citation block: arXiv + Zenodo DOI + SWHID
        # 4. Submission via mail-monitor outbound channel (depends on
        #    mail-monitor-006-webhook-receivers cc-task)
        ...
```

## Dependencies

The cc-task lists 2 dependencies; both are shipped or in-flight:

- `mail-monitor-006-webhook-receivers` — ships the outbound-mail channel the publisher uses. Status pending; check vault.
- `awareness-state-stream-canonical` — provides the cadence-throttling signal (don't post during high-stimmung windows). MERGED via PR #1605.

## 5-component shipping plan

| # | Component | Path | Effort | Dep |
|---|---|---|---|---|
| 0 | This architecture doc | shipped here | 30 min | none |
| 1 | Per-listserv config YAML | `config/marketing/listservs.yaml` | 1h | none |
| 2 | `ListservPublisher` class | `agents/marketing/listserv_publisher.py` | 2-3h | mail-monitor-006 |
| 3 | Outbound mail integration smoke test | `tests/marketing/test_listserv_publisher.py` | 1-2h | #2 |
| 4 | Daemon scheduler (cadence enforcement) | `agents/marketing/listserv_scheduler.py` + systemd timer | 2-3h | #2, #3 |
| 5 | Operator-approval gate (per-post) | UI hook in awareness panel | 1-2h | #4 |

**Total daemon scope:** ~7-11h across 5 follow-up PRs, gated on `mail-monitor-006-webhook-receivers` shipping first.

## Constitutional posture

- `feedback_full_automation_or_no_engagement`: composition + send daemon-tractable; per-post operator approval (#5) is the only operator-mediated step (CONDITIONAL_ENGAGE tier).
- `interpersonal_transparency`: no subscription-state on the listserv side; quarantine inbox for replies; no listserv-subscriber identification persisted.
- Refusal-as-data: rejected posts publish refusal briefs; the cumulative refusal corpus across listservs becomes meta-substrate.
- `single_user`: posts attributed to Oudepode (non-formal referent per `project_operator_referent_policy`); legal name reserved for formal-attribution fields if a listserv requires them (none of the candidates do).

## Cross-references

- Cold-contact graph-touch policy (cadence-cap pattern reuse): `agents/cold_contact/graph_touch_policy.py`
- Refusal-brief publisher: `agents/publication_bus/refusal_brief_publisher.py`
- Mail-monitor (outbound channel dependency): `agents/mail_monitor/`
- Velocity findings (per-post substrate): PR #1677
- arXiv velocity preprint architecture: PR #1663
- Operator-referent policy + CI guard: PR #1661

— alpha
