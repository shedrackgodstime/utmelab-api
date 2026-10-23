"""Passages and the media rows that hang off questions.

``MediaRow`` is the one table designed for a second half we have not written
yet. Downloading a figure is step one, uploading it to the media project is
step two, and transforming it before the upload is step three. All three write
columns on this one row, so adding them needs no migration and no second
inventory of what figures exist.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from utmelab_bank.model.base import Timed
from utmelab_bank.model.richtext import RichText

__all__ = ["MediaRow", "MediaStatus", "Passage", "PassageKind"]

PassageKind = Literal["Comprehension", "Data", "Reading"]

MediaStatus = Literal[
    "discovered",
    "fetched",
    "described",
    "uploaded",
    "failed",
]


class Passage(Timed):
    """A stimulus several questions share.

    ``kind`` is a closed set because the classifier that assigns it is a
    substring match, and an open set would let a model invent a fourth value
    that nothing downstream knows how to read.
    """

    id: str = Field(min_length=1, max_length=200)
    exam: str
    subject: str
    year: int | None = None
    kind: PassageKind = "Comprehension"
    title: str | None = None
    author: str | None = None
    text: str
    inline: list[dict[str, object]] = []

    @model_validator(mode="after")
    def _has_substance(self) -> Passage:
        """A passage too short to be a stimulus is a parsing accident.

        The threshold matches what the harvester has always used. Two places
        disagreed on it (200 in one, a length check on the stem in the other),
        so the number lives here once.
        """
        if len(self.text.strip()) < 200:
            raise ValueError(f"passage is {len(self.text.strip())} characters, the floor is 200")
        return self

    @property
    def rich(self) -> RichText:
        return RichText(text=self.text)


class MediaRow(Timed):
    """One figure, and everything the pipeline has learned about it.

    ``source_url`` is where it came from and never changes. ``blob_path`` is the
    content addressed path in the clone. ``media_url`` is *our* path, not the
    provider's, so moving off the media project is a config change.
    """

    id: str = Field(min_length=1, max_length=200)
    source_url: str = Field(min_length=1)
    question_id: str | None = None

    blob_path: str | None = None
    derived_path: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    bytes: int | None = Field(default=None, ge=0)
    media_url: str | None = None

    status: MediaStatus = "discovered"
    description: str | None = None
    description_model: str | None = None

    attempts: int = 0
    error: str | None = None
    next_retry_at: str | None = None

    @model_validator(mode="after")
    def _uploaded_implies_a_url(self) -> MediaRow:
        """A row cannot claim to be uploaded without saying where it went.

        This is what makes the upload task idempotent per row rather than per
        batch, so a push that dies halfway costs nothing on the retry.
        """
        if self.status == "uploaded" and not self.media_url:
            raise ValueError("status uploaded requires media_url")
        return self

    @property
    def is_local(self) -> bool:
        """Whether the bytes exist in the clone."""
        return bool(self.blob_path)
