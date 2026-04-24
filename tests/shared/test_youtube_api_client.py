"""Unit tests for YouTubeApiClient retry + silent-skip + auth-refresh."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class _FakeResp:
    def __init__(self, status: int) -> None:
        self.status = status
        self.reason = "fake"


def _http_error(status: int, *, quota: bool = False):
    from googleapiclient.errors import HttpError

    if quota:
        body = b'{"error": {"errors": [{"reason": "quotaExceeded"}]}}'
    else:
        body = b'{"error": {"errors": [{"reason": "forbidden"}]}}'
    return HttpError(resp=_FakeResp(status), content=body)


@patch("shared.youtube_api_client.build")
@patch("shared.youtube_api_client.get_google_credentials")
def test_disabled_when_no_creds(mock_creds, mock_build):
    from shared.youtube_api_client import YouTubeApiClient

    mock_creds.return_value = None
    client = YouTubeApiClient(scopes=[])
    assert not client.enabled
    assert mock_build.call_count == 0


@patch("shared.youtube_api_client.build")
@patch("shared.youtube_api_client.get_google_credentials")
def test_execute_ok(mock_creds, mock_build):
    from shared.youtube_api_client import YouTubeApiClient

    mock_creds.return_value = MagicMock()
    mock_request = MagicMock()
    mock_request.execute.return_value = {"items": []}
    client = YouTubeApiClient(scopes=[])
    resp = client.execute(mock_request, endpoint="test.endpoint")
    assert resp == {"items": []}


@patch("shared.youtube_api_client.build")
@patch("shared.youtube_api_client.get_google_credentials")
def test_execute_quota_silent_skip(mock_creds, mock_build):
    from shared.youtube_api_client import YouTubeApiClient

    mock_creds.return_value = MagicMock()
    mock_request = MagicMock()
    mock_request.execute.side_effect = _http_error(403, quota=True)
    client = YouTubeApiClient(scopes=[])
    resp = client.execute(mock_request, endpoint="test.endpoint")
    assert resp is None


@patch("shared.youtube_api_client.build")
@patch("shared.youtube_api_client.get_google_credentials")
def test_execute_403_permission_returns_none(mock_creds, mock_build):
    from shared.youtube_api_client import YouTubeApiClient

    mock_creds.return_value = MagicMock()
    mock_request = MagicMock()
    mock_request.execute.side_effect = _http_error(403, quota=False)
    client = YouTubeApiClient(scopes=[])
    assert client.execute(mock_request, endpoint="test.endpoint") is None


@patch("shared.youtube_api_client.build")
@patch("shared.youtube_api_client.get_google_credentials")
def test_execute_transient_500_retries_then_succeeds(mock_creds, mock_build):
    from shared.youtube_api_client import YouTubeApiClient

    mock_creds.return_value = MagicMock()
    mock_request = MagicMock()
    mock_request.execute.side_effect = [
        _http_error(500),
        _http_error(503),
        {"ok": True},
    ]
    client = YouTubeApiClient(scopes=[], backoff_base_s=0.001)
    resp = client.execute(mock_request, endpoint="test.endpoint")
    assert resp == {"ok": True}
    assert mock_request.execute.call_count == 3


@patch("shared.youtube_api_client.build")
@patch("shared.youtube_api_client.get_google_credentials")
def test_execute_429_backoff_then_succeeds(mock_creds, mock_build):
    from shared.youtube_api_client import YouTubeApiClient

    mock_creds.return_value = MagicMock()
    mock_request = MagicMock()
    mock_request.execute.side_effect = [
        _http_error(429),
        {"ok": True},
    ]
    client = YouTubeApiClient(scopes=[], backoff_base_s=0.001)
    assert client.execute(mock_request, endpoint="test.endpoint") == {"ok": True}


@patch("shared.youtube_api_client.build")
@patch("shared.youtube_api_client.get_google_credentials")
def test_rate_limiter_denial_skips_call(mock_creds, mock_build):
    from shared.youtube_api_client import YouTubeApiClient

    mock_creds.return_value = MagicMock()
    mock_request = MagicMock()
    bucket = MagicMock()
    bucket.try_acquire.return_value = False
    client = YouTubeApiClient(scopes=[], rate_limiter=bucket)
    resp = client.execute(mock_request, endpoint="test.endpoint", quota_cost_hint=50)
    assert resp is None
    assert mock_request.execute.call_count == 0
