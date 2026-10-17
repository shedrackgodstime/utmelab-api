"""The question, in the shape the API reads it.

The column list here is the pipeline's ``approved_questions`` table, minus the
staging bookkeeping. The API's ``READ_SHAPES`` entry for ``questions`` is the
authority on the other half of that agreement, and ``contract/check.py``
compares the two, so a column added here without a matching read shape fails
before it reaches production.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from utmelab_bank.model.base import BankModel, Timed
from utmelab_bank.model.richtext import Mark, Option, RichText

__all__ = ["Question", "GateStatus", "QUESTION_COLUMNS"]

#: Stamped by ``store.Repository`` on the way into a lane, because the hash is a
#: boundary field owned by ``contract.content_hash``.

GateStatus = Literal["pending", "pass", "refused", "unreviewed"]


class Question(Timed):
    """One row of the bank.

    ``gate_status`` and the review fields live in the work lane and are dropped
    on promotion, so they are optional here rather than a second model that has
    to be kept in step.
    """

    id: str = Field(min_length=1, max_length=200)
    exam: str = Field(min_length=1, max_length=40)
    subject: str = Field(min_length=1, max_length=80)
    year: int | None = Field(default=None, ge=1980, le=2100)
    source: str = Field(default="claimed_paper", max_length=80)

    text: RichText
    options: list[Option] = Field(min_length=2, max_length=10)
    answer: str = Field(min_length=1, max_length=8)

    subtopic_id: str | None = None
    section: str | None = None
    passage_id: str | None = None
    explanation: dict[str, RichText | None] | None = None
    marks: float = Field(default=1.0, ge=0.0, le=100.0)
    difficulty: int = Field(default=3, ge=1, le=5)
    content_hash: str = ""

    gate_status: GateStatus = "pending"
    gate_reason: str | None = None

    @model_validator(mode="after")
    def _answer_names_an_option(self) -> Self:
        """A key that points at nothing is the single most common bad row.

        The pipeline refused these at a gate after writing them, so they
        accumulated in staging and were counted in metrics. Refusing here means
        the row never exists.
        """
        known = {opt.id for opt in self.options}
        if self.answer not in known:
            raise ValueError(f"answer {self.answer!r} is not one of {sorted(known)}")
        return self

    @model_validator(mode="after")
    def _option_ids_unique(self) -> Self:
        ids = [opt.id for opt in self.options]
        if len(set(ids)) != len(ids):
            raise ValueError("option ids must be unique")
        return self


    @model_validator(mode="after")
    def _hash_is_stamped_not_computed(self) -> Self:
        """The content hash is stamped at write time, not computed here.

        It is the boundary field the API joins on, so it belongs to the contract
        layer, and the model layer must not depend on the contract layer or the
        two import each other. ``store.Repository`` stamps it on the way in.
        """
        return self

    @property
    def images(self) -> list[Mark]:
        """Every image mark on the stem and on the options."""
        found = [m for m in self.text.inline if m.kind == "image" and m.url]
        for opt in self.options:
            found.extend(m for m in opt.text.inline if m.kind == "image" and m.url)
        return found

    @property
    def has_figure_hint(self) -> bool:
        """The stem talks about a figure. If so, an image mark is required.

        This is the rule that decides a row is unusable, and it existed in four
        places with three different regexes before. One function, here.
        """
        from utmelab_bank.text.htmltext import mentions_figure

        return mentions_figure(self.text.text) or any(
            mentions_figure(opt.text.text) for opt in self.options
        )


#: Every column a question row has, in the API's order. ``contract/check.py``
#: compares this against ``READ_SHAPES`` for ``questions``.
QUESTION_COLUMNS: tuple[str, ...] = (
    "id",
    "exam",
    "subject",
    "year",
    "source",
    "text",
    "inline",
    "options",
    "answer",
    "subtopic_id",
    "section",
    "passage_id",
    "explanation",
    "marks",
    "difficulty",
    "content_hash",
)
