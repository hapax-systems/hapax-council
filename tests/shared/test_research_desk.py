"""Research-desk queue and delivery tests against a temporary vault tree."""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import pytest

# The CommonMark renderer is the locked markdown-it-py (uv.lock, via rich/textual).
from markdown_it import MarkdownIt

from shared.frontmatter import parse_frontmatter_with_diagnostics
from shared.research_desk import (
    ALLOWED_URI_SCHEMES,
    DEFAULT_DELIVERY_LANE,
    DEFAULT_STATE_ROOT,
    DEFAULT_VAULT_ROOT,
    MAX_CITATION_TITLE_CHARS,
    MAX_CITATIONS,
    MAX_LIST_LIMIT,
    MAX_MARKDOWN_BYTES,
    MAX_MODEL_NOTES_BYTES,
    MAX_REQUEST_BODY_BYTES,
    DeliveryReceipt,
    MalformedRequest,
    ResearchDeskConfig,
    ResearchDeskError,
    deliver_result,
    get_request,
    list_open_requests,
    neutralize_markdown,
    normalize_citations,
    render_drop,
    stamp_request_row,
    validate_request_id,
)
from shared.task_note_lock import projected_path_lock


@pytest.fixture
def desk(tmp_path: Path) -> ResearchDeskConfig:
    vault = tmp_path / "vault"
    (vault / "20-projects" / "hapax-cc-tasks" / "active").mkdir(parents=True)
    (vault / "30-areas" / "hapax" / "lanebus" / "cx-blue").mkdir(parents=True)
    return ResearchDeskConfig(
        vault_root=vault, state_root=tmp_path / "state", delivery_lane="cx-blue"
    )


def write_request(
    config: ResearchDeskConfig,
    request_id: str,
    *,
    status: str = "offered",
    kind: str = "research_request",
    route_family: str = "perplexity-desk",
    question: str = "What changed in the EU AI Act implementing acts this quarter?",
    priority: str = "p2",
    extra: str = "",
    body: str = "Full brief lives here.\n",
) -> Path:
    """Write a request row. Built line-by-line: a dedent-based fixture silently
    loses its dedent as soon as an interpolated value spans lines, and the result
    is a file that does not start with frontmatter at all."""
    lines = [
        "---",
        "type: cc-task",
        f"task_id: {request_id}",
        f'title: "{request_id} title"',
        f"kind: {kind}",
        f"route_family: {route_family}",
        f"status: {status}",
        f"priority: {priority}",
        f'question: "{question}"',
        "constraints:",
        "  - cite primary sources",
        "deadline: 2026-09-20",
        "created_at: 2026-09-16T02:00:00Z",
    ]
    if extra:
        lines.extend(extra.rstrip("\n").splitlines())
    lines.extend(["---", ""])
    path = config.requests_dir / f"{request_id}.md"
    path.write_text("\n".join(lines) + "\n" + body, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Identity
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "bad",
    ["", "   ", "../../etc/passwd", "a/b", "with space", "-leading-dash", "x" * 129, "a\x00b"],
)
def test_request_id_refuses_anything_that_could_leave_the_queue_directory(bad: str) -> None:
    with pytest.raises(ResearchDeskError) as exc:
        validate_request_id(bad)
    assert exc.value.reason_code == "request_id_invalid"
    assert exc.value.repair_action


def test_request_id_accepts_the_estate_row_shape() -> None:
    assert validate_request_id("perplexity-research-desk-connector-20260916") == (
        "perplexity-research-desk-connector-20260916"
    )


def test_traversal_id_never_reaches_the_filesystem(desk: ResearchDeskConfig) -> None:
    outside = desk.vault_root / "secret.md"
    outside.write_text("---\nkind: research_request\nroute_family: perplexity-desk\n---\n")
    with pytest.raises(ResearchDeskError) as exc:
        get_request(desk, "../secret")
    assert exc.value.reason_code == "request_id_invalid"


# --------------------------------------------------------------------------- #
# Configuration from the environment
# --------------------------------------------------------------------------- #


def test_from_env_happy_path_reads_strips_and_composes_all_three_roots() -> None:
    config = ResearchDeskConfig.from_env(
        {
            "HAPAX_RESEARCH_DESK_VAULT_ROOT": " /srv/vault ",
            "HAPAX_RESEARCH_DESK_STATE_ROOT": "/srv/state",
            "HAPAX_RESEARCH_DESK_LANE": " cx-blue ",
        }
    )
    assert config.vault_root == Path("/srv/vault")
    assert config.state_root == Path("/srv/state")
    assert config.delivery_lane == "cx-blue"
    assert config.requests_dir == Path("/srv/vault/20-projects/hapax-cc-tasks/active")
    assert config.lanebus_dir == Path("/srv/vault/30-areas/hapax/lanebus/cx-blue")
    assert config.lock_dir == Path("/srv/state/locks")


def test_from_env_without_the_environment_keeps_the_estate_defaults() -> None:
    config = ResearchDeskConfig.from_env({})
    assert config.vault_root == DEFAULT_VAULT_ROOT
    assert config.state_root == DEFAULT_STATE_ROOT
    assert config.delivery_lane == DEFAULT_DELIVERY_LANE


@pytest.mark.parametrize("lane", ["cx/blue", "/lane", "../evil", "a/../../b", ".", ".."])
def test_from_env_refuses_a_lane_that_could_leave_the_lanebus_directory(lane: str) -> None:
    """The lane is env-injected and lands in a path join one line later; any value
    carrying a separator or a traversal component must stop at this guard."""
    with pytest.raises(ResearchDeskError) as exc:
        ResearchDeskConfig.from_env({"HAPAX_RESEARCH_DESK_LANE": lane})
    assert exc.value.reason_code == "delivery_lane_invalid"
    assert exc.value.repair_action


def test_from_env_treats_an_empty_lane_as_unset_not_as_a_path_component() -> None:
    """The empty string never reaches the guard: the `or DEFAULT_DELIVERY_LANE`
    fallback runs first, so an empty or whitespace-only lane resolves to the fixed
    default and never composes a lanebus path from an empty segment. The guard's
    literal "" member is defense-in-depth for a refactor that drops the fallback."""
    for raw in ("", "   "):
        config = ResearchDeskConfig.from_env({"HAPAX_RESEARCH_DESK_LANE": raw})
        assert config.delivery_lane == DEFAULT_DELIVERY_LANE


def test_from_env_path_values_are_stripped_and_expand_a_leading_tilde() -> None:
    config = ResearchDeskConfig.from_env(
        {
            "HAPAX_RESEARCH_DESK_VAULT_ROOT": " ~/desk-vault ",
            "HAPAX_RESEARCH_DESK_STATE_ROOT": "~/.desk-state",
        }
    )
    assert config.vault_root == Path.home() / "desk-vault"
    assert config.state_root == Path.home() / ".desk-state"


@pytest.mark.parametrize("raw", ["", "   "])
def test_from_env_blank_path_values_fall_back_to_the_defaults(raw: str) -> None:
    config = ResearchDeskConfig.from_env(
        {
            "HAPAX_RESEARCH_DESK_VAULT_ROOT": raw,
            "HAPAX_RESEARCH_DESK_STATE_ROOT": raw,
        }
    )
    assert config.vault_root == DEFAULT_VAULT_ROOT
    assert config.state_root == DEFAULT_STATE_ROOT


# --------------------------------------------------------------------------- #
# Listing
# --------------------------------------------------------------------------- #


def test_list_returns_only_desk_rows_that_are_open(desk: ResearchDeskConfig) -> None:
    write_request(desk, "open-one", status="offered", priority="p2")
    write_request(desk, "open-two", status="queued", priority="p0")
    write_request(desk, "already-done", status="delivered")
    write_request(desk, "not-ours-kind", kind="engineering")
    write_request(desk, "not-ours-route", route_family="tavily")

    requests, malformed = list_open_requests(desk, limit=10)

    assert [r.request_id for r in requests] == ["open-two", "open-one"], "p0 sorts ahead of p2"
    assert malformed == []


def test_list_admits_a_quoted_route_family(desk: ResearchDeskConfig) -> None:
    write_request(desk, "quoted-route", route_family='"perplexity-desk"')
    listed, _ = list_open_requests(desk)
    assert [row.request_id for row in listed] == ["quoted-route"]


