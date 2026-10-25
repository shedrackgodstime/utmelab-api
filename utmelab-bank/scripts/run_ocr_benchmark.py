"""Run one bounded OCR pass over the current golden media manifest."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from utmelab_bank.adapters.media import OcrSpaceClient, OcrSpaceError
from utmelab_bank.config import load_settings

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "tests" / "fixtures" / "benchmark" / "manifest.json"
MEDIA_ROOT = ROOT / "var" / "media-repo" / "media"


def locate(root: Path, asset_id: str) -> Path | None:
    matches = tuple(root.rglob(f"{asset_id}.*"))
    return matches[0] if matches else None


async def run(media_root: Path) -> list[dict[str, object]]:
    settings = load_settings()
    if not settings.ocr_api_key:
        raise RuntimeError("OCR_API_KEY is not configured")
    client = OcrSpaceClient(settings.ocr_api_key)
    results: list[dict[str, object]] = []
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        for entry in manifest["entries"]:
            path = locate(media_root, entry["asset_id"])
            if path is None:
                results.append({"file": f"{entry['asset_id']}.png", "status": "missing"})
                continue
            data = path.read_bytes()
            mime = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
            started = time.perf_counter()
            try:
                record = await client.extract(asset_id=entry["asset_id"], data=data, mime=mime)
                results.append(
                    {
                        "file": path.name,
                        "status": "ok",
                        "chars": len(record.text),
                        "seconds": round(time.perf_counter() - started, 3),
                        "text": record.text,
                    }
                )
            except OcrSpaceError as exc:
                results.append(
                    {
                        "file": path.name,
                        "status": exc.category,
                        "chars": 0,
                        "seconds": round(time.perf_counter() - started, 3),
                        "text": "",
                        "error": str(exc),
                    }
                )
    finally:
        await client.close()
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the current OCR benchmark")
    parser.add_argument("--media-root", type=Path, default=MEDIA_ROOT)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.media_root)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
