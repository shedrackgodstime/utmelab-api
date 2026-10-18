"""The verify core: provider in, validated VerifyResult out.

Same shape as ``tag_question`` and ``explain_question``: prompt → provider →
parse → validate → result. A malformed reply is retried once; transport
failures surface as an errored result rather than raising.

A fail verdict is data, not an error: the row is recorded and left for a
human, which is why this function never raises for a judgement.
"""

from __future__ import annotations

import asyncio
import logging

from utmelab_bank.task.ai.jsonio import extract_json
from utmelab_bank.task.ai.providers import Provider
from utmelab_bank.task.ai.verify_prompt import build_verify_prompt
from utmelab_bank.task.ai.verify_schema import (
    VerifyResult,
    verify_output_from_text,
)

__all__ = ["verify_question"]

log = logging.getLogger(__name__)


async def verify_question(
    provider: Provider,
    question_id: str,
    stem: str,
    options: list[str],
    answer: str,
    key_point: str,
    body: str,
    trap: str,
    subtopic: str,
    *,
    parse_retries: int = 1,
    parse_backoff: float = 2.0,
) -> VerifyResult:
    """Ask the provider to verify one question and validate the reply."""
    last_error: Exception | None = None
    prompt = build_verify_prompt(stem, options, answer, key_point, body, trap, subtopic)

    for attempt in range(parse_retries + 1):
        try:
            response_text = await provider.complete(prompt)
            model_output = verify_output_from_text(response_text, extract_json)
            return VerifyResult.from_model_output(question_id, model_output)
        except ValueError as e:
            last_error = e
            if attempt < parse_retries:
                log.warning("%s: parse error (%s); retrying once...", question_id, e)
                await asyncio.sleep(parse_backoff)
        except Exception as e:  # noqa: BLE001 — transport failure, not a parse error
            last_error = e
            break

    return VerifyResult(question_id=question_id, error=f"{type(last_error).__name__}: {last_error}")
