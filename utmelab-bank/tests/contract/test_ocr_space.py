import asyncio

import httpx

from tests.media_fakes import PNG_1X1
from utmelab_bank.adapters.media.ocr_space import OcrSpaceClient, OcrSpaceError


def test_ocr_space_extracts_text_and_word_bounds() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["apikey"] == "test-key"
        return httpx.Response(
            200,
            json={
                "IsErroredOnProcessing": False,
                "ParsedResults": [
                    {
                        "ParsedText": "Question text",
                        "TextOverlay": {
                            "Lines": [
                                {
                                    "Words": [
                                        {
                                            "WordText": "Question",
                                            "Left": 1,
                                            "Top": 2,
                                            "Width": 3,
                                            "Height": 4,
                                        }
                                    ]
                                }
                            ]
                        },
                    }
                ],
            },
        )

    client = OcrSpaceClient(
        "test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    record = asyncio.run(client.extract(asset_id="a" * 64, data=PNG_1X1, mime="image/png"))

    assert record.text == "Question text"
    assert record.words[0].text == "Question"
    assert record.words[0].width == 3


def test_ocr_space_preserves_provider_failure() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "IsErroredOnProcessing": True,
                "ErrorMessage": "file too large",
            },
        )

    client = OcrSpaceClient(
        "test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    try:
        asyncio.run(client.extract(asset_id="a" * 64, data=PNG_1X1, mime="image/png"))
    except OcrSpaceError as exc:
        assert exc.provider == "ocr.space"
        assert exc.category == "provider"
        assert "file too large" in str(exc)
    else:
        raise AssertionError("expected OCR.space failure")
