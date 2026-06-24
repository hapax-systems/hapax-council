import json
import subprocess
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

module = types.ModuleType("hapax_openrouter_reviewer")
module.__dict__["__file__"] = "scripts/hapax-openrouter-reviewer"
with open("scripts/hapax-openrouter-reviewer") as f:
    exec(f.read(), module.__dict__)
sys.modules["hapax_openrouter_reviewer"] = module
hapax_openrouter_reviewer = module


def test_get_api_key_from_env(monkeypatch):
    monkeypatch.setenv("LITELLM_MASTER_KEY", "test-env-key")
    assert hapax_openrouter_reviewer._api_key() == "test-env-key"


@patch("subprocess.run")
def test_get_api_key_from_pass(mock_run, monkeypatch):
    monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
    mock_run.return_value = MagicMock(stdout="test-pass-key\n")
    assert hapax_openrouter_reviewer._api_key() == "test-pass-key"
    mock_run.assert_called_once()


@patch("subprocess.run")
def test_get_api_key_fails(mock_run, monkeypatch):
    monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
    mock_run.side_effect = subprocess.SubprocessError("Failed")
    with pytest.raises(SystemExit) as excinfo:
        hapax_openrouter_reviewer._api_key()
    assert excinfo.value.code == 1


@patch("urllib.request.urlopen")
def test_call_gateway_success(mock_urlopen):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(
        {"choices": [{"message": {"content": "```yaml\nverdict: accept\n```"}}]}
    ).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_response

    result = hapax_openrouter_reviewer._call_gateway(
        "test-model", "test-prompt", "http://test", "test-key"
    )
    assert result == "```yaml\nverdict: accept\n```"


@patch("urllib.request.urlopen")
def test_call_gateway_429(mock_urlopen):
    from urllib.error import HTTPError

    mock_urlopen.side_effect = HTTPError("http://test", 429, "Too Many Requests", {}, None)

    with pytest.raises(SystemExit) as excinfo:
        hapax_openrouter_reviewer._call_gateway(
            "test-model", "test-prompt", "http://test", "test-key"
        )
    assert excinfo.value.code == 1
