"""Describe image capability: run image describers on media assets."""

from utmelab_bank.adapters.providers import OpenAICompatibleProvider, OpenCodeProvider
from utmelab_bank.config import DEFAULT_AI_IMAGE_MODEL, DEFAULT_AI_IMAGE_SECOND_MODEL
from utmelab_bank.domain.capabilities import DescribeImageRequest
from utmelab_bank.domain.enums import State
from utmelab_bank.domain.models import OcrRecord, Producer, StagingItem
from utmelab_bank.domain.ports import ImageDescriber, MediaStore
from utmelab_bank.routing import select_routes

from .checks import check_media
from .consensus import DescribeImageConsensus
from .ocr_space import OcrSpaceClient, OcrSpaceError


class ImageDescriberService:
    """Orchestrate image description for staging items.

    The asset carries the url the row serves, which is remote. When a reader is
    wired, the service hands the describer the bytes it already holds, so a
    provider never has to turn a served url back into a local file.
    """

    def __init__(
        self,
        describer: ImageDescriber,
        reader: MediaStore | None = None,
        ocr: OcrSpaceClient | None = None,
    ) -> None:
        self.describer = describer
        self.reader = reader
        self.ocr = ocr

    async def describe(self, item: "StagingItem") -> "StagingItem":
        """Describe every media asset, then move the row to described.

        A row can reach this step with no assets, when every ref was skipped.
        It still moves on, because ``media_ready`` leads only to ``described``,
        and a skipped figure is a figure the row keeps as a source url rather
        than one it carries.
        """
        descriptions = []
        media_checks = []
        ocr_records: list[OcrRecord] = []
        for asset in item.media_assets:
            data = await self.reader.read(asset.storage_url) if self.reader is not None else None
            ocr_context: str | None = None
            ocr_text: str | None = None
            ocr_error: str | None = None
            if self.ocr is not None and data is not None:
                try:
                    ocr_record = await self.ocr.extract(
                        asset_id=asset.asset_id,
                        data=data,
                        mime=asset.mime,
                    )
                except OcrSpaceError as exc:
                    ocr_record = OcrRecord(
                        asset_id=asset.asset_id,
                        producer=self.ocr.producer,
                        error=str(exc),
                    )
                ocr_records.append(ocr_record)
                ocr_text = ocr_record.text
                ocr_error = ocr_record.error
                if ocr_record.text:
                    ocr_context = f"OCR text extracted from this image:\n{ocr_record.text}"
            if data is not None:
                media_checks.append(
                    check_media(
                        asset,
                        data,
                        ocr_text=ocr_text,
                        ocr_error=ocr_error,
                    )
                )
            request = DescribeImageRequest(asset=asset, context=ocr_context, data=data)
            description = await self.describer.describe(request)
            descriptions.append(description)

        evidence = item.evidence.model_copy(
            update={
                "media_checks": tuple(media_checks),
                "ocr": tuple(ocr_records),
                "image_descriptions": tuple(descriptions),
            }
        )

        updated = item.model_copy(update={"evidence": evidence})
        return updated.transition_to(State.DESCRIBED)


def create_describer(
    *,
    provider: str = "opencode",
    model: str = DEFAULT_AI_IMAGE_MODEL,
    second_model: str = DEFAULT_AI_IMAGE_SECOND_MODEL,
    api_key: str | None = None,
    base_url: str | None = None,
) -> "ImageDescriber":
    """The two-witness describer for figures.

    One model twice is not an independent witness, so the two ids must differ
    and the pair is built here rather than discovered later as a consensus that
    agrees with itself.
    """
    if provider == "mock":
        from utmelab_bank.adapters.providers.mock import MockProvider

        return DescribeImageConsensus(
            (
                MockProvider(),
                MockProvider(producer=Producer(provider="mock", model="mock-v2")),
            )
        )
    if provider == "openai":
        if not api_key or not base_url:
            raise ValueError("the openai-compatible describer needs an API key and base URL")
        if not model or not second_model or model == second_model:
            raise ValueError("a figure needs two different models to witness it")
        return DescribeImageConsensus(
            (
                OpenAICompatibleProvider(api_key=api_key, base_url=base_url, model=model),
                OpenAICompatibleProvider(api_key=api_key, base_url=base_url, model=second_model),
            )
        )
    if provider != "opencode":
        raise ValueError(f"Unknown describer: {provider}")
    if not model or not second_model or model == second_model:
        raise ValueError("a figure needs two different models to witness it")
    return DescribeImageConsensus(
        (
            OpenCodeProvider(model=model),
            OpenCodeProvider(model=second_model),
        )
    )


def create_configured_describer() -> "ImageDescriber":
    """Build the image consensus from the validated provider manifest."""
    routes = select_routes("image_description")
    if len(routes) < 2:
        raise ValueError("the provider manifest has fewer than two usable image witnesses")
    return DescribeImageConsensus(
        tuple(
            OpenAICompatibleProvider(
                api_key=route.api_key,
                base_url=route.base_url,
                model=route.model_id,
                provider_name=route.provider,
                account_id=route.account_id,
            )
            for route in routes[:2]
        )
    )
