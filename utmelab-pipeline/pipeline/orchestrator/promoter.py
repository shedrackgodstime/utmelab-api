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


def mark_key(m: Dict[str, Any]) -> str:
    kind = m.get("kind", "")
    if kind == "image":
        pos = m.get("position", "above")
        alt = m.get("alt") or ""
        url = m.get("url", "")
        kind_str = f"image:{url}:{pos}:{alt}"
    else:
        kind_str = kind
    s = m.get("start", 0)
    l = m.get("len", 0)
    return f"{s},{l},{kind_str}"


def compute_content_hash(
    stem: Dict[str, Any],
    options: List[Dict[str, Any]],
    answer_id: str,
    explanation: Optional[Dict[str, Any]] = None,
) -> str:
    """Computes content_hash with 100% byte-for-byte parity to Rust Question::content_fingerprint (D62 / R6)."""
    stem_text = stem.get("text", "") if isinstance(stem, dict) else str(stem)
    parts = [stem_text]
    for o in options:
        opt_text = o["text"].get("text", "") if isinstance(o["text"], dict) else str(o["text"])
        parts.append(f"{o['id']}\u001e{opt_text}")
    parts.append(answer_id)

    marks = [mark_key(m) for m in (stem.get("inline", []) if isinstance(stem, dict) else [])]
    for o in options:
        if isinstance(o["text"], dict):
            marks.extend([mark_key(m) for m in o["text"].get("inline", [])])
    parts.append("|".join(marks))

    if explanation:
        kp = explanation.get("key_point", {})
        kp_text = kp.get("text", "") if isinstance(kp, dict) else str(kp)
        kp_inline = [mark_key(m) for m in kp.get("inline", [])] if isinstance(kp, dict) else []
        parts.append(kp_text)
        parts.append("|".join(kp_inline))

        b = explanation.get("body", {})
        b_text = b.get("text", "") if isinstance(b, dict) else str(b)
        b_inline = [mark_key(m) for m in b.get("inline", [])] if isinstance(b, dict) else []
        parts.append(b_text)
        parts.append("|".join(b_inline))

        trap = explanation.get("trap")
        if trap:
            t_text = trap.get("text", "") if isinstance(trap, dict) else str(trap)
            t_inline = [mark_key(m) for m in trap.get("inline", [])] if isinstance(trap, dict) else []
            parts.append(t_text)
            parts.append("|".join(t_inline))
        else:
            parts.append("")
    else:
        parts.append("")

    joined = "\u001f".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


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
        audit_report: Optional[str] = None,
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
        inline_marks = list(detected_marks or [])

        # Rust model inline image anchor matching D55, D60, D61
        media_url = staging_row.get("media_url")
        if media_url:
            if media_url.startswith("http://"):
                media_url = f"https://{media_url[7:]}"
            elif media_url.startswith("//"):
                media_url = f"https:{media_url}"

            # Only attach if not already present
            if not any(m.get("kind") == "image" for m in inline_marks):
                position = "below" if "below" in stem_text.lower() else "above"
                anchor = len(stem_text) if position == "below" else 0
                inline_marks.append({
                    "start": anchor,
                    "len": 0,
                    "kind": "image",
                    "url": media_url,
                    "position": position,
                    "alt": None,
                })

        # Deterministic ordering by (start, len) to satisfy Rust's RichText validator
        inline_marks.sort(key=lambda m: (m.get("start", 0), m.get("len", 0)))
        stem_rich = to_rich_text(stem_text, inline_marks)

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

        now_iso = datetime.now(timezone.utc).isoformat()
        report = audit_report or staging_row.get("audit_report")

        # Handle passage stimulus creation & linking (R7 parity)
        passage_id = staging_row.get("passage_id")
        passage_raw = staging_row.get("passage_raw")
        if passage_raw and not passage_id:
            p_digest = hashlib.sha256(passage_raw.encode("utf-8")).hexdigest()[:8]
            kind = "Data" if "information below" in passage_raw.lower() else "Comprehension"
            passage_id = f"psg_{exam.lower()}_{year}_{subject.replace('-', '_')}_{kind.lower()}_{p_digest}"
            p_sql = """
            INSERT OR REPLACE INTO approved_passages (
                id, exam, subject, year, kind, title, author, text, inline, approved_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, '[]', ?)
            """
            await self.pipeline_db.execute(
                p_sql,
                [
                    passage_id,
                    exam,
                    subject,
                    year,
                    kind,
                    f"Recovered stimulus {p_digest}",
                    passage_raw,
                    now_iso,
                ],
            )

        content_hash = compute_content_hash(stem_rich, formatted_options, answer, explanation_obj)

        # 1. Insert into Pipeline DB approved_questions table
        q_sql = """
        INSERT OR REPLACE INTO approved_questions (
            id, staging_id, exam, subject, year, source, text, inline, options, answer,
            subtopic_id, section, passage_id, explanation, marks, difficulty, content_hash, audit_report, approved_at
        ) VALUES (?, ?, ?, ?, ?, 'claimed_paper', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                staging_row.get("section"),
                passage_id,
                json.dumps(explanation_obj) if explanation_obj else None,
                marks,
                difficulty,
                content_hash,
                report,
                now_iso,
            ],
        )

        # 2. Insert into Pipeline DB approved_verifications table
        v_id = f"v_{content_hash[:16]}"
        v_detail = f"Audit: {report}" if report else "Verified via utmelab-pipeline"
        v_sql = """
        INSERT OR REPLACE INTO approved_verifications (
            id, question_id, kind, verdict, scope, verifier, detail, content_hash, created_at
        ) VALUES (?, ?, 'ai_bulk', 'pass', '["answer", "subtopic"]', ?, ?, ?, ?)
        """
        await self.pipeline_db.execute(v_sql, [v_id, qid, verifier, v_detail, content_hash, now_iso])

        # 3. Mark staging row as approved_for_prod in Pipeline DB
        await self.pipeline_db.execute(
            "UPDATE harvest_staging SET pipeline_status = 'approved_for_prod', updated_at = ? WHERE id = ?",
            [now_iso, staging_id],
        )

        return qid


# Backwards compatibility alias
ProductionPromoter = PipelinePromoter
