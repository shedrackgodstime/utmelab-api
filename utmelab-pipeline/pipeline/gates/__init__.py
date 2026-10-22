"""Gate 0 Mechanical Validation and Deduplication module."""

from pipeline.gates.dedupe import compute_fingerprint
from pipeline.gates.mechanical import validate_gate0, Gate0Result
from pipeline.gates.media_check import check_media_reachability

__all__ = [
    "compute_fingerprint",
    "validate_gate0",
    "Gate0Result",
    "check_media_reachability",
]
