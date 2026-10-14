"""Promotion engine: converts verified staging items into canonical RichText and writes to the Pipeline DB approved queue.

IMPORTANT SAFETY INVARIANT:
The production database (TURSO_PROD_DB_*) is STRICTLY READ-ONLY to this pipeline.
All promotion writes go to `approved_questions` and `approved_verifications` inside the
DEDICATED PIPELINE DATABASE for tracking, auditing, and final human review before production merge.
"""

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional
from pipeline.storage.client import TursoClient


def compute_content_hash(stem_text: str, options: List[Dict[str, Any]], answer_id: str) -> str:
    """Computes content_hash matching utmelab-api Rust store invariant.
    
    Formula: SHA-256 of:
      stem_text + '|' + sorted(option_id + ':' + option_text) + '|' + answer_id
    """
    sorted_opts = sorted(
        [
            f"{opt['id']}:{opt['text'].get('text', '') if isinstance(opt['text'], dict) else str(opt['text'])}"
            for opt in options
        ]
    )
    payload = f"{stem_text}|{'|'.join(sorted_opts)}|{answer_id}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def to_rich_text(text: str, inline_marks: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return {
        "text": text,
        "inline": inline_marks or [],
    }


class PipelinePromoter:
    """Promotes approved staging questions into the Pipeline DB approved tables (never writes to prod)."""

    def __init__(self, pipeline_client: TursoClient):
        self.pipeline_db = pipeline_client

    async def promote(
        self,
        staging_row: Dict[str, Any],
        subtopic_id: str,
        detected_marks: Optional[List[Dict[str, Any]]] = None,
        verifier: str = "opencode/pipeline_v2",
    ) -> str:
        """Promotes one staging question into approved_questions & approved_verifications in Pipeline DB."""
        raw_options = (
            json.loads(staging_row["options_raw"])
            if isinstance(staging_row["options_raw"], str)
            else staging_row["options_raw"]
        )
        formatted_options = [
            {"id": opt["id"], "text": to_rich_text(opt["text"])}
            for opt in raw_options
        ]

        stem_text = staging_row["stem_raw"]
        stem_rich = to_rich_text(stem_text, detected_marks)

        # Parse proposed explanation
        explanation_obj = None
        if staging_row.get("proposed_explanation"):
            exp_data = (
                json.loads(staging_row["proposed_explanation"])
                if isinstance(staging_row["proposed_explanation"], str)
                else staging_row["proposed_explanation"]
            )
            explanation_obj = {
                "key_point": to_rich_text(exp_data.get("key_point", "")),
                "body": to_rich_text(exp_data.get("body", "")),
                "trap": to_rich_text(exp_data.get("trap", "")) if exp_data.get("trap") else None,
            }

        staging_id = staging_row["id"]
        qid = staging_id.replace("stage_", "")
        exam = staging_row["exam"]
        subject = staging_row["subject"]
        year = int(staging_row["year"])
        answer = staging_row["answer_raw"].lower()
        marks = 2.5 if exam.upper() == "JAMB" else 2.0
        difficulty = 2

        content_hash = compute_content_hash(stem_text, formatted_options, answer)
        now_iso = datetime.now(timezone.utc).isoformat()

        # 1. Insert into Pipeline DB approved_questions table
        q_sql = """
        INSERT OR REPLACE INTO approved_questions (
            id, staging_id, exam, subject, year, source, text, inline, options, answer,
            subtopic_id, section, passage_id, explanation, marks, difficulty, content_hash, approved_at
        ) VALUES (?, ?, ?, ?, ?, 'claimed_paper', ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?)
        """
        await self.pipeline_db.execute(
            q_sql,
            [
                qid,
                staging_id,
                exam,
                subject,
                year,
                stem_rich["text"],
                json.dumps(stem_rich["inline"]),
                json.dumps(formatted_options),
                answer,
                subtopic_id,
                json.dumps(explanation_obj) if explanation_obj else None,
                marks,
                difficulty,
                content_hash,
                now_iso,
            ],
        )

        # 2. Insert into Pipeline DB approved_verifications table
        v_id = f"v_{content_hash[:16]}"
        v_sql = """
        INSERT OR REPLACE INTO approved_verifications (
            id, question_id, kind, verdict, scope, verifier, detail, content_hash, created_at
        ) VALUES (?, ?, 'ai_bulk', 'pass', '["answer", "subtopic"]', ?, 'Verified via utmelab-pipeline', ?, ?)
        """
        await self.pipeline_db.execute(v_sql, [v_id, qid, verifier, content_hash, now_iso])

        # 3. Mark staging row as approved_for_prod in Pipeline DB
        await self.pipeline_db.execute(
            "UPDATE harvest_staging SET pipeline_status = 'approved_for_prod', updated_at = ? WHERE id = ?",
            [now_iso, staging_id],
        )

        return qid


# Backwards compatibility alias
ProductionPromoter = PipelinePromoter
