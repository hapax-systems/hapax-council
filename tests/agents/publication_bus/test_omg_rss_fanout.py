"""Tests for ``agents.publication_bus.omg_rss_fanout``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from agents.publication_bus.omg_rss_fanout import (
    FANOUT_LOOP_HEADER_PREFIX,
    OmgFanoutConfig,
    fanout,
    load_fanout_config,
)


def _make_client(enabled: bool = True) -> MagicMock:
    client = MagicMock()
    client.enabled = enabled
    client.set_entry = MagicMock(return_value={"id": "entry-1"})
    return client


class TestLoadFanoutConfig:
    def test_loads_addresses_list(self, tmp_path: Path) -> None:
        path = tmp_path / "fanout.yaml"
        path.write_text("addresses:\n  - hapax\n  - oudepode\n")
        config = load_fanout_config(path=path)
        assert config.addresses == ["hapax", "oudepode"]

    def test_missing_file_returns_empty_config(self, tmp_path: Path) -> None:
        config = load_fanout_config(path=tmp_path / "missing.yaml")
        assert config.addresses == []

    def test_empty_yaml_returns_empty_config(self, tmp_path: Path) -> None:
        path = tmp_path / "fanout.yaml"
        path.write_text("")
        config = load_fanout_config(path=path)
        assert config.addresses == []


class TestFanout:
    def test_posts_to_every_target_except_source(self) -> None:
        client = _make_client()
        config = OmgFanoutConfig(addresses=["hapax", "oudepode", "third"])
        result = fanout(
            source_address="hapax",
            entry_id="entry-1",
            content="hello",
            config=config,
            client=client,
        )
        # Two non-source targets
        assert client.set_entry.call_count == 2
        targets_called = {call.args[0] for call in client.set_entry.call_args_list}
        assert targets_called == {"oudepode", "third"}
        assert result["oudepode"] == "ok"
        assert result["third"] == "ok"

    def test_skips_source_address(self) -> None:
        client = _make_client()
        config = OmgFanoutConfig(addresses=["hapax"])
        result = fanout(
            source_address="hapax",
            entry_id="entry-1",
            content="hello",
            config=config,
            client=client,
        )
        client.set_entry.assert_not_called()
        assert result == {}

    def test_loop_prevention_skips_already_fanned_out_content(self) -> None:
        client = _make_client()
        config = OmgFanoutConfig(addresses=["hapax", "oudepode"])
        # Content already contains the fanout-source header
        body = f"{FANOUT_LOOP_HEADER_PREFIX} hapax -->\nthis entry already came from hapax fanout\n"
        result = fanout(
            source_address="oudepode",  # different "source" but body still has header
            entry_id="entry-1",
            content=body,
            config=config,
            client=client,
        )
        # Skipped due to loop-prevention
        client.set_entry.assert_not_called()
        assert result == {}

    def test_disabled_client_short_circuits(self) -> None:
        client = _make_client(enabled=False)
        config = OmgFanoutConfig(addresses=["hapax", "oudepode"])
        result = fanout(
            source_address="hapax",
            entry_id="entry-1",
            content="hello",
            config=config,
            client=client,
        )
        client.set_entry.assert_not_called()
        assert result == {"oudepode": "client-disabled"}

    def test_set_entry_failure_records_error(self) -> None:
        client = _make_client()
        client.set_entry = MagicMock(return_value=None)
        config = OmgFanoutConfig(addresses=["hapax", "oudepode"])
        result = fanout(
            source_address="hapax",
            entry_id="entry-1",
            content="hello",
            config=config,
            client=client,
        )
        assert result["oudepode"] == "error"

    def test_injects_fanout_source_header(self) -> None:
        client = _make_client()
        config = OmgFanoutConfig(addresses=["hapax", "oudepode"])
        fanout(
            source_address="hapax",
            entry_id="entry-1",
            content="body",
            config=config,
            client=client,
        )
        sent = client.set_entry.call_args.kwargs["content"]
        assert FANOUT_LOOP_HEADER_PREFIX in sent
        assert "hapax" in sent  # source address recorded
        assert "body" in sent

    def test_empty_config_no_targets(self) -> None:
        client = _make_client()
        config = OmgFanoutConfig(addresses=[])
        result = fanout(
            source_address="hapax",
            entry_id="entry-1",
            content="x",
            config=config,
            client=client,
        )
        assert result == {}
        client.set_entry.assert_not_called()
