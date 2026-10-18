"""Read-only snapshots of the bank.

The status command answers the question an operator actually asks before a run:
what is in each lane, what is waiting, what failed, and what ran last. It reads
only. The counts come from the same physical tables the tasks write, so a report
cannot disagree with a selector about what is there.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from utmelab_bank.config import Lane
from utmelab_bank.store.client import Store
from utmelab_bank.store.repository import Repository
from utmelab_bank.store.schema import LANES, table
from utmelab_bank.store.status import grouped_counts, lane_counts, recent_runs

__all__ = ["StatusReport", "collect_status", "render_status"]

#: Row-bearing tables, in the order an operator reads them.
ROW_TABLES = ("questions", "media", "passages", "verifications")

#: Catalogue tables, copied per lane from the production taxonomy.
CATALOGUE_TABLES = ("subjects", "topics", "subtopics")

QUESTION_QUEUE_SELECTORS = (
    "gated",
    "no explanation",
    "no subtopic",
    "unverified",
    "retryable",
)

MEDIA_QUEUE_SELECTORS = (
    "no description",
    "description unchecked",
    "description failed",
    "description verified",
    "needs review",
    "no blob",
    "not uploaded",
    "retryable",
)


@dataclass(frozen=True)
class StatusReport:
    """One read-only snapshot of the configured lane and its siblings."""

    database: str
    lane: Lane
    counts: dict[str, dict[str, int]]
    media_status: dict[str, int]
    media_verdicts: dict[str, int]
    questions: dict[str, int]
    media: dict[str, int]
    retry_due: dict[str, int]
    runs: list[dict[str, Any]]


async def collect_status(store: Store, lane: Lane, database: str) -> StatusReport:
    """Read every count a status report needs, without writing anything."""
    repo = Repository(store, lane=lane)

    counts = await lane_counts(store)
    media_physical = table("media", lane)
    media_status = await grouped_counts(store, media_physical, "status")
    media_verdicts = await grouped_counts(
        store, media_physical, "description_verdict", empty="unchecked"
    )

    questions = {
        selector: await repo.count("questions", selector) for selector in QUESTION_QUEUE_SELECTORS
    }
    media = {selector: await repo.count("media", selector) for selector in MEDIA_QUEUE_SELECTORS}
    retry_due = {
        "questions": await repo.count("questions", "retryable"),
        "media": await repo.count("media", "retryable"),
    }

    return StatusReport(
        database=database,
        lane=lane,
        counts=counts,
        media_status=media_status,
        media_verdicts=media_verdicts,
        questions=questions,
        media=media,
        retry_due=retry_due,
        runs=await recent_runs(store),
    )


def _block(title: str, values: dict[str, int]) -> list[str]:
    lines = [title]
    if not values:
        lines.append("  (none)")
    else:
        width = max(len(str(key)) for key in values)
        lines.extend(f"  {key!s:<{width}}  {value}" for key, value in values.items())
    lines.append("")
    return lines


def _table(title: str, names: tuple[str, ...], rows: dict[str, dict[str, int]]) -> list[str]:
    width = max(len(name) for name in names)
    lines = [
        title,
        "  " + f"{'lane':<7}" + "  ".join(f"{name:>{width}}" for name in names),
    ]
    for lane in LANES:
        values = rows.get(lane, {})
        lines.append(
            "  " + f"{lane:<7}" + "  ".join(f"{values.get(name, 0):>{width}}" for name in names)
        )
    lines.append("")
    return lines


def render_status(report: StatusReport) -> str:
    """A person-readable snapshot. The json form is the dataclass itself."""
    lines = [f"bank: {report.database}", f"lane: {report.lane}", ""]
    lines.extend(_table("rows", ROW_TABLES, report.counts))
    lines.extend(
        _block(
            "catalogue (current lane)",
            {name: report.counts.get(report.lane, {}).get(name, 0) for name in CATALOGUE_TABLES},
        )
    )
    lines.extend(_block("media status (current lane)", report.media_status))
    lines.extend(_block("description verdict (current lane)", report.media_verdicts))
    lines.extend(_block("questions queue (current lane)", report.questions))
    lines.extend(_block("media queue (current lane)", report.media))
    lines.extend(_block("retry due", report.retry_due))

    lines.append("last runs")
    if not report.runs:
        lines.append("  (none)")
    else:
        lines.append("  task             target  status   ok  skip  fail  started")
        for run in report.runs:
            lines.append(
                f"  {run.get('task', '')!s:<16} {run.get('target', '')!s:<7} "
                f"{run.get('status', '')!s:<8} {int(run.get('succeeded') or 0):>3} "
                f"{int(run.get('skipped') or 0):>5} {int(run.get('failed') or 0):>5}  "
                f"{run.get('started_at', '')}"
            )
    return "\n".join(lines)
