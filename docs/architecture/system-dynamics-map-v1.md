# System Dynamics Map v1

Task: `system-dynamics-map-v1-enhancement-20260618`

Authority case: `CASE-SYSTEM-DYNAMICS-MAP-V1-ENHANCEMENT-20260618`

Parent spec: `~/Documents/Personal/20-projects/hapax-research/specs/2026-06-18-system-dynamics-map-v1-enhancement-parent-spec.md`

## Decision

Use a source-neutral semantic backbone as the default focus.

The center should be a semantic graph backbone with validation, provenance,
temporal overlays, and reproducible view manifests:

```text
source models + telemetry + event logs
  -> canonical identity graph
  -> named graph partitions for asserted/inferred/observed/simulated/rendered claims
  -> SHACL-style validation gates
  -> PROV-style transformation and evidence records
  -> persisted snapshots
  -> view manifests
  -> interactive projections
```

This keeps the visualization honest. DMN, BPMN, CMMN, SysML, ArchiMate,
runtime topology, telemetry, event logs, traces, state observations, simulations,
and rendered views are source inputs or projections over shared identity. None
of them is the global model. Those are different claim types and must remain
separable.

## Conceptual Map

Source-model families:

- `DMN`: decision model and notation for decision requirements and executable
  decision logic.
- `BPMN`: process flow can invoke or be routed by decisions and produce
  process/event evidence.
- `CMMN`: case plans can invoke decisions in less prescriptive work.
- `ArchiMate`: enterprise architecture context for capabilities, applications,
  processes, motivation, and implementation.
- `SysML v2`: systems engineering structure, behavior, requirements, analysis,
  and verification context.
- `C4/runtime architecture`: implementation topology and deployable services.

Decision-modeling source details:

- `DRD/DRG`: decision dependency surface inside DMN.
- `Decision service`: packaging boundary for callable decision behavior.
- `Decision table`: common tabular decision logic representation.
- `FEEL`: DMN expression language.
- `SBVR`: adjacent business vocabulary and rule semantics.

Execution surfaces and artifacts:

- `DMN XML/DI`: interchange and diagram serialization.
- `Rule engines`: executable target for decision tables and FEEL-compatible logic.
- `Decision runtime API`: callable service boundary.
- `PMML/ONNX/PFA-class model artifacts`: adjacent predictive/analytical model
  artifacts that often feed or sit beside decisions.

Semantic backbone and dynamic evidence:

- `RDF/OWL`: canonical identity and relationship graph.
- `SHACL`: validation contracts and data quality gates.
- `PROV-O`: provenance for imports, mappings, generated views, and evidence.
- `JSON-LD/TriG`: portable graph exchange and named graph snapshots.
- `Temporal state/events`: state is modeled as time-bounded observation or event
  evidence, not as an overwrite of model topology.
- `SCXML/XES/CloudEvents/OpenTelemetry/Trace Context`: state machine, event log,
  event envelope, telemetry vocabulary, and distributed trace correlation inputs.
- `Cytoscape.js/React Flow/Sigma`: different rendering targets driven by view
  manifests, not by independent truth models.

## Why No Single Notation Is The Core

DMN is scoped to decisions. BPMN is scoped to processes. SysML is scoped to
systems modeling. ArchiMate is scoped to enterprise architecture. OpenTelemetry
is scoped to telemetry. Each is useful, and each becomes lossy if treated as the
center for system dynamics. A faithful system map needs to represent at least
five dimensions that no single notation owns:

- Topology: components, processes, systems, people, data stores, queues, models,
  and runtime edges.
- Dynamics: state transitions, event streams, traces, logs, simulations, and
  temporal validity.
- Evidence: source documents, observations, generated outputs, confidence, and
  stale/invalid states.
- Projection: which nodes and edges were rendered, hidden, aggregated, or inferred.
- Governance: versioned contracts, validation gates, review state, and provenance.

Pushing those into any one notation would produce a familiar diagram that lies
by omission. The semantic backbone gives every source a precise place without
letting any one source flatten the rest of the system.

