"""Canonical content values. Facts live here, not model proposals."""

from pydantic import AwareDatetime, Field, HttpUrl

from .common import (
    DomainModel,
    MimeType,
    NonEmptyStr,
    PositiveMarks,
    Sha256,
)


class MediaRef(DomainModel):
    key: NonEmptyStr
    source_url: HttpUrl
    mime: MimeType | None = None
    alt: NonEmptyStr | None = None
    required: bool = False