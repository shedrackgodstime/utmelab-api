"""Observability Metrics Collector and Dashboard Renderer for utmelab-pipeline.

Aggregates:
1. Pipeline conversion funnel & throughput (Scraped -> Gate 0 Valid -> AI Processed -> Approved / Review).
2. Gate 0 mechanical quality stats & rejection histograms.
3. Multimodal & NLP telemetry (OCR diagrams, reading passages, AI confidence buckets, verdict splits).
4. Coverage matrix (Exam x Subject breakdown of staged vs approved questions).
5. Exception review queue backlog & triage SLA.
6. Scrape run execution history.
"""

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional
from pipeline.storage.client import TursoClient


class MetricsCollector:
    """Collects comprehensive observability metrics across all pipeline stages."""

    def __init__(self, pipeline_client: TursoClient, prod_client: Optional[TursoClient] = None):
        self.pipeline_client = pipeline_client
        self.prod_client = prod_client

    async def collect(
        self,
        subject: Optional[str] = None,
        exam: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Queries the pipeline database and returns aggregated metrics."""
        filters = []
        params = []
        if exam:
            filters.append("exam = ?")
            params.append(exam)
        if subject:
            filters.append("subject = ?")
            params.append(subject)

        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

        # 1. Scrape runs overview
        runs_sql = f"SELECT COUNT(*) as total_runs, SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_runs, SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_runs, SUM(total_scraped) as sum_scraped, SUM(valid_admitted) as sum_admitted, SUM(rejected_gate0) as sum_rejected FROM scrape_runs {where_clause}"
        runs_res = await self.pipeline_client.execute(runs_sql, params)
        runs_data = runs_res.rows[0] if runs_res.rows else {}

        # 2. Staging funnel
        staging_sql = f"""
        SELECT
            COUNT(*) as total_staged,
            SUM(CASE WHEN gate0_status = 'valid' THEN 1 ELSE 0 END) as gate0_valid,
            SUM(CASE WHEN gate0_status = 'rejected' THEN 1 ELSE 0 END) as gate0_rejected,
            SUM(CASE WHEN ai_status != 'pending' THEN 1 ELSE 0 END) as ai_processed,
            SUM(CASE WHEN pipeline_status = 'auto_approved' THEN 1 ELSE 0 END) as auto_approved,
            SUM(CASE WHEN pipeline_status = 'flagged_for_review' THEN 1 ELSE 0 END) as flagged_for_review,
            SUM(CASE WHEN pipeline_status = 'approved_for_prod' THEN 1 ELSE 0 END) as approved_for_prod
        FROM harvest_staging {where_clause}
        """
        staging_res = await self.pipeline_client.execute(staging_sql, params)
        staging_data = staging_res.rows[0] if staging_res.rows else {}

        # 3. Approved tables counts
        appr_q_sql = f"SELECT COUNT(*) as count FROM approved_questions {where_clause}"
        appr_q_res = await self.pipeline_client.execute(appr_q_sql, params)
        approved_q_count = (appr_q_res.rows[0]["count"] if appr_q_res.rows else 0) or 0

        appr_p_sql = f"SELECT COUNT(*) as count FROM approved_passages {where_clause}"
        appr_p_res = await self.pipeline_client.execute(appr_p_sql, params)
        approved_p_count = (appr_p_res.rows[0]["count"] if appr_p_res.rows else 0) or 0

        appr_v_sql = "SELECT COUNT(*) as count FROM approved_verifications"
        appr_v_res = await self.pipeline_client.execute(appr_v_sql)
        approved_v_count = (appr_v_res.rows[0]["count"] if appr_v_res.rows else 0) or 0

        # 4. Review queue counts
        review_sql = f"""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN review_status = 'open' THEN 1 ELSE 0 END) as open_count,
            SUM(CASE WHEN review_status = 'resolved' THEN 1 ELSE 0 END) as resolved_count,
            SUM(CASE WHEN review_status = 'discarded' THEN 1 ELSE 0 END) as discarded_count
        FROM review_queue {where_clause}
        """
        review_res = await self.pipeline_client.execute(review_sql, params)
        review_data = review_res.rows[0] if review_res.rows else {}

        # 5. Gate 0 rejection reason histogram
        reasons_sql = f"""
        SELECT gate0_rejection_reason, COUNT(*) as count
        FROM harvest_staging
        WHERE gate0_status = 'rejected' {'AND ' + ' AND '.join(filters) if filters else ''}
        GROUP BY gate0_rejection_reason
        ORDER BY count DESC
        LIMIT 10
        """
        reasons_res = await self.pipeline_client.execute(reasons_sql, params)
        rejection_histogram = [
            {"reason": r["gate0_rejection_reason"] or "Unknown", "count": r["count"]}
            for r in reasons_res.rows
        ]

        # 6. AI Telemetry & Quality
        ai_telemetry_sql = f"""
        SELECT
            AVG(ai_confidence) as avg_confidence,
            SUM(CASE WHEN ai_confidence >= 0.90 THEN 1 ELSE 0 END) as high_conf,
            SUM(CASE WHEN ai_confidence >= 0.70 AND ai_confidence < 0.90 THEN 1 ELSE 0 END) as med_conf,
            SUM(CASE WHEN ai_confidence < 0.70 AND ai_confidence IS NOT NULL THEN 1 ELSE 0 END) as low_conf,
            SUM(CASE WHEN answer_check_verdict = 'VERIFIED' THEN 1 ELSE 0 END) as verdict_verified,
            SUM(CASE WHEN answer_check_verdict = 'DISAGREEMENT' THEN 1 ELSE 0 END) as verdict_disagreement,
            SUM(CASE WHEN answer_check_verdict = 'AMBIGUOUS' THEN 1 ELSE 0 END) as verdict_ambiguous,
            SUM(CASE WHEN media_url IS NOT NULL AND media_url != '' THEN 1 ELSE 0 END) as with_media,
            SUM(CASE WHEN passage_raw IS NOT NULL AND passage_raw != '' THEN 1 ELSE 0 END) as with_passage
        FROM harvest_staging
        WHERE ai_status != 'pending' {'AND ' + ' AND '.join(filters) if filters else ''}
        """
        ai_res = await self.pipeline_client.execute(ai_telemetry_sql, params)
        ai_data = ai_res.rows[0] if ai_res.rows else {}

        # 7. Coverage matrix (Exam x Subject)
        cov_staging_sql = f"""
        SELECT exam, subject,
               COUNT(*) as staged,
               SUM(CASE WHEN gate0_status = 'valid' THEN 1 ELSE 0 END) as valid,
               SUM(CASE WHEN pipeline_status IN ('auto_approved', 'approved_for_prod') THEN 1 ELSE 0 END) as approved_staging
        FROM harvest_staging {where_clause}
        GROUP BY exam, subject
        ORDER BY exam, subject
        """
        cov_res = await self.pipeline_client.execute(cov_staging_sql, params)

        cov_appr_sql = f"""
        SELECT exam, subject, COUNT(*) as approved_count
        FROM approved_questions {where_clause}
        GROUP BY exam, subject
        """
        cov_appr_res = await self.pipeline_client.execute(cov_appr_sql, params)
        approved_map = {(r["exam"], r["subject"]): r["approved_count"] for r in cov_appr_res.rows}

        coverage_matrix = []
        for r in cov_res.rows:
            key = (r["exam"], r["subject"])
            coverage_matrix.append({
                "exam": r["exam"],
                "subject": r["subject"],
                "staged": r["staged"] or 0,
                "valid": r["valid"] or 0,
                "approved_staging": r["approved_staging"] or 0,
                "approved_bank": approved_map.get(key, 0),
            })

        # 8. Review queue reasons
        rev_reasons_sql = f"""
        SELECT flag_reason, COUNT(*) as count
        FROM review_queue
        WHERE review_status = 'open' {'AND ' + ' AND '.join(filters) if filters else ''}
        GROUP BY flag_reason
        ORDER BY count DESC
        """
        rev_reasons_res = await self.pipeline_client.execute(rev_reasons_sql, params)
        review_reasons = [{"reason": r["flag_reason"], "count": r["count"]} for r in rev_reasons_res.rows]

        # 9. Recent scrape runs
        recent_runs_sql = f"""
        SELECT id, source_name, exam, subject, year, status, total_scraped, valid_admitted, rejected_gate0, started_at, finished_at
        FROM scrape_runs {where_clause}
        ORDER BY started_at DESC
        LIMIT 5
        """
        recent_runs_res = await self.pipeline_client.execute(recent_runs_sql, params)
        recent_runs = recent_runs_res.rows

        # Calculate ratios & funnel health
        total_staged = staging_data.get("total_staged") or 0
        gate0_valid = staging_data.get("gate0_valid") or 0
        gate0_rejected = staging_data.get("gate0_rejected") or 0
        gate0_pass_rate = round((gate0_valid / total_staged * 100), 1) if total_staged > 0 else 0.0

        ai_processed = staging_data.get("ai_processed") or 0
        auto_approved = staging_data.get("auto_approved") or 0
        approved_for_prod = staging_data.get("approved_for_prod") or 0
        total_approved = auto_approved + approved_for_prod
        ai_auto_approval_rate = round((total_approved / ai_processed * 100), 1) if ai_processed > 0 else 0.0

        # Health indicator
        health_status = "HEALTHY"
        health_reasons = []
        if total_staged > 20 and gate0_pass_rate < 50.0:
            health_status = "WARNING"
            health_reasons.append(f"Low Gate 0 admission rate ({gate0_pass_rate}%)")
        if (review_data.get("open_count") or 0) > 100:
            health_status = "WARNING"
            health_reasons.append("Review queue backlog exceeds 100 open items")
        avg_c = ai_data.get("avg_confidence")
        if avg_c is not None and avg_c < 0.80 and ai_processed > 10:
            health_status = "DEGRADED"
            health_reasons.append(f"Low average AI confidence ({round(avg_c, 2)})")

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "filter": {"subject": subject, "exam": exam},
            "health": {
                "status": health_status,
                "reasons": health_reasons,
            },
            "funnel": {
                "total_staged": total_staged,
                "gate0_valid": gate0_valid,
                "gate0_rejected": gate0_rejected,
                "gate0_pass_rate_pct": gate0_pass_rate,
                "ai_processed": ai_processed,
                "auto_approved": auto_approved,
                "flagged_for_review": staging_data.get("flagged_for_review") or 0,
                "approved_for_prod": approved_for_prod,
                "ai_auto_approval_rate_pct": ai_auto_approval_rate,
                "approved_questions_total": approved_q_count,
                "approved_passages_total": approved_p_count,
                "approved_verifications_total": approved_v_count,
            },
            "gate0_rejections": rejection_histogram,
            "ai_telemetry": {
                "avg_confidence": round(avg_c, 3) if avg_c is not None else None,
                "confidence_buckets": {
                    "high_ge_90": ai_data.get("high_conf") or 0,
                    "med_70_89": ai_data.get("med_conf") or 0,
                    "low_lt_70": ai_data.get("low_conf") or 0,
                },
                "verdicts": {
                    "verified": ai_data.get("verdict_verified") or 0,
                    "disagreement": ai_data.get("verdict_disagreement") or 0,
                    "ambiguous": ai_data.get("verdict_ambiguous") or 0,
                },
                "multimodal": {
                    "questions_with_media": ai_data.get("with_media") or 0,
                    "questions_with_passages": ai_data.get("with_passage") or 0,
                },
            },
            "coverage": coverage_matrix,
            "review_queue": {
                "open": review_data.get("open_count") or 0,
                "resolved": review_data.get("resolved_count") or 0,
                "discarded": review_data.get("discarded_count") or 0,
                "reasons": review_reasons,
            },
            "scrape_runs": {
                "total": runs_data.get("total_runs") or 0,
                "completed": runs_data.get("completed_runs") or 0,
                "failed": runs_data.get("failed_runs") or 0,
                "recent": recent_runs,
            },
        }

    @staticmethod
    def render_cli_dashboard(metrics: Dict[str, Any]) -> str:
        """Formats the collected metrics into an ANSI-styled terminal dashboard."""
        f = metrics["funnel"]
        ai = metrics["ai_telemetry"]
        health = metrics["health"]
        rev = metrics["review_queue"]
        filt = metrics.get("filter", {})

        filter_desc = []
        if filt.get("exam"):
            filter_desc.append(f"Exam: {filt['exam']}")
        if filt.get("subject"):
            filter_desc.append(f"Subject: {filt['subject']}")
        filter_str = f" ({', '.join(filter_desc)})" if filter_desc else ""

        status_emoji = {"HEALTHY": "🟢", "WARNING": "🟡", "DEGRADED": "🔴"}.get(health["status"], "⚪")

        lines = []
        lines.append("╔═══════════════════════════════════════════════════════════════════════════════╗")
        lines.append(f"║               UTMELAB CBT PIPELINE OBSERVABILITY DASHBOARD{filter_str.center(19)[:19]} ║")
        lines.append("╠═══════════════════════════════════════════════════════════════════════════════╣")
        lines.append(f"║ System Health: {status_emoji} {health['status']:<10} | Timestamp: {metrics['timestamp'][:19]}Z          ║")
        if health["reasons"]:
            for r in health["reasons"]:
                lines.append(f"║  ⚠️  {r:<73} ║")
        lines.append("╠═══════════════════════════════════════════════════════════════════════════════╣")
        lines.append("║ 1. CONVERSION FUNNEL & THROUGHPUT                                             ║")
        lines.append("╟───────────────────────────────────────────────────────────────────────────────╢")
        lines.append(f"║ Total Staged:        {f['total_staged']:<8} │ Approved Questions:    {f['approved_questions_total']:<8}     ║")
        lines.append(f"║ Gate 0 Admitted:     {f['gate0_valid']:<8} │ Approved Passages:     {f['approved_passages_total']:<8}     ║")
        lines.append(f"║ Gate 0 Rejected:     {f['gate0_rejected']:<8} │ Approved Verifications: {f['approved_verifications_total']:<8}     ║")
        lines.append(f"║ Gate 0 Pass Rate:    {str(f['gate0_pass_rate_pct']) + '%':<8} │ Open Review Items:     {rev['open']:<8}     ║")
        lines.append(f"║ AI Processed:        {f['ai_processed']:<8} │ AI Auto-Approval Rate: {str(f['ai_auto_approval_rate_pct']) + '%':<8}     ║")
        lines.append("╠═══════════════════════════════════════════════════════════════════════════════╣")
        lines.append("║ 2. AI VERIFICATION & MULTIMODAL TELEMETRY                                     ║")
        lines.append("╟───────────────────────────────────────────────────────────────────────────────╢")
        avg_conf_str = f"{ai['avg_confidence']:.2f}" if ai['avg_confidence'] is not None else "N/A"
        cb = ai["confidence_buckets"]
        v = ai["verdicts"]
        mm = ai["multimodal"]
        lines.append(f"║ Average Confidence:  {avg_conf_str:<8} │ Verdict Verified:     {v['verified']:<8}     ║")
        lines.append(f"║ High Conf (>=0.90):  {cb['high_ge_90']:<8} │ Verdict Disagreement: {v['disagreement']:<8}     ║")
        lines.append(f"║ Med Conf (0.7-0.9):  {cb['med_70_89']:<8} │ Verdict Ambiguous:    {v['ambiguous']:<8}     ║")
        lines.append(f"║ Low Conf (<0.70):    {cb['low_lt_70']:<8} │ Questions w/ Diagram: {mm['questions_with_media']:<8}     ║")
        lines.append(f"║ Reading Passages:    {mm['questions_with_passages']:<8} │                                       ║")

        # Gate 0 rejections
        if metrics["gate0_rejections"]:
            lines.append("╠═══════════════════════════════════════════════════════════════════════════════╣")
            lines.append("║ 3. GATE 0 MECHANICAL REJECTION BREAKDOWN                                      ║")
            lines.append("╟───────────────────────────────────────────────────────────────────────────────╢")
            for r in metrics["gate0_rejections"][:5]:
                reason = r["reason"][:55]
                lines.append(f"║ • {reason:<58} : {r['count']:<5} ║")

        # Coverage Matrix
        if metrics["coverage"]:
            lines.append("╠═══════════════════════════════════════════════════════════════════════════════╣")
            lines.append("║ 4. COVERAGE MATRIX (EXAM x SUBJECT)                                           ║")
            lines.append("╟───────────────────────────────────────────────────────────────────────────────╢")
            lines.append("║ Exam │ Subject                   │ Staged │ Valid  │ Ready  │ Approved (Bank) ║")
            lines.append("╟──────┼───────────────────────────┼────────┼────────┼────────┼─────────────────╢")
            for c in metrics["coverage"]:
                exam_s = c["exam"][:4]
                subj_s = c["subject"][:25]
                lines.append(
                    f"║ {exam_s:<4} │ {subj_s:<25} │ {c['staged']:<6} │ {c['valid']:<6} │ {c['approved_staging']:<6} │ {c['approved_bank']:<15} ║"
                )

        # Review Queue SLA
        lines.append("╠═══════════════════════════════════════════════════════════════════════════════╣")
        lines.append("║ 5. EXCEPTION REVIEW QUEUE STATUS                                              ║")
        lines.append("╟───────────────────────────────────────────────────────────────────────────────╢")
        lines.append(f"║ Open Backlog: {rev['open']:<6} │ Resolved: {rev['resolved']:<6} │ Discarded: {rev['discarded']:<18} ║")
        if rev["reasons"]:
            for r in rev["reasons"][:3]:
                lines.append(f"║   ↳ Flag: {r['reason'][:50]:<50} ({r['count']}) ║")

        lines.append("╚═══════════════════════════════════════════════════════════════════════════════╝")
        return "\n".join(lines)

    @staticmethod
    def render_markdown_summary(metrics: Dict[str, Any]) -> str:
        """Renders GitHub Flavored Markdown summary for $GITHUB_STEP_SUMMARY."""
        f = metrics["funnel"]
        ai = metrics["ai_telemetry"]
        health = metrics["health"]
        rev = metrics["review_queue"]
        filt = metrics.get("filter", {})

        filter_text = ""
        if filt.get("exam") or filt.get("subject"):
            filter_text = f" (Scope: `{filt.get('exam') or 'ALL'}` / `{filt.get('subject') or 'ALL'}`)"

        status_badge = {"HEALTHY": "🟢 Healthy", "WARNING": "🟡 Warning", "DEGRADED": "🔴 Degraded"}.get(
            health["status"], "⚪ Unknown"
        )

        md = []
        md.append(f"## 📊 UTME Lab Pipeline Telemetry Report{filter_text}\n")
        md.append(f"**Health Status:** {status_badge}  |  **Updated:** `{metrics['timestamp']}`\n")

        if health["reasons"]:
            md.append("> [!WARNING]\n" + "\n".join([f"> - {r}" for r in health["reasons"]]) + "\n")

        md.append("### 1. Funnel & Throughput\n")
        md.append("| Metric | Count | Ratio / Notes |")
        md.append("| :--- | :--- | :--- |")
        md.append(f"| **Total Staged** | `{f['total_staged']}` | Raw crawl items collected |")
        md.append(f"| **Gate 0 Admitted** | `{f['gate0_valid']}` | **Pass Rate:** `{f['gate0_pass_rate_pct']}%` |")
        md.append(f"| **Gate 0 Rejected** | `{f['gate0_rejected']}` | Filtered out by mechanical rules |")
        md.append(f"| **AI Processed** | `{f['ai_processed']}` | Evaluated by OpenCode Multimodal AI |")
        md.append(f"| **Auto-Approved** | `{f['auto_approved']}` | **AI Auto-Approval Rate:** `{f['ai_auto_approval_rate_pct']}%` |")
        md.append(f"| **Approved Questions in Pipeline** | `{f['approved_questions_total']}` | Verified & ready for production review |")
        md.append(f"| **Approved Passages in Pipeline** | `{f['approved_passages_total']}` | Deduplicated stimuli |")
        md.append(f"| **Approved Verifications** | `{f['approved_verifications_total']}` | Byte-parity content hashes |")
        md.append(f"| **Open Review Tickets** | `{rev['open']}` | Flagged exceptions requiring human triage |\n")

        md.append("### 2. AI Multimodal & Verification Telemetry\n")
        cb = ai["confidence_buckets"]
        v = ai["verdicts"]
        mm = ai["multimodal"]
        avg_c = f"`{ai['avg_confidence']:.2f}`" if ai['avg_confidence'] is not None else "`N/A`"

        md.append(f"- **Average Model Confidence:** {avg_c}")
        md.append(f"- **Confidence Buckets:** High (`>=0.90`): `{cb['high_ge_90']}` | Medium (`0.70-0.89`): `{cb['med_70_89']}` | Low (`<0.70`): `{cb['low_lt_70']}`")
        md.append(f"- **Verdict Split:** Verified: `{v['verified']}` | Disagreement: `{v['disagreement']}` | Ambiguous: `{v['ambiguous']}`")
        md.append(f"- **Multimodal Diagrams Handled:** `{mm['questions_with_media']}` questions OCR'd and diagram-anchored")
        md.append(f"- **Passages Linked / Recovered:** `{mm['questions_with_passages']}` reading passages\n")

        if metrics["gate0_rejections"]:
            md.append("### 3. Gate 0 Mechanical Rejection Analysis\n")
            md.append("| Rejection Reason | Count |")
            md.append("| :--- | :--- |")
            for r in metrics["gate0_rejections"]:
                md.append(f"| `{r['reason']}` | `{r['count']}` |")
            md.append("")

        if metrics["coverage"]:
            md.append("### 4. Coverage Matrix (Exam x Subject)\n")
            md.append("| Exam | Subject | Staged | Valid | Ready | Approved (Bank) |")
            md.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
            for c in metrics["coverage"]:
                md.append(f"| **{c['exam']}** | `{c['subject']}` | `{c['staged']}` | `{c['valid']}` | `{c['approved_staging']}` | `{c['approved_bank']}` |")
            md.append("")

        return "\n".join(md)