def test_list_reports_malformed_desk_rows_rather_than_skipping_them(
    desk: ResearchDeskConfig,
) -> None:
    write_request(desk, "good", status="offered")
    (desk.requests_dir / "broken.md").write_text(
        "---\nkind: research_request\nroute_family: perplexity-desk\nstatus: offered\n---\nno question\n",
        encoding="utf-8",
    )

    requests, malformed = list_open_requests(desk, limit=10)

    assert [r.request_id for r in requests] == ["good"]
    assert [(m.request_id, m.reason_code) for m in malformed] == [("broken", "question_absent")]


def test_list_reports_a_desk_row_whose_task_id_does_not_match_its_filename(
    desk: ResearchDeskConfig,
) -> None:
    path = write_request(desk, "on-disk")
    path.write_text(
        path.read_text(encoding="utf-8").replace("task_id: on-disk", "task_id: something-else"),
        encoding="utf-8",
    )
    _, malformed = list_open_requests(desk, limit=10)
    assert [m.reason_code for m in malformed] == ["request_id_mismatch"]


@pytest.mark.parametrize("limit", [0, -1, MAX_LIST_LIMIT + 1])
def test_list_refuses_an_out_of_range_limit(desk: ResearchDeskConfig, limit: int) -> None:
    with pytest.raises(ResearchDeskError) as exc:
        list_open_requests(desk, limit=limit)
    assert exc.value.reason_code == "limit_out_of_range"


def test_list_refuses_a_non_integer_limit(desk: ResearchDeskConfig) -> None:
    with pytest.raises(ResearchDeskError) as exc:
        list_open_requests(desk, limit="5")  # type: ignore[arg-type]
    assert exc.value.reason_code == "limit_invalid"


def test_list_truncates_to_the_limit(desk: ResearchDeskConfig) -> None:
    for index in range(5):
        write_request(desk, f"req-{index}")
    requests, _ = list_open_requests(desk, limit=2)
    assert len(requests) == 2


def test_missing_requests_dir_refuses_with_a_next_action(tmp_path: Path) -> None:
    config = ResearchDeskConfig(vault_root=tmp_path / "nope", state_root=tmp_path / "state")
    with pytest.raises(ResearchDeskError) as exc:
        list_open_requests(config)
    assert exc.value.reason_code == "requests_dir_absent"
    assert "HAPAX_RESEARCH_DESK_VAULT_ROOT" in exc.value.repair_action


# --------------------------------------------------------------------------- #
# Fetch
# --------------------------------------------------------------------------- #


def test_fetch_returns_the_full_brief(desk: ResearchDeskConfig) -> None:
    write_request(desk, "req-a", body="Line one.\nLine two.\n")
    request = get_request(desk, "req-a")
    assert request.question.startswith("What changed")
    assert request.constraints == ("cite primary sources",)
    assert request.deadline == "2026-09-20"
    assert "Line two." in request.brief
    assert request.full()["brief"].strip().endswith("Line two.")


def test_fetch_truncates_a_brief_past_the_128_kib_cap(desk: ResearchDeskConfig) -> None:
    write_request(desk, "req-huge", body="x" * (MAX_REQUEST_BODY_BYTES + 512))
    request = get_request(desk, "req-huge")
    marker = "\n\n[brief truncated by the research desk at 128 KiB]"
    assert request.brief.endswith(marker)
    assert len(request.brief[: -len(marker)].encode("utf-8")) == MAX_REQUEST_BODY_BYTES


def test_error_to_payload_carries_the_reason_and_the_next_action() -> None:
    error = ResearchDeskError("request_id_invalid", "pick an id from the list", detail="got '../x'")
    assert error.to_payload() == {
        "ok": False,
        "reason_code": "request_id_invalid",
        "next_action": "pick an id from the list",
        "detail": "got '../x'",
    }


def test_malformed_row_to_payload_names_the_row_and_the_reason() -> None:
    row = MalformedRequest("broken", "question_absent", "the row must carry a question")
    assert row.to_payload() == {
        "request_id": "broken",
        "reason_code": "question_absent",
        "detail": "the row must carry a question",
    }


def test_fetch_refuses_an_unknown_id(desk: ResearchDeskConfig) -> None:
    with pytest.raises(ResearchDeskError) as exc:
        get_request(desk, "no-such-request")
    assert exc.value.reason_code == "request_not_found"


def test_fetch_refuses_a_row_that_is_not_a_desk_row(desk: ResearchDeskConfig) -> None:
    write_request(desk, "engineering-row", kind="engineering")
    with pytest.raises(ResearchDeskError) as exc:
        get_request(desk, "engineering-row")
    assert exc.value.reason_code == "request_not_found"


def test_fetch_of_a_delivered_row_still_works(desk: ResearchDeskConfig) -> None:
    write_request(desk, "req-done", status="delivered")
    assert get_request(desk, "req-done").status == "delivered"


def test_symlinked_request_cannot_read_outside_the_active_directory(
    desk: ResearchDeskConfig,
) -> None:
    path = write_request(desk, "req-symlink")
    outside = desk.vault_root / "outside.md"
    path.rename(outside)
    path.symlink_to(outside)
    with pytest.raises(ResearchDeskError) as exc:
        get_request(desk, "req-symlink")
    assert exc.value.reason_code == "request_not_found"
    listed, _ = list_open_requests(desk)
    assert listed == []


def test_request_with_control_character_is_malformed(desk: ResearchDeskConfig) -> None:
    write_request(desk, "req-control", body="brief\x01payload")
    listed, malformed = list_open_requests(desk)
    assert listed == []
    assert [row.reason_code for row in malformed] == ["request_control_character"]


def test_citations_accept_strings_and_objects() -> None:
    assert normalize_citations(["https://example.org/a"]) == (
        {"url": "https://example.org/a", "title": ""},
    )
    assert normalize_citations([{"url": "https://example.org/b", "title": "B"}]) == (
        {"url": "https://example.org/b", "title": "B"},
    )
    assert normalize_citations(None) == ()


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "javascript:alert(1)", "data:text/html,x", "not-a-url", "ftp://x/y"],
)
def test_citations_refuse_non_http_schemes(url: str) -> None:
    with pytest.raises(ResearchDeskError) as exc:
        normalize_citations([url])
    assert exc.value.reason_code == "citation_scheme_refused"


def test_citations_are_count_capped() -> None:
    with pytest.raises(ResearchDeskError) as exc:
        normalize_citations([f"https://example.org/{i}" for i in range(MAX_CITATIONS + 1)])
    assert exc.value.reason_code == "payload_too_large"


def test_citation_titles_are_stripped_of_control_characters() -> None:
    (citation,) = normalize_citations([{"url": "https://example.org", "title": "a\x00b\x1fc"}])
    assert citation["title"] == "abc"


def test_citation_url_with_newline_cannot_add_drop_frontmatter(desk: ResearchDeskConfig) -> None:
    write_request(desk, "req-url")
    with pytest.raises(ResearchDeskError) as exc:
        deliver_result(
            desk,
            request_id="req-url",
            markdown="answer",
            citations=["https://example.org/a\ninjected: true"],
        )
    assert exc.value.reason_code == "citations_invalid"
    assert not list(desk.lanebus_dir.glob("*.md"))


def test_multiline_title_round_trips_through_drop_frontmatter(desk: ResearchDeskConfig) -> None:
    request = replace(get_request(desk, write_request(desk, "req-lines").stem), title="one\ntwo")
    drop = render_drop(
        request=request,
        lane="cx-blue",
        markdown="answer",
        citations=(),
        model_notes="",
        receipt_id="rd-lines",
        delivered_at="2026-09-28T19:00:00Z",
    )
    assert parse_frontmatter_with_diagnostics(drop).frontmatter["request_title"] == "one\ntwo"


