"""Tests for the graph-patch recruitment consumer.

Architectural fix per researcher audit + memory
``feedback_no_presets_use_parametric_modulation``: the consumer reads
``recent-recruitment.json`` for fresh ``node.*`` patch entries, builds
a ``GraphPatch``, applies it to the live ``EffectGraph``, and writes the
patched graph as a mutation file. These tests exercise the consumer's parsing + dispatch shape
without leaning on a live SHM surface or a real GraphRuntime.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from agents.effect_graph.types import EffectGraph, GraphPatch, NodeInstance
from agents.studio_compositor import graph_patch_consumer as gpc


def _base_graph() -> EffectGraph:
    return EffectGraph(
        name="base",
        nodes={
            "c": NodeInstance(type="colorgrade"),
            "b": NodeInstance(type="bloom"),
            "o": NodeInstance(type="output"),
        },
        edges=[["@live", "c"], ["c", "b"], ["b", "o"]],
    )


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Each test gets a fresh module-state + tmp paths."""
    from agents.studio_compositor import compositional_consumer as cc

    monkeypatch.setattr(cc, "_SEGMENT_CUE_HOLD", tmp_path / "segment-cue-hold.json")
    monkeypatch.setattr(gpc, "RECRUITMENT_FILE", tmp_path / "recent-recruitment.json")
    monkeypatch.setattr(gpc, "MUTATION_FILE", tmp_path / "graph-mutation.json")
    gpc._reset_state_for_tests()
    yield
    gpc._reset_state_for_tests()


