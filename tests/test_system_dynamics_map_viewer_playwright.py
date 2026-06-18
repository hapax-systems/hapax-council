import contextlib
import functools
import http.server
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

playwright_sync_api = pytest.importorskip("playwright.sync_api", reason="playwright not installed")
PlaywrightError = playwright_sync_api.Error
sync_playwright = playwright_sync_api.sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE_DIR = REPO_ROOT / "docs" / "architecture"
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


def test_system_dynamics_viewer_core_interactions():
    with _static_server() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
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
            assert (
                page.get_by_role("link", name="Seed JSON")
                .get_attribute("href")
                .endswith("/system-dynamics-map.seed.json")
            ), (
                "Seed JSON link drifted. Fix by keeping the viewer linked to the canonical seed file."
            )

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

            page.get_by_label("Search").fill("")
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().nodes === 35")
            page.locator('input[data-filter="status"][value="candidate"]').uncheck()
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().nodes < 35")
            assert page.evaluate(
                "window.systemDynamicsMapRuntime.visibleEdgesHaveVisibleEndpoints()"
            ), (
                "status filter left visible edges attached to hidden nodes. "
                "Fix by recomputing visible edge state after checkbox changes."
            )

            page.locator('input[data-filter="status"][value="candidate"]').check()
            page.get_by_label("Lens").select_option("operating-slice")
            page.wait_for_function(
                "window.systemDynamicsMapRuntime.activeLens() === 'operating-slice'"
            )
            operating_counts = page.evaluate("window.systemDynamicsMapRuntime.visibleCounts()")
            assert operating_counts == {"nodes": 8, "edges": 7}, (
                "operating-slice lens did not apply its persisted projection. "
                "Fix by honoring visible_node_ids and visible_edge_ids in applyFilters()."
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

            page.get_by_label("Lens").select_option("topology")
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().nodes === 35")
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
            assert page.locator("#panel").inner_text().startswith("OpenTelemetry"), (
                "details panel did not update after node selection. "
                "Fix by rendering node data in selectNode()."
            )

            with pytest.raises(PlaywrightError, match="nodes\\[\\]\\.id"):
                page.evaluate("window.systemDynamicsMapRuntime.selectNode('missing-node')")
        finally:
            browser.close()


def test_system_dynamics_viewer_reports_missing_local_cytoscape():
    with _static_server() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.route("**/vendor/cytoscape-3.34.0.min.js", lambda route: route.abort())
        try:
            page.goto(f"{base_url}/system-dynamics-map-viewer.html")
            error = page.locator("#cy .error")
            error.wait_for(timeout=10_000)
            assert (
                error.inner_text()
                == "Cytoscape.js did not load. Check that ./vendor/cytoscape-3.34.0.min.js is present."
            )
            assert page.evaluate("window.systemDynamicsMapRuntime") is None, (
                "viewer exposed runtime APIs after Cytoscape failed to load. "
                "Fix by returning before runtime initialization when the local asset is missing."
            )
        finally:
            browser.close()
