import contextlib
import functools
import http.server
import re
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageStat

playwright_sync_api = pytest.importorskip("playwright.sync_api", reason="playwright not installed")
sync_playwright = playwright_sync_api.sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE_DIR = REPO_ROOT / "docs" / "architecture"
VIEWER_PATH = ARCHITECTURE_DIR / "system-dynamics-map-viewer.html"
REFERENCE_CAPTURE_SPECS = (
    (
        {"width": 1440, "height": 960},
        ARCHITECTURE_DIR / "system-dynamics-map-viewer-desktop.png",
    ),
    (
        {"width": 390, "height": 844},
        ARCHITECTURE_DIR / "system-dynamics-map-viewer-mobile.png",
    ),
)
HIDDEN_SELECTION_MESSAGE = "hidden by the active lens or filters"
HIDDEN_SELECTION_RECOVERY = "Clear filters or choose a lens that includes it"
NONBLANK_CANVAS_SCRIPT = """
() => Array.from(document.querySelectorAll("#cy canvas")).some((canvas) => {
  if (!canvas.width || !canvas.height) {
    return false;
  }

  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) {
    return false;
  }

  try {
    const { data } = context.getImageData(0, 0, canvas.width, canvas.height);
    for (let index = 3; index < data.length; index += 4) {
      if (data[index] !== 0) {
        return true;
      }
    }
  } catch {
    return false;
  }

  return false;
})
"""


class QuietStaticHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


@contextlib.contextmanager
def _static_server() -> Iterator[str]:
    handler = functools.partial(QuietStaticHandler, directory=str(ARCHITECTURE_DIR))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _browser_error_message(page, expression: str) -> str | None:
    return page.evaluate(
        """
        (expression) => {
          try {
            Function(expression)();
            return null;
          } catch (error) {
            return error instanceof Error ? error.message : String(error);
          }
        }
        """,
        expression,
    )


def _assert_no_viewer_selection(page) -> None:
    assert page.evaluate("window.systemDynamicsMapRuntime.currentViewPayload().selected") is None
    assert page.evaluate("window.systemDynamicsMapRuntime.selectedElementCount()") == 0


def _mean_image_delta(left_path: Path, right_path: Path) -> float:
    with Image.open(left_path) as left_image, Image.open(right_path) as right_image:
        left = left_image.convert("RGB")
        right = right_image.convert("RGB")
        assert left.size == right.size
        diff = ImageChops.difference(left, right)
        return float(sum(ImageStat.Stat(diff).mean) / 3)


