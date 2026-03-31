"""Tests for utterance feature extraction."""

from __future__ import annotations

from agents.hapax_daimonion.salience.utterance_features import extract


class TestUtteranceFeatures:
    def test_wh_question_detected(self) -> None:
        f = extract("What time is it?", [])
        assert f.dialog_act == "wh_question"

    def test_yes_no_question_detected(self) -> None:
        f = extract("Is it raining?", [])
        assert f.dialog_act == "yes_no_question"

    def test_command_detected(self) -> None:
        f = extract("Switch off the lights", [])
        assert f.dialog_act == "command"

    def test_phatic_detected(self) -> None:
        f = extract("bye", [])
        assert f.is_phatic

    def test_backchannel_detected(self) -> None:
        f = extract("yeah", [])
        assert f.dialog_act == "backchannel"
        assert f.is_phatic

    def test_word_count(self) -> None:
        f = extract("one two three four", [])
        assert f.word_count == 4

    def test_empty_text(self) -> None:
        f = extract("", [])
        assert f.word_count == 0

    def test_meta_question(self) -> None:
        f = extract("Can you explain this concept?", [])
        assert f.dialog_act == "meta_question"

    def test_explicit_escalation(self) -> None:
        f = extract("Please elaborate on that point", [])
        assert f.has_explicit_escalation

    def test_topic_continuity(self) -> None:
        f = extract("python programming language", ["python coding language"])
        assert f.topic_continuity > 0.0

    def test_statement_default(self) -> None:
        f = extract("The weather is nice today", [])
        assert f.dialog_act == "statement"
