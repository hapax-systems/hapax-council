# Adoptability teeth

Row: `adoptability-teeth-gates-20260916`. Parent: `frame/coordination-20260904/ADOPTABILITY-DETERMINATION-20260916.md` §7.
Operator instruction (2026-09-16): *"make sure all the adoptability determinations have sharp teeth."*

A determination without a refusing mechanism is representation. Each determination below names
the gate that refuses, the typed reason it prints, and where it lives. One predicate module —
`shared/adoptability_gate.py` — is consulted by every writer; no writer re-derives a rule.

## The refusals

| Refusal | Gate | Fires when | Where it is enforced |
|---|---|---|---|
| `row_refused:adoptability_block_missing` | lint (A5) | a `garage-door` row has no `adoptability:` block | `scripts/gate-manifest-check.py --rows-dir`, and every stage writer (a row without its block cannot leave offered) |
| `row_refused:adoptability_field_missing:<field>` | lint (A5) | the block lacks a receipt path or one of the eleven acceptance fields | same |
| `row_refused:frontmatter_unparseable:<what>` | lint | any row's frontmatter fails to parse, or a list carries the unquoted `key: value` accident — a one-key mapping whose sole key is not an identifier (`- config/ (row schema: adoptability block)`), or any mapping inside a declared scalar-list field (`mutation_scope_refs`, `tags`, `depends_on`, `blocks`). Identifier-keyed structured items (`required_tools`, `refusal_history`, `source_touch_conflicts`, …) are design, not accidents: 1,522 of them measured across the vault on 2026-09-16, 3 accidents. `scripts/cc-scope-widen`, the estate's own writer of `mutation_scope_refs`, used to strip quotes on read and write items back bare — re-introducing the accident on every widen; it now quotes any item that would not round-trip as a scalar | `gate-manifest-check.py --rows-dir`; the hook refuses an edit that leaves a garage-door row unparseable |
| `stage_refused:prior_art_receipt_absent` | stage (A2) | a `garage-door` row would leave `offered`/S1 without a valid prior-art receipt | `scripts/cc-claim` (claim), `scripts/cc-stage-advance` (advance), `hooks/scripts/cc-task-gate.impl.sh` §3a (hand edit) |
| `stage_refused:demand_receipt_absent` | stage (A2) | … without a demand receipt naming who asked | same three writers |
| `stage_refused:garage_door_tag_removed` | stage (A2) | an edit deletes the tag — an escape is not a transition | hook §3a |
| `row_converted:contribution` | stage (A2) | prior art is BACKED and usable and the row is not yet `kind: contribution` | `cc-stage-advance` converts the row and proceeds; `cc-claim` and the hook refuse until the row says contribution |
| `release_refused:adoptability_receipt_absent` | release (A3) | a `garage-door` row releases without a receipt at `adoptability.receipt` | `scripts/avsdlc-release-precheck.py` (keystroke, via `pr-release-gate.sh`) and `scripts/cc-pr-autoqueue.py` (timer) |
| `release_refused:adoptability_receipt_unsigned` | release (A3) | the receipt's HMAC does not verify under the public-gate authority key, or its issuer is not trusted | same |
| `release_refused:adoptability_receipt_stale` | release (A3) | now is past `stale_after` (or `observed_at` + 24 h) | same |
| `release_refused:adoptability_receipt_mismatch` | release (A3) | the receipt is for another gate, another repo, or another install line | same |
| `release_refused:adoptability_failed:<check>` | release (A3) | a named check in the receipt did not pass | same |
| `release_refused:estate_binding_in_install_surface` | release (A1/A4) | `install_line`, `platforms`, `api` or `install_surface` names an estate noun (vault path, cc-task rows or tooling, reins, a hapax-council checkout, `~/.cache/hapax`, lanebus, `HAPAX_*`, hapax-secret, the dispatcher) — independent of the receipt | same |
| `receipt_refused:container_runtime_absent` · `receipt_refused:signing_credential_absent` · `receipt_refused:manifest_invalid:<field>` | producer | the producer cannot measure or cannot sign; nothing is written | `scripts/hapax-adoptability-receipt` |

The vocabulary is closed and pinned by `tests/shared/test_adoptability_gate.py::test_refusal_vocabulary_is_closed_and_exact`.

## What "garage-door" means here

A row is judged when its `tags` contain exactly `garage-door`. That tag marks **an artifact row** —
one thing the estate intends to publish through a door. Rows *about* the door (this one carries
`garage-door-teeth`) are not artifact rows and are not judged. Template:
`config/cc-task-templates/garage-door.md` (a test pins that it carries every required field).

## The row block

