"""Tests for ``agents.attribution.swh_register``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents.attribution.swh_register import (
    SWH_API_BASE,
    SaveResult,
    VisitStatus,
    _encode_repo_url,
    poll_visit,
    resolve_swhid,
    trigger_save,
)


def _mock_response(status_code: int, json_data=None, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    # Use ``is None`` rather than ``or {}``; empty list/dict are valid
    # JSON payloads and falsy, so ``or`` would substitute them.
    response.json = MagicMock(return_value={} if json_data is None else json_data)
    return response


# ── _encode_repo_url ──────────────────────────────────────────────


class TestEncodeRepoUrl:
    def test_encodes_scheme_separator(self) -> None:
        encoded = _encode_repo_url("https://github.com/ryanklee/hapax-council")
        assert "://" not in encoded
        assert "%3A%2F%2F" in encoded

    def test_encodes_path_slashes(self) -> None:
        encoded = _encode_repo_url("https://github.com/ryanklee/hapax-council")
        # All slashes should be percent-encoded
        assert "/" not in encoded
        assert "%2F" in encoded


# ── trigger_save ──────────────────────────────────────────────────


class TestTriggerSave:
    @patch("agents.attribution.swh_register.requests")
    def test_201_parses_request_id(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(
            201, {"id": 12345, "save_task_status": "queued"}
        )
        result = trigger_save("https://github.com/ryanklee/hapax-council")
        assert result.request_id == 12345
        assert result.visit_status == VisitStatus.QUEUED
        assert result.error is None

    @patch("agents.attribution.swh_register.requests")
    def test_200_parses_request_id(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(
            200, {"id": 999, "save_task_status": "pending"}
        )
        result = trigger_save("https://github.com/ryanklee/hapax-council")
        assert result.visit_status == VisitStatus.PENDING

    @patch("agents.attribution.swh_register.requests")
    def test_403_marks_failed_with_error(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(403, text="forbidden")
        result = trigger_save("https://github.com/ryanklee/hapax-council")
        assert result.visit_status == VisitStatus.FAILED
        assert "403" in result.error

    @patch("agents.attribution.swh_register.requests")
    def test_request_exception_returns_error(self, mock_requests: MagicMock) -> None:
        import requests as _requests_lib

        mock_requests.post.side_effect = _requests_lib.RequestException("network down")
        mock_requests.RequestException = _requests_lib.RequestException
        result = trigger_save("https://github.com/ryanklee/hapax-council")
        assert result.error is not None
        assert "transport failure" in result.error

    @patch("agents.attribution.swh_register.requests")
    def test_url_construction(self, mock_requests: MagicMock) -> None:
        mock_requests.post.return_value = _mock_response(201, {"id": 1})
        trigger_save("https://github.com/ryanklee/hapax-council")
        call_args = mock_requests.post.call_args
        url = call_args[0][0]
        assert url.startswith(SWH_API_BASE)
        assert "save/git/url" in url


# ── poll_visit ────────────────────────────────────────────────────


class TestPollVisit:
    @patch("agents.attribution.swh_register.requests")
    def test_200_dict_response_parses(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(
            200, {"id": 12345, "save_task_status": "done"}
        )
        result = poll_visit("https://github.com/ryanklee/hapax-council")
        assert result.visit_status == VisitStatus.DONE

    @patch("agents.attribution.swh_register.requests")
    def test_200_list_response_takes_latest(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(
            200,
            [
                {"id": 1, "save_task_status": "queued"},
                {"id": 2, "save_task_status": "ongoing"},
                {"id": 3, "save_task_status": "done"},
            ],
        )
        result = poll_visit("https://github.com/ryanklee/hapax-council")
        # Latest entry takes precedence (the one currently active).
        assert result.visit_status == VisitStatus.DONE

    @patch("agents.attribution.swh_register.requests")
    def test_404_marks_not_found(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(404, text="not found")
        result = poll_visit("https://github.com/ryanklee/hapax-council")
        assert result.visit_status == VisitStatus.NOT_FOUND

    @patch("agents.attribution.swh_register.requests")
    def test_empty_list_returns_not_found(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(200, [])
        result = poll_visit("https://github.com/ryanklee/hapax-council")
        assert result.visit_status == VisitStatus.NOT_FOUND


# ── resolve_swhid ─────────────────────────────────────────────────


class TestResolveSwhid:
    @patch("agents.attribution.swh_register.requests")
    def test_200_with_snapshot_returns_swhid(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(200, {"snapshot": "deadbeef" * 5})
        result = resolve_swhid("https://github.com/ryanklee/hapax-council")
        assert result.visit_status == VisitStatus.DONE
        assert result.swhid is not None
        assert result.swhid.startswith("swh:1:snp:")
        assert result.swhid.endswith("deadbeef" * 5)

    @patch("agents.attribution.swh_register.requests")
    def test_200_without_snapshot_marks_ongoing(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(200, {"snapshot": None})
        result = resolve_swhid("https://github.com/ryanklee/hapax-council")
        assert result.visit_status == VisitStatus.ONGOING
        assert result.swhid is None

    @patch("agents.attribution.swh_register.requests")
    def test_404_marks_not_found(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(404)
        result = resolve_swhid("https://github.com/ryanklee/hapax-council")
        assert result.visit_status == VisitStatus.NOT_FOUND


# ── SaveResult dataclass ──────────────────────────────────────────


class TestSaveResult:
    def test_minimal_construction(self) -> None:
        r = SaveResult(repo_url="x")
        assert r.repo_url == "x"
        assert r.swhid is None
        assert r.error is None

    def test_full_construction(self) -> None:
        r = SaveResult(
            repo_url="x",
            request_id=42,
            visit_status=VisitStatus.DONE,
            swhid="swh:1:snp:" + "a" * 40,
        )
        assert r.request_id == 42
        assert r.swhid is not None
