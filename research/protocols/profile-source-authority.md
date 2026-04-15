# Profile source authority — filesystem-authoritative

**Status:** decided — filesystem-authoritative
**Decided:** 2026-04-15 (LRR Phase 1 item 10e)
**Spec reference:** `docs/superpowers/specs/2026-04-15-lrr-phase-1-research-registry-design.md` §3.10e
**Epic reference:** LRR Phase 1 epic spec `docs/superpowers/specs/2026-04-14-livestream-research-ready-epic-design.md` §5 Phase 1 item 10

## Decision

**`profiles/*.yaml` on the filesystem is the canonical source of truth for operator profile facts. Qdrant `profile-facts` collection is a derived index.**

## Rationale

The council uses a filesystem-as-bus architecture per the constitutional `single_user` axiom: one operator, one machine, no multi-user coordination, filesystem surfaces are the canonical state. Qdrant `profile-facts` exists to support semantic retrieval (vector similarity over profile attributes) but the underlying facts live in `profiles/*.yaml` on disk. Treating the YAML as authoritative matches the filesystem-as-bus default and makes deletion semantics clean:

- **Edit flow:** operator edits `profiles/<dimension>.yaml` → reactive engine picks up the inotify event → sync agent re-embeds the changed entries into Qdrant → derived index reflects the new state
- **Delete flow:** operator removes an entry from `profiles/<dimension>.yaml` → reactive engine picks up the inotify event → sync agent computes the diff + issues Qdrant delete → derived index reflects the removal
- **Rebuild flow:** `profiles/*.yaml` can be re-embedded into Qdrant from scratch at any time; the reverse is not safe because Qdrant may hold stale embeddings from deleted-but-not-purged entries

## Drift detection

Q024 #88 (close-out handoff) and Q026 Phase 4 Finding 3 observed that Qdrant `profile-facts` and the `profiles/*.yaml` files diverge over time — Qdrant accumulates points for entries that have been removed from the YAML, and vice versa. The drift is a derived-index staleness problem, not a data-loss problem, because the YAML is authoritative. The sync agent needs a reconciliation pass that walks the YAML + issues corresponding Qdrant upserts/deletes.

## Implementation implications

Consumers reading profile facts:

1. **Prefer `profiles/*.yaml`** for exact fact lookups — parse directly, bypass Qdrant
2. **Use Qdrant** for semantic retrieval only — vector similarity search over profile attributes, no direct fact authority
3. **On divergence:** trust the YAML; treat Qdrant mismatches as a sync bug and surface via a reconciliation metric or manual `rebuild-profile-facts.py` invocation

Writers mutating profile facts:

1. **Write to the YAML first** — the sync agent picks up inotify events and propagates to Qdrant asynchronously
2. **Do NOT write to Qdrant directly** — that would bypass the YAML-authoritative invariant and create drift the sync agent won't detect

## Related items

- Q024 #88 (drift observation)
- Q026 Phase 4 Finding 3 (drift quantification)
- LRR Phase 1 item 10e (this decision)
- `shared/dimensions.py` — the 11 profile dimensions authority lives in code; the per-dimension YAML files live in `profiles/`
- Sync agents that touch `profile-facts`: see `agents/_profile_*` (may be several)

## Alternative rejected

**Qdrant-authoritative** was considered and rejected. Under that model, `profiles/*.yaml` would become a cache rebuilt from Qdrant on restart. Reasons for rejection:

1. **Violates filesystem-as-bus.** The constitutional architecture is "filesystem is canonical, services are derived." Inverting that just for profile facts would introduce an exception the operator has to remember.
2. **Qdrant is not a durable store in the council stack.** Qdrant containers have been restarted + restored from backups multiple times; the YAML files are git-tracked and survive any Qdrant wipe.
3. **YAML is operator-editable.** The operator can open a YAML in a text editor and fix a fact directly. Operator-editing a Qdrant vector is not a thing.
4. **Qdrant-authoritative would break tests.** Many council tests construct profiles by writing YAML fixtures; Qdrant is mocked or skipped. Inverting authority would require rewriting all those tests to seed Qdrant first.

The decision is defaulted to filesystem-authoritative and recorded here. Operator can override via a future condition + amendment if the tradeoffs shift.
