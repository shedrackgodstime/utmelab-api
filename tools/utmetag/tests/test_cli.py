import json

import pytest

from utmetag.cli import main


def test_mock_run_writes_output(data_dir, tmp_path):
    out = tmp_path / "results.json"
    rc = main([
        "--engine", "mock",
        "--data-dir", str(data_dir),
        "--subject", "mathematics",
        "--limit", "10",
        "--all",
        "--output", str(out),
    ])
    assert rc == 0
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["metadata"]["engine"] == "mock"
    assert data["metadata"]["model"] == "mock"
    assert data["metadata"]["subject"] == "mathematics"
    assert data["summary"]["total"] == 3
    assert data["summary"]["success"] == 3
    assert data["summary"]["failed"] == 0


def test_unverified_only_by_default(data_dir, tmp_path):
    out = tmp_path / "results.json"
    rc = main([
        "--engine", "mock",
        "--data-dir", str(data_dir),
        "--subject", "mathematics",
        "--output", str(out),
    ])
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["summary"]["total"] == 2  # q2 is verified


def test_limit_is_respected(data_dir, tmp_path):
    out = tmp_path / "results.json"
    rc = main([
        "--engine", "mock", "--data-dir", str(data_dir),
        "--subject", "mathematics", "--limit", "1", "--all",
        "--output", str(out),
    ])
    assert rc == 0
    assert json.loads(out.read_text())["summary"]["total"] == 1


def test_no_matching_questions_is_not_an_error(data_dir, tmp_path):
    out = tmp_path / "results.json"
    rc = main([
        "--engine", "mock", "--data-dir", str(data_dir),
        "--subject", "nonexistent-subject", "--output", str(out),
    ])
    assert rc == 0
    assert not out.exists()


def test_missing_data_dir_returns_error(tmp_path):
    rc = main(["--engine", "mock", "--data-dir", str(tmp_path / "nope")])
    assert rc == 1


def test_unknown_engine_is_rejected(data_dir):
    with pytest.raises(SystemExit):
        main(["--engine", "bogus", "--data-dir", str(data_dir)])


def test_mock_alias(data_dir, tmp_path):
    out = tmp_path / "results.json"
    rc = main(["--mock", "--data-dir", str(data_dir), "--subject", "mathematics", "--output", str(out)])
    assert rc == 0
    assert json.loads(out.read_text())["metadata"]["engine"] == "mock"
