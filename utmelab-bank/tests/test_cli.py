"""The command surface. The tasks themselves are proved in test_tasks."""

from __future__ import annotations

import json

import pytest

from utmelab_bank.cli import build_parser, main


def test_tasks_lists_tasks_and_presets(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["tasks"]) == 0
    out = capsys.readouterr().out
    assert "fetch" in out
    # "capture" appears in the fetch help text, but not as a task name
    assert "status" in out
    assert "scrape" in out
    assert any(line.split() == ["scrape", "fetch"] for line in out.splitlines())
    assert any(
        line.split()
        == [
            "process",
            "tag",
            "->",
            "media",
            "->",
            "explain",
            "->",
            "review",
            "->",
            "ready",
        ]
        for line in out.splitlines()
    )


def test_tasks_json_is_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["tasks", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "fetch" in payload["tasks"]
    assert "capture" not in payload["tasks"]
    assert payload["presets"]["scrape"] == ["fetch"]
    assert payload["presets"]["process"] == [
        "tag",
        "media",
        "explain",
        "review",
        "ready",
    ]


def test_fetch_requires_a_full_scope() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["fetch"])


def test_the_batch_commands_do_not_require_a_scope() -> None:
    args = build_parser().parse_args(["tag", "--limit", "5"])
    assert args.command == "tag"
    assert args.limit == 5