## Canonical Data Contract

V1 keeps `system-dynamics-map.seed.json` as the portable topology seed, but it is
no longer the whole contract. The durable package now separates topology,
claims, observations, relations, lenses, schemas, and reproducibility metadata:

- `default_focus`: neutral initial focus for the viewer; currently the
  canonical semantic backbone.
- `nodes[]`: stable identity, label, kind, layer, resolution, status, summary,
  context, hardening notes, aliases, tags, and documentation links.
- `edges[]`: stable identity, source, target, relation, layer, resolution, status,
  summary, confidence, and documentation/evidence links in `docs[]`.
- `view_scales[]`: declared scales that explain why an element appears at a given
  resolution.
- `status_kinds[]`: claim-type vocabulary. Topology elements must not use
  `observed`; observed state lives in temporal observations.
- `system-dynamics-map.claims.json`: first-class claim records for every node and
  edge, including provenance, valid time, transaction time, confidence basis,
  freshness, and contradiction state.
- `system-dynamics-map.observations.jsonl`: timestamped state/evidence records
  with observed time, valid interval, source hash, expiry, and freshness.
- `system-dynamics-map.relations.json`: controlled relation vocabulary derived
  from curated edge relations, including category, source/target kinds, layers,
  directionality, and allowed claim types.
- `system-dynamics-map.lenses.json`: persisted projections with visible/hidden
  node and edge IDs, layout, state mode, aggregation, and lossiness/reversibility.
- `schemas/system-dynamics-map/*.schema.json`: JSON Schema artifacts for seed,
  claims, observations, lenses, relations, view manifest, and package metadata.
- `system-dynamics-map.package.json` and `system-dynamics-map.lock.json`:
  reproducibility contract with source hashes, generated hashes, generator
  command, validation commands, and an explicit `git_sha: unknown` marker.
  `git_sha_role: not_recorded` is paired with that marker because artifact
  commits cannot embed their own future commit SHA. `--check` treats generated
  content hashes as the staleness key and PR history carries commit provenance.

The viewer consumes this shape and should remain replaceable. The graph contract
is the important artifact; Cytoscape is the current projection engine.

## Concrete Operating Slice

V1 adds a concrete Hapax SDLC operating slice instead of only expanding standards
coverage. The slice spans:

- `sdlc-intake`
- `cc-task-claim`
- `review-dossier`
- `pr-ci-checks`
- `merge-release`
- `operating-lens`

This slice is deliberately read-only. It shows how a real workflow can be
represented as topology plus temporal observations without making the map the
writer of task, PR, CI, or release truth. The fixture lives at
`docs/architecture/fixtures/system-dynamics-map/sdlc-operating-slice.json`.

## Hardening Rules

1. Identity must be canonical before rendering.
   Do not key nodes by display labels. Use stable IRIs or local IDs with a migration
   path to IRIs.

2. Graph partitions must remain explicit.
   Asserted architecture, inferred relationships, observed telemetry, simulated
   futures, and rendered projections belong in different named graphs.

3. Every rendered view needs a manifest.
   A view must record source snapshot, filters, aggregation rules, layout engine,
   selected scale, hidden layers, and generation time.

4. Validation runs before trust.
   SHACL-style gates should catch missing identity, invalid relation types, broken
   doc links, unsupported status values, stale observations, and orphaned render
   elements.

5. State is temporal evidence.
   Current state should be derived from observations/events with timestamps,
   confidence, source, and expiry. It should not overwrite the static topology.

6. Provenance is not optional.
   Imports, mappings, enrichments, generated edges, simulations, and view outputs
   need explicit agent/activity/source records.

7. Scale is a first-class property.
   Overview, domain, artifact, runtime, and evidence views are separate projections
   over shared identity. Aggregation must be declarative and reversible where
   practical.

8. Rendering is a product surface, not the model.
   Cytoscape.js is appropriate for the first dynamic map. React Flow is better for
   node/edge editing workflows. Sigma is a fallback for very large, simpler graphs.
   Graphviz/Mermaid remain useful for deterministic static snapshots.