def test_system_dynamics_viewer_core_interactions():
    with _static_server() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.add_init_script(
            """
            Object.defineProperty(navigator, "clipboard", {
              value: {
                writeText: async (text) => {
                  if (window.__rejectClipboard) {
                    throw new Error("clipboard blocked by test");
                  }
                  window.__clipboardWrites.push(text);
                  window.__copiedViewJson = text;
                }
              },
              configurable: true
            });
            window.__clipboardWrites = [];
            window.__rejectClipboard = false;
            window.__downloadClicks = [];
            HTMLAnchorElement.prototype.click = function () {
              window.__downloadClicks.push({
                download: this.download,
                href: this.href
              });
            };
            """
        )
        try:
            page.goto(f"{base_url}/system-dynamics-map-viewer.html")
            page.locator("#cy canvas").first.wait_for(timeout=10_000)
            page.wait_for_function(
                "window.systemDynamicsMapRuntime && "
                "document.querySelector('#counts').textContent === '35 nodes / 42 edges'"
            )
            page.wait_for_function(NONBLANK_CANVAS_SCRIPT, timeout=10_000)
            assert page.evaluate("window.systemDynamicsMapRuntime.activeLens()") == "topology", (
                "viewer did not load the persisted default topology lens. "
                "Fix by loading system-dynamics-map.lenses.json before initializing filters."
            )
            assert set(page.evaluate("window.systemDynamicsMapRuntime.lensIds()")) == {
                "topology",
                "operating-slice",
                "evidence-risk",
            }, (
                "viewer did not expose all persisted lenses. "
                "Fix by keeping system-dynamics-map.lenses.json wired into renderLensControls()."
            )
            assert page.evaluate("window.systemDynamicsMapRuntime.activeLayout()") == "cose", (
                "viewer did not start on the force-directed overview layout. "
                "Fix by keeping activeLayout initialized to cose."
            )

            assert page.locator("#panel").inner_text().startswith("RDF / OWL Knowledge Graph"), (
                "viewer initial panel is not focused on the semantic backbone. "
                "Fix by rendering seed.default_focus before any user selection."
            )
            assert page.evaluate("window.systemDynamicsMapRuntime.selectedElementCount()") == 0, (
                "viewer initialized with a Cytoscape selection but no selectedElement state. "
                "Fix by rendering the default panel without selecting the default node."
            )
            assert not page.locator("#data-health.active").is_visible(), (
                "served-mode healthy initialization displayed the data-health banner. "
                "Fix by only activating #data-health after seed or supplemental data fallback."
            )
            assert (
                page.get_by_role("link", name="Seed JSON")
                .get_attribute("href")
                .endswith("/system-dynamics-map.seed.json")
            ), (
                "Seed JSON link drifted. Fix by keeping the viewer linked to the canonical seed file."
            )
            assert (
                page.get_by_role("link", name="Claims")
                .get_attribute("href")
                .endswith("/system-dynamics-map.claims.json")
            )
            assert (
                page.get_by_role("link", name="Observations")
                .get_attribute("href")
                .endswith("/system-dynamics-map.observations.jsonl")
            )
            page.locator("details.data-drawer summary").click()
            provenance_text = page.locator("#data-provenance").inner_text().lower()
            assert "map" in provenance_text and "system-dynamics-map-v1" in provenance_text
            assert "version" in provenance_text and "1.0.0" in provenance_text
            assert (
                "authority" in provenance_text and "case-system-dynamics-map-v1" in provenance_text
            )
            assert "nodes" in provenance_text and "35" in provenance_text
            assert "edges" in provenance_text and "42" in provenance_text
            assert "claims" in provenance_text
            assert "observations" in provenance_text
            assert "relations" in provenance_text
            assert "VISIBLE" in page.locator("#lens-summary").inner_text()
            encoding_legend = page.locator("#encoding-legend").inner_text()
            assert "circle structural arrowheads" in encoding_legend
            assert "dashed governance" in encoding_legend
            assert "dotted observational" in encoding_legend
            assert "vee execution arrows" in encoding_legend
            assert "diamond projection arrows" in encoding_legend
            relation_cues = page.evaluate("window.systemDynamicsMapRuntime.relationVisualCues()")
            assert relation_cues["structural"]["target_arrow_shape"] == "circle"
            assert relation_cues["governance"]["line_style"] == "dashed"
            assert relation_cues["observational"]["line_style"] == "dotted"
            assert relation_cues["execution"]["target_arrow_shape"] == "vee"
            assert relation_cues["projection"]["target_arrow_shape"] == "diamond"

            page.get_by_label("Search").fill("telemetry")
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().nodes < 35")
            filtered_counts = page.evaluate("window.systemDynamicsMapRuntime.visibleCounts()")
            assert filtered_counts["nodes"] >= 1, (
                "search filter hid every telemetry match. "
                "Fix by keeping search wired to node labels, summaries, aliases, and contexts."
            )
            assert filtered_counts["edges"] >= 0, (
                "filtered edge count became invalid. "
                "Fix by deriving visible edge counts from non-hidden Cytoscape edges."
            )
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.visibleEdgesHaveVisibleEndpoints()"
            ), (
                "search filter left visible edges attached to hidden nodes. "
                "Fix by recomputing visible edge state from the explicit visible node set."
            )

            page.get_by_label("Search").fill("a")
            result_summary = page.locator("#search-results > p").inner_text()
            result_match = re.search(
                r"(\d+) visible matches\. (\d+) hidden by current view or filters\. "
                r"Showing (\d+) of (\d+) keyboard-selectable matches\.",
                result_summary,
            )
            assert result_match, (
                "search result summary did not expose visible, hidden, shown, and total counts."
            )
            assert int(result_match.group(3)) < int(result_match.group(4)), (
                "broad search summary reported capped result count as the total match count. "
                "Fix by computing headings before slicing rendered search results."
            )
            assert (
                f"{result_match.group(1)} visible matches; "
                f"{result_match.group(2)} hidden by current view or filters"
                in page.locator("#search-live").inner_text()
            )

            page.get_by_label("Search").fill("model")
            result_count = page.locator("#search-results [data-result-id]").count()
            assert result_count > 1
            second_search_result = page.locator("#search-results [data-result-id]").nth(1)
            second_result_id = second_search_result.get_attribute("data-result-id")
            second_result_group = second_search_result.get_attribute("data-result-group")
            page.get_by_label("Search").press("End")
            assert page.get_by_label("Search").get_attribute("aria-activedescendant") == (
                f"search-result-{result_count - 1}"
            )
            page.get_by_label("Search").press("Home")
            assert page.get_by_label("Search").get_attribute("aria-activedescendant") == (
                "search-result-0"
            )
            page.get_by_label("Search").press("ArrowUp")
            assert page.get_by_label("Search").get_attribute("aria-activedescendant") == (
                f"search-result-{result_count - 1}"
            )
            page.get_by_label("Search").press("ArrowDown")
            assert page.get_by_label("Search").get_attribute("aria-activedescendant") == (
                "search-result-0"
            )
            page.get_by_label("Search").press("ArrowDown")
            assert page.get_by_label("Search").get_attribute("aria-activedescendant") == (
                "search-result-1"
            )
            page.get_by_label("Search").press("Enter")
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload().selected"
            ) == {
                "group": second_result_group,
                "id": second_result_id,
            }

            page.get_by_label("Search").fill("advances_to")
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().edges >= 1")
            first_search_result = page.locator("#search-results [data-result-id]").first
            assert "Advances To" in first_search_result.inner_text(), (
                "relation-only search ranked a promoted endpoint before the matching edge. "
                "Fix by ordering direct edge text matches ahead of endpoint promotions."
            )
            page.keyboard.press("Enter")
            assert page.locator("#panel").inner_text().startswith("SDLC Intake -> cc-task Claim"), (
                "relation-only Enter search did not focus the matching edge. "
                "Fix by ranking direct edge text matches before promoted endpoint nodes."
            )
            page.get_by_role("button", name="Copy View JSON").click()
            page.wait_for_function("window.__copiedViewJson")
            copied_payload = page.evaluate("JSON.parse(window.__copiedViewJson)")
            assert copied_payload["search"] == "advances_to"
            assert "sdlc-intake-to-claim" in copied_payload["visible_edge_ids"]
            assert "viewport" in copied_payload
            assert "visible_relation_categories" in copied_payload
            assert (
                "Current view JSON copied to clipboard."
                in page.locator("#action-status").inner_text()
            )
            page.get_by_role("button", name="PNG").click()
            download_click = page.evaluate("window.__downloadClicks.at(-1)")
            assert download_click["download"] == "system-dynamics-current-view.png"
            assert download_click["href"].startswith("data:image/png;base64,")

            page.get_by_label("Search").fill("")
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().nodes === 35")
            page.locator('input[data-filter="relation"][value="governance"]').uncheck()
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().edges < 42")
            page.locator('input[data-filter="relation"][value="governance"]').check()
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().edges === 42")
            page.evaluate(
                """
                document.querySelectorAll('input[data-filter="relation"]').forEach((input) => {
                  if (input.checked) {
                    input.click();
                  }
                });
                """
            )
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().edges === 0")
            assert (
                page.evaluate(
                    "window.systemDynamicsMapRuntime.currentViewPayload().visible_relation_categories"
                )
                == []
            ), (
                "unchecked relation categories exported no active categories but still showed edges. "
                "Fix by treating an empty checked relation set as show none when filter controls exist."
            )
            page.evaluate(
                """
                document.querySelectorAll('input[data-filter="relation"]').forEach((input) => {
                  if (!input.checked) {
                    input.click();
                  }
                });
                """
            )
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().edges === 42")
            page.get_by_label("Search").fill("zzzznomatchq")
            assert (
                "No visible or hidden elements match"
                in page.locator("#search-results").inner_text()
            )
            page.locator("#cy").focus()
            page.keyboard.press("ArrowDown")
            assert (
                "No visible graph elements to select. Clear search or reset filters to recover."
                in page.locator("#action-status").inner_text()
            )
            page.locator("#cy").focus()
            page.keyboard.press("/")
            assert page.evaluate("document.activeElement.id") == "search"
            page.locator("#cy").focus()
            page.keyboard.press("Escape")
            assert page.get_by_label("Search").input_value() == ""
            assert page.locator("#panel").inner_text().startswith("RDF / OWL Knowledge Graph")
            page.get_by_label("Search").fill("zzzznomatchq")
            page.get_by_role("button", name="Reset to Topology").click()
            page.wait_for_function("window.systemDynamicsMapRuntime.activeLens() === 'topology'")
            assert page.get_by_label("Search").input_value() == ""
            assert "Reset to Topology." in page.locator("#action-status").inner_text()
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().edges === 42")
            page.locator('input[data-filter="status"][value="candidate"]').uncheck()
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().nodes < 35")
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.visibleEdgesHaveVisibleEndpoints()"
            ), (
                "status filter left visible edges attached to hidden nodes. "
                "Fix by recomputing visible edge state after checkbox changes."
            )

            page.locator('input[data-filter="status"][value="candidate"]').check()
            page.get_by_label("View").select_option("operating-slice")
            page.wait_for_function(
                "window.systemDynamicsMapRuntime.activeLens() === 'operating-slice'"
            )
            operating_counts = page.evaluate("window.systemDynamicsMapRuntime.visibleCounts()")
            assert operating_counts == {"nodes": 8, "edges": 7}, (
                "operating-slice lens did not apply its persisted projection. "
                "Fix by honoring visible_node_ids and visible_edge_ids in applyFilters()."
            )
            lens_summary = page.locator("#lens-summary").inner_text()
            lens_summary_lower = lens_summary.lower()
            assert "focus on current operating state" in lens_summary_lower
            assert "trust basis" in lens_summary_lower
            assert "projection" in lens_summary_lower
            assert "8 nodes / 7 edges" in lens_summary
            assert "27 nodes / 35 edges" in lens_summary
            assert "observed" in lens_summary
            assert "false" in lens_summary and "true" in lens_summary
            assert (
                "Operating Slice / 5 in-scope observations / 0 stale in scope / 1 global stale"
                in page.evaluate("window.systemDynamicsMapRuntime.stateSummary()")
            ), (
                "viewer reported hidden stale evidence as in-scope for the operating slice. "
                "Fix by scoping freshness counts to currently visible node IDs."
            )
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.visibleEdgesHaveVisibleEndpoints()"
            )
            assert (
                page.evaluate("window.systemDynamicsMapRuntime.observationsFor('cc-task-claim')")[
                    0
                ]["state"]
                == "claimed"
            ), (
                "viewer did not load temporal observations for the SDLC claim node. "
                "Fix by loading system-dynamics-map.observations.jsonl."
            )
            page.evaluate("window.systemDynamicsMapRuntime.selectNode('cc-task-claim')")
            panel_text = page.locator("#panel").inner_text()
            assert "STATE" in panel_text and "claimed" in panel_text
            assert "CLAIMS" in panel_text and "declares_node" in panel_text
            page.locator("details.evidence-row", has_text="claimed").locator("summary").click()
            page.locator("details.evidence-row", has_text="declares_node").locator(
                "summary"
            ).click()
            panel_text = page.locator("#panel").inner_text()
            assert "SOURCE" in panel_text and "scripts/cc-claim" in panel_text
            assert "AUTHORITY" in panel_text and "architecture_contract" in panel_text

            page.get_by_label("Search").fill("cc-task claim")
            page.wait_for_function(
                "window.systemDynamicsMapRuntime.currentViewPayload().visible_node_ids.includes('cc-task-claim')"
            )
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload().selected"
            ) == {
                "group": "nodes",
                "id": "cc-task-claim",
            }
            assert page.evaluate("window.systemDynamicsMapRuntime.selectedElementCount()") == 1, (
                "visible selection was not reselected after a filter kept it in scope. "
                "Fix by reselecting visible selectedElement during reconciliation."
            )
            page.get_by_label("Search").fill("")
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().nodes === 8")
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload().selected"
            ) == {
                "group": "nodes",
                "id": "cc-task-claim",
            }
            assert page.evaluate("window.systemDynamicsMapRuntime.selectedElementCount()") == 1

            page.evaluate("window.systemDynamicsMapRuntime.selectEdge('sdlc-intake-to-claim')")
            edge_panel_text = page.locator("#panel").inner_text()
            assert "Advances To" in edge_panel_text and "governance" in edge_panel_text
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.relationFor('advances_to').category"
            ) == ("governance")
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload().selected"
            ) == {
                "group": "edges",
                "id": "sdlc-intake-to-claim",
            }
            assert page.evaluate("window.systemDynamicsMapRuntime.selectedElementCount()") == 1
            page.keyboard.press("Escape")
            assert (
                page.evaluate("window.systemDynamicsMapRuntime.currentViewPayload().selected")
                is None
            ), (
                "Escape reset left stale selected edge state in current-view export. "
                "Fix by clearing selectedElement and Cytoscape selection when resetting the panel."
            )
            assert page.evaluate("window.systemDynamicsMapRuntime.selectedElementCount()") == 0, (
                "Escape reset left a stale Cytoscape element selected. "
                "Fix by calling cy.elements().unselect() when clearing viewer selection."
            )
            assert page.locator("#panel").inner_text().startswith("RDF / OWL Knowledge Graph")
            page.evaluate("window.systemDynamicsMapRuntime.selectEdge('sdlc-intake-to-claim')")
            assert page.evaluate("window.systemDynamicsMapRuntime.selectedElementCount()") == 1
            page.get_by_label("Search").fill("advances_to")
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().edges >= 1")
            page.get_by_label("Search").press("Escape")
            focused_escape_payload = page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload()"
            )
            assert focused_escape_payload["search"] == "", (
                "focused-control Escape did not clear the active search. "
                "Fix by handling Escape before returning from input/select/button key targets."
            )
            assert focused_escape_payload["selected"] is None, (
                "focused-control Escape left stale selected edge state in current-view export. "
                "Fix by handling Escape before the focused-control keyboard shortcut guard."
            )
            assert page.evaluate("window.systemDynamicsMapRuntime.selectedElementCount()") == 0, (
                "focused-control Escape left a stale Cytoscape element selected. "
                "Fix by routing focused-control Escape through clearSelection()."
            )
            assert page.locator("#panel").inner_text().startswith("RDF / OWL Knowledge Graph")

            page.evaluate("window.systemDynamicsMapRuntime.selectEdge('sdlc-intake-to-claim')")
            assert page.evaluate("window.systemDynamicsMapRuntime.selectedElementCount()") == 1
            page.get_by_label("View").focus()
            page.get_by_label("View").press("Escape")
            select_escape_payload = page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload()"
            )
            assert select_escape_payload["selected"] is None, (
                "focused-select Escape left stale selected edge state in current-view export. "
                "Fix by handling Escape before the focused-control keyboard shortcut guard."
            )
            assert page.evaluate("window.systemDynamicsMapRuntime.selectedElementCount()") == 0, (
                "focused-select Escape left a stale Cytoscape element selected. "
                "Fix by routing focused select Escape through clearSelection()."
            )

            page.get_by_label("View").select_option("topology")
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().nodes === 35")
            page.evaluate("window.systemDynamicsMapRuntime.selectNode('dmn')")
            assert page.evaluate("window.systemDynamicsMapRuntime.selectedElementCount()") == 1
            assert page.locator("#panel").inner_text().startswith("DMN")
            page.get_by_label("View").select_option("operating-slice")
            page.wait_for_function(
                "window.systemDynamicsMapRuntime.activeLens() === 'operating-slice'"
            )
            lens_payload = page.evaluate("window.systemDynamicsMapRuntime.currentViewPayload()")
            assert lens_payload["selected"] is None, (
                "lens transition exported a selected node that the active lens hides. "
                "Fix by reconciling selectedElement after lens/filter visibility changes."
            )
            assert "dmn" not in lens_payload["visible_node_ids"]
            assert page.locator("#panel").inner_text().startswith("RDF / OWL Knowledge Graph")
            assert page.evaluate("window.systemDynamicsMapRuntime.selectedElementCount()") == 0
            assert (
                "DMN hidden by the active view or filters"
                in page.locator("#action-status").inner_text()
            )
            page.get_by_role("button", name="Dismiss").click()
            assert page.locator("#action-status").inner_text() == ""
            error_message = _browser_error_message(
                page, "window.systemDynamicsMapRuntime.selectNode('dmn')"
            )
            assert HIDDEN_SELECTION_MESSAGE in error_message
            assert HIDDEN_SELECTION_RECOVERY in error_message
            page.get_by_label("Search").fill("dmn")
            hidden_result = page.locator(
                '#search-results [data-hidden="true"][data-result-id="dmn"]'
            )
            assert "DMN" in hidden_result.inner_text()
            hidden_result.click()
            page.wait_for_function("window.systemDynamicsMapRuntime.activeLens() === 'topology'")
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload().selected"
            ) == {
                "group": "nodes",
                "id": "dmn",
            }
            assert "DMN revealed in Topology." in page.locator("#action-status").inner_text()
            page.keyboard.press("Escape")
            _assert_no_viewer_selection(page)

            page.get_by_label("View").select_option("topology")
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().nodes === 35")
            _assert_no_viewer_selection(page)
            page.evaluate("window.systemDynamicsMapRuntime.selectEdge('dmn-to-sbvr')")
            assert page.evaluate("window.systemDynamicsMapRuntime.selectedElementCount()") == 1
            page.get_by_label("View").select_option("operating-slice")
            page.wait_for_function(
                "window.systemDynamicsMapRuntime.activeLens() === 'operating-slice'"
            )
            lens_edge_payload = page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload()"
            )
            assert lens_edge_payload["selected"] is None, (
                "lens transition exported a selected edge that the active lens hides. "
                "Fix by reconciling selectedElement for edges after lens visibility changes."
            )
            assert "dmn-to-sbvr" not in lens_edge_payload["visible_edge_ids"]
            assert page.evaluate("window.systemDynamicsMapRuntime.selectedElementCount()") == 0
            assert (
                "DMN -> SBVR hidden by the active view or filters"
                in page.locator("#action-status").inner_text()
            )
            page.get_by_role("button", name="Show in Topology").click()
            page.wait_for_function("window.systemDynamicsMapRuntime.activeLens() === 'topology'")
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload().selected"
            ) == {
                "group": "edges",
                "id": "dmn-to-sbvr",
            }
            assert (
                "DMN -> SBVR revealed in Topology." in page.locator("#action-status").inner_text()
            )
            page.get_by_label("View").select_option("operating-slice")
            page.wait_for_function(
                "window.systemDynamicsMapRuntime.activeLens() === 'operating-slice'"
            )
            error_message = _browser_error_message(
                page, "window.systemDynamicsMapRuntime.selectEdge('dmn-to-sbvr')"
            )
            assert HIDDEN_SELECTION_MESSAGE in error_message
            assert HIDDEN_SELECTION_RECOVERY in error_message

            page.get_by_label("View").select_option("topology")
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().nodes === 35")
            _assert_no_viewer_selection(page)
            traversal_items = page.evaluate("window.systemDynamicsMapRuntime.traversalItems()")
            assert len(traversal_items) > 2

            page.locator("#cy").focus()
            page.keyboard.press("Home")
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload().selected"
            ) == {
                "group": traversal_items[0]["group"],
                "id": traversal_items[0]["id"],
            }
            page.keyboard.press("End")
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload().selected"
            ) == {
                "group": traversal_items[-1]["group"],
                "id": traversal_items[-1]["id"],
            }
            page.keyboard.press("ArrowLeft")
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload().selected"
            ) == {
                "group": traversal_items[-2]["group"],
                "id": traversal_items[-2]["id"],
            }
            page.keyboard.press("ArrowRight")
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload().selected"
            ) == {
                "group": traversal_items[-1]["group"],
                "id": traversal_items[-1]["id"],
            }
            page.keyboard.press("Enter")
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload().selected"
            ) == {
                "group": traversal_items[-1]["group"],
                "id": traversal_items[-1]["id"],
            }
            page.keyboard.press("Space")
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload().selected"
            ) == {
                "group": traversal_items[-1]["group"],
                "id": traversal_items[-1]["id"],
            }
            assert page.evaluate("window.systemDynamicsMapRuntime.selectedElementCount()") == 1
            page.keyboard.press("Escape")
            _assert_no_viewer_selection(page)
            page.locator("#cy").focus()
            page.keyboard.press("/")
            assert page.evaluate("document.activeElement.id") == "search"
            page.get_by_role("button", name="Directed").click()
            page.wait_for_function(
                "window.systemDynamicsMapRuntime.activeLayout() === 'breadthfirst'"
            )
            assert (
                page.evaluate("window.systemDynamicsMapRuntime.directedLayoutRootId()")
                == "rdf-owl-kg"
            ), (
                "Directed layout is not rooted at the source-neutral default focus. "
                "Fix by passing cy.$id(seed.default_focus) as the breadthfirst roots option."
            )
            page.wait_for_function(NONBLANK_CANVAS_SCRIPT, timeout=10_000)
            assert "active" in page.get_by_role("button", name="Directed").get_attribute("class"), (
                "Directed layout button did not enter active state. "
                "Fix by syncing data-layout button state in runLayout()."
            )
            assert (
                page.get_by_role("button", name="Directed").get_attribute("aria-pressed") == "true"
            )
            page.get_by_role("button", name="Circle").click()
            page.wait_for_function("window.systemDynamicsMapRuntime.activeLayout() === 'circle'")
            page.wait_for_function(NONBLANK_CANVAS_SCRIPT, timeout=10_000)
            assert "active" in page.get_by_role("button", name="Circle").get_attribute("class"), (
                "Circle layout button did not enter active state. "
                "Fix by syncing data-layout button state in runLayout()."
            )
            page.get_by_role("button", name="Grid").click()
            page.wait_for_function("window.systemDynamicsMapRuntime.activeLayout() === 'grid'")
            page.wait_for_function(NONBLANK_CANVAS_SCRIPT, timeout=10_000)
            assert "active" in page.get_by_role("button", name="Grid").get_attribute("class"), (
                "Grid layout button did not enter active state. "
                "Fix by syncing data-layout button state in runLayout()."
            )

            selected = page.evaluate("window.systemDynamicsMapRuntime.selectNode('opentelemetry')")
            assert selected["id"] == "opentelemetry", (
                "runtime node selection returned the wrong node. "
                "Fix by selecting nodes by exact nodes[].id."
            )
            assert page.evaluate("window.systemDynamicsMapRuntime.selectedElementCount()") == 1
            assert page.locator("#panel").inner_text().startswith("OpenTelemetry"), (
                "details panel did not update after node selection. "
                "Fix by rendering node data in selectNode()."
            )
            page.get_by_label("Search").fill("scripts/cc-claim")
            page.wait_for_function(
                "!window.systemDynamicsMapRuntime.currentViewPayload().visible_node_ids.includes('opentelemetry')"
            )
            search_payload = page.evaluate("window.systemDynamicsMapRuntime.currentViewPayload()")
            assert search_payload["selected"] is None, (
                "search filter exported a selected node after hiding it. "
                "Fix by reconciling selectedElement after search-driven visibility changes."
            )
            assert "opentelemetry" not in search_payload["visible_node_ids"]
            assert page.locator("#panel").inner_text().startswith("RDF / OWL Knowledge Graph")
            error_message = _browser_error_message(
                page, "window.systemDynamicsMapRuntime.selectNode('opentelemetry')"
            )
            assert HIDDEN_SELECTION_MESSAGE in error_message
            assert HIDDEN_SELECTION_RECOVERY in error_message
            page.get_by_label("Search").fill("")
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().nodes === 35")
            _assert_no_viewer_selection(page)

            page.evaluate("window.systemDynamicsMapRuntime.selectNode('opentelemetry')")
            assert page.evaluate("window.systemDynamicsMapRuntime.selectedElementCount()") == 1
            resolution = page.locator("#resolution")
            resolution.focus()
            resolution.press("ArrowLeft")
            resolution.press("ArrowLeft")
            assert resolution.input_value() == "3"
            page.wait_for_function(
                "!window.systemDynamicsMapRuntime.currentViewPayload().visible_node_ids.includes('opentelemetry')"
            )
            resolution_payload = page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload()"
            )
            assert resolution_payload["selected"] is None, (
                "resolution filter exported a selected node after hiding it. "
                "Fix by reconciling selectedElement after resolution changes."
            )
            assert "opentelemetry" not in resolution_payload["visible_node_ids"]
            error_message = _browser_error_message(
                page, "window.systemDynamicsMapRuntime.selectNode('opentelemetry')"
            )
            assert HIDDEN_SELECTION_MESSAGE in error_message
            assert HIDDEN_SELECTION_RECOVERY in error_message
            resolution.press("ArrowRight")
            resolution.press("ArrowRight")
            assert resolution.input_value() == "5"
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().nodes === 35")
            _assert_no_viewer_selection(page)

            page.evaluate("window.systemDynamicsMapRuntime.selectNode('opentelemetry')")
            assert page.evaluate("window.systemDynamicsMapRuntime.selectedElementCount()") == 1
            page.locator('input[data-filter="layer"][value="observation-state"]').uncheck()
            page.wait_for_function(
                "!window.systemDynamicsMapRuntime.currentViewPayload().visible_node_ids.includes('opentelemetry')"
            )
            layer_payload = page.evaluate("window.systemDynamicsMapRuntime.currentViewPayload()")
            assert layer_payload["selected"] is None, (
                "layer filter exported a selected node after hiding it. "
                "Fix by reconciling selectedElement after layer checkbox changes."
            )
            assert "opentelemetry" not in layer_payload["visible_node_ids"]
            error_message = _browser_error_message(
                page, "window.systemDynamicsMapRuntime.selectNode('opentelemetry')"
            )
            assert HIDDEN_SELECTION_MESSAGE in error_message
            assert HIDDEN_SELECTION_RECOVERY in error_message
            page.locator('input[data-filter="layer"][value="observation-state"]').check()
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().nodes === 35")
            _assert_no_viewer_selection(page)

            page.evaluate("window.systemDynamicsMapRuntime.selectNode('sbvr')")
            assert page.evaluate("window.systemDynamicsMapRuntime.selectedElementCount()") == 1
            assert page.locator("#panel").inner_text().startswith("SBVR")
            page.locator('input[data-filter="status"][value="candidate"]').uncheck()
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().nodes < 35")
            status_payload = page.evaluate("window.systemDynamicsMapRuntime.currentViewPayload()")
            assert status_payload["selected"] is None, (
                "status filter exported a selected candidate node after hiding candidates. "
                "Fix by clearing hidden selectedElement state after filter changes."
            )
            assert "sbvr" not in status_payload["visible_node_ids"]
            assert page.locator("#panel").inner_text().startswith("RDF / OWL Knowledge Graph")
            error_message = _browser_error_message(
                page, "window.systemDynamicsMapRuntime.selectNode('sbvr')"
            )
            assert HIDDEN_SELECTION_MESSAGE in error_message
            assert HIDDEN_SELECTION_RECOVERY in error_message
            page.locator('input[data-filter="status"][value="candidate"]').check()
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().nodes === 35")
            _assert_no_viewer_selection(page)

            page.evaluate("window.systemDynamicsMapRuntime.selectEdge('dmn-to-sbvr')")
            assert page.evaluate("window.systemDynamicsMapRuntime.selectedElementCount()") == 1
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload().selected"
            ) == {
                "group": "edges",
                "id": "dmn-to-sbvr",
            }
            page.locator('input[data-filter="status"][value="candidate"]').uncheck()
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().nodes < 35")
            hidden_edge_payload = page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload()"
            )
            assert hidden_edge_payload["selected"] is None, (
                "status filter exported a selected edge after hiding it. "
                "Fix by reconciling selectedElement for hidden edges as well as nodes."
            )
            assert "dmn-to-sbvr" not in hidden_edge_payload["visible_edge_ids"]
            error_message = _browser_error_message(
                page, "window.systemDynamicsMapRuntime.selectEdge('dmn-to-sbvr')"
            )
            assert HIDDEN_SELECTION_MESSAGE in error_message
            assert HIDDEN_SELECTION_RECOVERY in error_message
            page.locator('input[data-filter="status"][value="candidate"]').check()
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().nodes === 35")
            _assert_no_viewer_selection(page)

            page.get_by_label("Search").fill("scripts/cc-claim")
            page.get_by_label("Search").press("Enter")
            page.wait_for_function(
                "document.querySelector('#panel').innerText.startsWith('cc-task Claim')"
            )
            assert (
                page.locator("#search-results")
                .get_by_role("button", name=re.compile("cc-task Claim"))
                .is_visible()
            )

            payload = page.evaluate("window.systemDynamicsMapRuntime.currentViewPayload()")
            assert payload["schema"] == "system-dynamics-map-current-view-v1"
            assert payload["lens"] == "topology"
            assert payload["visible_node_ids"], (
                "current view export did not include visible nodes. "
                "Fix by deriving export payload from the active Cytoscape visibility state."
            )

            error_message = _browser_error_message(
                page, "window.systemDynamicsMapRuntime.selectNode('missing-node')"
            )
            assert error_message is not None and "nodes[].id" in error_message
        finally:
            browser.close()


