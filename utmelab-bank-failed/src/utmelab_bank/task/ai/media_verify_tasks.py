"""The media verification core: provider in, checked verdict out.

Same shape as ``verify_question``: prompt, provider, parse, validate. The
difference is the image. A check that cannot see the figure is not a check, so
``image`` is threaded through to the provider's attachment argument.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from utmelab_bank.task.ai.jsonio import extract_json
from utmelab_bank.task.ai.media_verify_prompt import build_media_verify_prompt
from utmelab_bank.task.ai.media_verify_schema import (
    MediaVerifyResult,
    media_verify_output_from_text,
)
from utmelab_bank.task.ai.providers import Provider

__all__ = ["verify_media"]

log = logging.getLogger(__name__)


async def verify_media(
    provider: Provider,
    media: dict[str, Any],
    description: str,
    stem: str,
    options: list[str],
    *,
    image: str | None = None,
    parse_retries: int = 1,
    parse_backoff: float = 2.0,
) -> MediaVerifyResult:
    """Ask the provider to check one description against one figure."""
    media_id = str(media.get("id", ""))
    prompt = build_media_verify_prompt(stem, options, description)
    last_error: Exception | None = None

    for attempt in range(parse_retries + 1):
        try:
            text = await provider.complete(prompt, image=image)
            out = media_verify_output_from_text(text, extract_json)
            return MediaVerifyResult.from_model_output(media_id, out)
        except ValueError as exc:
            last_error = exc
            if attempt < parse_retries:
                log.warning("%s: parse error (%s); retrying once...", media_id, exc)
                await asyncio.sleep(parse_backoff)
        except Exception as exc:  # noqa: BLE001 — transport failure, not a parse error
            last_error = exc
            break

    return MediaVerifyResult(media_id=media_id, error=f"{type(last_error).__name__}: {last_error}")