## V1 Viewer

`system-dynamics-map-viewer.html` is intentionally a static file. It provides:

- Embedded seed, claim, observation, lens, and relation-vocabulary fallbacks so
  direct file-open mode does not silently degrade the projection contract.
- Persisted lens selection with visible/hidden scope, state mode,
  lossiness/reversibility, validation state, and source snapshot.
- Layer filters.
- Claim-partition filters, distinct from temporal observation state.
- Resolution slider with scale descriptions.
- Search/finder controls over labels, aliases, tags, claims, observations,
  relation vocabulary, and documentation links.
- Layout switching.
- Node and edge context panels.
- Claim/evidence/relation drilldown with source refs, source hashes,
  confidence, authority ceiling, valid time, transaction time, expiry, relation
  category, directionality, and allowed claim types.
- Lens-scoped temporal observation summaries that distinguish in-scope stale
  evidence from hidden/global stale evidence.
- Keyboard-selectable visible-element result controls, ARIA button state,
  reduced-motion layout handling, and larger touch targets.
- Current-view JSON export and PNG export from the active projection.
- External documentation links from the graph data.

This is enough to review the concept and refine the graph without committing to a
live backend or frontend framework. The viewer defaults to the semantic backbone,
not to any source notation. It loads a committed local Cytoscape
3.34.0 runtime asset from `vendor/cytoscape-3.34.0.min.js`, so basic rendering no
longer depends on CDN egress.

Persisted hardening artifacts:

- `system-dynamics-map.canonical.trig`: named-graph RDF/TriG-style snapshot for
  asserted graph content, observations, claim records, rendered-view metadata,
  and provenance.
- `system-dynamics-map.shacl.ttl`: SHACL shape contract for nodes, edges,
  rendered views, claims, observations, and provenance activity records.
- `system-dynamics-map.view-manifest.json`: versioned projection manifest with
  source hashes, visible/hidden IDs, lens metadata, runtime asset hash, and
  validation commands.
- `system-dynamics-map.package.json` / `system-dynamics-map.lock.json`:
  reproducible package metadata and generated-file hash lock.
- `system-dynamics-map.claims.json`, `system-dynamics-map.observations.jsonl`,
  `system-dynamics-map.lenses.json`, and `system-dynamics-map.relations.json`:
  companion semantic artifacts consumed by tests, the served viewer, and embedded
  direct-open fallbacks.

Browser verification lives in `tests/test_system_dynamics_map_viewer_playwright.py`.
It exercises the static viewer through Playwright and asserts that Cytoscape
draws nonblank canvas pixels after layout, not just that the seed data loaded.
The viewer tests also cover direct file-open supplemental data, lens-scoped
freshness, relation-vocabulary detail panels, finder-driven keyboard selection,
current-view export payloads, ARIA layout state, and reduced-motion behavior.

## V2 Sensemaking Workbench Slice

The viewer now treats question-first sensemaking and explanation as part of the
projection contract. The map still renders source-neutral topology, state,
evidence, projection, and governance; it does not make any notation the center.

The v2 workbench layer adds:

- inquiry modes for recurring operator questions: what gates release, what is
  stuck, what changed, what is stale, what is trustworthy, and what context is
  missing;
- synthesized readouts that derive from visible topology, relation paths,
  claim fragments, observations, stale evidence, hidden scope, and lens
  aggregation metadata;
- audience modes for operator, newcomer, collaborator, reviewer/auditor, and
  executive explanations without changing graph truth;
- guided explanation paths with scene-level focus, takeaway, and an explicit
  "what this does not prove" warning;
- an explanation export payload embedded in the current-view export, carrying
  `schema`, `inquiry_mode`, `inquiry_label`, `audience_mode`,
  `audience_label`, `explanation_path`, `explanation_label`,
  `explanation_step`, `scene_title`, visible counts, evidence summary,
  `scope_warning`, and `does_not_prove`;
