"""Tests for shared/olaf.py — Olaf fingerprinting CLI wrapper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from shared.olaf import OlafMatch, OlafResult, _parse_query_output, available, delete, query, store


def _mock_run(returncode=0, stdout="", stderr=""):
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


def test_available_when_installed():
    with patch("shared.olaf._run_olaf", return_value=_mock_run(0)):
        assert available() is True


def test_available_when_not_installed():
    with patch("shared.olaf._run_olaf", side_effect=FileNotFoundError):
        assert available() is False


def test_store_success(tmp_path):
    audio = tmp_path / "test.flac"
    audio.touch()

    with patch("shared.olaf._run_olaf", return_value=_mock_run(0)):
        assert store(audio) is True


def test_store_missing_file(tmp_path):
    audio = tmp_path / "missing.flac"
    assert store(audio) is False


def test_store_failure(tmp_path):
    audio = tmp_path / "test.flac"
    audio.touch()

    with patch("shared.olaf._run_olaf", return_value=_mock_run(1, stderr="error")):
        assert store(audio) is False


def test_query_with_matches(tmp_path):
    audio = tmp_path / "test.flac"
    audio.touch()

    stdout = "song1.wav  0.85  1.23\nsong2.wav  0.72  0.50\n"
    with patch("shared.olaf._run_olaf", return_value=_mock_run(0, stdout=stdout)):
        result = query(audio)

    assert result.replay_count == 2
    assert result.is_replay is True
    assert len(result.matches) == 2
    assert result.matches[0].matched_file == "song1.wav"
    assert result.matches[0].match_score == 0.85
    assert result.matches[1].time_offset == 0.50


def test_query_no_matches(tmp_path):
    audio = tmp_path / "test.flac"
    audio.touch()

    with patch("shared.olaf._run_olaf", return_value=_mock_run(0, stdout="")):
        result = query(audio)

    assert result.replay_count == 0
    assert result.is_replay is False
    assert result.matches == []


def test_query_missing_file(tmp_path):
    audio = tmp_path / "missing.flac"
    result = query(audio)
    assert result.replay_count == 0


def test_delete_success(tmp_path):
    audio = tmp_path / "test.flac"
    with patch("shared.olaf._run_olaf", return_value=_mock_run(0)):
        assert delete(audio) is True


def test_delete_failure(tmp_path):
    audio = tmp_path / "test.flac"
    with patch("shared.olaf._run_olaf", return_value=_mock_run(1, stderr="not found")):
        assert delete(audio) is False


def test_parse_query_output_valid():
    stdout = "track1.wav  0.95  2.30\ntrack2.wav  0.80  0.10\n"
    matches = _parse_query_output(stdout)
    assert len(matches) == 2
    assert matches[0] == OlafMatch("track1.wav", 0.95, 2.30)
    assert matches[1] == OlafMatch("track2.wav", 0.80, 0.10)


def test_parse_query_output_empty():
    assert _parse_query_output("") == []
    assert _parse_query_output("\n") == []


def test_parse_query_output_malformed():
    stdout = "badline\ntrack.wav  notanumber  0.5\ntrack2.wav  0.8  1.0\n"
    matches = _parse_query_output(stdout)
    assert len(matches) == 1
    assert matches[0].matched_file == "track2.wav"


def test_olaf_result_frozen():
    result = OlafResult(query_file="test.wav", matches=[], replay_count=0)
    assert result.query_file == "test.wav"
