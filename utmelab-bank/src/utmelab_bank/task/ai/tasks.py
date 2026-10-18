"""The tagging task: provider in, validated TagResult out.

This module depends only on the ``Provider`` protocol and the schema — never on
a concrete backend — which is what keeps the model API swappable.

Ported from ``tools/utmetag/tasks.py`` with the same parse-retry + underline-
snap behaviour. The key insight it carries: models frequently return the right
underline *word* but a wrong *start* offset, so we trust the word and recompute
the offset from the stem; if the word is not in the stem at all, we drop the
underline rather than ship a hallucinated mark.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from utmelab_bank.task.ai.jsonio import extract_json
from utmelab_bank.task.ai.prompt import build_tagging_prompt
from utmelab_bank.task.ai.providers import Provider
from utmelab_bank.task.ai.schema import (
    ModelOutput,
    TagResult,
    model_output_from_text,
)

__all__ = ["snap_underline", "tag_question"]

log = logging.getLogger(__name__)


def snap_underline(out: ModelOutput, stem: str) -> ModelOutput:
    """Snap a hallucinated/incorrect underline offset to the word's real position.

    Models frequently return the right word but a wrong ``start``. We trust the
    word and recompute the offset; if the word is not in the stem, drop it.
    """
    u = out.underline
    if u is None:
        return out
    if u.word and stem[u.start : u.start + u.len] == u.word:
        return out
    found = stem.find(u.word) if u.word else -1
    if found >= 0:
        u.start = found
        u.len = len(u.word)
    else:
        out.underline = None
    return out


async def tag_question(
    provider: Provider,
    question: dict[str, Any],
    subtopics: list[dict[str, Any]],
    topics: list[dict[str, Any]],
    *,
    parse_retries: int = 1,
    parse_backoff: float = 2.0,
) -> TagResult:
    """Ask the provider to tag one question and validate the reply.

    A malformed reply is retried (models occasionally wrap JSON in prose);
    transport errors surface as an errored ``TagResult`` rather than raising.
    """
    stem = question["text"]["text"]
    last_error: Exception | None = None
    prompt = build_tagging_prompt(question, subtopics, topics)

    for attempt in range(parse_retries + 1):
        try:
            response_text = await provider.complete(prompt)
            model_output = model_output_from_text(response_text, extract_json)
            model_output = snap_underline(model_output, stem)
            return TagResult.from_model_output(question["id"], model_output)
        except ValueError as e:
            last_error = e
            if attempt < parse_retries:
                log.warning("%s: parse error (%s); retrying once...", question["id"], e)
                await asyncio.sleep(parse_backoff)
        except Exception as e:  # noqa: BLE001 — transport failure, not a parse error
            last_error = e
            break

    return TagResult(question_id=question["id"], error=f"{type(last_error).__name__}: {last_error}")
