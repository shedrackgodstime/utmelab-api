"""Score an OCR result file against the manually checked media labels."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "tests" / "fixtures" / "benchmark" / "manifest.json"


def compact(value: str) -> str:
    """Normalise case and punctuation without correcting model output."""
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def main() -> int:
    parser = argparse.ArgumentParser(description="Score OCR benchmark output")
    parser.add_argument("results", type=Path, help="JSON result file from an OCR run")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    results = {
        Path(row["file"]).stem: row
        for row in json.loads(args.results.read_text(encoding="utf-8"))
    }
    checked: list[dict[str, object]] = []
    failures = 0
    for entry in manifest["entries"]:
        asset_id = entry["asset_id"]
        row = results.get(asset_id)
        expected = entry["expected"]
        if row is None:
            checked.append({"id": entry["id"], "accepted": False, "reason": "missing_result"})
            failures += 1
            continue

        status = row.get("status")
        text = str(row.get("text") or "")
        if expected.get("media_status") == "malformed":
            accepted = status == "input"
            reason = "malformed_input_expected" if accepted else "malformed_input_not_reported"
        elif status != "ok":
            accepted = False
            reason = "ocr_request_failed"
        else:
            missing = [
                fragment
                for fragment in expected["ocr_must_include"]
                if compact(fragment) not in compact(text)
            ]
            accepted = not missing
            reason = "ok" if accepted else "missing_expected_text"
            if missing:
                checked.append(
                    {
                        "id": entry["id"],
                        "accepted": False,
                        "reason": reason,
                        "missing": missing,
                        "text": text,
                    }
                )
                failures += 1
                continue
        checked.append(
            {"id": entry["id"], "accepted": accepted, "reason": reason, "text": text}
        )
        if not accepted:
            failures += 1

    print(json.dumps({"cases": len(checked), "failures": failures, "results": checked}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
