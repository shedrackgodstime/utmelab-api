"""The describe core: provider in, validated DescribeResult out.

Same shape as ``tag_question``: a text prompt plus the figure's local path
handed to the provider's ``describe`` entry point, a malformed reply retried,
transport errors surfacing as an errored result rather than raising.

The image model is ``config.ai_image_model`` when set, else ``config.ai_model``:
the free text model answers figure questions acceptably, and forcing a second
model key before anyone has one would make describe unrunnable.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from utmelab_bank.task.ai.describe_prompt import build_describe_prompt
from utmelab_bank.task.ai.describe_schema import (
    DescribeResult,
    describe_output_from_text,
)
from utmelab_bank.task.ai.jsonio import extract_json
from utmelab_bank.task.ai.providers import Provider

__all__ = ["describe_figure"]

log = logging.getLogger(__name__)


async def describe_figure(
    provider: Provider,
    media: dict[str, Any],
    stem: str,
    options: list[str],
    *,
    parse_retries: int = 1,
    parse_backoff: float = 2.0,
) -> DescribeResult:
    """Ask the provider to describe one figure and validate the reply."""
    media_id = str(media.get("id", ""))
    last_error: Exception | None = None
    prompt = build_describe_prompt(stem, options)

    for attempt in range(parse_retries + 1):
        try:
            response_text = await provider.complete(prompt)
            model_output = describe_output_from_text(response_text, extract_json)
            if not model_output.description:
                raise ValueError("the model returned an empty description")
            return DescribeResult.from_model_output(media_id, model_output)
        except ValueError as e:
            last_error = e
            if attempt < parse_retries:
                log.warning("%s: parse error (%s); retrying once...", media_id, e)
                await asyncio.sleep(parse_backoff)
        except Exception as e:  # noqa: BLE001 — transport failure, not a parse error
            last_error = e
            break

    return DescribeResult(media_id=media_id, error=f"{type(last_error).__name__}: {last_error}")
