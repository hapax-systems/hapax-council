# System Dynamics Map v0

Task: `system-dynamics-map-v0-20260618`

Authority case: `CASE-SYSTEM-DYNAMICS-MAP-20260618`

Parent spec: `~/Documents/Personal/20-projects/hapax-research/specs/2026-06-18-system-dynamics-map-v0-parent-spec.md`

## Decision

Use DMN as the entry point, not the center.

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

This keeps the visualization honest. A DMN decision requirement diagram can show
decision dependencies, but it cannot by itself represent runtime topology, current
state, provenance, telemetry, simulation state, process history, and rendering
projection. Those are different claim types and must remain separable.

## Conceptual Map Around DMN

DMN's directly related layer:

- `DMN`: decision model and notation for decision requirements and executable
  decision logic.
- `DRD/DRG`: decision dependency surface inside DMN.
- `Decision service`: packaging boundary for callable decision behavior.
- `Decision table`: common tabular decision logic representation.
- `FEEL`: DMN expression language.
- `SBVR`: adjacent business vocabulary and rule semantics.

One layer up:

- `BPMN`: process flow can invoke or be routed by decisions.
- `CMMN`: case plans can invoke decisions in less prescriptive work.
- `ArchiMate`: enterprise architecture context for capabilities, applications,
  processes, and motivation.
- `SysML v2`: systems engineering structure, behavior, requirements, and
  verification context.
- `C4/runtime architecture`: implementation topology and deployable services.

One layer down:

- `DMN XML/DI`: interchange and diagram serialization.
- `Rule engines`: executable target for decision tables and FEEL-compatible logic.
- `Decision runtime API`: callable service boundary.
- `PMML/ONNX/PFA-class model artifacts`: adjacent predictive/analytical model
  artifacts that often feed or sit beside decisions.

Adjacent systems required by the actual goal:

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

## Why Not Make DMN The Core?

DMN is scoped to decisions. It is excellent for decision dependency and executable
decision logic, but it is a lossy center for system dynamics. A faithful system
map needs to represent at least five dimensions that DMN does not own:

- Topology: components, processes, systems, people, data stores, queues, models,
  and runtime edges.
- Dynamics: state transitions, event streams, traces, logs, simulations, and
  temporal validity.
- Evidence: source documents, observations, generated outputs, confidence, and
  stale/invalid states.
- Projection: which nodes and edges were rendered, hidden, aggregated, or inferred.
- Governance: versioned contracts, validation gates, review state, and provenance.

Pushing those into DMN would produce a familiar diagram that lies by omission.
The semantic backbone gives DMN a precise place without letting it flatten the
rest of the system.

## Canonical Data Contract

V0 uses `system-dynamics-map.seed.json` as a portable seed shape. The eventual
persisted form should be RDF named graphs plus SHACL shapes, but the seed file is
structured so it can be lifted into that backend:

- `nodes[]`: stable identity, label, kind, layer, resolution, status, summary,
  context, hardening notes, aliases, tags, and documentation links.
- `edges[]`: stable identity, source, target, relation, layer, resolution, status,
  summary, confidence, and documentation/evidence links in `docs[]`.
- `view_scales[]`: declared scales that explain why an element appears at a given
  resolution.
- `status_kinds[]`: claim-type vocabulary that distinguishes asserted, inferred,
  observed, simulated, rendered, and candidate elements.

The viewer consumes this shape and should remain replaceable. The graph contract
is the important artifact; Cytoscape is the current projection engine.

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

## V0 Viewer

`system-dynamics-map-viewer.html` is intentionally a static file. It provides:

- Layer filters.
- Status filters.
- Resolution slider.
- Search.
- Layout switching.
- Node and edge context panels.
- External documentation links from the graph data.

This is enough to review the concept and refine the graph without committing to a
live backend or frontend framework. The viewer loads a committed local Cytoscape
3.34.0 runtime asset from `vendor/cytoscape-3.34.0.min.js`, so basic rendering no
longer depends on CDN egress.

Persisted hardening artifacts:

- `system-dynamics-map.canonical.trig`: named-graph RDF/TriG-style snapshot for
  asserted graph content, rendered-view metadata, and provenance.
- `system-dynamics-map.shacl.ttl`: SHACL shape contract for nodes, edges,
  rendered views, and provenance activity records.
- `system-dynamics-map.view-manifest.json`: versioned projection manifest with
  source hashes, visible layers/statuses, runtime asset hash, and validation
  commands.

Browser verification lives in `tests/test_system_dynamics_map_viewer_playwright.py`.
It exercises the static viewer through Playwright and asserts that Cytoscape
draws nonblank canvas pixels after layout, not just that the seed data loaded.

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
rg -n '#[0-9A-Fa-f]{3,8}\b' \
  docs/architecture/system-dynamics-map-v0.md \
  docs/architecture/system-dynamics-map.seed.json \
  docs/architecture/system-dynamics-map-viewer.html \
  scripts/system_dynamics_map_materialize.py \
  tests/test_system_dynamics_map_artifacts.py \
  tests/test_system_dynamics_map_viewer_playwright.py
```

The hardcoded-hex scan should return no matches. The viewer uses intrinsic flex
wrapping for narrow screens; it should not contain conditional CSS at-rules:

```bash
python3 - <<'PY'
from pathlib import Path

text = Path("docs/architecture/system-dynamics-map-viewer.html").read_text()
for token in ("@" + "container", "@" + "media"):
    assert token not in text, f"unexpected conditional CSS at-rule: {token}"
PY
```

```bash
git diff --check -- \
  docs/architecture/system-dynamics-map-v0.md \
  docs/architecture/system-dynamics-map.seed.json \
  docs/architecture/system-dynamics-map-viewer.html
```

For visual regression, serve `docs/architecture/` locally and capture the viewer:

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

npx playwright screenshot --browser chromium --viewport-size 1440,960 \
  --wait-for-selector '#cy canvas' --wait-for-timeout 3000 --full-page \
  http://127.0.0.1:8765/system-dynamics-map-viewer.html /tmp/system-dynamics-map-viewer-desktop.png
npx playwright screenshot --browser chromium --viewport-size 390,844 \
  --wait-for-selector '#cy canvas' --wait-for-timeout 3000 --full-page \
  http://127.0.0.1:8765/system-dynamics-map-viewer.html /tmp/system-dynamics-map-viewer-mobile.png
kill "$server_pid" 2>/dev/null || true
trap - EXIT
)
```

## Source Notes

Primary standards and docs used for the v0 map. Date-sensitive release notes
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