- a non-canvas companion readout for visible nodes, states, relations, and
  relation categories.

This remains a static-file viewer. The workbench is intentionally derived from
the existing seed, claims, observations, relation vocabulary, lenses, and
manifest metadata. It is not a second source of truth.

The generated `system-dynamics-map.view-manifest.json` declares a
`workbench_contract` so inquiry modes, audience modes, explanation paths, and
follow-on tranches are package-level metadata rather than untracked UI prose.

The major platform work still belongs in separate governed tranches:

- bitemporal snapshot registry and diff lens;
- causality, guard, evidence, correlation, containment, and projection relation
  semantics that are distinct from edge direction;
- uncertainty classes, contradiction groups, competing evidence, and confidence
  basis categories;
- source adapter provenance chains and verification receipts;
- visible invariant registry and aggregation/lossiness ledger.

## Recheck Commands

Run these from `~/projects/hapax-council` after changing the seed graph or viewer:

```bash
uv run pytest tests/test_system_dynamics_map_artifacts.py
```

```bash
uv run --extra ci playwright install chromium
uv run --extra ci pytest tests/test_system_dynamics_map_viewer_playwright.py
```

```bash
python3 -m json.tool docs/architecture/system-dynamics-map.seed.json >/tmp/system-dynamics-map.seed.pretty.json
```

```bash
python3 scripts/system_dynamics_map_materialize.py --check
```

```bash
scripts/system-dynamics-map-gate
```

```bash
rg -n '#[0-9A-Fa-f]{3,8}\b' \
  docs/architecture/system-dynamics-map-v1.md \
  docs/architecture/system-dynamics-map.seed.json \
  docs/architecture/system-dynamics-map-viewer.html \
  scripts/system_dynamics_map_materialize.py \
  tests/test_system_dynamics_map_artifacts.py \
  tests/test_system_dynamics_map_viewer_playwright.py
```

The hardcoded-hex scan should return no matches. The viewer intentionally uses
two conditional media rules: one mobile/narrow layout rule and one
forced-colors accessibility rule. It should not contain container queries or
unregistered media rules:

```bash
python3 - <<'PY'
import re
from pathlib import Path

text = Path("docs/architecture/system-dynamics-map-viewer.html").read_text()
assert "@" + "container" not in text, "unexpected container query"
expected_media = {"@media (max-width: 860px)", "@media (forced-colors: active)"}
found_media = set(re.findall(r"@media\s*\([^)]+\)", text))
assert found_media == expected_media, found_media
PY
```

```bash
git diff --check -- \
  docs/architecture/system-dynamics-map-v1.md \
  docs/architecture/system-dynamics-map.seed.json \
  docs/architecture/system-dynamics-map-viewer.html
```

For visual regression, serve `docs/architecture/` locally and capture the viewer.
The committed reference captures are:

- `docs/architecture/system-dynamics-map-viewer-desktop.png`
- `docs/architecture/system-dynamics-map-viewer-mobile.png`

The maintained recheck target for the Pillow-backed shape/nonblank guard is:

```bash
.venv/bin/pytest -q tests/test_system_dynamics_map_artifacts.py::test_committed_viewer_reference_captures_have_expected_shape_and_nonblank_content
```

For standalone use outside the repo environment, install Pillow first and run
the equivalent portable recheck. Keep this snippet's dimensions and color
threshold in sync with the maintained pytest target above if either guard
changes:

```bash
python3 - <<'PY'
from pathlib import Path

try:
    from PIL import Image
except ImportError as error:
    raise SystemExit("Install Pillow before running this standalone recheck.") from error

expected = {
    Path("docs/architecture/system-dynamics-map-viewer-desktop.png"): (1440, 960),
    Path("docs/architecture/system-dynamics-map-viewer-mobile.png"): (390, 844),
}
for path, dimensions in expected.items():
    with Image.open(path) as image:
        assert image.size == dimensions, (path, image.size)
        colors = image.convert("RGB").getcolors(maxcolors=1_000_000)
        assert colors is not None and len(colors) > 50, path
PY
```

