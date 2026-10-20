"""Describe image capability: run image describers on media assets."""

from utmelab_pipeline.adapters.providers import OpenCodeProvider
from utmelab_pipeline.adapters.providers.mock import MockProvider
from utmelab_pipeline.domain.capabilities import DescribeImageRequest
from utmelab_pipeline.domain.models import MediaAsset, StagingItem
from utmelab_pipeline.domain.ports import ImageDescriber


class ImageDescriberService:
    """Orchestrate image description for staging items."""

    def __init__(self, describer: ImageDescriber) -> None:
        self.describer = describer

    async def describe(self, item: "StagingItem") -> "StagingItem":
        """Describe all media assets in the item."""
        if not item.media_assets:
            return item

        descriptions = []
        for asset in item.media_assets:
            request = DescribeImageRequest(asset=asset, context=None)
            description = await self.describer.describe(request)
            descriptions.append(description)

        # Update evidence with descriptions
        evidence = item.evidence.model_copy(update={
            "image_descriptions": tuple(descriptions)
        })

        return item.model_copy(
            update={
                "evidence": evidence,
                "state": "described",
                "updated_at": __import__("datetime").datetime.now(__import__("datetime").UTC),
            }
        )


def create_describer(provider_name: str = "opencode") -> "ImageDescriber":
    """Factory for image describer implementations."""
    if provider_name == "mock":
        from utmelab_pipeline.adapters.providers.mock import MockProvider
        return MockProvider()
    elif provider_name == "opencode":
        return OpenCodeProvider(model="opencode/deepseek-v4.1-flash-free")
    else:
        raise ValueError(f"Unknown describer: {provider_name}")