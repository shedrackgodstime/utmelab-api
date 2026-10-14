"""Pydantic schemas for structured AI verification output."""

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class UnderlineProposal(BaseModel):
    target_text: Optional[str] = Field(None, description="The exact text word/phrase that is or should be underlined")
    offset_in_stem: Optional[int] = Field(None, description="Starting character index of target_text in stem")


class ExplanationProposal(BaseModel):
    key_point: str = Field(description="One-sentence core concept, principle, or formula")
    body: str = Field(description="Clear, complete step-by-step reasoning or mathematical working")
    trap: Optional[str] = Field(None, description="Explanation of why wrong options/distractors are tempting")


class QuestionAIResponse(BaseModel):
    subtopic_slug: str = Field(description="Exact subtopic slug from the provided syllabus list")
    answer_check: Literal["VERIFIED", "DISAGREEMENT", "AMBIGUOUS"] = Field(
        description="Whether the recorded answer is correct (VERIFIED) or incorrect (DISAGREEMENT)"
    )
    explanation_quality: Literal["GOOD", "PARTIAL", "POOR", "MISSING"] = Field(
        description="Assessment of the existing explanation"
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0"
    )
    underline: Optional[UnderlineProposal] = None
    explanation: Optional[ExplanationProposal] = None
    reasoning: str = Field(description="Concise audit rationale for the answer and subtopic choice")
