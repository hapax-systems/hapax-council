"""Probe AffordancePipeline recruitment quality against representative impingement narratives.

Operator-runnable diagnostic for the description-quality follow-up from
cc-task ``wgsl-node-recruitment-investigation`` (PRs #2281, #2295, #2297,
#2307, #2309 — full WGSL coverage epic). After the catalog reaches 100%
coverage, the next axis of recruitment quality is description tuning:
do the descriptions actually match the kinds of narratives the director
emits?

This script:

1. Embeds each of N representative impingement narratives via the same
   ``embed_safe`` path the AffordancePipeline uses.
2. Queries Qdrant ``affordances`` for top-K cosine-similarity matches.
3. Reports per-narrative the matches + similarity scores.

The output is human-judgement input for the operator: are the top-3
matches semantically appropriate? If a narrative about "lo-fi VHS
texture" returns ``node.solid`` instead of ``node.vhs``, that's a
description-quality bug to fix.

No assertions; this is a probe, not a test. Tests live in
``tests/test_affordance_recruitment_probe.py`` and exercise the
narrative fixture loading + payload-shape contract without hitting
Qdrant.

Usage:
    uv run scripts/probe-affordance-recruitment.py
    uv run scripts/probe-affordance-recruitment.py --top-k 5
    uv run scripts/probe-affordance-recruitment.py --narratives custom.json
    uv run scripts/probe-affordance-recruitment.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# Representative narratives the director loop tends to emit, grouped by
# the matching shader-node register the operator likely intended. Each
# entry is the kind of phrase that would land in ``compositional_impingements[i].narrative``
# at a tick where the named effect *should* recruit.
REPRESENTATIVE_NARRATIVES: dict[str, list[str]] = {
    "warm cinematic glow": ["node.bloom", "node.colorgrade"],
    "nostalgic VHS lo-fi tape texture": ["node.vhs", "node.scanlines"],
    "newsprint comic halftone print": ["node.halftone", "node.dither"],
    "psychedelic kaleidoscopic mandala symmetry": ["node.kaleidoscope", "node.mirror"],
    "retro CRT scanlines arcade glow": ["node.scanlines", "node.vhs"],
    "ASCII terminal text-art": ["node.ascii"],
    "datamosh blocky digital glitch": ["node.glitch_block", "node.stutter"],
    "painterly impressionist brush smoothing": ["node.kuwahara"],
    "limited-palette retro-computing dithering": ["node.dither", "node.posterize"],
    "infinite spiral mise-en-abyme recursion": ["node.droste"],
    "thermal infrared body heat predator vision": ["node.thermal", "node.color_map"],
    "hypnotic vortex tunnel motion": ["node.tunnel"],
    "Rorschach symmetry ritual reflection": ["node.mirror"],
    "comet trail brush stroke persistence": ["node.trail", "node.echo"],
    "Navier-Stokes fluid plume smoke": ["node.fluid_sim"],
    "viscous syrupy underwater dream lag": ["node.syrup"],
    "Warhol grid pop multiviewer tile": ["node.tile"],
    "vintage funhouse mirror dream warp": ["node.warp", "node.fisheye"],
    "calm-textural slow ambient field": ["node.colorgrade", "node.drift"],
    "audio-reactive beat rhythmic pulse": ["node.waveform_render", "node.particle_system"],
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--top-k", type=int, default=3, help="how many candidates per narrative")
    p.add_argument(
        "--narratives",
        type=Path,
        default=None,
        help="JSON file with custom narrative→expected-nodes map (defaults to built-in fixture)",
    )
    p.add_argument("--json", action="store_true", help="emit machine-parseable JSON only")
    p.add_argument("--collection", default="affordances", help="Qdrant collection name")
    return p.parse_args()


def load_narratives(path: Path | None) -> dict[str, list[str]]:
    if path is None:
        return REPRESENTATIVE_NARRATIVES
    return json.loads(path.read_text())


def probe(narratives: dict[str, list[str]], top_k: int, collection: str):
    try:
        from shared.config import embed_safe, get_qdrant
    except Exception as exc:
        return None, f"shared.config import failed: {exc}"

    try:
        client = get_qdrant()
    except Exception as exc:
        return None, f"qdrant connection failed: {exc}"

    results: list[dict] = []
    for narrative, expected in narratives.items():
        embedding = embed_safe(narrative, prefix="search_query")
        if embedding is None:
            results.append(
                {
                    "narrative": narrative,
                    "expected": expected,
                    "error": "embed_safe returned None",
                }
            )
            continue
        try:
            # qdrant-client ≥1.10 deprecated .search() in favor of .query_points().
            # Try the new API first; fall back if the running client is older.
            if hasattr(client, "query_points"):
                response = client.query_points(
                    collection_name=collection,
                    query=embedding,
                    limit=top_k,
                    with_payload=True,
                )
                hits = response.points
            else:
                hits = client.search(
                    collection_name=collection,
                    query_vector=embedding,
                    limit=top_k,
                    with_payload=True,
                )
        except Exception as exc:
            results.append({"narrative": narrative, "expected": expected, "error": str(exc)})
            continue

        matches = [
            {
                "name": (hit.payload or {}).get("capability_name", "<unknown>"),
                "score": round(float(hit.score), 4),
            }
            for hit in hits
        ]
        match_names = [m["name"] for m in matches]
        hit_in_top_k = any(name in match_names for name in expected)
        results.append(
            {
                "narrative": narrative,
                "expected": expected,
                "matches": matches,
                "hit_in_top_k": hit_in_top_k,
            }
        )

    summary = {
        "total": len(results),
        "errors": sum(1 for r in results if "error" in r),
        "hits": sum(1 for r in results if r.get("hit_in_top_k")),
        "misses": sum(1 for r in results if "error" not in r and not r.get("hit_in_top_k")),
    }
    return {"summary": summary, "results": results}, None


def main() -> int:
    args = parse_args()
    narratives = load_narratives(args.narratives)

    report, err = probe(narratives, args.top_k, args.collection)
    if err:
        print(json.dumps({"status": "skipped", "reason": err}))
        return 0

    assert report is not None  # narrowing for the type checker
    if args.json:
        print(json.dumps(report, indent=2))
        return 0 if report["summary"]["misses"] == 0 else 2

    s = report["summary"]
    print(
        f"Probed {s['total']} narratives at top-{args.top_k}: "
        f"{s['hits']} hit, {s['misses']} miss, {s['errors']} error"
    )
    for r in report["results"]:
        if "error" in r:
            print(f"  [ERR] {r['narrative']!r}: {r['error']}")
            continue
        marker = "✓" if r["hit_in_top_k"] else "✗"
        names = ", ".join(f"{m['name']}@{m['score']}" for m in r["matches"])
        print(f"  [{marker}] {r['narrative']!r}")
        print(f"        expected one of: {r['expected']}")
        print(f"        top-{args.top_k}: {names}")

    return 0 if s["misses"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
