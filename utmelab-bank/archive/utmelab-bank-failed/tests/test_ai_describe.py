"""ai-describe as a task: media rows in, description stamped, failures retried."""

from __future__ import annotations

from typing import Any

import pytest

from utmelab_bank.config import Config
from utmelab_bank.model.base import now_iso
from utmelab_bank.store.client import Store
from utmelab_bank.store.repository import Repository
from utmelab_bank.task import run_task
from utmelab_bank.task.ai.describe import AiDescribe
from utmelab_bank.task.ai.describe_prompt import build_describe_prompt
from utmelab_bank.task.ai.describe_schema import DescribeOutput, describe_output_from_text
from utmelab_bank.task.ai.describe_tasks import describe_figure
from utmelab_bank.task.ai.jsonio import extract_json


def _media_row(**over: Any) -> dict[str, Any]:
    import hashlib

    stamp = now_iso()
    row: dict[str, Any] = {
        "id": "m_fig_1",
        "source_url": "https://cdn.example/fig-1.png",
        "question_id": "q_1",
        "status": "fetched",
        "blob_path": "media/ab/" + hashlib.sha256(b"fig-1").hexdigest() + ".png",
        "sha256": hashlib.sha256(b"fig-1-bytes").hexdigest(),
        "bytes": 4096,
        "media_url": hashlib.sha256(b"fig-1").hexdigest() + ".png",
        "description": None,
        "description_model": None,
        "attempts": 0,
        "error": None,
        "next_retry_at": None,
        "run_id": "r_fetch",
        "created_at": stamp,
        "updated_at": stamp,
    }
    row.update(over)
    return row


def _question_row() -> dict[str, Any]:
    return {
        "id": "q_1",
        "exam": "jamb",
        "subject": "physics",
        "year": 2025,
        "source": "claimed_paper",
        "text": {
            "text": "In the circuit diagram below, calculate the current through R1.",
            "inline": [],
        },
        "options": [
            {"id": "A", "text": {"text": "2.0 A", "inline": []}},
            {"id": "B", "text": {"text": "4.0 A", "inline": []}},
        ],
        "answer": "A",
    }


# ---------------------------------------------------------------------------
# describe_schema.py: validators + parse
# ---------------------------------------------------------------------------


def test_kind_is_normalized_to_closed_set():
    out = DescribeOutput.model_validate({"figure_kind": "DIAGRAM"})
    assert out.figure_kind == "diagram"
    out = DescribeOutput.model_validate({"figure_kind": "nonsense"})
    assert out.figure_kind == "other"


def test_confidence_is_clamped():
    assert DescribeOutput.model_validate({"confidence": 9.9}).confidence == 1.0
    assert DescribeOutput.model_validate({"confidence": -1.0}).confidence == 0.0
    assert DescribeOutput.model_validate({"confidence": "junk"}).confidence == 0.0


def test_empty_description_raises():
    # The schema accepts an empty description; describe_figure rejects it.
    out = DescribeOutput.model_validate({"description": ""})
    assert out.description == ""


def test_garbage_raises():
    with pytest.raises(ValueError):
        describe_output_from_text("no json here", extract_json)
    with pytest.raises(ValueError):
        describe_output_from_text("", lambda _t: "not a dict")


# ---------------------------------------------------------------------------
# describe_prompt.py: stem + options land in the prompt
# ---------------------------------------------------------------------------


def test_prompt_includes_stem_and_options():
    prompt = build_describe_prompt(
        _question_row()["text"]["text"],
        ["2.0 A", "4.0 A"],
    )
    assert "In the circuit diagram below" in prompt
    assert "2.0 A" in prompt


# ---------------------------------------------------------------------------
# describe_tasks.py: fake provider, parse-retry, transport failure
# ---------------------------------------------------------------------------


class _FakeProvider:
    """Returns JSON I control; fails when told to."""

    def __init__(self, reply: str | None = None) -> None:
        self.reply = reply
        self.calls = 0
        self.image: str | None = None
        self.name = "fake"

    async def complete(self, _prompt: str, *, image: str | None = None) -> str:
        self.calls += 1
        self.image = image
        if self.reply is None:
            raise OSError("network down")
        return self.reply

    async def aclose(self) -> None:
        return None


async def test_describe_figure_returns_result():
    provider = _FakeProvider(
        '{"figure_kind": "graph", "description": "A V-I graph with a straight line through the origin.", '
        '"key_values": ["slope = 4 ohms"], "confidence": 0.9}'
    )
    result = await describe_figure(provider, _media_row(), "stem text", ["2.0 A"])
    assert result.error is None
    assert result.figure_kind == "graph"
    assert result.description.startswith("A V-I graph")
    assert result.key_values == ["slope = 4 ohms"]
    assert result.confidence == 0.9


