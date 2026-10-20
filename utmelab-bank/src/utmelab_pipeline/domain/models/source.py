"""What a source declares and what it returns."""

from typing import Any

from pydantic import AwareDatetime, Field, HttpUrl, model_validator

from ..enums import SourceCapability
from .common import DomainModel, NonEmptyStr, Scope, Sha256, Slug, Year


class SourceCapabilities(DomainModel):
    passages: bool = False
    passage_sets: bool = False
    figures: bool = False
    option_figures: bool = False
    rich_text: bool = False
    answer: bool = True
    explanation: bool = False
    sections: bool = False
    marks: bool = False

    def supports(self, capability: SourceCapability) -> bool:
        return bool(getattr(self, capability.value))


class SourceProfile(DomainModel):
    name: Slug
    version: NonEmptyStr
    exams: tuple[NonEmptyStr, ...] = Field(min_length=1)
    subjects: dict[NonEmptyStr, NonEmptyStr] = Field(min_length=1)
    years: tuple[Year, Year] | None = None
    capabilities: SourceCapabilities
    rate_limit_per_second: float = Field(default=1.0, gt=0.0)
    health_url: HttpUrl | None = None

    @model_validator(mode="after")
    def _check(self) -> "SourceProfile":
        if len(set(self.exams)) != len(self.exams):
            raise ValueError("exams must be unique")
        if self.years is not None and self.years[0] > self.years[1]:
            raise ValueError("years must be ordered low to high")
        return self


class Coverage(DomainModel):
    source: Slug
    scope: Scope
    item_count: int = Field(ge=0)
    has_more: bool = False
    notes: NonEmptyStr | None = None


class SourceItem(DomainModel):
    source: Slug
    source_url: HttpUrl
    source_item_id: NonEmptyStr
    fetched_at: AwareDatetime
    payload: dict[str, Any]
    payload_hash: Sha256
    scope: Scope
    source_version: NonEmptyStr

    @property
    def external_key(self) -> str:
        return f"{self.source}:{self.source_item_id}"
