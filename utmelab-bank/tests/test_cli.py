"""The command surface. The tasks themselves are proved in test_tasks."""

from __future__ import annotations

import json

import pytest

from utmelab_bank.cli import build_parser, main


def test_tasks_lists_tasks_and_presets(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["tasks"]) == 0
    out = capsys.readouterr().out
    assert "fetch" in out
    assert "status" in out
    assert "scrape" in out
    assert "fetch -> tag" in out
    assert "media -> explain -> review -> ready" in out


def test_tasks_json_is_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["tasks", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "fetch" in payload["tasks"]
    assert payload["presets"]["process"] == ["media", "explain", "review", "ready"]


def test_fetch_requires_a_full_scope() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["fetch"])


def test_the_batch_commands_do_not_require_a_scope() -> None:
    args = build_parser().parse_args(["tag", "--limit", "5"])
    assert args.command == "tag"
    assert args.limit == 5
