"""Run deterministic checks over the local golden media manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from utmelab_bank.adapters.media import check_media
from utmelab_bank.domain.models import MediaAsset

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "tests" / "fixtures" / "benchmark" / "manifest.json"
MEDIA_ROOT = ROOT / "var" / "media-repo" / "media"


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local golden media assets")
    parser.add_argument("--media-root", type=Path, default=MEDIA_ROOT)
    args = parser.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    results: list[dict[str, object]] = []
    failures = 0
    for entry in manifest["entries"]:
        asset_id = entry["asset_id"]
        path = args.media_root / asset_id[:2] / f"{asset_id}.png"
        if not path.is_file():
            matches = tuple(args.media_root.rglob(f"{asset_id}.*"))
            path = matches[0] if matches else path
        if not path.is_file():
            results.append({"id": entry["id"], "status": "missing"})
            failures += 1
            continue

        data = path.read_bytes()
        mime = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
        asset = MediaAsset(
            asset_id=asset_id,
            mime=mime,
            byte_size=len(data),
            storage_url=path.name,
            fetched_at=datetime.now(UTC),
        )
        check = check_media(asset, data, expected_kind=entry["kind"])
        expected_status = entry["expected"].get("media_status")
        accepted = (
            check.status == "invalid"
            if expected_status == "malformed"
            else check.status != "invalid"
        )
        if not accepted:
            failures += 1
        results.append(
            {
                "id": entry["id"],
                "asset_id": asset_id,
                "status": check.status,
                "issues": list(check.issues),
                "accepted": accepted,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )

    print(json.dumps({"cases": len(results), "failures": failures, "results": results}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
