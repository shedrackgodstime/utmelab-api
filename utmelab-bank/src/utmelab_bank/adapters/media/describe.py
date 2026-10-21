"""Describe image capability: run image describers on media assets."""

from utmelab_bank.adapters.providers import OpenCodeProvider
from utmelab_bank.config import DEFAULT_AI_IMAGE_MODEL, DEFAULT_AI_IMAGE_SECOND_MODEL
from utmelab_bank.domain.capabilities import DescribeImageRequest
from utmelab_bank.domain.enums import State
from utmelab_bank.domain.models import Producer, StagingItem
from utmelab_bank.domain.ports import ImageDescriber

from .consensus import DescribeImageConsensus


class ImageDescriberService:
    """Orchestrate image description for staging items."""

    def __init__(self, describer: ImageDescriber) -> None:
        self.describer = describer

    async def describe(self, item: "StagingItem") -> "StagingItem":
        """Describe every media asset, then move the row to described.

        A row can reach this step with no assets, when every ref was skipped.
        It still moves on, because ``media_ready`` leads only to ``described``,
        and a skipped figure is a figure the row keeps as a source url rather
        than one it carries.
        """
        descriptions = []
        for asset in item.media_assets:
            request = DescribeImageRequest(asset=asset, context=None)
            description = await self.describer.describe(request)
            descriptions.append(description)

        # Update evidence with descriptions
        evidence = item.evidence.model_copy(update={"image_descriptions": tuple(descriptions)})

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
