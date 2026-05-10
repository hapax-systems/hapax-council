from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN = REPO_ROOT / "agents" / "studio_compositor" / "__main__.py"


def test_cli_supports_explicit_layout_and_env_layout() -> None:
    source = MAIN.read_text(encoding="utf-8")

    assert '"--layout"' in source
    assert "HAPAX_COMPOSITOR_LAYOUT_PATH" in source
    assert "StudioCompositor(cfg, layout_path=layout_path)" in source
