"""Shared model pieces.

``now_iso`` lives here because the pipeline inlined
``datetime.now(timezone.utc).isoformat()`` in four modules while a helper of the
same name sat unused in its repository. One place, one format, and every
timestamp the API reads is written the same way.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["BankModel", "now_iso", "parse_iso"]


def now_iso() -> str:
    """Utc now, in the format every timestamp column uses.

    Seconds precision with an explicit offset. The API stores ``created_at`` on
    ``verifications`` as text and compares it as text, so precision and offset
    have to be identical on both sides of the join.
    """
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def parse_iso(value: str) -> datetime:
    """Parse a timestamp column back, assuming what :func:`now_iso` writes."""
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class BankModel(BaseModel):
    """Base for every persisted shape.

    ``extra="forbid"`` is the point. A scraped payload with a field we did not
    expect should be refused at the edge rather than silently dropped halfway
    through a write, which is how ``section`` became permanently null in the
    pipeline.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=False,
        validate_assignment=True,
    )

    def to_row(self) -> dict[str, Any]:
        """Flat dict for a parameterised insert.

        Nested values become json strings here and nowhere else, so the
        repository never has to guess whether a column wants text or json.
        """
        import json

        row: dict[str, Any] = {}
        for name, _field in type(self).model_fields.items():
            value = getattr(self, name)
            if isinstance(value, BaseModel):
                row[name] = json.dumps(value.model_dump(mode="json"), separators=(",", ":"))
            elif isinstance(value, list):
                row[name] = json.dumps(
                    [v.model_dump(mode="json") if isinstance(v, BaseModel) else v for v in value],
                    separators=(",", ":"),
                )
            else:
                row[name] = value
        return row

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Self:
        """Rebuild from a database row, parsing the json columns back."""
        import json

        parsed: dict[str, Any] = {}
        for name, field in cls.model_fields.items():
            value = row.get(name)
            if value is None:
                parsed[name] = None
                continue
            annotation = str(field.annotation)
            if (value is not None and "dict" in annotation) or "list" in annotation:
                try:
                    parsed[name] = json.loads(value)
                except (TypeError, ValueError):
                    parsed[name] = value
            else:
                parsed[name] = value
        return cls.model_validate(parsed)


class Identified(BankModel):
    """Anything with a stable id we mint."""

    id: str = Field(min_length=1, max_length=200)


class Timed(BankModel):
    """Anything that records when it happened."""

    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
