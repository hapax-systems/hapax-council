import contextlib
import functools
import http.server
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

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
                "document.querySelector('#counts').textContent === '29 nodes / 35 edges'"
            )
            page.wait_for_function(NONBLANK_CANVAS_SCRIPT, timeout=10_000)

            assert page.locator("#panel").inner_text().startswith("DMN")
            assert (
                page.get_by_role("link", name="Seed JSON")
                .get_attribute("href")
                .endswith("/system-dynamics-map.seed.json")
            )

            page.get_by_label("Search").fill("telemetry")
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().nodes < 29")
            filtered_counts = page.evaluate("window.systemDynamicsMapRuntime.visibleCounts()")
            assert filtered_counts["nodes"] >= 1
            assert filtered_counts["edges"] >= 0

            page.get_by_label("Search").fill("")
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().nodes === 29")
            page.locator('input[data-filter="status"][value="candidate"]').uncheck()
            page.wait_for_function("window.systemDynamicsMapRuntime.visibleCounts().nodes < 29")

            page.locator('input[data-filter="status"][value="candidate"]').check()
            page.get_by_role("button", name="Circle").click()
            page.wait_for_function("window.systemDynamicsMapRuntime.activeLayout() === 'circle'")
            page.wait_for_function(NONBLANK_CANVAS_SCRIPT, timeout=10_000)
            assert "active" in page.get_by_role("button", name="Circle").get_attribute("class")

            selected = page.evaluate("window.systemDynamicsMapRuntime.selectNode('opentelemetry')")
            assert selected["id"] == "opentelemetry"
            assert page.locator("#panel").inner_text().startswith("OpenTelemetry")

            with pytest.raises(PlaywrightError):
                page.evaluate("window.systemDynamicsMapRuntime.selectNode('missing-node')")
        finally:
            browser.close()