def test_citation_title_cannot_add_active_markdown(desk: ResearchDeskConfig) -> None:
    request = get_request(desk, write_request(desk, "req-cite-title").stem)
    title = "![beacon](https://tracker.example/x) [run](javascript:alert(1)) <img src=x>"
    drop = render_drop(
        request=request,
        lane="cx-blue",
        markdown="answer",
        citations=(
            {"url": "https://example.org/a)![x](https://tracker.example/y)", "title": title},
        ),
        model_notes="",
        receipt_id="rd-title",
        delivered_at="2026-09-28T19:00:00Z",
    )
    body = parse_frontmatter_with_diagnostics(drop).body
    assert "&lt;img" in body
    assert "\\![beacon]" not in body
    assert "\\!\\[beacon\\]" in body
    assert "[run](javascript:" not in body
    assert ")![x](https://tracker" not in body


def test_delivery_writes_a_labelled_drop_and_stamps_the_row(desk: ResearchDeskConfig) -> None:
    path = write_request(desk, "req-deliver")
    receipt = deliver_result(
        desk,
        request_id="req-deliver",
        markdown="## Finding\n\nThe answer.",
        citations=["https://example.org/source"],
        model_notes="sonar-deep-research, 3 passes",
        now=datetime(2026, 9, 16, 4, 5, 6, tzinfo=UTC),
    )

    assert isinstance(receipt, DeliveryReceipt)
    assert receipt.duplicate is False
    assert receipt.drop_path.name == "20260916T040506Z-perplexity-desk-req-deliver.md"
    assert receipt.drop_path.parent == desk.lanebus_dir

    drop = parse_frontmatter_with_diagnostics(receipt.drop_path)
    assert drop.ok
    assert drop.frontmatter["source"] == "perplexity-computer"
    assert drop.frontmatter["content_trust"] == "untrusted_external"
    assert drop.frontmatter["request_id"] == "req-deliver"
    assert drop.frontmatter["receipt_id"] == receipt.receipt_id
    assert drop.frontmatter["citations"] == [{"url": "https://example.org/source"}]
    assert "Untrusted external content" in drop.body
    assert "The answer." in drop.body
    assert "sonar-deep-research" in drop.body

    row = parse_frontmatter_with_diagnostics(path)
    assert row.ok
    assert row.frontmatter["status"] == "delivered"
    assert row.frontmatter["delivery_receipt"] == receipt.receipt_id
    assert row.frontmatter["delivered_at"] == "2026-09-16T04:05:06Z"
    assert row.frontmatter["delivery_drop"] == (
        "30-areas/hapax/lanebus/cx-blue/20260916T040506Z-perplexity-desk-req-deliver.md"
    )
    assert row.frontmatter["delivery_citations"] == 1


def test_delivery_preserves_every_other_row_field(desk: ResearchDeskConfig) -> None:
    path = write_request(desk, "req-preserve", extra="wsjf: 12.5\ntags: [a, b]\n")
    before = parse_frontmatter_with_diagnostics(path).frontmatter or {}
    deliver_result(desk, request_id="req-preserve", markdown="answer")
    after = parse_frontmatter_with_diagnostics(path).frontmatter or {}

    changed = {"status", "delivered_at", "delivery_receipt", "delivery_drop", "delivery_citations"}
    for key, value in before.items():
        if key in changed:
            continue
        assert after[key] == value, f"{key} was mutated by delivery"
    assert after["wsjf"] == 12.5
    assert after["tags"] == ["a", "b"]
    assert parse_frontmatter_with_diagnostics(path).body.strip() == "Full brief lives here."


