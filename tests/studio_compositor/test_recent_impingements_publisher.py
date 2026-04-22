import json
from pathlib import Path

from agents.studio_compositor.recent_impingements_publisher import (
    TOP_N,
    RecentImpingementsPublisher,
)


def test_reads_impingements_and_writes_top_n(tmp_path: Path):
    src = tmp_path / "impingements.jsonl"
    dst = tmp_path / "recent-impingements.json"
    lines = [
        json.dumps({"intent_family": f"family_{i}", "salience": i * 0.1}) + "\n" for i in range(10)
    ]
    src.write_text("".join(lines))

    pub = RecentImpingementsPublisher(src=src, dst=dst)
    pub.tick()

    assert dst.exists()
    payload = json.loads(dst.read_text())
    assert len(payload["entries"]) == TOP_N
    assert payload["entries"][0]["value"] == 0.9  # highest salience first


def test_missing_source_does_not_crash(tmp_path: Path):
    pub = RecentImpingementsPublisher(
        src=tmp_path / "nonexistent.jsonl",
        dst=tmp_path / "recent-impingements.json",
    )
    pub.tick()  # no exception
    assert not (tmp_path / "recent-impingements.json").exists()


def test_malformed_line_skipped(tmp_path: Path):
    src = tmp_path / "impingements.jsonl"
    dst = tmp_path / "recent-impingements.json"
    src.write_text(json.dumps({"intent_family": "good", "salience": 0.5}) + "\nthis is not json\n")
    pub = RecentImpingementsPublisher(src=src, dst=dst)
    pub.tick()
    payload = json.loads(dst.read_text())
    assert len(payload["entries"]) == 1
