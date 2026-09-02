# Estate store registration — Stage 1

Status: source files only; report-only; not installed or enabled.

`config/estate-store-registry.yaml` is the passive enumeration artifact. The
reader in `shared.estate_store_registry` returns only entries declared for the
calling consumer. It never discovers an undeclared filesystem path on a
consumer's behalf. The sweep is the separate reality check.

## Report surfaces

An activated sweep would write JSON reports beneath
`~/.cache/hapax/estate-registration/reports/`. Individual Canary B flags,
canary registrations, and detector state live under the same declared runtime
store. Stage 1 writes reports and receipts only. Its report records
`mutation_actions: []`; it has no rename, move, delete, quarantine, or restore
operation.

Vendor binary roots, including `~/.claude`, `~/.codex`, `~/.kimi-code`,
`~/.gemini`, `~/.grok`, and the opencode store, are permanently
`class: vendor-root, action: flag-only`. Registry validation refuses a stronger
action even if a future stage changes the general policy.

The grandfather command writes a reviewable YAML fragment and refuses an
incomplete scan. Every emitted row is `lifecycle: grandfathered`, carries the
scan root and timestamp that discovered it, and records
`operator_blessing: null`. It does not edit the registry or confer blessing:

```bash
uv run python scripts/hapax-estate-store-registry grandfather \
  --host appendix --output reports/appendix-grandfather.yaml
```

## Canary contract

The hourly originator writes both canaries on its local host. Canary A writes a
unique artifact under the registered runtime store and a matching runtime
registration receipt. Canary B writes a unique store-shaped directory beneath
`30-areas/hapax`; at UTC hour 00 it instead writes a new `$HOME` dotfile root.
It has a manifest but deliberately has no registration.

The opposite host checks Canary A over the existing SSH link within 90 minutes.
It also requires the same origination event's Canary B manifest, so a partially
dead originator is not reported healthy. The daily unit asks the opposite host
to run its own sweep. A dead host, broken SSH link, stale Canary A, or incomplete
pair makes the peer unit fail loudly.

The sweep reads Canary B manifests independently from candidate classification.
Two consecutive distinct manifests that do not appear in the sweep's
unregistered findings cause it to file
`incident-estate-detector-dead-*.json`. The incident names
`hapax-estate-store-registry sweep` as the dead detector. Stage 1 deliberately
does not self-clean either canary because the accepted stage forbids sweep
deletion; cleanup remains an activation-stage decision.

## New-unit declaration report

The deploy checker is advisory in Stage 1. A new service with `ExecStart=` must
declare one or more registered store IDs as `X-Hapax-Store=...`, or declare the
computed absence explicitly as `X-Hapax-Store=None`. Findings return exit zero
and say `blocking: false`; inability to determine the exact new-unit set refuses
instead of substituting a guessed base:

```bash
uv run python scripts/check-estate-store-declarations.py --base-ref origin/main
```

This is not registered as a hook and is not called by a deploy service.

## Consumption binding status

The council worktree contains the registry and reader, but the named frame
consumers are canonical vault files outside this lane's permitted mutation
root. They must not be silently represented as bound:

- TODO `census`: replace the hard-coded `~/.claude`, foreign-capability, vault,
  and repo source enumeration in
  `30-areas/hapax/frame/census.py` with
  `enumerate_stores(..., consumer="census")` from this reader.
- TODO `assemble.py`: replace `DATA.glob("brief-*.jsonl")` in
  `30-areas/hapax/frame/assemble.py` with registry entries declared for
  `assemble`; explicit `--extra` inputs must be registered or refused.
- TODO brief dispatch: bind the frame brief producer/dispatcher to
  `consumer="brief-dispatch"`; no uniquely named brief-dispatch implementation
  exists in this council tree.
- TODO pillar matcher: replace memory/vault/project root constants and recursive
  walks in `30-areas/hapax/frame/pillar_census.py` with
  `consumer="pillar-matcher"` enumeration.
- TODO task intake: identify the frame task-intake dominator, then replace its
  source enumeration with `consumer="task-intake"`; the council tree contains
  multiple unrelated intake surfaces, so choosing one here would be an
  unmeasured binding.

These TODOs require a separately authorized vault/source-activation lane. No
unit file in this change is installed, enabled, started, or added to a preset.
