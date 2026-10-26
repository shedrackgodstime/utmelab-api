"""Deterministic checks for captured media and OCR evidence."""

from __future__ import annotations

import hashlib
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from utmelab_bank.domain.models import MediaAsset, MediaCheck

DIAGRAM_KINDS = {"diagram_only", "electrical_diagram", "graph"}


def validate_image_hash(asset: MediaAsset, data: bytes) -> tuple[bool, list[str]]:
    """Validate the image asset hash and byte size."""
    issues: list[str] = []
    digest = hashlib.sha256(data).hexdigest()
    if digest != asset.asset_id:
        issues.append("asset_hash_mismatch")
    if len(data) != asset.byte_size:
        issues.append("byte_size_mismatch")
    hash_ok = not issues
    return hash_ok, issues


def validate_image_dimensions(
    asset: MediaAsset,
    data: bytes,
) -> tuple[dict[str, int | str | None], list[str]]:
    """Validate image MIME type and dimensions."""
    issues: list[str] = []
    detected_mime: str | None = None
    width: int | None = None
    height: int | None = None

    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
            detected_mime = Image.MIME.get(image.format or "")
    except UnidentifiedImageError, OSError, ValueError:
        issues.append("unreadable_image")

    if not issues:
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
        if detected_mime != asset.mime:
            issues.append("mime_mismatch")
        if not width or not height:
            issues.append("unusable_dimensions")
        if asset.width is not None and width != asset.width:
            issues.append("width_mismatch")
        if asset.height is not None and height != asset.height:
            issues.append("height_mismatch")

    dimensions = {"width": width, "height": height, "detected_mime": detected_mime}
    return dimensions, issues


def determine_ocr_status(
    ocr_error: str | None,
    ocr_text: str | None,
    expected_kind: str | None = None,
) -> tuple[str, list[str]]:
    """Determine OCR status and any related issues."""
    issues: list[str] = []
    if ocr_error:
        return "error", issues
    elif ocr_text is None:
        return "not_run", issues
    elif not ocr_text.strip():
        if expected_kind is not None and expected_kind not in DIAGRAM_KINDS:
            issues.append("ocr_empty_on_expected_text_media")
        return "empty", issues
    elif len(ocr_text.strip()) < 3:
        return "weak", issues
    else:
        return "usable", issues


def determine_media_status(
    hash_ok: bool,
    dim_issues: list[str],
    ocr_status: str,
    ocr_issues: list[str],
) -> str:
    """Determine the final media check status."""
    core_issues = {
        "asset_hash_mismatch",
        "byte_size_mismatch",
        "unreadable_image",
        "mime_mismatch",
        "unusable_dimensions",
        "width_mismatch",
        "height_mismatch",
    }
    all_issues_set: set[str] = set()
    if not hash_ok:
        all_issues_set.add("asset_hash_mismatch")
    all_issues_set.update(dim_issues)
    all_issues_set.update(ocr_issues)

    core_issues_found = core_issues & all_issues_set
    if core_issues_found:
        return "invalid"
    elif all_issues_set:
        return "review"
    else:
        return "ok"


def check_media(
    asset: MediaAsset,
    data: bytes,
    *,
    ocr_text: str | None = None,
    ocr_error: str | None = None,
    expected_kind: str | None = None,
) -> MediaCheck:
    """Check stored bytes without contacting a network or model provider."""
    # Step 1: Validate hash and byte size
    hash_ok, hash_issues = validate_image_hash(asset, data)

    # Step 2: Validate MIME type and dimensions
    dimensions, dim_issues = validate_image_dimensions(asset, data)

    # Step 3: Determine OCR status
    ocr_status, ocr_issues = determine_ocr_status(
        ocr_error,
        ocr_text,
        expected_kind,
    )

    # Step 4: Determine final status
    status = determine_media_status(hash_ok, dim_issues, ocr_status, ocr_issues)

    return MediaCheck(
        asset_id=asset.asset_id,
        status=status,
        mime=asset.mime,
        detected_mime=dimensions["detected_mime"],
        byte_size=len(data),
        width=dimensions["width"],
        height=dimensions["height"],
        ocr_status=ocr_status,
        issues=tuple(hash_issues + dim_issues + ocr_issues),
    )
