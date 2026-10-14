"""Promotion engine: converts verified staging items into canonical RichText and writes to production Turso."""

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
        [f"{opt['id']}:{opt['text'].get('text', '') if isinstance(opt['text'], dict) else str(opt['text'])}" for opt in options]
    )
    payload = f"{stem_text}|{'|'.join(sorted_opts)}|{answer_id}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def to_rich_text(text: str, inline_marks: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return {
        "text": text,
        "inline": inline_marks or [],
    }


class ProductionPromoter:
    """Promotes approved staging questions into the live Production Turso database."""

    def __init__(self, prod_client: TursoClient):
        self.prod_db = prod_client

    async def promote(
        self,
        staging_row: Dict[str, Any],
        subtopic_id: str,
        detected_marks: Optional[List[Dict[str, Any]]] = None,
        verifier: str = "opencode/pipeline_v2",
    ) -> str:
        """Promotes one staging question into production questions & verifications tables."""
        raw_options = json.loads(staging_row["options_raw"])
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

        qid = staging_row["id"].replace("stage_", "")
        exam = staging_row["exam"]
        subject = staging_row["subject"]
        year = int(staging_row["year"])
        answer = staging_row["answer_raw"].lower()
        marks = 2.5 if exam.upper() == "JAMB" else 2.0
        difficulty = 2

        content_hash = compute_content_hash(stem_text, formatted_options, answer)

        # 1. Insert into production questions table
        q_sql = """
        INSERT OR REPLACE INTO questions (
            id, exam, subject, year, source, text, inline, options, answer,
            subtopic_id, section, passage_id, explanation, marks, difficulty, content_hash
        ) VALUES (?, ?, ?, ?, 'claimed_paper', ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?)
        """
        await self.prod_db.execute(
            q_sql,
            [
                qid,
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
            ],
        )

        # 2. Append to production verifications table (D62)
        v_id = f"v_{content_hash[:16]}"
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()

        v_sql = """
        INSERT OR REPLACE INTO verifications (
            id, question_id, kind, verdict, scope, verifier, detail, content_hash, created_at
        ) VALUES (?, ?, 'ai_bulk', 'pass', '["answer", "subtopic"]', ?, 'Verified via utmelab-pipeline', ?, ?)
        """
        await self.prod_db.execute(v_sql, [v_id, qid, verifier, content_hash, now_iso])

        return qid
