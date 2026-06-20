from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from shared.hkp_bundle_export import export_shadow_bundle
from shared.hkp_prompt_context import (
    FORBIDDEN_FIELDS,
    NON_AUTHORITY_BANNER,
    PromptContextError,
    _effective_allowed_fields,
    assert_local_route,
    build_prompt_context,
    build_prompt_context_for_route,
    context_for_task,
)

GENERATED_AT = "2026-06-19T20:03:41Z"


def _write_task(path: Path, *, task_id: str, description: str = "A normal description.") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "type": "cc-task",
        "task_id": task_id,
        "title": f"Task {task_id}",
        "description": description,
        "status": "done",
        "depends_on": [],
        "privacy_class": "internal",
        "authority_case": "CASE-SDLC-REFORM-001",
        "parent_spec": "/redacted/spec.md",
        "route_metadata_schema": 1,
        "quality_floor": "frontier_required",
        "mutation_surface": "source",
        "authority_level": "authoritative",
    }
    path.write_text(
        "---\n"
        + yaml.safe_dump(frontmatter, sort_keys=False)
        + "---\n\n# Task\nPrivate body text.\n",
        encoding="utf-8",
    )
    return path


def _bundle(tmp_path: Path, monkeypatch, **kw) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    source_root = tmp_path / "repo"
    task = _write_task(source_root / "tasks" / "a.md", task_id="ctx-a", **kw)
    result = export_shadow_bundle(
        [task],
        bundle_id="ctx-bundle",
        source_root=source_root,
        source_root_id="repo:test",
        source_commit="abc123",
        generated_at=GENERATED_AT,
    )
    return result.bundle_path


def test_prompt_context_carries_banner_and_allowed_fields(tmp_path: Path, monkeypatch) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    result = build_prompt_context(bundle)

    assert result.concept_count == 1
    # mandatory non-authority banner present in rendered text and every snippet
    assert NON_AUTHORITY_BANNER in result.text
    snip = result.snippets[0]
    assert snip["non_authority"] == NON_AUTHORITY_BANNER
    # authority ceiling preserved, never upgraded
    assert snip["authority"]["may_authorize"] is False
    assert snip["authority"]["level"] == "support_non_authoritative"
    assert "freshness" in snip
    # allowed fields surfaced
    assert snip["title"] == "Task ctx-a"


def test_prompt_context_excludes_forbidden_fields(tmp_path: Path, monkeypatch) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    result = build_prompt_context(bundle)
    serialized = json.dumps(result.snippets)
    for forbidden in FORBIDDEN_FIELDS:
        assert f'"{forbidden}"' not in serialized
    # raw body never leaks into the assembled context
    assert "Private body text" not in result.text


def test_prompt_context_redacts_private_path_in_fields(tmp_path: Path, monkeypatch) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    # inject an absolute path into a projected concept field, post-export
    concept = next((bundle / "concepts").glob("*.md"))
    text = concept.read_text(encoding="utf-8")
    # the exporter carries the source title through; inject an absolute path there
    assert "Task ctx-a" in text
    concept.write_text(
        text.replace("Task ctx-a", "Task /private/secrets/key.pem"),
        encoding="utf-8",
    )
    result = build_prompt_context(bundle)
    assert "/private/secrets/key.pem" not in result.text
    assert "[private-path-redacted]" in json.dumps(result.snippets)


def test_prompt_context_fails_closed_on_deny_policy() -> None:
    deny = {"consumers": [{"consumer": "local_prompt_context", "default": "deny"}]}
    assert _effective_allowed_fields(deny) == frozenset()


def test_build_prompt_context_raises_on_denied_bundle(tmp_path: Path, monkeypatch) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    policy_path = bundle / "_hkp" / "consumer_policy.yaml"
    policy = yaml.safe_load(policy_path.read_text())
    for row in policy["consumers"]:
        if row["consumer"] == "local_prompt_context":
            row["default"] = "deny"
    policy_path.write_text(yaml.safe_dump(policy), encoding="utf-8")
    with pytest.raises(PromptContextError):
        build_prompt_context(bundle)


@pytest.mark.parametrize(
    "api_base",
    [
        "http://localhost:5000/v1",
        "http://127.0.0.1:11434",
        "http://192.168.68.50:5000/v1",
        "http://hapax-podium.tailf9491.ts.net:5000/v1",
    ],
)
def test_assert_local_route_accepts_fleet_private(api_base: str) -> None:
    assert_local_route(api_base)  # must not raise


@pytest.mark.parametrize(
    "api_base",
    [
        "https://api.anthropic.com",
        "https://generativelanguage.googleapis.com/v1",
        "https://api.openai.com/v1",
        "https://api.perplexity.ai",
        "",
    ],
)
def test_assert_local_route_rejects_public_provider(api_base: str) -> None:
    with pytest.raises(PromptContextError):
        assert_local_route(api_base)


def test_build_for_route_enforces_local(tmp_path: Path, monkeypatch) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    with pytest.raises(PromptContextError):
        build_prompt_context_for_route(bundle, api_base="https://api.anthropic.com")
    ok = build_prompt_context_for_route(bundle, api_base="http://localhost:5000/v1")
    assert ok.concept_count == 1


def test_symlink_concept_rejected(tmp_path: Path, monkeypatch) -> None:
    bundle = _bundle(tmp_path, monkeypatch)
    concept = next((bundle / "concepts").glob("*.md"))
    real = concept.read_bytes()
    concept.unlink()
    target = bundle / "concepts" / "_real.md.hidden"
    target.write_bytes(real)
    concept.symlink_to(target)
    with pytest.raises(PromptContextError, match="symlink"):
        build_prompt_context(bundle)


def _build_sdlc_bundle(tmp_path: Path):
    from shared.hkp_bundle_export import export_shadow_bundle

    src = tmp_path / "repo"

    def w(name: str, tid: str, deps: list[str]) -> Path:
        p = src / name
        p.parent.mkdir(parents=True, exist_ok=True)
        fm = {
            "type": "cc-task",
            "task_id": tid,
            "title": f"Task {tid}",
            "description": "d",
            "status": "done",
            "depends_on": deps,
            "privacy_class": "internal",
            "authority_case": "CASE-SDLC-REFORM-001",
            "parent_spec": "/redacted/spec.md",
            "route_metadata_schema": 1,
            "quality_floor": "frontier_required",
            "mutation_surface": "source",
            "authority_level": "authoritative",
        }
        p.write_text(
            "---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\n\n# T\nbody\n", encoding="utf-8"
        )
        return p

    a = w("a.md", "ctx-a", ["ctx-b"])
    b = w("b.md", "ctx-b", [])
    return export_shadow_bundle(
        [a, b],
        bundle_id="sdlc",
        source_root=src,
        source_root_id="repo:test",
        generated_at=GENERATED_AT,
    )


def test_context_for_task_includes_resolved_neighbour(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _build_sdlc_bundle(tmp_path)
    ctx = context_for_task("ctx-a")
    assert NON_AUTHORITY_BANNER in ctx
    assert "Task ctx-a" in ctx
    assert "Task ctx-b" in ctx  # 1-hop depends_on neighbour, resolved


def test_context_for_task_missing_task_fails_open(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _build_sdlc_bundle(tmp_path)
    assert context_for_task("no-such-task") == ""


def test_context_for_task_missing_bundle_fails_open(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert context_for_task("anything") == ""
