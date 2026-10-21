"""Selectors choose bundles by lifecycle state and scope. They are data, not logic."""

from pydantic import Field

from .enums import State
from .models import DomainModel, NonEmptyStr, Slug, StagingItem, Year


class Selector(DomainModel):
    state: State
    limit: int = Field(default=100, ge=1, le=1000)
    source: Slug | None = None
    exam: NonEmptyStr | None = None
    subject: NonEmptyStr | None = None
    year: Year | None = None
    has_media: bool | None = None

    def matches(self, item: StagingItem) -> bool:
        if item.state != self.state:
            return False
        if self.source is not None and item.provenance.source != self.source:
            return False
        scope = item.provenance.scope
        if self.exam is not None and scope.exam != self.exam:
            return False
        if self.subject is not None and scope.subject != self.subject:
            return False
        if self.year is not None and scope.year != self.year:
            return False
        return self.has_media is None or bool(item.media_assets) == self.has_media
