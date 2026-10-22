"""The tagging task: provider in, validated TagResult out.

This module depends only on the ``Provider`` protocol and the schema — never on
a concrete backend — which is what keeps the model API swappable.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from .jsonio import extract_json
from .prompt import build_tagging_prompt
from .providers.base import Provider
from .schema import (
    ModelOutput,
    QuestionInput,
    SubtopicInfo,
    TagResult,
    TopicInfo,
    model_output_from_text,
)


def _snap_underline(data: ModelOutput, stem: str) -> ModelOutput:
    """Snap a hallucinated/incorrect underline offset to the word's real position.

    Models frequently return the right word but a wrong ``start``. We trust the
    word and recompute the offset; if the word is not in the stem, drop it.
    """
    u = data.underline
    if u is None:
        return data
    if u.word and stem[u.start:u.start + u.len] == u.word:
        return data
    found = stem.find(u.word) if u.word else -1
    if found >= 0:
        u.start = found
        u.len = len(u.word)
    else:
        data.underline = None
    return data


async def tag_question(
    provider: Provider,
    question: QuestionInput,
    subtopics: list[SubtopicInfo],
    topics: list[TopicInfo],
    parse_retries: int = 1,
    parse_backoff: float = 2.0,
) -> TagResult:
    """Ask the provider to tag one question and validate the reply.

    A malformed reply is retried (models occasionally wrap JSON in prose);
    transport errors surface as an errored ``TagResult`` rather than raising.
    """
    stem = question.text.get("text", "")
    last_error: Optional[Exception] = None
    prompt = build_tagging_prompt(question, subtopics, topics)

    for attempt in range(parse_retries + 1):
        try:
            response_text = await provider.complete(prompt)
            model_output = model_output_from_text(response_text, extract_json)
            model_output = _snap_underline(model_output, stem)
            return TagResult.from_model_output(question.id, model_output)
        except (ValueError,) as e:
            last_error = e
            if attempt < parse_retries:
                print(f"  {question.id}: parse error ({e}); retrying once...")
                await asyncio.sleep(parse_backoff)
        except Exception as e:  # noqa: BLE001 - transport failure
            last_error = e
            break

    return TagResult(question_id=question.id, error=f"{type(last_error).__name__}: {last_error}")