def test_system_dynamics_viewer_toolbar_and_panel_actions_are_operable():
    with _static_server() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.add_init_script(
            """
            Object.defineProperty(navigator, "clipboard", {
              value: {
                writeText: async (text) => {
                  if (window.__rejectClipboard) {
                    throw new Error("clipboard blocked by test");
                  }
                  window.__clipboardWrites.push(text);
                }
              },
              configurable: true
            });
            window.__clipboardWrites = [];
            window.__rejectClipboard = false;
            window.__downloadClicks = [];
            HTMLAnchorElement.prototype.click = function () {
              window.__downloadClicks.push({
                download: this.download,
                href: this.href
              });
            };
            """
        )
        try:
            page.goto(f"{base_url}/system-dynamics-map-viewer.html")
            page.locator("#cy canvas").first.wait_for(timeout=10_000)
            page.wait_for_function("window.systemDynamicsMapRuntime")
            page.wait_for_function(NONBLANK_CANVAS_SCRIPT, timeout=10_000)

            page.evaluate("window.systemDynamicsMapRuntime.selectNode('opentelemetry')")
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload().selected"
            ) == {
                "group": "nodes",
                "id": "opentelemetry",
            }
            page.locator('#panel [data-panel-action="copy-id"]').click()
            page.wait_for_function("window.__clipboardWrites.at(-1) === 'opentelemetry'")
            assert "Element ID copied." in page.locator("#action-status").inner_text()

            page.evaluate("window.__rejectClipboard = true")
            page.locator('#panel [data-panel-action="copy-id"]').click()
            assert "Element ID: opentelemetry" in page.locator("#action-status").inner_text()
            page.evaluate("window.__rejectClipboard = false")

            page.locator('#panel [data-panel-action="neighborhood"]').click()
            assert (
                "OpenTelemetry neighborhood framed." in page.locator("#action-status").inner_text()
            )
            page.locator("#zoom-out").click()
            page.locator("#zoom-out").click()
            panel_fit_zoom_before = page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload().viewport.zoom"
            )
            page.locator('#panel [data-panel-action="fit-selected"]').click()
            page.wait_for_function(
                "(zoomBefore) => "
                "window.systemDynamicsMapRuntime.currentViewPayload().viewport.zoom "
                "> zoomBefore",
                arg=panel_fit_zoom_before,
            )
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload().selected"
            ) == {
                "group": "nodes",
                "id": "opentelemetry",
            }
            page.locator("#zoom-out").click()
            toolbar_fit_zoom_before = page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload().viewport.zoom"
            )
            page.locator("#fit-selected").click()
            page.wait_for_function(
                "(zoomBefore) => "
                "window.systemDynamicsMapRuntime.currentViewPayload().viewport.zoom "
                "> zoomBefore",
                arg=toolbar_fit_zoom_before,
            )
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload().selected"
            ) == {
                "group": "nodes",
                "id": "opentelemetry",
            }

            zoom_before = page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload().viewport.zoom"
            )
            page.locator("#zoom-in").click()
            page.wait_for_function(
                "(zoomBefore) => "
                "window.systemDynamicsMapRuntime.currentViewPayload().viewport.zoom "
                "> zoomBefore",
                arg=zoom_before,
            )
            zoom_after_in = page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload().viewport.zoom"
            )
            page.locator("#zoom-out").click()
            page.wait_for_function(
                "(zoomAfterIn) => "
                "window.systemDynamicsMapRuntime.currentViewPayload().viewport.zoom "
                "< zoomAfterIn",
                arg=zoom_after_in,
            )
            page.locator("#zoom-reset").click()
            assert isinstance(
                page.evaluate("window.systemDynamicsMapRuntime.currentViewPayload().viewport.zoom"),
                (int, float),
            )

            assert (
                page.evaluate(
                    "window.systemDynamicsMapRuntime.currentViewPayload().edge_labels_visible"
                )
                is False
            )
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.edgeLabelState('dmn-to-sbvr')"
            ) == {
                "hasShowLabel": False,
                "label": "",
            }
            page.locator("#edge-labels").click()
            assert page.locator("#edge-labels").get_attribute("aria-pressed") == "true"
            assert (
                page.evaluate(
                    "window.systemDynamicsMapRuntime.currentViewPayload().edge_labels_visible"
                )
                is True
            )
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.edgeLabelState('dmn-to-sbvr')"
            ) == {
                "hasShowLabel": True,
                "label": "Adjacent Vocabulary",
            }
            assert "Edge labels shown." in page.locator("#action-status").inner_text()

            page.evaluate("window.systemDynamicsMapRuntime.selectEdge('dmn-to-sbvr')")
            page.locator('#panel [data-panel-action="source"]').click()
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload().selected"
            ) == {
                "group": "nodes",
                "id": "dmn",
            }
            page.evaluate("window.systemDynamicsMapRuntime.selectEdge('dmn-to-sbvr')")
            page.locator('#panel [data-panel-action="target"]').click()
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.currentViewPayload().selected"
            ) == {
                "group": "nodes",
                "id": "sbvr",
            }

            page.evaluate("window.__rejectClipboard = true")
            page.get_by_role("button", name="Copy View JSON").click()
            page.wait_for_function(
                "window.__downloadClicks.some((item) => "
                "item.download === 'system-dynamics-current-view.json')"
            )
            assert (
                "Clipboard unavailable; current view JSON downloaded."
                in page.locator("#action-status").inner_text()
            )
        finally:
            browser.close()


