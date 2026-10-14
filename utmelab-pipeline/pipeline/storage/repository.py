"""Repository layer for pipeline database and production queries."""

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional
from pipeline.storage.client import TursoClient


class PipelineRepository:
    def __init__(self, pipeline_client: TursoClient, prod_client: Optional[TursoClient] = None):
        self.db = pipeline_client
        self.prod_db = prod_client

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    # --- Scrape Runs ---
    async def create_scrape_run(
        self,
        run_id: str,
        source_name: str,
        exam: str,
        subject: str,
        year: Optional[int] = None,
    ) -> None:
        sql = """
        INSERT INTO scrape_runs (
            id, source_name, exam, subject, year, status, started_at
        ) VALUES (?, ?, ?, ?, ?, 'running', ?)
        """
        await self.db.execute(sql, [run_id, source_name, exam, subject, year, self.now_iso()])

    async def complete_scrape_run(
        self,
        run_id: str,
        total_scraped: int,
        valid_admitted: int,
        rejected_gate0: int,
        error_summary: Optional[str] = None,
    ) -> None:
        sql = """
        UPDATE scrape_runs SET
            status = ?,
            total_scraped = ?,
            valid_admitted = ?,
            rejected_gate0 = ?,
            finished_at = ?,
            error_summary = ?
        WHERE id = ?
        """
        status = "failed" if error_summary else "completed"
        await self.db.execute(
            sql,
            [status, total_scraped, valid_admitted, rejected_gate0, self.now_iso(), error_summary, run_id],
        )

    # --- Staging & Fingerprinting ---
    async def is_fingerprint_staged(self, fingerprint: str) -> bool:
        sql = "SELECT id FROM harvest_staging WHERE fingerprint = ? LIMIT 1"
        res = await self.db.execute(sql, [fingerprint])
        return len(res.rows) > 0

    async def insert_staging_question(
        self,
        qid: str,
        run_id: str,
        source_name: str,
        source_url: Optional[str],
        source_item_id: Optional[str],
        exam: str,
        subject: str,
        year: int,
        stem_raw: str,
        options_raw: List[Dict[str, str]],
        answer_raw: str,
        fingerprint: str,
        gate0_status: str,
        gate0_rejection_reason: Optional[str] = None,
        explanation_raw: Optional[str] = None,
        media_url: Optional[str] = None,
    ) -> None:
        now = self.now_iso()
        sql = """
        INSERT INTO harvest_staging (
            id, run_id, source_name, source_url, source_item_id, exam, subject, year,
            stem_raw, options_raw, answer_raw, explanation_raw, media_url, fingerprint,
            gate0_status, gate0_rejection_reason, ai_status, pipeline_status,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unprocessed', ?, ?, ?)
        """
        pipeline_status = "validated" if gate0_status == "valid" else "gate0_rejected"
        await self.db.execute(
            sql,
            [
                qid,
                run_id,
                source_name,
                source_url,
                source_item_id,
                exam,
                subject,
                year,
                stem_raw,
                json.dumps(options_raw),
                answer_raw,
                explanation_raw,
                media_url,
                fingerprint,
                gate0_status,
                gate0_rejection_reason,
                pipeline_status,
                now,
                now,
            ],
        )

    async def get_pending_ai_questions(
        self,
        subject: str,
        exam: str = "JAMB",
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        sql = """
        SELECT * FROM harvest_staging
        WHERE exam = ? AND subject = ? AND gate0_status = 'valid' AND ai_status = 'unprocessed'
        ORDER BY created_at ASC
        LIMIT ?
        """
        res = await self.db.execute(sql, [exam, subject, limit])
        return res.rows

    async def update_ai_results(
        self,
        question_id: str,
        proposed_topic: Optional[str],
        proposed_subtopic: Optional[str],
        answer_verdict: str,
        explanation_quality: str,
        proposed_explanation: Optional[Dict[str, Any]],
        confidence: float,
        detected_marks: Optional[List[Dict[str, Any]]] = None,
        ai_raw_response: Optional[str] = None,
        audit_report: Optional[str] = None,
    ) -> None:
        now = self.now_iso()
        pipeline_status = (
            "auto_approved"
            if (confidence >= 0.85 and answer_verdict == "VERIFIED")
            else "ready_for_review"
        )
        sql = """
        UPDATE harvest_staging SET
            ai_status = 'completed',
            proposed_topic = ?,
            proposed_subtopic = ?,
            answer_check_verdict = ?,
            explanation_quality = ?,
            proposed_explanation = ?,
            ai_confidence = ?,
            detected_marks = ?,
            ai_raw_response = ?,
            audit_report = ?,
            pipeline_status = ?,
            updated_at = ?
        WHERE id = ?
        """
        await self.db.execute(
            sql,
            [
                proposed_topic,
                proposed_subtopic,
                answer_verdict,
                explanation_quality,
                json.dumps(proposed_explanation) if proposed_explanation else None,
                confidence,
                json.dumps(detected_marks) if detected_marks else None,
                ai_raw_response,
                audit_report,
                pipeline_status,
                now,
                question_id,
            ],
        )

    # --- Review Queue ---
    async def add_to_review_queue(
        self,
        question_id: str,
        subject: str,
        exam: str,
        flag_reason: str,
        priority: int = 1,
    ) -> None:
        now = self.now_iso()
        sql = """
        INSERT OR REPLACE INTO review_queue (
            question_id, subject, exam, flag_reason, priority, review_status, created_at
        ) VALUES (?, ?, ?, ?, ?, 'open', ?)
        """
        await self.db.execute(sql, [question_id, subject, exam, flag_reason, priority, now])

    async def get_review_queue(self, status: str = "open", limit: int = 50) -> List[Dict[str, Any]]:
        sql = """
        SELECT r.*, h.stem_raw, h.options_raw, h.answer_raw, h.proposed_subtopic, h.answer_check_verdict
        FROM review_queue r
        JOIN harvest_staging h ON r.question_id = h.id
        WHERE r.review_status = ?
        ORDER BY r.priority ASC, r.created_at ASC
        LIMIT ?
        """
        res = await self.db.execute(sql, [status, limit])
        return res.rows

    # --- Production Read (Syllabus) ---
    async def fetch_syllabus_from_prod(self, subject: str, exam: str = "JAMB") -> Dict[str, Any]:
        """Reads authoritative syllabus (topics + subtopics + objectives) from Production Turso."""
        if not self.prod_db:
            return {"topics": [], "subtopics": []}

        topics_sql = """
        SELECT slug, name, "order", weight, objectives
        FROM topics
        WHERE subject = ? AND exam = ?
        ORDER BY "order" ASC
        """
        t_res = await self.prod_db.execute(topics_sql, [subject, exam])

        subtopics_sql = """
        SELECT slug, topic AS topic_slug, name, "order", objectives
        FROM subtopics
        WHERE topic IN (SELECT slug FROM topics WHERE subject = ? AND exam = ?)
        ORDER BY "order" ASC
        """
        s_res = await self.prod_db.execute(subtopics_sql, [subject, exam])

        return {
            "topics": t_res.rows,
            "subtopics": s_res.rows,
        }
