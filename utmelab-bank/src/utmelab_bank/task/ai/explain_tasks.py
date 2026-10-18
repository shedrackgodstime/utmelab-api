"""The explain core: provider in, validated ExplainResult out.

Same shape as ``tag_question`` and ``describe_figure``: prompt → provider →
parse → validate → result. A malformed reply is retried once; transport
failures surface as an errored result rather than raising.
"""

from __future__ import annotations

import asyncio
import logging

from utmelab_bank.task.ai.explain_prompt import build_explain_prompt
from utmelab_bank.task.ai.explain_schema import (
    ExplainResult,
    explain_output_from_text,
)
from utmelab_bank.task.ai.jsonio import extract_json
from utmelab_bank.task.ai.providers import Provider

__all__ = ["explain_question"]

log = logging.getLogger(__name__)


async def explain_question(
    provider: Provider,
    question_id: str,
    stem: str,
    options: list[str],
    answer: str,
    *,
    parse_retries: int = 1,
    parse_backoff: float = 2.0,
) -> ExplainResult:
    """Ask the provider to explain one question and validate the reply."""
    last_error: Exception | None = None
    prompt = build_explain_prompt(stem, options, answer)

    for attempt in range(parse_retries + 1):
        try:
            response_text = await provider.complete(prompt)
            model_output = explain_output_from_text(response_text, extract_json)
            if not model_output.body:
                raise ValueError("the model returned an empty explanation")
            return ExplainResult.from_model_output(question_id, model_output)
        except ValueError as e:
            last_error = e
            if attempt < parse_retries:
                log.warning("%s: parse error (%s); retrying once...", question_id, e)
                await asyncio.sleep(parse_backoff)
        except Exception as e:  # noqa: BLE001 — transport failure, not a parse error
            last_error = e
            break

    return ExplainResult(
        question_id=question_id, error=f"{type(last_error).__name__}: {last_error}"
    )