def test_retry_refuses_an_unstamped_drop_without_creating_another(
    desk: ResearchDeskConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_request(desk, "req-interrupted")

    def fail_stamp(*args: object, **kwargs: object) -> None:
        raise OSError("simulated stamp failure")

    monkeypatch.setattr("shared.research_desk.stamp_request_row", fail_stamp)
    with pytest.raises(OSError, match="simulated stamp failure"):
        deliver_result(desk, request_id="req-interrupted", markdown="first answer")
    with pytest.raises(ResearchDeskError) as exc:
        deliver_result(desk, request_id="req-interrupted", markdown="second answer")
    assert exc.value.reason_code == "delivery_drop_unstamped"
    assert len(list(desk.lanebus_dir.glob("*.md"))) == 1


@pytest.mark.parametrize("label", ["a", "a [b]", "a [b [c]]"])
def test_nested_label_active_content_is_neutralized_in_delivery(
    desk: ResearchDeskConfig, label: str
) -> None:
    write_request(desk, "req-nested")
    receipt = deliver_result(
        desk,
        request_id="req-nested",
        markdown=f"![{label}](https://tracker.example/p.gif) [{label}](javascript:alert(1))",
    )
    drop = parse_frontmatter_with_diagnostics(receipt.drop_path)
    assert drop.frontmatter["withheld_images"] == 1
    assert drop.frontmatter["withheld_links"] == 1
    assert "![" not in drop.body
    assert f"[{label}](javascript:" not in drop.body


def test_unbalanced_image_label_is_neutralized_in_delivery(desk: ResearchDeskConfig) -> None:
    write_request(desk, "req-unbalanced")
    receipt = deliver_result(
        desk,
        request_id="req-unbalanced",
        markdown="![a [b](https://tracker.example/p.gif) answer",
    )
    drop = parse_frontmatter_with_diagnostics(receipt.drop_path)
    assert drop.frontmatter["withheld_images"] == 1
    assert "![" not in drop.body
    assert "https://tracker.example" not in drop.body


def test_raw_html_is_inert_in_delivery(desk: ResearchDeskConfig) -> None:
    write_request(desk, "req-html")
    markup = (
        "<iframe src=//t><link rel=stylesheet href=//t><video src=//t><audio src=//t>"
        "<source src=//t><object data=//t><embed src=//t><svg><image href=//t>"
        '<div style="background:url(//t)">'
    )
    markup += " ".join(
        f"[x]({scheme}alert(1))"
        for scheme in (
            "javascript&#58;",
            "javascript&colon;",
            "&#106;avascript:",
            "javascript&#x3A;",
        )
    )
    receipt = deliver_result(desk, request_id="req-html", markdown=markup)
    drop = parse_frontmatter_with_diagnostics(receipt.drop_path)
    assert "<" not in drop.body
    assert "&lt;" in drop.body
    assert drop.frontmatter["withheld_links"] == 4


def test_a_markdown_rule_in_the_answer_cannot_forge_the_drop_frontmatter(
    desk: ResearchDeskConfig,
) -> None:
    write_request(desk, "req-forge")
    receipt = deliver_result(
        desk,
        request_id="req-forge",
        markdown="---\nsource: hapax-estate\ncontent_trust: trusted\n---\n\nforged",
    )
    drop = parse_frontmatter_with_diagnostics(receipt.drop_path)
    assert drop.ok
    assert drop.frontmatter["source"] == "perplexity-computer"
    assert drop.frontmatter["content_trust"] == "untrusted_external"


def test_stamp_refuses_a_symlinked_row(desk: ResearchDeskConfig) -> None:
    path = write_request(desk, "req-stamp-link")
    outside = desk.vault_root / "outside-stamp.md"
    path.rename(outside)
    path.symlink_to(outside)
    original = outside.read_bytes()
    with pytest.raises(ResearchDeskError) as exc:
        stamp_request_row(
            path,
            receipt_id="rd-test",
            delivered_at="2026-09-28T18:00:00Z",
            drop_relpath="drop.md",
            citation_count=0,
        )
    assert exc.value.reason_code == "request_not_found"
    assert path.is_symlink()
    assert outside.read_bytes() == original


def test_stamp_waits_for_projection_lock_and_preserves_concurrent_edit(
    desk: ResearchDeskConfig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    path = write_request(desk, "req-race")
    started = threading.Event()

    def stamp() -> None:
        started.set()
        stamp_request_row(
            path, receipt_id="rd-race", delivered_at="now", drop_relpath="a.md", citation_count=0
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        with projected_path_lock("req-race", (path,)):
            future = pool.submit(stamp)
            assert started.wait(2)
            time.sleep(0.05)
            assert not future.done(), "the stamp did not wait for the projection lock"
            path.write_text(path.read_text() + "concurrent_edit: survived\n")
        future.result(timeout=5)
    assert "concurrent_edit: survived" in path.read_text()
    assert "status: delivered" in path.read_text()


# --------------------------------------------------------------------------- #
# Active content in the delivered body (review finding, 2026-09-16)
# --------------------------------------------------------------------------- #


def test_images_are_demoted_to_links_so_nothing_auto_loads() -> None:
    """An image target auto-loads when the drop is opened — no click required.

    That turns any URL the external agent picks into a read receipt on the operator's
    vault. Demotion removes the auto-load and keeps the reference.
    """
    result = neutralize_markdown("before ![a beacon](https://tracker.example/p.gif) after")
    assert result.images == 1
    assert "![" not in result.markdown
    assert "[image withheld — a beacon](https://tracker.example/p.gif)" in result.markdown


def test_raw_html_image_with_backtick_cannot_break_out_of_neutralization() -> None:
    result = neutralize_markdown('<img src="https://tracker.example/x`y">')
    assert result.images == 1
    assert "<img" not in result.markdown
    assert "&lt;img" in result.markdown


def test_control_byte_in_link_target_is_neutralized() -> None:
    result = neutralize_markdown("[x](\x01https://example.org)")
    assert result.links == 1
    assert "](\x01https:" not in result.markdown


@pytest.mark.parametrize("label", ["a", "a [b]", "a [b [c]]", "`a` [b [c]]"])
def test_nested_image_labels_cannot_auto_load(label: str) -> None:
    result = neutralize_markdown(f"before ![{label}](https://tracker.example/p.gif) after")
    assert result.images == 1
    assert "![" not in result.markdown


def test_unbalanced_image_label_is_removed_whole() -> None:
    result = neutralize_markdown("before ![a [b](https://tracker.example/p.gif) after")
    assert result.images == 1
    assert "![" not in result.markdown
    assert "https://tracker.example" not in result.markdown


def test_excessively_nested_image_label_is_removed_whole() -> None:
    label = "a " + "[" * 20 + "b" + "]" * 20
    result = neutralize_markdown(f"before ![{label}](https://tracker.example/p.gif) after")
    assert result.images == 1
    assert "![" not in result.markdown
    assert "https://tracker.example" not in result.markdown


def test_raw_html_images_are_defanged_too() -> None:
    result = neutralize_markdown('text <img src="http://tracker.example/p.gif"> more')
    assert result.images == 1
    assert '&lt;img src="http://tracker.example/p.gif"&gt;' in result.markdown


@pytest.mark.parametrize(
    "tag",
    [
        '<iframe src="https://t.example/"></iframe>',
        '<link rel="stylesheet" href="https://t.example/a.css">',
        '<video src="https://t.example/v.mp4"></video>',
        '<audio src="https://t.example/a.mp3"><source src="https://t.example/a.mp3"></audio>',
        '<object data="https://t.example/o"></object><embed src="https://t.example/e">',
        '<svg><image href="https://t.example/i"/></svg>',
        '<div style="background:url(https://t.example/i)">x</div>',
        '<x title="<iframe src=https://t.example>">',
        "`unclosed <iframe src=https://t.example>",
    ],
)
def test_raw_html_cannot_load_external_content(tag: str) -> None:
    result = neutralize_markdown(tag)
    assert "<" not in result.markdown
    assert "&lt;" in result.markdown


@pytest.mark.parametrize(
    "target",
    ["javascript:alert(1)", "file:///etc/passwd", "data:text/html,<b>x", "vbscript:x"],
)
def test_links_with_a_disallowed_scheme_are_defanged_to_inert_text(target: str) -> None:
    result = neutralize_markdown(f"see [click me]({target}) here")
    assert result.links == 1
    assert f"]({target})" not in result.markdown
    assert "link withheld" in result.markdown
    assert target in result.markdown, "the original is shown, just not as a live link"


@pytest.mark.parametrize("label", ["a", "a [b]", "a [b [c]]"])
def test_nested_link_labels_cannot_keep_active_destinations(label: str) -> None:
    result = neutralize_markdown(f"before [{label}](javascript:alert(1)) after")
    assert result.links == 1
    assert "](javascript:" not in result.markdown


def test_excessively_nested_link_label_is_removed_whole() -> None:
    label = "[" * 17 + "x" + "]" * 17
    result = neutralize_markdown(f"before [{label}](javascript:alert(1)) after")
    assert result.links == 1
    assert "](javascript:" not in result.markdown


def test_unbalanced_link_label_keeps_its_text_and_withholds_the_inner_link() -> None:
    # F1: an unbalanced `[` keeps its opener and text; the link inside is judged alone.
    result = neutralize_markdown("before [a [b](javascript:alert(1)) after")
    assert result.links == 1
    assert "](javascript:" not in result.markdown
    assert (
        result.markdown == "before [a `b [link withheld — javascript: javascript:alert(1)]` after"
    )


def test_http_links_survive_untouched() -> None:
    body = "see [the source](https://example.org/a) and [another](http://example.org/b)"
    result = neutralize_markdown(body)
    assert result.links == 0
    assert result.markdown == body


def test_relative_and_fragment_links_survive() -> None:
    body = "see [here](#section) and [there](./notes.md)"
    result = neutralize_markdown(body)
    assert result.links == 0
    assert result.markdown == body


def test_autolinks_with_a_disallowed_scheme_are_defanged() -> None:
    result = neutralize_markdown("raw <file:///etc/passwd> here and <https://ok.example> there")
    assert result.links == 1
    assert "`[link withheld — file:///etc/passwd]`" in result.markdown
    assert "<https://ok.example>" in result.markdown


def test_neutralisation_is_total_on_ordinary_prose() -> None:
    body = "# Heading\n\nJust prose, a `code span`, and a list:\n\n- one\n- two\n"
    result = neutralize_markdown(body)
    assert result.markdown == body
    assert result.total == 0


def test_delivery_neutralises_the_body_and_records_the_counts(desk: ResearchDeskConfig) -> None:
    write_request(desk, "req-active")
    receipt = deliver_result(
        desk,
        request_id="req-active",
        markdown=(
            "Findings.\n\n"
            "![beacon](https://tracker.example/p.gif)\n\n"
            "[payload](javascript:alert(1))\n\n"
            "[legitimate](https://example.org/source)\n"
        ),
        model_notes="notes with [a file link](file:///tmp/x)",
    )
    drop = parse_frontmatter_with_diagnostics(receipt.drop_path)

    assert drop.ok
    assert drop.frontmatter["withheld_images"] == 1
    assert drop.frontmatter["withheld_links"] == 2, "one in the body, one in the model notes"
    body = drop.body
    assert "![" not in body
    assert "](javascript:" not in body
    assert "](file://" not in body
    assert "[legitimate](https://example.org/source)" in body
    assert "Active content removed:" in body


def test_the_citation_allowlist_and_the_body_allowlist_are_the_same_set() -> None:
    """One allowlist for every URI the desk writes, wherever it appears."""
    assert frozenset({"http", "https"}) == ALLOWED_URI_SCHEMES
    with pytest.raises(ResearchDeskError):
        normalize_citations(["ftp://example.org/x"])
    assert neutralize_markdown("[x](ftp://example.org/x)").links == 1


@pytest.mark.parametrize(
    "body",
    [
        "[x]( javascript:alert(1) )",
        "[x](\tjavascript:alert(1))",
        "[x](javascript:alert(1))",
        '[x](javascript:alert(1) "title")',
        "[x](<javascript:alert(1)>)",
        "[x](javascript&#58;alert(1))",
        "[x](javascript&colon;alert(1))",
        "[x](&#106;avascript:alert(1))",
        "[x](javascript&#x3A;alert(1))",
    ],
)
def test_no_commonmark_destination_spelling_smuggles_a_live_scheme(body: str) -> None:
    result = neutralize_markdown(body)
    assert result.links == 1, f"{body!r} was not recognised as a link at all"
    assert "](javascript:" not in result.markdown
    assert "]( javascript:" not in result.markdown
    assert "link withheld" in result.markdown


def test_a_destination_with_balanced_parens_is_not_truncated() -> None:
    result = neutralize_markdown("[wiki](https://en.wikipedia.org/wiki/Foo_(bar))")
    assert result.links == 0
    assert result.markdown == "[wiki](https://en.wikipedia.org/wiki/Foo_(bar))"


@pytest.mark.parametrize(
    "body",
    [
        "[click][r]\n\n[r]: javascript:alert(1)\n",
        "[r]\n\n[r]: javascript:alert(1)\n",
        "[click][r]\n\n> [r]:\n>   <JavaScript:alert(1)>\n",
        "[click][r]\n\n[r]: javascript&#58;alert(1)\n",
    ],
)
def test_a_reference_definition_cannot_carry_a_live_scheme(body: str) -> None:
    result = neutralize_markdown(body)
    assert result.links >= 1
    assert "\\]:" in result.markdown


def test_reference_definitions_with_allowed_schemes_survive() -> None:
    body = "[a][r] and [b][s]\n\n[r]: https://example.org/a\n[s]: ./notes.md\n"
    result = neutralize_markdown(body)
    assert result.links == 0
    assert result.markdown == body


def test_an_escaped_bracket_is_not_double_escaped_into_a_definition() -> None:
    result = neutralize_markdown("[r\\]: javascript:alert(1)")
    assert result.markdown == "[r\\]: javascript:alert(1)"


def test_an_autolink_cannot_carry_raw_html() -> None:
    result = neutralize_markdown("<http://x/<script>alert(1)//<http://y/</script>")
    assert "<script>" not in result.markdown
    assert "</script>" not in result.markdown


def test_a_reference_image_cannot_load_and_keeps_the_text_after_it() -> None:
    body = "![a][r] Finding one.\n\nFinding two (important).\n\n[r]: https://t.example/p.gif\n"
    result = neutralize_markdown(body)
    assert result.images == 1
    assert "![" not in result.markdown
    assert "Finding one." in result.markdown
    assert "Finding two (important)." in result.markdown


def test_delivery_refuses_a_request_that_is_not_open(desk: ResearchDeskConfig) -> None:
    write_request(desk, "req-closed", status="refused")
    with pytest.raises(ResearchDeskError) as exc:
        deliver_result(desk, request_id="req-closed", markdown="answer")
    assert exc.value.reason_code == "request_not_open"


def test_delivery_refuses_a_delivered_row_with_no_receipt(desk: ResearchDeskConfig) -> None:
    write_request(desk, "req-orphan", status="delivered")
    with pytest.raises(ResearchDeskError) as exc:
        deliver_result(desk, request_id="req-orphan", markdown="answer")
    assert exc.value.reason_code == "request_already_delivered"


def test_delivery_refuses_an_unknown_request(desk: ResearchDeskConfig) -> None:
    with pytest.raises(ResearchDeskError) as exc:
        deliver_result(desk, request_id="ghost", markdown="answer")
    assert exc.value.reason_code == "request_not_found"


def test_delivery_refuses_empty_markdown(desk: ResearchDeskConfig) -> None:
    write_request(desk, "req-empty")
    with pytest.raises(ResearchDeskError) as exc:
        deliver_result(desk, request_id="req-empty", markdown="   \n  ")
    assert exc.value.reason_code == "markdown_empty"


def test_delivery_refuses_oversized_markdown(desk: ResearchDeskConfig) -> None:
    write_request(desk, "req-big")
    with pytest.raises(ResearchDeskError) as exc:
        deliver_result(desk, request_id="req-big", markdown="x" * (MAX_MARKDOWN_BYTES + 1))
    assert exc.value.reason_code == "payload_too_large"
    assert not list(desk.lanebus_dir.glob("*.md"))


def test_delivery_refuses_control_characters_in_the_answer(desk: ResearchDeskConfig) -> None:
    write_request(desk, "req-ctrl")
    with pytest.raises(ResearchDeskError) as exc:
        deliver_result(desk, request_id="req-ctrl", markdown="fine\x00not fine")
    assert exc.value.reason_code == "payload_control_characters"


def test_delivery_with_no_citations_emits_an_empty_list(desk: ResearchDeskConfig) -> None:
    write_request(desk, "req-nocite")
    receipt = deliver_result(desk, request_id="req-nocite", markdown="answer")
    drop = parse_frontmatter_with_diagnostics(receipt.drop_path)
    assert drop.frontmatter["citations"] == []


def test_quotes_in_a_title_do_not_break_the_drop_frontmatter(desk: ResearchDeskConfig) -> None:
    path = write_request(desk, "req-quote")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            'title: "req-quote title"', "title: 'a \"quoted\" title\\'"
        ),
        encoding="utf-8",
    )
    receipt = deliver_result(desk, request_id="req-quote", markdown="answer")
    drop = parse_frontmatter_with_diagnostics(receipt.drop_path)
    assert drop.ok, drop.error_message
    assert '"quoted"' in drop.frontmatter["request_title"]


def test_stamp_refuses_a_row_with_no_status_line(desk: ResearchDeskConfig) -> None:
    path = desk.requests_dir / "no-status.md"
    path.write_text("---\nkind: research_request\n---\nbody\n", encoding="utf-8")
    with pytest.raises(ResearchDeskError) as exc:
        stamp_request_row(
            path, receipt_id="rd-x", delivered_at="now", drop_relpath="a.md", citation_count=0
        )
    assert exc.value.reason_code == "request_malformed"
    assert "status" in exc.value.repair_action


def test_stamp_replaces_rather_than_duplicates_an_existing_delivery_field(
    desk: ResearchDeskConfig,
) -> None:
    path = write_request(desk, "req-restamp", extra="delivered_at: 1999-01-01T00:00:00Z\n")
    stamp_request_row(
        path,
        receipt_id="rd-new",
        delivered_at="2026-09-16T00:00:00Z",
        drop_relpath="drop.md",
        citation_count=2,
    )
    text = path.read_text(encoding="utf-8")
    assert text.count("delivered_at:") == 1
    assert parse_frontmatter_with_diagnostics(text).frontmatter["delivered_at"] == (
        "2026-09-16T00:00:00Z"
    )


def test_render_drop_addresses_the_configured_lane(desk: ResearchDeskConfig) -> None:
    write_request(desk, "req-lane")
    request = get_request(desk, "req-lane")
    body = render_drop(
        request=request,
        lane="theta",
        markdown="answer",
        citations=(),
        model_notes="",
        receipt_id="rd-1",
        delivered_at="2026-09-16T00:00:00Z",
    )
    assert parse_frontmatter_with_diagnostics(body).frontmatter["to"] == "theta"


def test_a_clean_answer_carries_zero_withheld_counts_and_no_banner(
    desk: ResearchDeskConfig,
) -> None:
    write_request(desk, "req-clean")
    receipt = deliver_result(
        desk, request_id="req-clean", markdown="Plain prose with [a source](https://example.org)."
    )
    drop = parse_frontmatter_with_diagnostics(receipt.drop_path)
    assert drop.frontmatter["withheld_images"] == 0
    assert drop.frontmatter["withheld_links"] == 0
    assert "Active content removed:" not in drop.body


# --------------------------------------------------------------------------- #
# Review of #4899 at 608b3612 (2026-10-05): F1, F3-F11, F13, F14, F16
# --------------------------------------------------------------------------- #

INTERVAL_ANSWER = (
    "## Summary\n\nThe CDF is supported on [0, 1).\n\n"
    "## Method\n\nInverse transform sampling.\n\n"
    "## Results\n\nThe fit holds.\n\n"
    "## Sources\n\n- [Primary study](https://example.org/study)\n- Other notes.\n"
)


def test_an_unbalanced_bracket_keeps_the_text_and_the_safe_link_after_it() -> None:
    result = neutralize_markdown("supported on [0, 1) and [src](https://example.org/x) tail")
    assert result.links == 0
    assert "0, 1) and [src](https://example.org/x) tail" in result.markdown


@pytest.mark.parametrize(
    "body",
    [
        "[a [b](javascript:alert(1)) tail",
        "[[a](javascript:alert(1))",
        "[x [y](data:text/html,x)",
        "[ [ [ [ [z](vbscript:x)",
    ],
)
def test_an_unbalanced_label_still_withholds_the_unsafe_link_inside_it(body: str) -> None:
    result = neutralize_markdown(body)
    assert result.links == 1
    for scheme in ("javascript", "data", "vbscript"):
        assert f"]({scheme}:" not in result.markdown


def test_delivery_of_a_half_open_interval_loses_no_answer_text(desk: ResearchDeskConfig) -> None:
    write_request(desk, "req-interval")
    receipt = deliver_result(desk, request_id="req-interval", markdown=INTERVAL_ANSWER)
    drop = parse_frontmatter_with_diagnostics(receipt.drop_path)
    assert drop.frontmatter["withheld_links"] == 0
    for kept in ("0, 1).", "## Method", "## Results", "- Other notes."):
        assert kept in drop.body
    assert "[Primary study](https://example.org/study)" in drop.body


def test_delivery_keeps_the_text_after_a_reference_style_image(desk: ResearchDeskConfig) -> None:
    write_request(desk, "req-refimg")
    receipt = deliver_result(
        desk, request_id="req-refimg", markdown="Revenue tripled![1] The board approved it."
    )
    drop = parse_frontmatter_with_diagnostics(receipt.drop_path)
    assert "The board approved it." in drop.body


def test_delivery_defuses_and_counts_a_javascript_reference_definition(
    desk: ResearchDeskConfig,
) -> None:
    write_request(desk, "req-refdef")
    receipt = deliver_result(
        desk,
        request_id="req-refdef",
        markdown="See [the note][1].\n\n[1]: javascript:alert(document.cookie)\n",
    )
    drop = parse_frontmatter_with_diagnostics(receipt.drop_path)
    assert drop.frontmatter["withheld_links"] == 1
    assert "\n[1]: javascript:" not in drop.body


@pytest.mark.parametrize(
    "title",
    ["Don\x92t Panic", "bad￾x", "line sep", "next\x85line", 'plain "q" \\ ok'],
)
def test_a_citation_title_round_trips_through_the_drop_frontmatter(
    desk: ResearchDeskConfig, title: str
) -> None:
    write_request(desk, "req-yaml")
    receipt = deliver_result(
        desk,
        request_id="req-yaml",
        markdown="answer",
        citations=[{"url": "https://example.org/a", "title": title}],
    )
    drop = parse_frontmatter_with_diagnostics(receipt.drop_path)
    assert drop.ok, drop.error_message
    assert drop.frontmatter["content_trust"] == "untrusted_external"
    assert drop.frontmatter["citations"] == [{"url": "https://example.org/a", "title": title}]


@pytest.mark.parametrize("title", ["Don\x92t Panic", "bad￿x", "para graph"])
def test_a_request_title_round_trips_through_the_drop_frontmatter(
    desk: ResearchDeskConfig, title: str
) -> None:
    request = replace(get_request(desk, write_request(desk, "req-rtitle").stem), title=title)
    drop = render_drop(
        request=request,
        lane="cx-blue",
        markdown="answer",
        citations=(),
        model_notes="",
        receipt_id="rd-rtitle",
        delivered_at="2026-10-05T00:00:00Z",
    )
    parsed = parse_frontmatter_with_diagnostics(drop)
    assert parsed.ok, parsed.error_message
    assert parsed.frontmatter["request_title"] == title


@pytest.mark.parametrize("url", ["https://example.org/a\x9bb", "https://example.org/a\x85b"])
def test_a_citation_url_with_a_c1_control_is_refused(desk: ResearchDeskConfig, url: str) -> None:
    write_request(desk, "req-c1")
    with pytest.raises(ResearchDeskError) as exc:
        deliver_result(desk, request_id="req-c1", markdown="answer", citations=[url])
    assert exc.value.reason_code == "citations_invalid"
    assert not list(desk.lanebus_dir.glob("*.md"))


def test_a_drop_whose_frontmatter_does_not_round_trip_is_never_written(
    desk: ResearchDeskConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_request(desk, "req-render")
    before = path.read_bytes()
    monkeypatch.setattr("shared.research_desk._yaml_scalar", lambda value: value)
    with pytest.raises(ResearchDeskError) as exc:
        deliver_result(
            desk,
            request_id="req-render",
            markdown="answer",
            citations=[{"url": "https://example.org/a", "title": "a: b: c"}],
        )
    assert exc.value.reason_code == "drop_render_invalid"
    assert not list(desk.lanebus_dir.iterdir())
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "body",
    [
        "[" * 16384,
        "![)" * 5462,
        "[" * 8192 + "]" * 8192,
        "![" * 8192,
        "[a](" + "x" * 65536,
        "[a](" + "(y)" + "x" * 65536,
        "<" * 131072,
        "`]" * (MAX_MARKDOWN_BYTES // 2),
        "[a](" * 32768 + ")",
        "](" * 65536 + ")",
        "[<a:]>" * 21845,
    ],
    ids=[
        "open",
        "image-paren",
        "nested",
        "image-open",
        "dest",
        "dest-group",
        "lt",
        "tick-bracket",
        "kept-links",
        "sever",
        "autolinks",
    ],
)
def test_neutralizing_adversarial_markdown_is_linear(body: str) -> None:
    started = time.perf_counter()
    neutralize_markdown(body)
    assert time.perf_counter() - started < 2.0


def test_neutralizing_a_maximal_bracket_flood_is_bounded() -> None:
    started = time.perf_counter()
    result = neutralize_markdown("[" * MAX_MARKDOWN_BYTES)
    assert time.perf_counter() - started < 5.0
    assert result.links == 0


def test_delivery_does_not_hold_the_row_lock_while_neutralizing(
    desk: ResearchDeskConfig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    path = write_request(desk, "req-lockfree")
    original = neutralize_markdown
    entered = threading.Event()
    release = threading.Event()

    def slow(body: str):  # noqa: ANN202 - mirrors the patched function
        entered.set()
        release.wait(10)
        return original(body)

    monkeypatch.setattr("shared.research_desk.neutralize_markdown", slow)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(deliver_result, desk, request_id="req-lockfree", markdown="answer")
        try:
            assert entered.wait(5)
            with projected_path_lock("req-lockfree", (path,), timeout=1.0):
                pass
        finally:
            release.set()
        future.result(timeout=30)


def test_the_drop_is_never_visible_at_its_final_name_while_it_is_written(
    desk: ResearchDeskConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_request(desk, "req-atomic")
    seen: list[list[str]] = []
    real_fsync = os.fsync

    def watching_fsync(fd: int) -> None:
        seen.append(sorted(p.name for p in desk.lanebus_dir.glob("*-perplexity-desk-*.md")))
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", watching_fsync)
    receipt = deliver_result(desk, request_id="req-atomic", markdown="answer")
    assert seen[0] == [], "the drop existed at its final name before its bytes were synced"
    assert receipt.drop_path.is_file()
    assert [p.name for p in desk.lanebus_dir.iterdir()] == [receipt.drop_path.name]


def test_a_failed_drop_write_leaves_no_drop_and_no_temp_file(
    desk: ResearchDeskConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_request(desk, "req-fsync")
    before = path.read_bytes()

    def failing_fsync(fd: int) -> None:
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(os, "fsync", failing_fsync)
    with pytest.raises(OSError, match="simulated fsync failure"):
        deliver_result(desk, request_id="req-fsync", markdown="answer")
    monkeypatch.undo()
    assert not list(desk.lanebus_dir.iterdir())
    assert path.read_bytes() == before
    assert deliver_result(desk, request_id="req-fsync", markdown="answer").drop_path.is_file()


def test_publishing_never_replaces_a_file_that_appears_at_the_drop_name(
    desk: ResearchDeskConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shared.research_desk as research_desk

    path = write_request(desk, "req-clobber")
    before = path.read_bytes()
    racer = desk.lanebus_dir / "20261005T010203Z-perplexity-desk-req-clobber.md"
    real_check = research_desk._check_rendered_drop

    def racing_check(text: str, **kwargs: str) -> None:
        real_check(text, **kwargs)
        racer.write_text("written by another tool\n", encoding="utf-8")

    monkeypatch.setattr(research_desk, "_check_rendered_drop", racing_check)
    with pytest.raises(FileExistsError):
        deliver_result(
            desk,
            request_id="req-clobber",
            markdown="answer",
            now=datetime(2026, 10, 5, 1, 2, 3, tzinfo=UTC),
        )
    assert racer.read_text(encoding="utf-8") == "written by another tool\n"
    assert [p.name for p in desk.lanebus_dir.iterdir()] == [racer.name]
    assert path.read_bytes() == before


def test_the_drop_records_a_digest_of_its_body(desk: ResearchDeskConfig) -> None:
    write_request(desk, "req-digest")
    receipt = deliver_result(desk, request_id="req-digest", markdown="## Finding\n\nThe answer.")
    raw = receipt.drop_path.read_bytes()
    body = raw.split(b"\n---\n", 1)[1]
    drop = parse_frontmatter_with_diagnostics(receipt.drop_path)
    assert drop.frontmatter["body_sha256"] == hashlib.sha256(body).hexdigest()


def test_a_row_the_stamp_cannot_flip_is_refused_before_any_drop_is_written(
    desk: ResearchDeskConfig,
) -> None:
    path = write_request(desk, "req-twostatus", status="queued", extra="status: offered\n")
    before = path.read_bytes()
    with pytest.raises(ResearchDeskError) as exc:
        deliver_result(desk, request_id="req-twostatus", markdown="answer")
    assert exc.value.reason_code == "row_stamp_would_corrupt"
    assert not list(desk.lanebus_dir.iterdir())
    assert path.read_bytes() == before

    write_request(desk, "req-twostatus")
    receipt = deliver_result(desk, request_id="req-twostatus", markdown="answer")
    assert parse_frontmatter_with_diagnostics(path).frontmatter["status"] == "delivered"
    assert receipt.drop_path.is_file()


def test_a_stale_multiline_stamp_field_is_replaced_whole(desk: ResearchDeskConfig) -> None:
    path = write_request(desk, "req-stale", extra="delivery_drop:\n  - old/drop.md\n")
    before = parse_frontmatter_with_diagnostics(path).frontmatter
    receipt = deliver_result(desk, request_id="req-stale", markdown="answer")
    after = parse_frontmatter_with_diagnostics(path).frontmatter
    assert after["created_at"] == before["created_at"]
    assert after["delivery_drop"].endswith(receipt.drop_path.name)


def test_a_stamp_that_would_change_another_field_is_refused_before_any_drop(
    desk: ResearchDeskConfig,
) -> None:
    question = (
        "Which carriers changed their\ndelivered_at: semantics (signature vs doorstep)\nin 2026?"
    )
    path = write_request(desk, "req-wrapped", question=question)
    before = path.read_bytes()
    with pytest.raises(ResearchDeskError) as exc:
        deliver_result(desk, request_id="req-wrapped", markdown="answer")
    assert exc.value.reason_code == "row_stamp_would_corrupt"
    assert not list(desk.lanebus_dir.iterdir())
    assert path.read_bytes() == before


def test_the_stamp_keeps_crlf_line_endings(desk: ResearchDeskConfig) -> None:
    path = write_request(desk, "req-crlf")
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    deliver_result(desk, request_id="req-crlf", markdown="answer")
    raw = path.read_bytes()
    assert raw.count(b"\n") == raw.count(b"\r\n")
    assert parse_frontmatter_with_diagnostics(path).frontmatter["status"] == "delivered"


def test_a_retry_after_delivery_is_told_the_stored_receipt(desk: ResearchDeskConfig) -> None:
    write_request(desk, "req-again")
    receipt = deliver_result(desk, request_id="req-again", markdown="answer")
    with pytest.raises(ResearchDeskError) as exc:
        deliver_result(desk, request_id="req-again", markdown="answer")
    assert exc.value.reason_code == "request_already_delivered"
    assert "without a receipt" not in exc.value.repair_action
    assert receipt.receipt_id in (exc.value.detail or "")


@pytest.mark.parametrize("request_id", ["12345", "2026-09-16", "no", "1.5"])
def test_scalar_shaped_ids_stay_strings_in_the_drop(
    desk: ResearchDeskConfig, request_id: str
) -> None:
    write_request(desk, request_id)
    receipt = deliver_result(desk, request_id=request_id, markdown="answer")
    drop = parse_frontmatter_with_diagnostics(receipt.drop_path)
    assert drop.frontmatter["request_id"] == request_id
    assert drop.frontmatter["thread"] == request_id


def test_a_scalar_shaped_lane_stays_a_string_in_the_drop(desk: ResearchDeskConfig) -> None:
    request = get_request(desk, write_request(desk, "req-lane-no").stem)
    drop = render_drop(
        request=request,
        lane="no",
        markdown="answer",
        citations=(),
        model_notes="",
        receipt_id="rd-no",
        delivered_at="2026-10-05T00:00:00Z",
    )
    assert parse_frontmatter_with_diagnostics(drop).frontmatter["to"] == "no"


def test_another_requests_drop_does_not_block_this_one(desk: ResearchDeskConfig) -> None:
    write_request(desk, "b-perplexity-desk-a2")
    write_request(desk, "a2")
    deliver_result(desk, request_id="b-perplexity-desk-a2", markdown="answer b")
    receipt = deliver_result(desk, request_id="a2", markdown="answer a")
    assert receipt.drop_path.name.endswith("Z-perplexity-desk-a2.md")


def test_concurrent_deliveries_write_exactly_one_drop(
    desk: ResearchDeskConfig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HAPAX_COORD_DIR", str(tmp_path / "coord"))
    write_request(desk, "req-race-deliver")
    real_get_request = get_request

    def slow_get_request(config: ResearchDeskConfig, request_id: str):  # noqa: ANN202
        request = real_get_request(config, request_id)
        time.sleep(0.3)
        return request

    monkeypatch.setattr("shared.research_desk.get_request", slow_get_request)

    def attempt() -> str:
        try:
            deliver_result(desk, request_id="req-race-deliver", markdown="answer")
        except ResearchDeskError as exc:
            return exc.reason_code
        return "ok"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(lambda _: attempt(), range(2)))
    assert outcomes == ["ok", "request_already_delivered"]
    assert len(list(desk.lanebus_dir.glob("*.md"))) == 1


def test_a_stamp_whose_rebuilt_row_fails_to_parse_leaves_the_row_untouched(
    desk: ResearchDeskConfig,
) -> None:
    path = write_request(desk, "req-flow", extra="meta: {a: 1,\ndelivered_at: x}\n")
    before = path.read_bytes()
    with pytest.raises(ResearchDeskError) as exc:
        stamp_request_row(
            path, receipt_id="rd-flow", delivered_at="now", drop_relpath="a.md", citation_count=0
        )
    assert exc.value.reason_code == "row_stamp_would_corrupt"
    assert path.read_bytes() == before
    assert "meta" not in (exc.value.detail or ""), "the refusal must not quote the row"


@pytest.mark.parametrize(
    ("kwargs", "reason_code"),
    [
        ({"model_notes": "x" * (MAX_MODEL_NOTES_BYTES + 1)}, "payload_too_large"),
        ({"citations": ["https:///no-host"]}, "citation_scheme_refused"),
        ({"citations": {"url": "https://example.org"}}, "citations_invalid"),
        ({"citations": [123]}, "citations_invalid"),
        ({"citations": ["https://example.org"] * (MAX_CITATIONS + 1)}, "payload_too_large"),
        ({"markdown": 123}, "payload_invalid"),
    ],
)
def test_delivery_refuses_bad_shapes_before_writing(
    desk: ResearchDeskConfig, kwargs: dict[str, object], reason_code: str
) -> None:
    write_request(desk, "req-shape")
    call: dict[str, object] = {"markdown": "answer", **kwargs}
    with pytest.raises(ResearchDeskError) as exc:
        deliver_result(desk, request_id="req-shape", **call)  # type: ignore[arg-type]
    assert exc.value.reason_code == reason_code
    assert not list(desk.lanebus_dir.iterdir())


def test_a_long_citation_title_is_capped() -> None:
    (citation,) = normalize_citations([{"url": "https://example.org", "title": "t" * 600}])
    assert len(citation["title"]) == MAX_CITATION_TITLE_CHARS


def test_an_offset_timestamp_is_recorded_in_utc(desk: ResearchDeskConfig) -> None:
    write_request(desk, "req-tz")
    moment = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone(timedelta(hours=-7)))
    receipt = deliver_result(desk, request_id="req-tz", markdown="answer", now=moment)
    assert receipt.delivered_at == "2026-09-16T19:00:00Z"
    assert receipt.drop_path.name.startswith("20260916T190000Z-")


def test_a_lane_without_an_inbox_is_refused(desk: ResearchDeskConfig) -> None:
    path = write_request(desk, "req-bleu")
    before = path.read_bytes()
    config = replace(desk, delivery_lane="cx-bleu")
    with pytest.raises(ResearchDeskError) as exc:
        deliver_result(config, request_id="req-bleu", markdown="answer")
    assert exc.value.reason_code == "lanebus_dir_absent"
    assert not config.lanebus_dir.exists()
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "body", ["[a](http://x[y) ok", "[r]: https://e.org![\n", "<https://[x> ok"]
)
def test_a_target_the_url_parser_rejects_is_withheld_not_raised(body: str) -> None:
    result = neutralize_markdown(body)
    assert result.total >= 1


# --------------------------------------------------------------------------- #
# Brackets CommonMark does not count (review of #4899, N2, 2026-10-05)
# --------------------------------------------------------------------------- #

_COMMONMARK = MarkdownIt("commonmark")
#: Render every destination as written: screening it is the desk's job, not the renderer's.
_COMMONMARK.validateLink = lambda url: True
_ACTIVE_SCHEMES = ("javascript:", "data:", "vbscript:", "file:")


class _Rendered(HTMLParser):
    """What a CommonMark reader would load or follow, and the text it would show."""

    def __init__(self, markdown: str) -> None:
        super().__init__(convert_charrefs=True)
        self.live: list[str] = []
        self.text: list[str] = []
        self.feed(_COMMONMARK.render(markdown))
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "img":
            self.live.append("<img>")
        for name, value in attrs:
            target = re.sub(r"[\x00-\x20]", "", value or "").lower()
            if name in {"href", "src"} and target.startswith(_ACTIVE_SCHEMES):
                self.live.append(f"{name}={value}")

    def handle_data(self, data: str) -> None:
        self.text.append(data)

    @property
    def visible(self) -> str:
        return _plain("".join(self.text))


def _plain(text: str) -> str:
    """Text as a reader sees it, set as code or not: marks that only delimit drop out."""
    return " ".join(re.sub(r"[`\\<>]", " ", text).split())


@pytest.mark.parametrize(
    ("body", "label"),
    [
        ("[a `]` b](javascript:alert(1))", "a `]` b"),
        ("[a \\] b](javascript:alert(1))", "a \\] b"),
        ("[a ``]`` b](javascript:alert(1))", "a ``]`` b"),
        ("[a ``x]`y`` b](javascript:alert(1))", "a ``x]`y`` b"),
        ("[a \\[ b](javascript:alert(1))", "a \\[ b"),
        ("[even \\\\](javascript:alert(1))", "even"),
        ("[even \\\\\\\\](javascript:alert(1))", "even"),
        ("[odd \\\\\\] b](javascript:alert(1))", "odd \\\\\\] b"),
        ("[a [b] `]` c](javascript:alert(1))", "a [b] `]` c"),
        ("[a [`]`] c](javascript:alert(1))", "a [`]`] c"),
        ("[a `[` b](javascript:alert(1))", "a `[` b"),
        ("[a <https://e.org/]> b](javascript:alert(1))", "a <https://e.org/]> b"),
        ("![a `]` b](javascript:alert(1))", "a `]` b"),
        ("![a \\] b](javascript:alert(1))", "a \\] b"),
        ("![a ``]`` b](javascript:alert(1))", "a ``]`` b"),
        ("![a \\[ b](javascript:alert(1))", "a \\[ b"),
        ("![even \\\\](javascript:alert(1))", "even"),
        ("![a [b] `]` c](javascript:alert(1))", "a [b] `]` c"),
        ("![a `](x)` b](javascript:alert(1))", "a `](x)` b"),
        ("![a <https://e.org/]> b](javascript:alert(1))", "a <https://e.org/]> b"),
        ("![a `]` b](data:image/png;base64,AAAA)", "a `]` b"),
        ("![a \\] b](https://tracker.example/p.gif)", "a \\] b"),
    ],
)
def test_an_escaped_or_code_span_bracket_cannot_end_a_label_early(body: str, label: str) -> None:
    """CommonMark skips escaped brackets and those in code spans or autolinks.

    So must the pairing, or the label it judges is not the label a reader renders.
    """
    assert _Rendered(body).live, "without the desk this shape renders live"
    page = _Rendered(neutralize_markdown(body).markdown)
    assert page.live == []
    assert _plain(label) in page.visible


@pytest.mark.parametrize(
    "body",
    [
        "[r \\]]: javascript:alert(1)\n\n[r \\]]\n",
        "[r \\\\]: javascript:alert(1)\n\n[r \\\\]\n",
        "[r `x\\]]: javascript:alert(1)\n\n[r `x\\]]\n",
    ],
)
def test_a_reference_definition_label_is_read_with_its_escapes(body: str) -> None:
    """Definitions are found by their ``]:``, not by the pairing; code spans do not bind there."""
    assert _Rendered(body).live, "without the desk this shape renders live"
    assert _Rendered(neutralize_markdown(body).markdown).live == []


@pytest.mark.parametrize(
    "body",
    [
        "[x](javascript\\:alert(1))",
        "[x](<javascript\\:alert(1)>)",
        "[r]: javascript\\:alert(1)\n\n[r]\n",
        "![x](data\\:image/png;base64,AAAA)",
    ],
)
def test_a_backslash_escape_cannot_hide_a_scheme(body: str) -> None:
    """CommonMark unescapes a destination before it is used, so the scheme check must too."""
    assert _Rendered(body).live, "without the desk this shape renders live"
    result = neutralize_markdown(body)
    assert result.total >= 1
    assert _Rendered(result.markdown).live == []


def test_a_demoted_image_after_a_bang_is_not_an_image_again() -> None:
    result = neutralize_markdown("wow!![a](https://tracker.example/p.gif)")
    assert result.images == 1
    page = _Rendered(result.markdown)
    assert page.live == []
    assert "wow!" in page.visible


@pytest.mark.parametrize(
    "body",
    [
        "[a](https://example.org/x [b](javascript:alert(1)))",
        "[a](./x [b](javascript:alert(1)))",
        '[a](https://example.org/x "t" [b](javascript:alert(1)))',
        "[]([](javascript:alert(1))",
    ],
)
def test_text_after_a_kept_destination_is_still_screened(body: str) -> None:
    """A space ends a destination; what follows it is not part of the kept link."""
    assert _Rendered(body).live, "without the desk this shape renders live"
    result = neutralize_markdown(body)
    assert result.links == 1
    assert _Rendered(result.markdown).live == []


@pytest.mark.parametrize(
    "body",
    [
        "[r]\n# ]:\n[r]:vbscript:alert(1)\n",
        "    ]:\n[r]:javascript:alert(1)\n[r]\n",
        "x]:\n> [r]:javascript:alert(1)\n\n[r]\n",
    ],
)
def test_a_definition_is_screened_after_a_stray_definition_marker(body: str) -> None:
    """One ``]:`` must not take the next line's definition as its own destination."""
    assert _Rendered(body).live, "without the desk this shape renders live"
    result = neutralize_markdown(body)
    assert result.links >= 1
    assert _Rendered(result.markdown).live == []


@pytest.mark.parametrize(
    "body",
    [
        "[``[](vbscript:alert(1))``[`",
        "[ ![a ![b](https://t.example/p.gif) c](javascript:alert(1)) `",
    ],
)
def test_a_code_span_a_reader_drops_cannot_carry_live_content(body: str) -> None:
    """markdown-it's backtick cache drops these code spans after an unclosed ``[``.

    The final sweep reads no code spans, so it still breaks the target and the image.
    """
    assert _Rendered(body).live, "without the desk this shape renders live"
    result = neutralize_markdown(body)
    assert result.total >= 1
    assert _Rendered(result.markdown).live == []


def test_a_withheld_marker_cannot_pair_with_a_backtick_before_it() -> None:
    """A literal backtick before a marker can close on the marker's fence and open it."""
    result = neutralize_markdown("`<t:](data:text/html,x)>")
    assert result.links >= 1
    assert _Rendered(result.markdown).live == []


@pytest.mark.parametrize("newline", ["\r\n", "\r"])
def test_a_definition_destination_after_a_carriage_return_is_screened(newline: str) -> None:
    body = newline.join(["[r]:", "javascript:alert(1)", "", "[r]", ""])
    assert _Rendered(body).live, "without the desk this shape renders live"
    result = neutralize_markdown(body)
    assert result.links == 1
    assert _Rendered(result.markdown).live == []