def test_system_dynamics_viewer_reference_captures_match_current_served_render(tmp_path):
    with _static_server() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for viewport, reference_path in REFERENCE_CAPTURE_SPECS:
                page = browser.new_page(viewport=viewport)
                try:
                    page.goto(f"{base_url}/system-dynamics-map-viewer.html")
                    page.locator("#cy canvas").first.wait_for(timeout=10_000)
                    page.wait_for_function("window.systemDynamicsMapRuntime")
                    page.wait_for_function(NONBLANK_CANVAS_SCRIPT, timeout=10_000)
                    page.wait_for_timeout(500)
                    current_path = tmp_path / reference_path.name
                    page.screenshot(path=str(current_path), full_page=False)
                finally:
                    page.close()

                mean_delta = _mean_image_delta(reference_path, current_path)
                assert mean_delta < 12.0, (
                    f"{reference_path}: committed capture drifted from the current served viewer "
                    f"(mean pixel delta {mean_delta:.2f}). Regenerate the reference PNG at "
                    f"{viewport['width']}x{viewport['height']}."
                )
        finally:
            browser.close()


def test_system_dynamics_viewer_direct_file_mode_preserves_supplemental_data():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        try:
            page.goto(VIEWER_PATH.as_uri())
            page.locator("#cy canvas").first.wait_for(timeout=10_000)
            page.wait_for_function(
                "window.systemDynamicsMapRuntime && "
                "document.querySelector('#counts').textContent === '35 nodes / 42 edges'"
            )
            assert set(page.evaluate("window.systemDynamicsMapRuntime.lensIds()")) == {
                "topology",
                "operating-slice",
                "evidence-risk",
            }, (
                "direct file-open mode dropped persisted lenses. "
                "Fix by embedding supplemental lens data in the static viewer."
            )
            assert (
                page.evaluate("window.systemDynamicsMapRuntime.observationsFor('cc-task-claim')")[
                    0
                ]["state"]
                == "claimed"
            ), (
                "direct file-open mode dropped temporal observations. "
                "Fix by embedding observations-data in the static viewer."
            )
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.relationFor('advances_to').label"
            ) == ("Advances To"), (
                "direct file-open mode dropped relation vocabulary. "
                "Fix by embedding relations-data in the static viewer."
            )
            page.get_by_label("Search").fill("advances_to")
            page.locator("#search-results").get_by_role(
                "button", name=re.compile("Advances To")
            ).click()
            assert page.locator("#panel").inner_text().startswith("SDLC Intake -> cc-task Claim")
            payload = page.evaluate("window.systemDynamicsMapRuntime.currentViewPayload()")
            assert payload["search"] == "advances_to"
            assert "sdlc-intake-to-claim" in payload["visible_edge_ids"]
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.pngDataUri().startsWith('data:image/png;base64,')"
            )
            assert not page.locator("#data-health.active").is_visible()
        finally:
            browser.close()


