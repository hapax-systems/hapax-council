"""Load-balance the rulesets read across REST and GraphQL (the real consumer).

Task github-rest-hourly-budget-exhausted-by-estate-20261004 (operator: "graphql and rest are
supposed to be lb"). cc-pr-autoqueue's `fetch_merge_queue_merge_method` was REST-only, so a
REST-core exhaustion (measured 2026-10-04 at 01:55Z while GraphQL sat at 4993/5000) 403'd the
rulesets fetch and no PR could arm. It now routes the read through `choose_transport`
(authoritative HEADER headroom, both directions), diverting BEFORE the call and holding with a
reason only when BOTH pools are measured below floor.

These pin the ROUTING at the consumer: choose_transport is mocked to each decision and the test
asserts which transport implementation ran. No REST is looped; nothing is measured live.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _load_autoqueue():
    if "cc_pr_autoqueue" in sys.modules:
        return sys.modules["cc_pr_autoqueue"]
    spec = importlib.util.spec_from_file_location(
        "cc_pr_autoqueue", _SCRIPTS / "cc-pr-autoqueue.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["cc_pr_autoqueue"] = module
    spec.loader.exec_module(module)
    return module


autoqueue = _load_autoqueue()


def _full_ruleset() -> list[dict]:
    """An active branch ruleset with the merge-queue method inline, matching either transport."""
    return [
        {
            "id": 1,
            "name": autoqueue.AUTOQUEUE_MERGE_QUEUE_RULESET_NAME,
            "target": "branch",
            "enforcement": "active",
            "rules": [{"type": "merge_queue", "parameters": {"merge_method": "squash"}}],
        }
    ]


def _patch(monkeypatch, transport, reason) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(autoqueue, "choose_transport", lambda **_k: (transport, reason))

    def fake_graphql(_repo, **_k):
        calls.append("graphql")
        return _full_ruleset(), "rulesets_via_graphql"

    def fake_rest(_path, **_k):
        calls.append("rest")
        return True, _full_ruleset(), ""

    monkeypatch.setattr(autoqueue, "_rulesets_graphql", fake_graphql)
    monkeypatch.setattr(autoqueue, "_gh_api_get_json", fake_rest)
    return calls


def _run(tmp_path):
    return autoqueue.fetch_merge_queue_merge_method(
        repo="owner/repo", repo_root=tmp_path, runner=lambda *_a, **_k: None
    )


def test_rest_exhausted_routes_rulesets_to_graphql(tmp_path: Path, monkeypatch) -> None:
    calls = _patch(monkeypatch, "graphql", "github_rest_below_floor:0<200;graphql_remaining=4993")
    method, _source = _run(tmp_path)
    assert calls == ["graphql"], (
        f"REST exhausted must route the rulesets read to GraphQL; calls={calls}"
    )
    assert method is not None


def test_graphql_low_routes_rulesets_to_rest(tmp_path: Path, monkeypatch) -> None:
    calls = _patch(monkeypatch, "rest", "github_graphql_below_floor:0<500")
    method, _source = _run(tmp_path)
    assert calls == ["rest"], (
        f"GraphQL below floor must route the rulesets read to REST; calls={calls}"
    )
    assert method is not None


def test_both_pools_low_holds_with_a_reason(tmp_path: Path, monkeypatch) -> None:
    calls = _patch(monkeypatch, None, "github_both_pools_below_floor:core=0 graphql=0")
    method, source = _run(tmp_path)
    assert method is None, "both pools below floor must hold, not spend into a doomed transport"
    assert calls == [], "no transport implementation may run when both pools are below floor"
    assert source.startswith("rulesets_fetch_failed:github_both_pools_below_floor")
