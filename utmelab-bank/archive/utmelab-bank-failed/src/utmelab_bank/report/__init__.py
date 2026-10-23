"""Read-only reports over the bank."""

from __future__ import annotations

from utmelab_bank.report.status import StatusReport, collect_status, render_status

__all__ = ["StatusReport", "collect_status", "render_status"]
