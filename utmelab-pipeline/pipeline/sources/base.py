"""Base interfaces and data models for pluggable source harvesters."""

from abc import ABC, abstractmethod
from typing import AsyncIterator, List, Optional
from pydantic import BaseModel, Field


class RawOption(BaseModel):
    id: str = Field(description="Option letter: a, b, c, d, e")
    text: str = Field(description="Text of the option")


class RawQuestionPayload(BaseModel):
    source_name: str
    source_url: Optional[str] = None
    source_item_id: Optional[str] = None
    exam: str  # "JAMB" | "WAEC" | "NECO"
    subject: str  # canonical slug e.g. "mathematics"
    year: int  # cohort year e.g. 2025
    stem: str
    options: List[RawOption]
    reported_answer: str
    reported_explanation: Optional[str] = None
    media_url: Optional[str] = None
    section: Optional[str] = None
    passage_text: Optional[str] = None


class BaseHarvester(ABC):
    """Abstract base class that all source crawlers must implement."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Unique identifier for this harvester source."""
        pass

    @property
    @abstractmethod
    def supported_exams(self) -> List[str]:
        """List of exam codes supported by this harvester."""
        pass

    @abstractmethod
    async def crawl(
        self,
        subject: str,
        year: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[RawQuestionPayload]:
        """Asynchronously streams raw questions from the external source."""
        pass
