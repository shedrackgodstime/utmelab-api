"""Gate 0 Mechanical Pre-Verification."""

import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from pipeline.gates.dedupe import compute_fingerprint

# Regex patterns that indicate a question depends on an external diagram/figure
FIGURE_HINT_PATTERNS = [
    r"\b(diagram|figure|chart|stave|graph|circuit|illustration|table)\s+(above|below|shown|given|adjacent)\b",
    r"\b(in|from|refer to|based on)\s+the\s+(diagram|figure|graph|chart|circuit|stave|table)\b",
    r"\bshown\s+in\s+the\s+(figure|diagram|graph|circuit|stave)\b",
    r"\bstudy\s+the\s+(diagram|figure|graph|chart|circuit|table)\b",
    r"\bthe\s+given\s+(diagram|figure|graph|circuit|stave)\b",
]

COMPILED_FIGURE_HINTS = [re.compile(p, re.IGNORECASE) for p in FIGURE_HINT_PATTERNS]

PROMISED_STIMULUS_PATTERNS = [
    r"\b(passage\s+(below|above))\b",
    r"\b(the\s+(passage|text|information|data|table)\s+(below|above))\b",
    r"\b(following\s+(the\s+)?passage)\b",
    r"\b(read\s+the\s+passage)\b",
    r"\b(use\s+the\s+information\s+below)\b",
    r"\b(according\s+to\s+the\s+(passage|text|information))\b",
    r"\b(gap\s+labelled\s+\d+)\b",
]

COMPILED_STIMULUS_HINTS = [re.compile(p, re.IGNORECASE) for p in PROMISED_STIMULUS_PATTERNS]


class Gate0Result(BaseModel):
    is_valid: bool
    rejection_reason: Optional[str] = None
    fingerprint: str
    requires_media: bool = False
    requires_passage: bool = False


def validate_gate0(
    stem: str,
    options: List[Dict[str, str]],
    reported_answer: str,
    exam: str = "JAMB",
    media_url: Optional[str] = None,
    passage_text: Optional[str] = None,
    passage_id: Optional[str] = None,
) -> Gate0Result:
    """Performs zero-cost mechanical validation on a raw question payload."""
    fp = compute_fingerprint(stem)

    # 1. Stem sanity
    if not stem or len(stem.strip()) < 10:
        return Gate0Result(
            is_valid=False,
            rejection_reason="stem_too_short",
            fingerprint=fp,
        )

    # 2. Options sanity
    exam_upper = exam.upper()
    if exam_upper == "JAMB":
        if len(options) != 4:
            return Gate0Result(
                is_valid=False,
                rejection_reason=f"invalid_option_count_jamb_requires_4_got_{len(options)}",
                fingerprint=fp,
            )
    else:  # WAEC, NECO
        if len(options) not in (4, 5):
            return Gate0Result(
                is_valid=False,
                rejection_reason=f"invalid_option_count_requires_4_or_5_got_{len(options)}",
                fingerprint=fp,
            )

    option_keys = set()
    for opt in options:
        opt_id = opt.get("id", "").strip().lower()
        opt_text = opt.get("text", "").strip()
        if not opt_id:
            return Gate0Result(
                is_valid=False,
                rejection_reason="missing_option_id",
                fingerprint=fp,
            )
        if not opt_text:
            return Gate0Result(
                is_valid=False,
                rejection_reason=f"empty_option_text_for_option_{opt_id}",
                fingerprint=fp,
            )
        if opt_id in option_keys:
            return Gate0Result(
                is_valid=False,
                rejection_reason=f"duplicate_option_key_{opt_id}",
                fingerprint=fp,
            )
        option_keys.add(opt_id)

    # 3. Answer key validity
    clean_answer = reported_answer.strip().lower()
    if clean_answer not in option_keys:
        return Gate0Result(
            is_valid=False,
            rejection_reason=f"reported_answer_{clean_answer}_not_in_options_{sorted(option_keys)}",
            fingerprint=fp,
        )

    # 4. Diagram hint check
    requires_media = False
    for pat in COMPILED_FIGURE_HINTS:
        if pat.search(stem):
            requires_media = True
            break

    if requires_media and not media_url:
        return Gate0Result(
            is_valid=False,
            rejection_reason="missing_referenced_figure_in_stem",
            fingerprint=fp,
            requires_media=True,
        )

    # 5. Passage stimulus hint check (R7 parity)
    requires_passage = False
    for pat in COMPILED_STIMULUS_HINTS:
        if pat.search(stem):
            requires_passage = True
            break

    # If stem promises a passage, it must carry one unless the stem itself carries an inline stimulus (>200 chars)
    if requires_passage and not passage_text and not passage_id and len(stem) < 200:
        return Gate0Result(
            is_valid=False,
            rejection_reason="missing_referenced_passage_in_stem",
            fingerprint=fp,
            requires_passage=True,
        )

    return Gate0Result(
        is_valid=True,
        fingerprint=fp,
        requires_media=requires_media,
        requires_passage=requires_passage,
    )
