"""OCR.space image-text enrichment."""

from __future__ import annotations

from typing import Any

import httpx

from utmelab_bank.domain.models import OcrRecord, OcrWord, Producer


class OcrSpaceError(RuntimeError):
    """A classified OCR.space request or response failure."""

    def __init__(
        self, message: str, *, category: str = "provider", status: int | None = None
    ) -> None:
        self.provider = "ocr.space"
        self.category = category
        self.status = status
        label = f"provider={self.provider} category={category}"
        if status is not None:
            label += f" status={status}"
        super().__init__(f"{label}: {message}")


class OcrSpaceClient:
    """Extract text and coordinates without making OCR responsible for vision."""

    endpoint = "https://api.ocr.space/parse/image"

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
        engine: int = 2,
    ) -> None:
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None
        self._timeout = timeout
        self._engine = engine
        self.producer = Producer(provider="ocr.space", model=f"engine-{engine}")

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def extract(
        self,
        *,
        asset_id: str,
        data: bytes,
        mime: str,
    ) -> OcrRecord:
        """OCR one captured image and retain text, coordinates, or the failure."""
        try:
            response = await self._client.post(
                self.endpoint,
                headers={"apikey": self._api_key},
                files={"file": (f"{asset_id}.image", data, mime)},
                data={
                    "language": "eng",
                    "OCREngine": str(self._engine),
                    "isOverlayRequired": "true",
                },
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise OcrSpaceError("request timed out", category="timeout") from exc
        except httpx.HTTPError as exc:
            raise OcrSpaceError(f"transport failed: {exc}", category="transport") from exc

        if response.is_error:
            raise OcrSpaceError(
                _response_message(response),
                category="http",
                status=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise OcrSpaceError("response was not valid JSON", category="protocol") from exc
        if not isinstance(payload, dict):
            raise OcrSpaceError("response must be a JSON object", category="protocol")
        if payload.get("IsErroredOnProcessing"):
            raise OcrSpaceError(
                str(payload.get("ErrorMessage") or payload.get("ErrorDetails") or "OCR failed"),
                category="provider",
            )

        results = payload.get("ParsedResults")
        if not isinstance(results, list):
            raise OcrSpaceError("response had no ParsedResults", category="protocol")
        text_parts: list[str] = []
        words: list[OcrWord] = []
        for result in results:
            if not isinstance(result, dict):
                continue
            parsed = result.get("ParsedText")
            if isinstance(parsed, str) and parsed.strip():
                text_parts.append(parsed.strip())
            _append_words(result.get("TextOverlay"), words)
        return OcrRecord(
            asset_id=asset_id,
            producer=self.producer,
            text="\n".join(text_parts),
            words=tuple(words),
        )


def _append_words(overlay: object, words: list[OcrWord]) -> None:
    if not isinstance(overlay, dict):
        return
    lines = overlay.get("Lines")
    if not isinstance(lines, list):
        return
    for line in lines:
        if not isinstance(line, dict) or not isinstance(line.get("Words"), list):
            continue
        for word in line["Words"]:
            if not isinstance(word, dict) or not isinstance(word.get("WordText"), str):
                continue
            try:
                words.append(
                    OcrWord(
                        text=word["WordText"],
                        left=int(word.get("Left", 0)),
                        top=int(word.get("Top", 0)),
                        width=int(word.get("Width", 0)),
                        height=int(word.get("Height", 0)),
                    )
                )
            except (TypeError, ValueError):
                continue


def _response_message(response: httpx.Response) -> str:
    try:
        payload: Any = response.json()
    except ValueError:
        return response.text[:300] or "OCR request failed"
    if isinstance(payload, dict):
        return str(payload.get("ErrorMessage") or payload.get("message") or payload)
    return str(payload)
