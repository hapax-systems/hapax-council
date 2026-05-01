"""Tests for ``scripts/grafana-panel-import-runner.py``.

Per cc-task ``grafana-panel-import-runner``. Exercises the API-key
resolution chain, missing-file failure, missing-key failure, and the
import_dashboard request shape (mocked HTTP).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "grafana-panel-import-runner.py"


def _load_module() -> ModuleType:
    name = "grafana_panel_import_runner_under_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_M = _load_module()


def test_resolve_api_key_uses_env_when_pass_unavailable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("GRAFANA_API_KEY", "env-key-xyz")
    with patch.object(_M, "subprocess") as mock_sub:
        mock_sub.run.side_effect = FileNotFoundError()
        mock_sub.TimeoutExpired = TimeoutError
        assert _M._resolve_api_key(None) == "env-key-xyz"


def test_resolve_api_key_uses_cli_fallback(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("GRAFANA_API_KEY", raising=False)
    with patch.object(_M, "subprocess") as mock_sub:
        result = MagicMock()
        result.returncode = 1
        result.stdout = ""
        mock_sub.run.return_value = result
        mock_sub.TimeoutExpired = TimeoutError
        assert _M._resolve_api_key("cli-key") == "cli-key"


def test_resolve_api_key_returns_none_when_all_sources_empty(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("GRAFANA_API_KEY", raising=False)
    with patch.object(_M, "subprocess") as mock_sub:
        result = MagicMock()
        result.returncode = 1
        result.stdout = ""
        mock_sub.run.return_value = result
        mock_sub.TimeoutExpired = TimeoutError
        assert _M._resolve_api_key(None) is None


def test_resolve_api_key_prefers_pass_over_env(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("GRAFANA_API_KEY", "env-key")
    with patch.object(_M, "subprocess") as mock_sub:
        result = MagicMock()
        result.returncode = 0
        result.stdout = "pass-key\n"
        mock_sub.run.return_value = result
        mock_sub.TimeoutExpired = TimeoutError
        assert _M._resolve_api_key(None) == "pass-key"


def test_main_missing_panel_json_returns_2(tmp_path: Path) -> None:
    rc = _M.main(["--panel-json", str(tmp_path / "nonexistent.json")])
    assert rc == 2


def test_main_missing_api_key_returns_3(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    panel_path = tmp_path / "panel.json"
    panel_path.write_text(json.dumps({"dashboard": {"title": "TV"}}), encoding="utf-8")
    monkeypatch.delenv("GRAFANA_API_KEY", raising=False)
    with patch.object(_M, "_resolve_api_key", return_value=None):
        rc = _M.main(["--panel-json", str(panel_path)])
    assert rc == 3


def test_import_dashboard_posts_correct_body(tmp_path: Path) -> None:
    panel_path = tmp_path / "panel.json"
    panel_path.write_text(
        json.dumps({"dashboard": {"title": "TV", "panels": []}}),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    class FakeResponse:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def read(self) -> bytes:
            return self._body

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_urlopen(request: object, timeout: float = 0) -> FakeResponse:
        captured["url"] = request.full_url  # type: ignore[attr-defined]
        captured["method"] = request.method  # type: ignore[attr-defined]
        captured["body"] = json.loads(request.data.decode())  # type: ignore[attr-defined]
        captured["auth"] = request.headers.get("Authorization")  # type: ignore[attr-defined]
        return FakeResponse(b'{"uid": "abc-123", "url": "/d/abc-123"}')

    with patch.object(_M.urllib.request, "urlopen", side_effect=fake_urlopen):
        result = _M.import_dashboard(
            panel_path, grafana_url="http://example:3000", api_key="test-key"
        )

    assert result["uid"] == "abc-123"
    assert captured["url"] == "http://example:3000/api/dashboards/db"
    assert captured["method"] == "POST"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["overwrite"] is True
    assert body["dashboard"]["title"] == "TV"
    assert "Bearer test-key" in str(captured["auth"])


def test_import_dashboard_unwraps_dashboard_key(tmp_path: Path) -> None:
    """If panel JSON already has top-level 'dashboard' key, use it directly."""
    panel_path = tmp_path / "panel.json"
    panel_path.write_text(
        json.dumps({"dashboard": {"title": "Already-wrapped"}, "extra": "ignored"}),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    class FakeResponse:
        def read(self) -> bytes:
            return b'{"uid": "x"}'

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_urlopen(request: object, timeout: float = 0) -> FakeResponse:
        captured["body"] = json.loads(request.data.decode())  # type: ignore[attr-defined]
        return FakeResponse()

    with patch.object(_M.urllib.request, "urlopen", side_effect=fake_urlopen):
        _M.import_dashboard(panel_path, grafana_url="http://x:3000", api_key="k")

    body = captured["body"]
    assert isinstance(body, dict)
    assert body["dashboard"]["title"] == "Already-wrapped"
