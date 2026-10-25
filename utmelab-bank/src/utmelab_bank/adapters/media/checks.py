"""Deterministic checks for captured media and OCR evidence."""

from __future__ import annotations

import hashlib
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from utmelab_bank.domain.models import MediaAsset, MediaCheck

DIAGRAM_KINDS = {"diagram_only", "electrical_diagram", "graph"}


def check_media(
    asset: MediaAsset,
    data: bytes,
    *,
    ocr_text: str | None = None,
    ocr_error: str | None = None,
    expected_kind: str | None = None,
) -> MediaCheck:
    """Check stored bytes without contacting a network or model provider."""
    issues: list[str] = []
    digest = hashlib.sha256(data).hexdigest()
    if digest != asset.asset_id:
        issues.append("asset_hash_mismatch")
    if len(data) != asset.byte_size:
        issues.append("byte_size_mismatch")

    detected_mime: str | None = None
    width: int | None = None
    height: int | None = None
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
            detected_mime = Image.MIME.get(image.format or "")
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
    except (UnidentifiedImageError, OSError, ValueError):
        issues.append("unreadable_image")
    else:
        if detected_mime != asset.mime:
            issues.append("mime_mismatch")
        if not width or not height:
            issues.append("unusable_dimensions")
        if asset.width is not None and width != asset.width:
            issues.append("width_mismatch")
        if asset.height is not None and height != asset.height:
            issues.append("height_mismatch")

    if ocr_error:
        ocr_status = "error"
    elif ocr_text is None:
        ocr_status = "not_run"
    elif not ocr_text.strip():
        ocr_status = "empty"
        if expected_kind is not None and expected_kind not in DIAGRAM_KINDS:
            issues.append("ocr_empty_on_expected_text_media")
    elif len(ocr_text.strip()) < 3:
        ocr_status = "weak"
    else:
        ocr_status = "usable"

    core_issues = {
        "asset_hash_mismatch",
        "byte_size_mismatch",
        "unreadable_image",
        "mime_mismatch",
        "unusable_dimensions",
        "width_mismatch",
        "height_mismatch",
    }
    if core_issues & set(issues):
        status = "invalid"
    elif issues:
        status = "review"
    else:
        status = "ok"
    return MediaCheck(
        asset_id=asset.asset_id,
        status=status,
        mime=asset.mime,
        detected_mime=detected_mime,
        byte_size=len(data),
        width=width,
        height=height,
        ocr_status=ocr_status,
        issues=tuple(issues),
    )