The `>50` color threshold is a blank/sparse-image guard; the Playwright viewer
suite performs the stronger current-served-render comparison against these
committed references.

The AV-SDLC task evidence also carries operator-local copies under the closing
task evidence directory named in the cc-task dossier.

```bash
(
set -euo pipefail
python3 -m http.server 8765 --bind 127.0.0.1 --directory docs/architecture \
  >/tmp/system-dynamics-map-http.log 2>&1 &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT
python3 - <<'PY'
import socket
import time

deadline = time.time() + 5
while time.time() < deadline:
    try:
        with socket.create_connection(("127.0.0.1", 8765), timeout=0.2):
            raise SystemExit(0)
    except OSError:
        time.sleep(0.1)
raise SystemExit("local docs server did not start on 127.0.0.1:8765")
PY

# The reference files are viewport captures; do not add --full-page here.
npx playwright screenshot --browser chromium --viewport-size 1440,960 \
  --wait-for-selector '#cy canvas' --wait-for-timeout 3000 \
  http://127.0.0.1:8765/system-dynamics-map-viewer.html docs/architecture/system-dynamics-map-viewer-desktop.png
npx playwright screenshot --browser chromium --viewport-size 390,844 \
  --wait-for-selector '#cy canvas' --wait-for-timeout 3000 \
  http://127.0.0.1:8765/system-dynamics-map-viewer.html docs/architecture/system-dynamics-map-viewer-mobile.png
kill "$server_pid" 2>/dev/null || true
trap - EXIT
)
```

## Source Notes

Primary standards and docs used for the v1 map. Date-sensitive release notes
below were rechecked against the linked official pages on 2026-06-18 UTC
(2026-06-17 America/Chicago).

- OMG DMN 1.5 formal, August 2024: https://www.omg.org/spec/DMN/1.5/About-DMN
- OMG DMN 1.6 beta: https://www.omg.org/spec/DMN/1.6/Beta1/About-DMN
- OMG BPMN 2.0.2 formal, January 2014: https://www.omg.org/spec/BPMN/2.0.2/
- OMG CMMN 1.1 formal, December 2016: https://www.omg.org/spec/CMMN/1.1/About-CMMN
- OMG SysML 2.0 formal, September 2025: https://www.omg.org/spec/SysML/2.0/About-SysML
- OMG final-adoption press release for SysML v2.0, July 2025: https://www.omg.org/news/releases/pr2025/07-21-25.htm
- The Open Group ArchiMate 4 release announcement, dated April 27, 2026: https://www.opengroup.org/The-Open-Group-Announces-ArchiMate%C2%AE-4-Specification
- The Open Group ArchiMate licensed downloads landing page: https://www.opengroup.org/archimate-licensed-downloads
- W3C RDF 1.2 Concepts, Candidate Recommendation Snapshot, April 2026: https://www.w3.org/TR/rdf12-concepts/
- W3C RDF 1.2 Concepts publication history, 7 April 2026 CRS: https://www.w3.org/standards/history/rdf12-concepts/
- W3C SHACL and SHACL 1.2 Core: https://www.w3.org/TR/shacl/ and https://www.w3.org/TR/shacl12-core/
- W3C PROV-O: https://www.w3.org/TR/prov-o/
- W3C JSON-LD 1.1: https://www.w3.org/TR/json-ld11/
- W3C SCXML: https://www.w3.org/TR/scxml/
- W3C Trace Context: https://www.w3.org/TR/trace-context/
- OpenTelemetry semantic conventions: https://opentelemetry.io/docs/concepts/semantic-conventions/
- CloudEvents: https://cloudevents.io/
- Cytoscape.js documentation checked through Context7 for current initialization,
  element, style, layout, and event APIs: https://js.cytoscape.org/
- Playwright documentation checked through Context7 for local web server,
  locator, form interaction, and browser assertion patterns:
  https://playwright.dev/
