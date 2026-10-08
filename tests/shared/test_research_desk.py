"""Research-desk queue tests against a temporary vault tree."""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.research_desk import (
    DEFAULT_DELIVERY_LANE,
    DEFAULT_STATE_ROOT,
    DEFAULT_VAULT_ROOT,
    MAX_LIST_LIMIT,
    MAX_REQUEST_BODY_BYTES,
    MalformedRequest,
    ResearchDeskConfig,
    ResearchDeskError,
    get_request,
    list_open_requests,
    neutralize_markdown,
    validate_request_id,
)


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


# --------------------------------------------------------------------------- #

# Content screening: a safe, independently usable domain function.


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


def test_unbalanced_link_label_is_removed_whole() -> None:
    result = neutralize_markdown("before [a [b](javascript:alert(1)) after")
    assert result.links == 1
    assert "](javascript:" not in result.markdown
    assert result.markdown == "before `[link withheld]`) after"


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
