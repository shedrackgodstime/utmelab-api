from datetime import UTC, datetime

from tests.media_fakes import PNG_1X1
from utmelab_bank.adapters.media import check_media
from utmelab_bank.domain.models import MediaAsset


def _asset(data: bytes = PNG_1X1) -> MediaAsset:
    import hashlib

    return MediaAsset(
        asset_id=hashlib.sha256(data).hexdigest(),
        mime="image/png",
        byte_size=len(data),
        width=1,
        height=1,
        storage_url="figure.png",
        fetched_at=datetime.now(UTC),
    )


def test_media_check_accepts_matching_image_and_empty_diagram_ocr() -> None:
    result = check_media(
        _asset(),
        PNG_1X1,
        ocr_text="",
        expected_kind="diagram_only",
    )

    assert result.status == "ok"
    assert result.ocr_status == "empty"
    assert result.issues == ()


def test_media_check_flags_empty_ocr_for_expected_text_media() -> None:
    result = check_media(_asset(), PNG_1X1, ocr_text="", expected_kind="labelled_diagram")

    assert result.status == "review"
    assert result.issues == ("ocr_empty_on_expected_text_media",)


def test_media_check_rejects_changed_bytes() -> None:
    result = check_media(_asset(), b"not-an-image")

    assert result.status == "invalid"
    assert "asset_hash_mismatch" in result.issues
    assert "unreadable_image" in result.issues