```yaml
tags: [cc-task, garage-door]
adoptability:
  prior_art_receipt: <path>      # A2 — see receipt shapes
  demand_receipt: <path>         # A2
  install_line: "curl -fsSL https://… | sh"   # (i)
  platforms: [linux, macos, windows]          # (i)
  zero_config: true              # (ii)
  ttfv_seconds: 60               # (iii) budget; the receipt carries the measurement
  replaces_nothing: true         # (iv)
  api: "cli + unix socket"       # (v)
  licence: Apache-2.0            # (vii) Apache-2.0 or MIT
  repo_open: owner/name          # (vii) the public repository; the receipt must name the same repo
  release_notes: <url>           # (viii)
  compare_page: <url>            # (vi)
  operator_voice_post: <url>     # (ix)
  receipt: <path>                # A3 — written by scripts/hapax-adoptability-receipt
```

Receipt paths are relative to the vault root (`~/Documents/Personal`; override with
`HAPAX_ADOPTABILITY_RECEIPT_ROOTS`, `os.pathsep`-separated). Absolute paths must lie inside a
root; `..` escapes, unknown extensions and missing files read as *absent*. Recommended home:
`20-projects/hapax-cc-tasks/_evidence/adoptability/<artifact>/`.

## Receipt shapes

**Prior art** (`prior_art_receipt`) — standing epistemic rule 2 made mechanical: two
differently-shaped searches, then a verdict.

```yaml
search_shapes:
  - {shape: github_code_search, query: "PreToolUse PermissionRequest idle working blocked", result: "…"}
  - {shape: package_registry,   query: "claude code status reporter tmux", result: "…"}
verdict: BACKED          # or UNBACKED
tier: "1"                # required when BACKED
source: daocoding/herdr-claude-lifecycle   # required when BACKED
usable: true             # required when BACKED; true ⇒ the row converts to kind: contribution
```

**Demand** (`demand_receipt`) — who asked, in their words or by count:

```yaml
asked_by: ["issue #12 (two tmux users)", "operator directive 2026-09-16"]
# or
probe: {asked: 5, answers: ["keep", "keep", "drop", "keep", "keep"]}
```

**Adoptability** (`receipt`) — produced, never hand-written:

```bash
export HAPAX_PUBLIC_GATE_AUTHORITY_HMAC_KEY=…    # the same key the public gates verify with
scripts/hapax-adoptability-receipt --manifest artifact.yaml \
  --out ~/Documents/Personal/20-projects/hapax-cc-tasks/_evidence/adoptability/<artifact>/adoptability.json
```

The producer runs the install line in a bare container (`podman`, else `docker`; neither ⇒
refusal) with no volumes and no estate environment, then the zero-config command and the
first-value command, timing both against the budget; it reads the repository facts through
`gh api` (licence SPDX ∈ {Apache-2.0, MIT}, public, issues enabled, not archived, a latest
release with a non-empty body, a compare page that answers). The receipt carries every check
with its detail, `observed_at`/`stale_after` (24 h default), the repo and install-line digest it
was measured for, and an HMAC signature under the public-gate authority key with issuer
`review-team:hapax-adoptability-receipt`. Exit 0 on pass, 1 on fail (receipt still written, so
the failing numbers are on record), 2 on a typed refusal.

## Killswitch (incident-only, ledgered)

The SDLC gate-composition charter requires an emergency bypass for every gate. For the
teeth it is `HAPAX_ADOPTABILITY_TEETH_OFF=1` (exactly `1`): every stage and release
refusal empties — in `cc-claim`, `cc-stage-advance`, the hook's hand-edit path, the
release precheck and the autoqueue — and each bypassed evaluation writes one row
(`kind: adoptability_teeth_off_bypass`, role, surface) to
`~/.cache/hapax/methodology-emergency-ledger.jsonl` (`HAPAX_METHODOLOGY_LEDGER` overrides)
and one line to stderr. It is for the case the charter names: the receipt producer or every
container runtime failing globally, which would otherwise block every garage-door release.
It does not touch the row lint or the producer. The hook tooth also sits after the gate's own
`HAPAX_CC_TASK_GATE_OFF` / `HAPAX_METHODOLOGY_EMERGENCY` bypasses, so those cover it as they
cover the rest of the gate. Prefer a scoped, signed escape
(`scripts/coord-grant-mint --scope adoptability-teeth`) when the incident allows one.

## Operator rechecks

```bash
# lint the live rows (exit 1 lists every refusal, one line per row)
uv run python scripts/gate-manifest-check.py --skip-claude-settings \
  --rows-dir ~/Documents/Personal/20-projects/hapax-cc-tasks/active
# would this row leave offered?
python3 -m shared.adoptability_gate stage-check <row.md> --to-status claimed
# would this row release?
python3 -m shared.adoptability_gate release-check <row.md>
# the mutation battery (gate 5): every tooth removed once, every removal caught
bash tests/mutation/adoptability_teeth_mutations.sh
```

## Bindings declared swappable (delete-the-estate test)

The tag name, the block key, the receipt roots, the estate-noun list and the refusal words are
the bindings; the architecture is: *a tagged work item cannot advance without two receipts and
cannot release without a third that a producer measured and signed.* Each binding is a constant
at the top of `shared/adoptability_gate.py`.