def test_system_dynamics_viewer_reports_served_seed_fallback():
    with _static_server() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        seed_fallback_urls = []

        def route_seed_fallback(route):
            seed_fallback_urls.append(route.request.url)
            route.fulfill(status=404, body="missing seed")

        page.route("**/system-dynamics-map.seed.json", route_seed_fallback)
        try:
            page.goto(f"{base_url}/system-dynamics-map-viewer.html")
            page.locator("#cy canvas").first.wait_for(timeout=10_000)
            page.wait_for_function("window.systemDynamicsMapRuntime")
            assert len(seed_fallback_urls) == 1
            assert seed_fallback_urls[0].endswith("/system-dynamics-map.seed.json")
            assert (
                page.evaluate("window.systemDynamicsMapRuntime.currentViewPayload().map_id")
                == "system-dynamics-map-v1"
            )
            assert page.locator("#data-health.active").is_visible(), (
                "served-mode seed fallback did not surface visible recovery guidance. "
                "Fix by reporting seed fallback through the same data-health banner as companion data."
            )
            assert (
                "Seed data loaded from embedded fallback"
                in page.locator("#data-health").inner_text()
            )
            assert (
                "Restore system-dynamics-map.seed.json or rerun "
                "scripts/system_dynamics_map_materialize.py"
                in page.locator("#data-health").inner_text()
            )
            assert "could not be loaded" not in page.locator("#data-health").inner_text()
        finally:
            browser.close()