def _wait_for_thread(name: str = "graph-patch-apply", timeout: float = 2.0) -> None:
    """Block until the named daemon thread exits — avoids racy assertions."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        active = [t for t in threading.enumerate() if t.name == name]
        if not active:
            return
        time.sleep(0.01)


def _write_recruitment(
    path: Path,
    *,
    add_suffixes: list[str] | None = None,
    remove_suffixes: list[str] | None = None,
    ts: float | None = None,
) -> None:
    if ts is None:
        ts = time.time()
    families: dict = {}
    if add_suffixes:
        items = [
            {
                "capability": f"node.add.{s}",
                "suffix": s,
                "last_recruited_ts": ts,
                "ttl_s": 30.0,
            }
            for s in add_suffixes
        ]
        families["node.add"] = {"last_recruited_ts": ts, "items": items}
    if remove_suffixes:
        items = [
            {
                "capability": f"node.remove.{s}",
                "suffix": s,
                "last_recruited_ts": ts,
                "ttl_s": 30.0,
            }
            for s in remove_suffixes
        ]
        families["node.remove"] = {"last_recruited_ts": ts, "items": items}
    path.write_text(json.dumps({"families": families}), encoding="utf-8")


def _node_payload(family: str, suffix: str, ts: float | None = None) -> dict:
    if ts is None:
        ts = time.time()
    return {
        "families": {
            family: {
                "last_recruited_ts": ts,
                "items": [
                    {
                        "capability": f"{family}.{suffix}",
                        "suffix": suffix,
                        "last_recruited_ts": ts,
                        "ttl_s": 30.0,
                    },
                ],
            },
        },
    }


# ── _build_patch_from_recruitment parsing ───────────────────────────────────


def test_build_patch_returns_empty_for_no_families() -> None:
    patch, ts = gpc._build_patch_from_recruitment({"families": {}})
    assert patch.is_empty
    assert ts == 0.0


def test_build_patch_extracts_add_nodes() -> None:
    now = time.time()
    payload = {
        "families": {
            "node.add": {
                "last_recruited_ts": now,
                "items": [
                    {
                        "capability": "node.add.halftone",
                        "suffix": "halftone",
                        "last_recruited_ts": now,
                    },
                ],
            },
        }
    }
    patch, ts = gpc._build_patch_from_recruitment(payload)
    assert "sat_halftone" in patch.add_nodes
    assert patch.add_nodes["sat_halftone"].type == "halftone"
    assert ts == pytest.approx(now)


def test_build_patch_extracts_remove_nodes() -> None:
    now = time.time()
    payload = {
        "families": {
            "node.remove": {
                "last_recruited_ts": now,
                "items": [
                    {
                        "capability": "node.remove.last_satellite",
                        "suffix": "last_satellite",
                        "last_recruited_ts": now,
                    },
                ],
            },
        }
    }
    patch, ts = gpc._build_patch_from_recruitment(payload)
    assert "last_satellite" in patch.remove_nodes
    assert ts == pytest.approx(now)


def test_build_patch_drops_stale_items_beyond_ttl() -> None:
    """Items older than PATCH_BIAS_TTL_S are filtered out."""
    stale = time.time() - gpc.PATCH_BIAS_TTL_S - 5.0
    payload = {
        "families": {
            "node.add": {
                "last_recruited_ts": stale,
                "items": [
                    {
                        "capability": "node.add.halftone",
                        "suffix": "halftone",
                        "last_recruited_ts": stale,
                    },
                ],
            },
        }
    }
    patch, ts = gpc._build_patch_from_recruitment(payload)
    assert patch.is_empty
    assert ts == 0.0


def test_build_patch_coalesces_multiple_add_recruitments() -> None:
    now = time.time()
    payload = {
        "families": {
            "node.add": {
                "last_recruited_ts": now,
                "items": [
                    {
                        "capability": "node.add.halftone",
                        "suffix": "halftone",
                        "last_recruited_ts": now,
                    },
                    {
                        "capability": "node.add.kaleidoscope",
                        "suffix": "kaleidoscope",
                        "last_recruited_ts": now - 2.0,
                    },
                ],
            },
        }
    }
    patch, _ = gpc._build_patch_from_recruitment(payload)
    assert "sat_halftone" in patch.add_nodes
    assert "sat_kaleidoscope" in patch.add_nodes


def test_build_patch_composes_two_existing_nodes() -> None:
    base = _base_graph()
    patch, _ = gpc._build_patch_from_recruitment(_node_payload("node.compose", "c,b"), base)

    assert "meta_c_b" in patch.add_nodes
    assert patch.add_nodes["meta_c_b"].type == "blend"
    assert ["c", "meta_c_b:a"] in patch.add_edges
    assert ["b", "meta_c_b:b"] in patch.add_edges
    assert ["meta_c_b", "o"] in patch.add_edges
    assert ["b", "o"] in patch.remove_edges


def test_build_patch_forks_existing_node() -> None:
    base = _base_graph()
    patch, _ = gpc._build_patch_from_recruitment(_node_payload("node.fork", "c"), base)

    assert "fork_c" in patch.add_nodes
    assert patch.add_nodes["fork_c"].type == base.nodes["c"].type
    assert ["@live", "fork_c"] in patch.add_edges
    assert ["fork_c", "b"] in patch.add_edges


def test_build_patch_merges_parallel_branches() -> None:
    base = _base_graph().apply_patch(
        GraphPatch(
            add_nodes={"fork_c": NodeInstance(type="colorgrade")},
            add_edges=[["@live", "fork_c"], ["fork_c", "b"]],
        )
    )
    patch, _ = gpc._build_patch_from_recruitment(_node_payload("node.merge", "c,fork_c"), base)

    assert "merge_c_fork_c" in patch.add_nodes
    assert patch.add_nodes["merge_c_fork_c"].type == "blend"
    assert ["c", "merge_c_fork_c:a"] in patch.add_edges
    assert ["fork_c", "merge_c_fork_c:b"] in patch.add_edges
    assert ["merge_c_fork_c", "b"] in patch.add_edges
    assert ["c", "b"] in patch.remove_edges
    assert ["fork_c", "b"] in patch.remove_edges


def test_build_patch_routes_source_to_existing_target() -> None:
    base = _base_graph()
    patch, _ = gpc._build_patch_from_recruitment(_node_payload("node.route", "c,o"), base)

    assert ["c", "b"] in patch.remove_edges
    assert ["c", "o"] in patch.add_edges


def test_build_patch_smoke_advances_through_all_structural_primitives() -> None:
    graph = EffectGraph(
        name="reverie-core",
        nodes={
            "color": NodeInstance(type="colorgrade"),
            "drift": NodeInstance(type="drift"),
            "fb": NodeInstance(type="feedback"),
            "content": NodeInstance(type="content_layer"),
            "post": NodeInstance(type="postprocess"),
            "out": NodeInstance(type="output"),
        },
        edges=[
            ["@live", "color"],
            ["color", "drift"],
            ["drift", "fb"],
            ["fb", "content"],
            ["content", "post"],
            ["post", "out"],
        ],
    )
    for family, suffix in (
        ("node.compose", "color,drift"),
        ("node.fork", "fb"),
        ("node.merge", "fb,fork_fb"),
        ("node.route", "content,out"),
    ):
        patch, _ = gpc._build_patch_from_recruitment(_node_payload(family, suffix), graph)
        assert not patch.is_empty, f"{family}.{suffix} did not produce a patch"
        graph = graph.apply_patch(patch)

    assert "meta_color_drift" in graph.nodes
    assert "fork_fb" in graph.nodes
    assert "merge_fb_fork_fb" in graph.nodes
    assert ["content", "post"] not in graph.edges
    assert ["content", "out"] in graph.edges


def test_build_patch_coalesces_structural_primitives_in_one_window() -> None:
    ts = time.time()
    payload = {"families": {}}
    for family, suffix in (
        ("node.compose", "color,drift"),
        ("node.fork", "fb"),
        ("node.merge", "fb,fork_fb"),
        ("node.route", "content,out"),
    ):
        payload["families"].update(_node_payload(family, suffix, ts)["families"])
    graph = EffectGraph(
        name="reverie-core",
        nodes={
            "color": NodeInstance(type="colorgrade"),
            "drift": NodeInstance(type="drift"),
            "fb": NodeInstance(type="feedback"),
            "content": NodeInstance(type="content_layer"),
            "post": NodeInstance(type="postprocess"),
            "out": NodeInstance(type="output"),
        },
        edges=[
            ["@live", "color"],
            ["color", "drift"],
            ["drift", "fb"],
            ["fb", "content"],
            ["content", "post"],
            ["post", "out"],
        ],
    )

    patch, _ = gpc._build_patch_from_recruitment(payload, graph)
    graph = graph.apply_patch(patch)

    assert "meta_color_drift" in graph.nodes
    assert "fork_fb" in graph.nodes
    assert "merge_fb_fork_fb" in graph.nodes
    assert ["content", "post"] not in graph.edges
    assert ["content", "out"] in graph.edges


# ── process_graph_patch_recruitment integration ─────────────────────────────


def test_process_no_recruitment_file_returns_false() -> None:
    assert gpc.process_graph_patch_recruitment() is False


def test_process_empty_recruitment_returns_false() -> None:
    gpc.RECRUITMENT_FILE.write_text(json.dumps({"families": {}}), encoding="utf-8")
    assert gpc.process_graph_patch_recruitment() is False


def test_process_no_current_graph_returns_false() -> None:
    """Without a current graph provider, nothing to patch."""
    _write_recruitment(gpc.RECRUITMENT_FILE, add_suffixes=["halftone"])
    # No provider set — _get_current_graph() returns None.
    assert gpc.process_graph_patch_recruitment() is False


def test_process_writes_patched_graph_to_mutation_file() -> None:
    """End-to-end: with a current graph provider + fresh recruitment,
    the consumer dispatches a patch, the background thread runs, and
    the mutation file contains the patched graph."""
    base = _base_graph()
    gpc.set_current_graph_provider(lambda: base)
    _write_recruitment(gpc.RECRUITMENT_FILE, add_suffixes=["halftone"])

    assert gpc.process_graph_patch_recruitment() is True
    _wait_for_thread()
    assert gpc.MUTATION_FILE.exists()
    payload = json.loads(gpc.MUTATION_FILE.read_text(encoding="utf-8"))
    assert "sat_halftone" in payload["nodes"]
    assert payload["nodes"]["sat_halftone"]["type"] == "halftone"


def test_process_writes_remove_patch_to_mutation_file() -> None:
    """Remove operation lands in the mutation file."""
    base = _base_graph()
    gpc.set_current_graph_provider(lambda: base)
    _write_recruitment(gpc.RECRUITMENT_FILE, remove_suffixes=["b"])

    assert gpc.process_graph_patch_recruitment() is True
    _wait_for_thread()
    assert gpc.MUTATION_FILE.exists()
    payload = json.loads(gpc.MUTATION_FILE.read_text(encoding="utf-8"))
    assert "b" not in payload["nodes"]
    # Edges that touched `b` are gone.
    for edge in payload["edges"]:
        assert "b" not in edge


def test_process_cooldown_blocks_repeat_dispatch() -> None:
    base = _base_graph()
    gpc.set_current_graph_provider(lambda: base)
    _write_recruitment(gpc.RECRUITMENT_FILE, add_suffixes=["halftone"])

    assert gpc.process_graph_patch_recruitment() is True
    _wait_for_thread()
    # Bump the recruitment ts forward and try to fire again before cooldown.
    _write_recruitment(gpc.RECRUITMENT_FILE, add_suffixes=["kaleidoscope"], ts=time.time() + 0.001)
    # Inside cooldown — no new dispatch.
    assert gpc.process_graph_patch_recruitment() is False


def test_process_idempotent_on_same_recruitment_ts() -> None:
    """Same recruitment ts twice in a row → second call is a no-op."""
    base = _base_graph()
    gpc.set_current_graph_provider(lambda: base)
    fixed_ts = time.time()
    _write_recruitment(gpc.RECRUITMENT_FILE, add_suffixes=["halftone"], ts=fixed_ts)

    assert gpc.process_graph_patch_recruitment() is True
    _wait_for_thread()
    # Same file, same ts — second invocation declines (already-seen guard).
    assert gpc.process_graph_patch_recruitment() is False


def test_process_skips_when_only_stale_items() -> None:
    """If every recruitment item is beyond the TTL, the consumer declines."""
    base = _base_graph()
    gpc.set_current_graph_provider(lambda: base)
    stale = time.time() - gpc.PATCH_BIAS_TTL_S - 5.0
    _write_recruitment(gpc.RECRUITMENT_FILE, add_suffixes=["halftone"], ts=stale)
    assert gpc.process_graph_patch_recruitment() is False


def test_process_handles_corrupt_recruitment_file() -> None:
    """Corrupt JSON → no exception, returns False."""
    base = _base_graph()
    gpc.set_current_graph_provider(lambda: base)
    gpc.RECRUITMENT_FILE.write_text("{not json", encoding="utf-8")
    assert gpc.process_graph_patch_recruitment() is False


def test_process_combined_add_and_remove_patch() -> None:
    """Combined add + remove recruitments coalesce into a single patch."""
    base = _base_graph()
    gpc.set_current_graph_provider(lambda: base)
    _write_recruitment(
        gpc.RECRUITMENT_FILE,
        add_suffixes=["halftone"],
        remove_suffixes=["b"],
    )

    assert gpc.process_graph_patch_recruitment() is True
    _wait_for_thread()
    payload = json.loads(gpc.MUTATION_FILE.read_text(encoding="utf-8"))
    assert "sat_halftone" in payload["nodes"]
    assert "b" not in payload["nodes"]


def test_set_current_graph_provider_can_be_cleared() -> None:
    """Provider can be unset without breaking the consumer."""
    base = _base_graph()
    gpc.set_current_graph_provider(lambda: base)
    assert gpc._get_current_graph() is base
    gpc.set_current_graph_provider(None)
    assert gpc._get_current_graph() is None


def test_provider_returning_none_falls_back_to_last_patched() -> None:
    """If the provider returns None but a patch was previously applied,
    the consumer uses the cached _last_patched_graph."""
    base = _base_graph()
    gpc.set_current_graph_provider(lambda: base)
    # First apply: writes _last_patched_graph.
    _write_recruitment(gpc.RECRUITMENT_FILE, add_suffixes=["halftone"])
    assert gpc.process_graph_patch_recruitment() is True
    _wait_for_thread()
    cached = gpc._last_patched_graph
    assert cached is not None
    # Switch the provider to return None.
    gpc.set_current_graph_provider(lambda: None)
    assert gpc._get_current_graph() is cached


# ── compositional_consumer dispatch path ─────────────────────────────────────


def test_dispatch_node_patch_writes_recruitment_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The compositional dispatcher writes node.add / node.remove into
    the recent-recruitment.json file in the shape the consumer reads."""
    from agents.studio_compositor import compositional_consumer as cc

    rfile = tmp_path / "recent-recruitment.json"
    monkeypatch.setattr(cc, "_RECENT_RECRUITMENT", rfile)

    assert cc.dispatch_node_patch("node.add.halftone", 30.0) is True
    payload = json.loads(rfile.read_text(encoding="utf-8"))
    assert "node.add" in payload["families"]
    items = payload["families"]["node.add"]["items"]
    assert len(items) == 1
    assert items[0]["suffix"] == "halftone"
    assert items[0]["capability"] == "node.add.halftone"


