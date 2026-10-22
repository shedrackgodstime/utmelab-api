"""Production Synchronization Engine: transfers verified and audited questions from Pipeline DB to Production Turso DB.

SAFETY INVARIANTS:
1. Production writes are strictly guarded behind an explicit confirmation flag (--confirm).
2. Default execution is strictly DRY-RUN.
3. Every candidate question must pass 4 mechanical & relational validations before sync:
   - Verification record exists in `approved_verifications` with matching `content_hash`.
   - `subtopic_id` exists in the authoritative production `subtopics` table (satisfies Rust D26 / R7).
   - If `passage_id` is set, the stimulus exists in `approved_passages` or production `passages`.
   - Content hash parity check: re-calculated SHA-256 matches stored content hash byte-for-byte.
4. If any question fails integrity validation, it is rejected and reported; valid items can proceed.
"""

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional
from pipeline.orchestrator.promoter import compute_content_hash, to_rich_text
from pipeline.storage.client import TursoClient


class ProductionSyncEngine:
    """Manages audited synchronization from the Pipeline DB to the Production Turso DB."""

    def __init__(self, pipeline_client: TursoClient, prod_client: TursoClient):
        self.pipe_db = pipeline_client
        self.prod_db = prod_client

    async def validate_and_sync(
        self,
        subject: Optional[str] = None,
        exam: Optional[str] = None,
        limit: Optional[int] = None,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        """Validates all approved items in the pipeline DB and syncs them to production."""
        # 1. Fetch candidate approved questions
        filters = []
        params = []
        if exam:
            filters.append("exam = ?")
            params.append(exam)
        if subject:
            filters.append("subject = ?")
            params.append(subject)

        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        limit_clause = f"LIMIT {limit}" if limit else ""

        q_sql = f"SELECT * FROM approved_questions {where_clause} ORDER BY approved_at ASC {limit_clause}"
        res = await self.pipe_db.execute(q_sql, params)
        candidates = res.rows

        results = {
            "total_candidates": len(candidates),
            "validated_pass": 0,
            "validation_failures": [],
            "passages_to_sync": [],
            "questions_to_sync": [],
            "passages_synced": 0,
            "questions_synced": 0,
            "dry_run": dry_run,
        }

        if not candidates:
            return results

        # Cache existing production subtopics and passages for efficient validation
        prod_subtopics_res = await self.prod_db.execute("SELECT slug FROM subtopics")
        valid_subtopics = {r["slug"] for r in prod_subtopics_res.rows}

        prod_passages_res = await self.prod_db.execute("SELECT id FROM passages")
        prod_passages = {r["id"] for r in prod_passages_res.rows}

        # Cache pipeline approved passages
        pipe_passages_res = await self.pipe_db.execute("SELECT * FROM approved_passages")
        pipe_passages_map = {r["id"]: r for r in pipe_passages_res.rows}

        passages_to_write: Dict[str, Dict[str, Any]] = {}
        valid_questions: List[Dict[str, Any]] = []

        for q in candidates:
            qid = q["id"]
            errors = []

            # 1. Verify existence of verification record in approved_verifications
            v_res = await self.pipe_db.execute(
                "SELECT * FROM approved_verifications WHERE question_id = ? AND content_hash = ?",
                [qid, q["content_hash"]],
            )
            if not v_res.rows:
                errors.append(f"No matching approved_verifications record for content_hash={q['content_hash'][:12]}")

            # 2. Foreign key subtopic validation against production catalog
            subtopic = q.get("subtopic_id")
            if subtopic and subtopic not in valid_subtopics:
                errors.append(f"Subtopic '{subtopic}' not found in production subtopics catalog")

            # 3. Stimulus / passage validation
            passage_id = q.get("passage_id")
            if passage_id:
                if passage_id in prod_passages:
                    pass  # Already in production
                elif passage_id in pipe_passages_map:
                    passages_to_write[passage_id] = pipe_passages_map[passage_id]
                else:
                    errors.append(f"Referenced passage stimulus '{passage_id}' not found in pipeline or prod DB")

            # 4. Hash verification parity
            try:
                raw_inline = json.loads(q["inline"]) if isinstance(q["inline"], str) else q["inline"]
                stem_rich = to_rich_text(q["text"], raw_inline)
                opts_data = json.loads(q["options"]) if isinstance(q["options"], str) else q["options"]
                exp_data = json.loads(q["explanation"]) if q.get("explanation") and isinstance(q["explanation"], str) else q.get("explanation")
                computed_hash = compute_content_hash(stem_rich, opts_data, q["answer"], exp_data)

                if computed_hash != q["content_hash"]:
                    errors.append(f"Content hash mismatch: stored={q['content_hash']} != recomputed={computed_hash}")
            except Exception as e:
                errors.append(f"Failed to verify content hash parity: {str(e)}")

            if errors:
                results["validation_failures"].append({
                    "question_id": qid,
                    "subject": q.get("subject"),
                    "errors": errors,
                })
            else:
                results["validated_pass"] += 1
                valid_questions.append(q)

        results["passages_to_sync"] = list(passages_to_write.keys())
        results["questions_to_sync"] = [q["id"] for q in valid_questions]

        if dry_run:
            return results

        # Execute Write to Production DB
        # 1. Sync Passages first (Foreign Key dependency)
        for pid, p in passages_to_write.items():
            p_sql = """
            INSERT OR REPLACE INTO passages (
                id, exam, subject, year, kind, title, author, text, inline
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            await self.prod_db.execute(
                p_sql,
                [
                    p["id"],
                    p["exam"],
                    p["subject"],
                    int(p["year"]),
                    p["kind"],
                    p.get("title"),
                    p.get("author"),
                    p["text"],
                    p.get("inline") or "[]",
                ],
            )
            results["passages_synced"] += 1

        # 2. Sync Questions
        now_iso = datetime.now(timezone.utc).isoformat()
        for q in valid_questions:
            q_sql = """
            INSERT OR REPLACE INTO questions (
                id, exam, subject, year, source, text, inline, options, answer,
                subtopic_id, section, passage_id, explanation, marks, difficulty, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            await self.prod_db.execute(
                q_sql,
                [
                    q["id"],
                    q["exam"],
                    q["subject"],
                    int(q["year"]),
                    q["source"],
                    q["text"],
                    q.get("inline") or "[]",
                    q["options"],
                    q["answer"],
                    q.get("subtopic_id"),
                    q.get("section"),
                    q.get("passage_id"),
                    q.get("explanation"),
                    float(q["marks"]),
                    int(q["difficulty"]),
                    q["content_hash"],
                ],
            )
            results["questions_synced"] += 1

            # Update pipeline DB staging status if staging_id exists
            if q.get("staging_id"):
                await self.pipe_db.execute(
                    "UPDATE harvest_staging SET pipeline_status = 'synced_to_prod', updated_at = ? WHERE id = ?",
                    [now_iso, q["staging_id"]],
                )

        return results