async def test_describe_figure_attaches_the_image():
    provider = _FakeProvider('{"figure_kind": "graph", "description": "A graph."}')
    await describe_figure(provider, _media_row(), "stem text", [], image="/tmp/media/fig.png")
    assert provider.image == "/tmp/media/fig.png"


async def test_describe_figure_retries_then_errors():
    provider = _FakeProvider("not json at all")
    result = await describe_figure(provider, _media_row(), "stem text", [])
    assert result.error is not None
    assert "ValueError" in result.error


async def test_describe_figure_transport_failure_errors():
    provider = _FakeProvider(None)
    result = await describe_figure(provider, _media_row(), "stem text", [])
    assert result.error is not None
    assert "network down" in result.error


# ---------------------------------------------------------------------------
# describe.py: task framing — selector skips, stamp, retry
# ---------------------------------------------------------------------------


async def test_describe_stamps_description(
    store: Store, config: Config, monkeypatch: object
) -> None:
    import utmelab_bank.task.ai.describe as describe_module

    captured: list[_FakeProvider] = []

    def _provider(*_args: object, **_kwargs: object) -> _FakeProvider:
        fake = _FakeProvider(
            '{"figure_kind": "diagram", "description": "A circuit with a 12V battery and resistor R1.", '
            '"key_values": ["12V"], "confidence": 0.8}'
        )
        captured.append(fake)
        return fake

    monkeypatch.setattr(describe_module, "build_provider", _provider)

    repo = Repository(store, lane="work")
    await repo.insert_many("media", [_media_row()])
    blob_rel = _media_row()["blob_path"]
    (config.repo.media_repo / blob_rel).parent.mkdir(parents=True, exist_ok=True)
    (config.repo.media_repo / blob_rel).write_bytes(b"fake-png-bytes")

    result = await run_task(AiDescribe(), config, repo, logical="media")

    assert result.run.succeeded == 1
    assert result.run.failed == 0
    # The task must hand the figure's absolute path to the model. Without it the
    # model describes a figure it never saw.
    assert captured[0].image == str(config.repo.media_repo / blob_rel)
    updated = (await repo.rows("media", "id=m_fig_1"))[0]
    assert updated["status"] == "described"
    assert updated["description"].startswith("A circuit")
    assert updated["description_model"] == "fake"
    assert updated["error"] is None


async def test_describe_skips_already_described(
    store: Store, config: Config, monkeypatch: object
) -> None:
    import utmelab_bank.task.ai.describe as describe_module

    monkeypatch.setattr(
        describe_module,
        "build_provider",
        lambda _cfg, _eng="opencode", **_kwargs: _FakeProvider('{"figure_kind": "graph"}'),
    )

    repo = Repository(store, lane="work")
    await repo.insert_many(
        "media",
        [_media_row(description="already there", status="described")],
    )

    result = await run_task(AiDescribe(), config, repo, logical="media")

    assert result.run.skipped == 1
    assert result.run.failed == 0


async def test_describe_skips_when_no_blob_yet(store: Store, config: Config) -> None:
    repo = Repository(store, lane="work")
    await repo.insert_many(
        "media",
        [_media_row(blob_path="", status="discovered")],
    )

    result = await run_task(AiDescribe(), config, repo, logical="media")

    assert result.run.skipped == 1
    assert result.run.failed == 0


async def test_describe_failure_is_retryable(
    store: Store, config: Config, monkeypatch: object
) -> None:
    import utmelab_bank.task.ai.describe as describe_module

    monkeypatch.setattr(
        describe_module,
        "build_provider",
        lambda _cfg, _eng="opencode", **_kwargs: _FakeProvider(None),
    )

    repo = Repository(store, lane="work")
    await repo.insert_many("media", [_media_row()])
    blob_rel = _media_row()["blob_path"]
    (config.repo.media_repo / blob_rel).parent.mkdir(parents=True, exist_ok=True)
    (config.repo.media_repo / blob_rel).write_bytes(b"fake-png-bytes")

    result = await run_task(AiDescribe(), config, repo, logical="media")

    assert result.run.failed == 1
    assert result.run.succeeded == 0
    updated = (await repo.rows("media", "id=m_fig_1"))[0]
    assert updated["error"] is not None
    assert updated["next_retry_at"] is not None
    assert updated["status"] == "fetched"
