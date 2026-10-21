"""Describe image capability: run image describers on media assets."""

from utmelab_bank.adapters.providers import OpenCodeProvider
from utmelab_bank.domain.capabilities import DescribeImageRequest
from utmelab_bank.domain.enums import State
from utmelab_bank.domain.models import StagingItem
from utmelab_bank.domain.ports import ImageDescriber


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


def create_describer(provider_name: str = "opencode") -> "ImageDescriber":
    """Factory for image describer implementations."""
    if provider_name == "mock":
        from utmelab_bank.adapters.providers.mock import MockProvider

        return MockProvider()
    elif provider_name == "opencode":
        return OpenCodeProvider(model="opencode/deepseek-v4.1-flash-free")
    else:
        raise ValueError(f"Unknown describer: {provider_name}")
