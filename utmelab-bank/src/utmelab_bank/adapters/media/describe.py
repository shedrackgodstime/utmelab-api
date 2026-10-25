"""Describe image capability: run image describers on media assets."""

from utmelab_bank.adapters.providers import OpenCodeProvider
from utmelab_bank.config import DEFAULT_AI_IMAGE_MODEL, DEFAULT_AI_IMAGE_SECOND_MODEL
from utmelab_bank.domain.capabilities import DescribeImageRequest
from utmelab_bank.domain.enums import State
from utmelab_bank.domain.models import OcrRecord, Producer, StagingItem
from utmelab_bank.domain.ports import ImageDescriber, MediaStore

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
        ocr_records: list[OcrRecord] = []
        for asset in item.media_assets:
            data = await self.reader.read(asset.storage_url) if self.reader is not None else None
            ocr_context: str | None = None
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
                if ocr_record.text:
                    ocr_context = f"OCR text extracted from this image:\n{ocr_record.text}"
            request = DescribeImageRequest(asset=asset, context=ocr_context, data=data)
            description = await self.describer.describe(request)
            descriptions.append(description)

        evidence = item.evidence.model_copy(
            update={
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