def test_system_dynamics_viewer_mobile_layout_remains_operable():
    with _static_server() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        try:
            page.goto(f"{base_url}/system-dynamics-map-viewer.html")
            page.locator("#cy canvas").first.wait_for(timeout=10_000)
            page.wait_for_function("window.systemDynamicsMapRuntime")
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert page.get_by_role("searchbox", name="Search").is_visible()
            assert page.locator("#cy").is_visible()
            mobile_layout = page.evaluate(
                """
                () => {
                  const styleFor = (selector) => getComputedStyle(document.querySelector(selector));
                  const app = styleFor(".app");
                  const controls = styleFor(".controls");
                  const details = styleFor(".details");
                  const workspace = document.querySelector(".workspace");
                  const graph = styleFor("#cy");
                  return {
                    appDisplay: app.display,
                    appOverflowY: app.overflowY,
                    controlsMaxHeight: controls.maxHeight,
                    controlsOverflowY: controls.overflowY,
                    controlsWidth: Math.round(document.querySelector(".controls").getBoundingClientRect().width),
                    detailsMaxHeight: details.maxHeight,
                    detailsOverflowY: details.overflowY,
                    detailsWidth: Math.round(document.querySelector(".details").getBoundingClientRect().width),
                    graphMinHeight: graph.minHeight,
                    viewportWidth: window.innerWidth,
                    workspaceHeight: Math.round(workspace.getBoundingClientRect().height)
                  };
                }
                """
            )
            assert mobile_layout["appDisplay"] == "block"
            assert mobile_layout["appOverflowY"] == "visible"
            assert mobile_layout["controlsMaxHeight"] == "none"
            assert mobile_layout["controlsOverflowY"] == "visible"
            assert mobile_layout["detailsMaxHeight"] == "none"
            assert mobile_layout["detailsOverflowY"] == "visible"
            assert mobile_layout["controlsWidth"] <= mobile_layout["viewportWidth"]
            assert mobile_layout["detailsWidth"] <= mobile_layout["viewportWidth"]
            assert mobile_layout["graphMinHeight"] == "340px"
            assert mobile_layout["workspaceHeight"] >= 420
            page.get_by_role("searchbox", name="Search").fill("dmn")
            assert page.locator("#search-results [data-result-id]").first.is_visible()
            page.locator("#cy").focus()
            page.keyboard.press("ArrowDown")
            assert (
                page.evaluate("window.systemDynamicsMapRuntime.currentViewPayload().selected")
                is not None
            )
        finally:
            browser.close()


