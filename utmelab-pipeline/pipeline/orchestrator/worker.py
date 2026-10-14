"""Batch orchestration worker with bounded concurrency."""

import asyncio
import json
from typing import Any, Dict, List, Optional
from pipeline.ai.prompts import build_verification_prompt
from pipeline.ai.runner import OpenCodeRunner
from pipeline.ai.tasks import parse_and_snap_response
from pipeline.media.downloader import MediaDownloader
from pipeline.orchestrator.promoter import ProductionPromoter
from pipeline.storage.repository import PipelineRepository


class BatchProcessor:
    """Orchestrates parallel question verification, tagging, and promotion."""

    def __init__(
        self,
        repository: PipelineRepository,
        runner: Optional[OpenCodeRunner] = None,
        downloader: Optional[MediaDownloader] = None,
        promoter: Optional[ProductionPromoter] = None,
    ):
        self.repo = repository
        self.runner = runner or OpenCodeRunner()
        self.downloader = downloader or MediaDownloader()
        self.promoter = promoter or PipelinePromoter(self.repo.db)

    async def process_subject(
        self,
        subject: str,
        exam: str = "JAMB",
        limit: int = 50,
        concurrency: int = 4,
        auto_promote: bool = False,
    ) -> Dict[str, Any]:
        """Processes a batch of pending staging questions for a subject."""
        # 1. Fetch authoritative syllabus
        syllabus = await self.repo.fetch_syllabus_from_prod(subject, exam)

        # 2. Fetch pending staging questions
        questions = await self.repo.get_pending_ai_questions(subject, exam, limit=limit)
        if not questions:
            return {
                "total_processed": 0,
                "verified": 0,
                "discrepancies": 0,
                "promoted": 0,
                "errors": 0,
            }

        sem = asyncio.Semaphore(concurrency)
        stats = {
            "total_processed": 0,
            "verified": 0,
            "discrepancies": 0,
            "promoted": 0,
            "errors": 0,
        }

        async def _process_one(q_row: Dict[str, Any]):
            async with sem:
                try:
                    qid = q_row["id"]
                    stem = q_row["stem_raw"]
                    options = json.loads(q_row["options_raw"])
                    answer = q_row["answer_raw"]
                    media_url = q_row.get("media_url")
                    explanation_raw = q_row.get("explanation_raw")

                    # Handle image download if media_url present
                    local_image = None
                    if media_url:
                        local_image = await self.downloader.get_or_download(media_url)

                    # Build prompt
                    prompt = build_verification_prompt(
                        stem=stem,
                        options=options,
                        recorded_answer=answer,
                        subject=subject,
                        syllabus=syllabus,
                        recorded_explanation=explanation_raw,
                        has_image=bool(local_image),
                    )

                    # Execute OpenCode model
                    raw_ai_out = await self.runner.complete(prompt, image_path=local_image)

                    # Parse response & snap underline
                    ai_resp, detected_marks = parse_and_snap_response(raw_ai_out, stem)

                    # Update staging row
                    await self.repo.update_ai_results(
                        question_id=qid,
                        proposed_topic=None,
                        proposed_subtopic=ai_resp.subtopic_slug,
                        answer_verdict=ai_resp.answer_check,
                        explanation_quality=ai_resp.explanation_quality,
                        proposed_explanation=ai_resp.explanation.model_dump() if ai_resp.explanation else None,
                        confidence=ai_resp.confidence,
                        detected_marks=detected_marks,
                        ai_raw_response=raw_ai_out,
                    )

                    stats["total_processed"] += 1

                    if ai_resp.answer_check == "DISAGREEMENT" or ai_resp.confidence < 0.85:
                        stats["discrepancies"] += 1
                        reason = (
                            "answer_mismatch"
                            if ai_resp.answer_check == "DISAGREEMENT"
                            else "low_confidence"
                        )
                        await self.repo.add_to_review_queue(qid, subject, exam, reason)
                    else:
                        stats["verified"] += 1
                        if auto_promote and self.promoter:
                            await self.promoter.promote(
                                staging_row=q_row,
                                subtopic_id=ai_resp.subtopic_slug,
                                detected_marks=detected_marks,
                            )
                            stats["promoted"] += 1

                except Exception as e:
                    stats["errors"] += 1
                    # Flag for review on failure
                    await self.repo.add_to_review_queue(
                        q_row["id"], subject, exam, f"error: {str(e)[:100]}"
                    )

        tasks = [_process_one(q) for q in questions]
        await asyncio.gather(*tasks)

        return stats
