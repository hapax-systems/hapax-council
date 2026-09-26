from pathlib import Path

import scripts.operator_statement_corpus as corpus


def test_claude_rows_use_only_measured_hosts(monkeypatch):
    observations = [
        {"endpoint": "podium-alias", "host": "podium-real", "status": "reachable"},
        {"endpoint": "appendix", "host": "appendix-real", "status": "reachable"},
        {"endpoint": "monocle", "host": "unknown", "status": "unreachable"},
    ]
    records = {
        "podium-alias": [
            (
                Path("/remote/.claude/projects/a.jsonl"),
                1,
                {
                    "type": "user",
                    "sessionId": "p",
                    "timestamp": "2026-08-22T00:00:00Z",
                    "promptSource": "typed",
                    "origin": {"kind": "human"},
                    "message": {"content": "podium"},
                },
            )
        ],
        "appendix": [
            (
                Path("/remote/.claude/projects/b.jsonl"),
                1,
                {
                    "type": "user",
                    "sessionId": "a",
                    "timestamp": "2026-08-22T00:00:01Z",
                    "promptSource": "queued",
                    "origin": {"kind": "human"},
                    "message": {"content": "appendix"},
                },
            )
        ],
        "monocle": [],
    }

    def fake_records(cap, observation):
        yield from records[observation["endpoint"]]

    monkeypatch.setattr(corpus, "source_records", fake_records)
    rows, _ = corpus.extract("claude", observations)
    assert {row["host"] for row in rows} == {"podium-real", "appendix-real"}
    assert all(row["host"] in {"podium-real", "appendix-real", "unknown"} for row in rows)


def test_unknown_host_is_retained_in_inventory(monkeypatch):
    monkeypatch.setattr(
        corpus,
        "subprocess",
        type(
            "S",
            (),
            {
                "run": staticmethod(
                    lambda *args, **kwargs: type(
                        "R", (), {"stdout": "", "stderr": "unreachable", "returncode": 255}
                    )()
                )
            },
        ),
    )
    observations = corpus.host_inventory()
    assert any(
        item["status"] == "unreachable" and item["host"] == "unknown" for item in observations
    )


def test_mutated_unmeasured_host_fails(monkeypatch):
    observations = [{"endpoint": "podium", "host": "measured", "status": "reachable"}]

    def fake_records(cap, observation):
        yield (
            Path("/x.jsonl"),
            1,
            {
                "type": "user",
                "sessionId": "s",
                "timestamp": "2026-08-22T00:00:00Z",
                "message": {"content": "x"},
            },
        )

    monkeypatch.setattr(corpus, "source_records", fake_records)
    rows, _ = corpus.extract("claude", observations)
    assert rows[0]["host"] == "measured"
