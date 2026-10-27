"""Describe image capability: run image describers on media assets."""

from utmelab_bank.adapters.providers import OpenAICompatibleProvider, OpenCodeProvider
from utmelab_bank.adapters.providers.factory import create_from_route
from utmelab_bank.config import (
    DEFAULT_AI_IMAGE_MODEL,
    DEFAULT_AI_IMAGE_SECOND_MODEL,
    ConfigError,
)
from utmelab_bank.domain.capabilities import DescribeImageRequest
from utmelab_bank.domain.enums import State
from utmelab_bank.domain.models import OcrRecord, StagingItem
from utmelab_bank.domain.ports import ImageDescriber, MediaStore
from utmelab_bank.routing import ProviderRoute, select_routes, task_policy

from .checks import check_media
from .consensus import DescribeImageConsensus
from .errors import InsufficientWitnesses
from .ocr_space import OcrSpaceClient, OcrSpaceError

#: A consensus cannot be built from one model, whatever the policy says.
MINIMUM_CONSENSUS_WITNESSES = 2


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

    async def describe(self, item: StagingItem) -> StagingItem:
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
) -> ImageDescriber:
    """The two-witness describer for figures.

    One model twice is not an independent witness, so the two ids must differ
    and the pair is built here rather than discovered later as a consensus that
    agrees with itself.
    """
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


def distinct_witnesses(routes: tuple[ProviderRoute, ...]) -> tuple[ProviderRoute, ...]:
    """Collapse the resolved routes to one route per model, in priority order.

    ``select_routes`` expands every authorized account, so two routes can be
    the same model on two keys. Those are not two witnesses, and the consensus
    would refuse the pair anyway; dropping the duplicate here keeps the first
    account as the model's route and moves on to the next model.
    """
    seen: set[tuple[str, str]] = set()
    chosen: list[ProviderRoute] = []
    for route in routes:
        identity = (route.provider, route.model_id)
        if identity in seen:
            continue
        seen.add(identity)
        chosen.append(route)
    return tuple(chosen)


def create_configured_describer() -> ImageDescriber:
    """Build the image consensus from the routing file's own policy.

    The policy decides how many witnesses are needed and whether they must be
    different models. A configuration that cannot supply them is refused with
    a named error before a figure is touched, because a single witness is not
    a check and describing the figure anyway would record one.
    """
    policy = task_policy("image_description")
    if policy.strategy != "consensus":
        raise ConfigError(
            f"image_description strategy is {policy.strategy!r}; "
            "only 'consensus' can build a figure describer"
        )
    if policy.on_insufficient_witnesses != "block":
        raise ConfigError(
            "image_description must set on_insufficient_witnesses to 'block', "
            f"not {policy.on_insufficient_witnesses!r}"
        )
    if not policy.require_distinct_models:
        raise ConfigError(
            "image_description must require distinct models; two runs of one "
            "model agree because they are the same model"
        )

    needed = max(MINIMUM_CONSENSUS_WITNESSES, policy.minimum_successful_witnesses)
    routes = distinct_witnesses(select_routes("image_description"))
    if len(routes) < needed:
        raise InsufficientWitnesses(
            f"image_description needs {needed} distinct model witnesses and "
            f"the routing resolved {len(routes)}",
            hint="authorize another model in config/routing.json and its provider manifest",
            task=policy.task,
            required=needed,
            resolved=len(routes),
        )
    return DescribeImageConsensus(tuple(create_from_route(route) for route in routes[:needed]))