def test_system_dynamics_viewer_respects_reduced_motion():
    with _static_server() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(
            viewport={"width": 1280, "height": 900},
            reduced_motion="reduce",
        )
        try:
            page.goto(f"{base_url}/system-dynamics-map-viewer.html")
            page.locator("#cy canvas").first.wait_for(timeout=10_000)
            page.wait_for_function("window.systemDynamicsMapRuntime")
            assert (
                page.evaluate("window.systemDynamicsMapRuntime.layoutAnimationEnabled()") is False
            )
        finally:
            browser.close()


def test_system_dynamics_viewer_forced_colors_keeps_focus_and_boundaries_visible():
    with _static_server() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(
            viewport={"width": 1280, "height": 900},
            forced_colors="active",
        )
        try:
            page.goto(f"{base_url}/system-dynamics-map-viewer.html")
            page.locator("#cy canvas").first.wait_for(timeout=10_000)
            page.wait_for_function("window.systemDynamicsMapRuntime")
            assert page.evaluate("window.matchMedia('(forced-colors: active)').matches")
            forced_color_styles = page.evaluate(
                """
                () => {
                  const cyStyle = getComputedStyle(document.querySelector("#cy"));
                  const buttonStyle = getComputedStyle(document.querySelector("button"));
                  return {
                    borderColor: cyStyle.borderTopColor,
                    borderStyle: cyStyle.borderTopStyle,
                    borderWidth: cyStyle.borderTopWidth,
                    buttonTextColor: buttonStyle.color,
                    canvasColor: cyStyle.backgroundColor
                  };
                }
                """
            )
            assert forced_color_styles["borderStyle"] == "solid"
            assert forced_color_styles["borderWidth"] != "0px"
            assert forced_color_styles["borderColor"] == forced_color_styles["buttonTextColor"]
            assert forced_color_styles["borderColor"] != forced_color_styles["canvasColor"], (
                "forced-colors mode did not render a contrastive graph boundary. "
                "Fix by keeping #cy in the forced-colors border-color rule."
            )
            page.locator("#cy").focus()
            graph_focus_style = page.evaluate(
                """
                () => {
                  const graph = document.querySelector("#cy");
                  const style = getComputedStyle(graph);
                  return {
                    activeElementId: document.activeElement.id,
                    outlineStyle: style.outlineStyle,
                    outlineWidth: style.outlineWidth
                  };
                }
                """
            )
            assert graph_focus_style["activeElementId"] == "cy"
            assert graph_focus_style["outlineStyle"] == "solid"
            assert graph_focus_style["outlineWidth"] != "0px"
            page.get_by_role("button", name="Force").focus()
            focus_style = page.evaluate(
                """
                () => {
                  const style = getComputedStyle(document.activeElement);
                  return { outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth };
                }
                """
            )
            assert focus_style["outlineStyle"] == "solid"
            assert focus_style["outlineWidth"] != "0px"
        finally:
            browser.close()


def test_system_dynamics_viewer_reports_missing_local_cytoscape():
    with _static_server() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.route("**/vendor/cytoscape-3.34.0.min.js", lambda route: route.abort())
        try:
            page.goto(f"{base_url}/system-dynamics-map-viewer.html")
            error = page.get_by_role("alert")
            error.wait_for(timeout=10_000)
            assert (
                error.inner_text()
                == "Cytoscape.js did not load. Check that ./vendor/cytoscape-3.34.0.min.js is present."
            )
            assert page.evaluate("document.activeElement.getAttribute('role')") == "alert"
            assert page.evaluate("window.systemDynamicsMapRuntime") is None, (
                "viewer exposed runtime APIs after Cytoscape failed to load. "
                "Fix by returning before runtime initialization when the local asset is missing."
            )
        finally:
            browser.close()
