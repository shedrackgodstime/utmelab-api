"""media-verify: a second, image-bound check on a figure description.

The important test is the negative control: a plausible description that names
the wrong values must come back failed, with the wrong claim named. A verifier
that only ever passes is decoration.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from utmelab_bank.config import Config
from utmelab_bank.model.base import now_iso
from utmelab_bank.store.client import Store
from utmelab_bank.store.repository import Repository
from utmelab_bank.task import run_task
from utmelab_bank.task.ai.media_verify import MediaVerify
from utmelab_bank.task.ai.media_verify_schema import (
    MediaVerifyOutput,
    MediaVerifyResult,
    media_verify_output_from_text,
)
from utmelab_bank.task.ai.media_verify_tasks import verify_media


def _reply(**over: Any) -> str:
    payload: dict[str, Any] = {
        "verdict": "pass",
        "fidelity": "pass",
        "fit": "pass",
        "confidence": 0.9,
        "claims": [
            {
                "claim": "the inductor is 0.5H",
                "status": "supported",
                "evidence": "label 0.5H beside the coil",
            }
        ],
        "reasoning": "the attached figure shows a 0.5H inductor in series with a 45 ohm resistor.",
    }
    payload.update(over)
    return json.dumps(payload)


PASS = _reply()
WRONG = _reply(
    claims=[
        {
            "claim": "the inductor is 2H",
            "status": "contradicted",
            "evidence": "the figure is labelled 0.5H",
        },
        {
            "claim": "the resistor is 10 ohms",
            "status": "contradicted",
            "evidence": "the figure is labelled 45 ohms",
        },
    ],
    reasoning="the description names 2H and 10 ohms; the figure shows 0.5H and 45 ohms.",
)


class _FakeProvider:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.image: str | None = None
        self.name = "fake"

    async def complete(self, _prompt: str, *, image: str | None = None) -> str:
        self.image = image
        return self.reply

    async def aclose(self) -> None:
        return None


def _media_row(**over: Any) -> dict[str, Any]:
    stamp = now_iso()
    digest = hashlib.sha256(b"fig-bytes").hexdigest()
    row: dict[str, Any] = {
        "id": "m_media_test.png",
        "source_url": "https://cdn.example/media-test.png",
        "question_id": "q_media_test",
        "blob_path": f"media/{digest[:2]}/{digest}.png",
        "derived_path": None,
        "sha256": digest,
        "bytes": 9,
        "media_url": "https://cdn.example/media-test.png",
        "status": "described",
        "description": "A series circuit with a 0.5H inductor, a 45 ohm resistor and a 220V AC source.",
        "description_model": "fake",
        "description_verdict": None,
        "description_verified_at": None,
        "attempts": 0,
        "error": None,
        "next_retry_at": None,
        "run_id": "r_describe",
        "created_at": stamp,
        "updated_at": stamp,
    }
    row.update(over)
    return row


# ---------------------------------------------------------------------------
# Schema: the fail-closed rules
# ---------------------------------------------------------------------------


def test_all_supported_claims_pass():
    out = media_verify_output_from_text(PASS, json.loads)
    result = MediaVerifyResult.from_model_output("m1", out)
    assert result.verdict == "pass"


def test_contradicted_claim_downgrades_a_pass():
    out = media_verify_output_from_text(WRONG, json.loads)
    result = MediaVerifyResult.from_model_output("m1", out)
    assert result.verdict == "fail"
    assert "downgraded from pass" in result.reasoning
    assert "2H" in result.reasoning


def test_failed_fidelity_downgrades_a_pass():
    out = media_verify_output_from_text(_reply(fidelity="fail"), json.loads)
    assert MediaVerifyResult.from_model_output("m1", out).verdict == "fail"


def test_failed_fit_downgrades_a_pass():
    out = media_verify_output_from_text(_reply(fit="fail"), json.loads)
    assert MediaVerifyResult.from_model_output("m1", out).verdict == "fail"


def test_pass_without_claims_is_not_evidence():
    out = media_verify_output_from_text(_reply(claims=[]), json.loads)
    result = MediaVerifyResult.from_model_output("m1", out)
    assert result.verdict == "fail"
    assert "no claims" in result.reasoning


def test_pass_without_reasoning_is_not_evidence():
    out = media_verify_output_from_text(_reply(reasoning=""), json.loads)
    result = MediaVerifyResult.from_model_output("m1", out)
    assert result.verdict == "fail"
    assert "no evidence" in result.reasoning


def test_low_confidence_downgrades_a_pass():
    out = media_verify_output_from_text(_reply(confidence=0.3), json.loads)
    result = MediaVerifyResult.from_model_output("m1", out)
    assert result.verdict == "fail"
    assert "confidence" in result.reasoning


def test_unknown_claim_status_becomes_unsupported():
    out = MediaVerifyOutput.model_validate({"claims": [{"claim": "something", "status": "vibes"}]})
    assert out.claims[0].status == "unsupported"


# ---------------------------------------------------------------------------
# Core: the image is attached
# ---------------------------------------------------------------------------


async def test_verify_media_attaches_the_image():
    provider = _FakeProvider(PASS)
    result = await verify_media(
        provider,
        {"id": "m1"},
        "a circuit",
        "calculate the current",
        ["1A"],
        image="/tmp/figure.png",
    )
    assert result.verdict == "pass"
    assert provider.image == "/tmp/figure.png"


async def test_verify_media_surfaces_a_transport_error():
    class _Broken(_FakeProvider):
        async def complete(self, _prompt: str, *, image: str | None = None) -> str:
            raise OSError("network down")

    result = await verify_media(_Broken(PASS), {"id": "m1"}, "a circuit", "", [], image="x")
    assert result.error is not None
    assert "network down" in result.error


# ---------------------------------------------------------------------------
# Task: stamp the verdict, fail closed, stay idempotent
# ---------------------------------------------------------------------------


async def _run(store: Store, config: Config, monkeypatch: Any, reply: str) -> Any:
    import utmelab_bank.task.ai.media_verify as module

    fake = _FakeProvider(reply)
    monkeypatch.setattr(module, "build_provider", lambda *_a, **_k: fake)
    repo = Repository(store, lane="work")
    row = _media_row()
    await repo.insert_many("media", [row])
    blob = config.repo.media_repo / row["blob_path"]
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(b"fig-bytes")
    result = await run_task(MediaVerify(), config, repo, logical="media")
    return repo, row, blob, result, fake


async def test_task_stamps_a_pass(store: Store, config: Config, monkeypatch: Any) -> None:
    repo, row, blob, result, fake = await _run(store, config, monkeypatch, PASS)

    assert result.run.succeeded == 1
    updated = (await repo.rows("media", f"id={row['id']}"))[0]
    assert updated["description_verdict"] == "pass"
    assert updated["status"] == "described"
    assert fake.image == str(blob)

    verifications = await repo.rows("verifications", f"question_id={row['question_id']}")
    assert len(verifications) == 1
    assert verifications[0]["kind"] == "ai_verify"
    assert json.loads(verifications[0]["scope"]) == ["media"]
    assert verifications[0]["verdict"] == "pass"
    detail = json.loads(verifications[0]["detail"])
    assert detail["image_sha256"] == row["sha256"]
    assert detail["claims"][0]["status"] == "supported"


async def test_task_sends_a_failed_description_to_review(
    store: Store, config: Config, monkeypatch: Any
) -> None:
    repo, row, _blob, result, _fake = await _run(store, config, monkeypatch, WRONG)

    assert result.run.succeeded == 1
    updated = (await repo.rows("media", f"id={row['id']}"))[0]
    assert updated["description_verdict"] == "fail"
    assert updated["status"] == "needs_review"

    verifications = await repo.rows("verifications", f"question_id={row['question_id']}")
    assert verifications[0]["verdict"] == "fail"
    detail = json.loads(verifications[0]["detail"])
    assert any(claim["status"] == "contradicted" for claim in detail["claims"])
    assert "0.5H" in detail["reasoning"]


async def test_task_is_idempotent_for_the_same_description(
    store: Store, config: Config, monkeypatch: Any
) -> None:
    repo, row, _blob, _result, _fake = await _run(store, config, monkeypatch, PASS)

    # Rewriting the description clears the verdict, as ai-describe does.
    await repo.update(
        "media",
        row["id"],
        {"description_verdict": None, "description_verified_at": None},
    )

    second = await run_task(MediaVerify(), config, repo, logical="media")
    assert second.run.skipped == 1
    assert second.run.failed == 0


async def test_task_skips_a_row_without_a_description(store: Store, config: Config) -> None:
    repo = Repository(store, lane="work")
    await repo.insert_many("media", [_media_row(description="")])

    result = await run_task(MediaVerify(), config, repo, logical="media")

    assert result.run.skipped == 1
    assert result.run.failed == 0