def test_dispatch_node_patch_appends_multiple_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.studio_compositor import compositional_consumer as cc

    rfile = tmp_path / "recent-recruitment.json"
    monkeypatch.setattr(cc, "_RECENT_RECRUITMENT", rfile)

    cc.dispatch_node_patch("node.add.halftone", 30.0)
    cc.dispatch_node_patch("node.add.kaleidoscope", 30.0)
    payload = json.loads(rfile.read_text(encoding="utf-8"))
    suffixes = sorted(it["suffix"] for it in payload["families"]["node.add"]["items"])
    assert suffixes == ["halftone", "kaleidoscope"]


def test_dispatch_node_patch_routes_remove_family(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.studio_compositor import compositional_consumer as cc

    rfile = tmp_path / "recent-recruitment.json"
    monkeypatch.setattr(cc, "_RECENT_RECRUITMENT", rfile)

    assert cc.dispatch_node_patch("node.remove.last_satellite", 30.0) is True
    payload = json.loads(rfile.read_text(encoding="utf-8"))
    assert "node.remove" in payload["families"]
    items = payload["families"]["node.remove"]["items"]
    assert items[0]["suffix"] == "last_satellite"


@pytest.mark.parametrize(
    ("capability", "family", "suffix"),
    [
        ("node.compose.color,drift", "node.compose", "color,drift"),
        ("node.fork.fb", "node.fork", "fb"),
        ("node.merge.fb,fork_fb", "node.merge", "fb,fork_fb"),
        ("node.route.content,out", "node.route", "content,out"),
    ],
)
def test_dispatch_node_patch_routes_structural_families(
    capability: str,
    family: str,
    suffix: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agents.studio_compositor import compositional_consumer as cc

    rfile = tmp_path / "recent-recruitment.json"
    monkeypatch.setattr(cc, "_RECENT_RECRUITMENT", rfile)

    assert cc.dispatch_node_patch(capability, 30.0) is True
    payload = json.loads(rfile.read_text(encoding="utf-8"))
    assert family in payload["families"]
    items = payload["families"][family]["items"]
    assert items[0]["suffix"] == suffix
    assert items[0]["capability"] == capability


def test_dispatch_node_patch_rejects_malformed_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.studio_compositor import compositional_consumer as cc

    rfile = tmp_path / "recent-recruitment.json"
    monkeypatch.setattr(cc, "_RECENT_RECRUITMENT", rfile)

    assert cc.dispatch_node_patch("node.add.", 30.0) is False  # empty suffix
    assert cc.dispatch_node_patch("node.invalid.x", 30.0) is False  # bad family
    assert cc.dispatch_node_patch("not.a.node", 30.0) is False  # not a node.* name


def test_dispatch_routes_node_add_to_dispatch_node_patch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Top-level dispatch() routes node.add.* names through dispatch_node_patch."""
    from agents.studio_compositor import compositional_consumer as cc

    rfile = tmp_path / "recent-recruitment.json"
    monkeypatch.setattr(cc, "_RECENT_RECRUITMENT", rfile)

    rec = cc.RecruitmentRecord(name="node.add.halftone", ttl_s=30.0)
    assert cc.dispatch(rec) == "node.patch"


def test_dispatch_routes_node_remove_to_dispatch_node_patch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.studio_compositor import compositional_consumer as cc

    rfile = tmp_path / "recent-recruitment.json"
    monkeypatch.setattr(cc, "_RECENT_RECRUITMENT", rfile)

    rec = cc.RecruitmentRecord(name="node.remove.last_satellite", ttl_s=30.0)
    assert cc.dispatch(rec) == "node.patch"


@pytest.mark.parametrize(
    "name",
    [
        "node.compose.color,drift",
        "node.fork.fb",
        "node.merge.fb,fork_fb",
        "node.route.content,out",
    ],
)
def test_dispatch_routes_structural_node_primitives_to_dispatch_node_patch(
    name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agents.studio_compositor import compositional_consumer as cc

    rfile = tmp_path / "recent-recruitment.json"
    monkeypatch.setattr(cc, "_RECENT_RECRUITMENT", rfile)

    rec = cc.RecruitmentRecord(name=name, ttl_s=30.0)
    assert cc.dispatch(rec) == "node.patch"


# ── catalog / affordance registration ──────────────────────────────────────


def test_node_patch_capabilities_registered_in_catalog() -> None:
    """Node-patch vocabulary includes add/remove plus structural primitives."""
    from shared.compositional_affordances import COMPOSITIONAL_CAPABILITIES

    add_names = {c.name for c in COMPOSITIONAL_CAPABILITIES if c.name.startswith("node.add.")}
    remove_names = {c.name for c in COMPOSITIONAL_CAPABILITIES if c.name.startswith("node.remove.")}
    names = {c.name for c in COMPOSITIONAL_CAPABILITIES}
    assert len(add_names) >= 5, f"expected ≥5 node.add.* capabilities, got {add_names}"
    assert len(remove_names) >= 1, f"expected ≥1 node.remove.* capability, got {remove_names}"
    assert {
        "node.compose.color,drift",
        "node.fork.fb",
        "node.merge.fb,fork_fb",
        "node.route.content,out",
    }.issubset(names)


def test_node_patch_capability_descriptions_are_gibson_verb() -> None:
    """Every node.add / node.remove capability has a non-trivial
    Gibson-verb cognitive-function description (15+ words; not just the
    shader's name)."""
    from shared.compositional_affordances import COMPOSITIONAL_CAPABILITIES

    for c in COMPOSITIONAL_CAPABILITIES:
        if not c.name.startswith("node."):
            continue
        words = c.description.split()
        assert len(words) >= 15, (
            f"{c.name}: description too short ({len(words)} words) — "
            f"Gibson-verb descriptions need ≥15 words: {c.description!r}"
        )
        # The description shouldn't be just the technical type name.
        suffix = c.name.split(".", 2)[2]
        assert c.description.lower() != suffix.lower()


# ── Defensive recruitment reader — non-dict JSON root ──────────────────


@pytest.mark.parametrize(
    "payload,kind",
    [("null", "null"), ('"a"', "string"), ("[1,2]", "list"), ("42", "int")],
)
def test_process_recruitment_non_dict_root_returns_false(
    tmp_path: Path, payload: str, kind: str, monkeypatch: pytest.MonkeyPatch
):
    """Pin process_graph_patch_recruitment against non-dict JSON roots.
    _build_patch_from_recruitment and _family_timestamps both call
    payload.get(...) — a non-dict root previously raised AttributeError.
    Same corruption-class as #2638 (preset-recruitment, in flight)."""
    from agents.studio_compositor import graph_patch_consumer as gpc

    path = tmp_path / "recruitment.json"
    path.write_text(payload)
    monkeypatch.setattr(gpc, "RECRUITMENT_FILE", path)
    assert gpc.process_graph_patch_recruitment() is False, f"non-dict root={kind} must yield False"


def test_process_graph_patch_recruitment_honors_autonomous_disable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gpc.RECRUITMENT_FILE.write_text(
        json.dumps(
            {
                "families": {
                    "node.add": {
                        "items": [
                            {
                                "capability": "node.add.feedback",
                                "suffix": "feedback",
                                "last_recruited_ts": time.time(),
                                "ttl_s": 30.0,
                            }
                        ],
                        "last_recruited_ts": time.time(),
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HAPAX_FX_AUTONOMOUS_MUTATIONS", "0")
    monkeypatch.setattr(
        gpc,
        "_apply_patch_async",
        lambda *_args, **_kwargs: pytest.fail("disabled graph patch must not apply"),
    )

    assert gpc.process_graph_patch_recruitment() is False
