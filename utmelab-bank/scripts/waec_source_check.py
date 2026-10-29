#!/usr/bin/env python3
"""
Strict WAEC source check against MySchool.

Loads prod WAEC subjects, maps via current subjects.json, probes MySchool for 2022-2025.
Outputs CSV/JSON with availability per subject per year.
"""
import asyncio
import json
import sys
import subprocess
from pathlib import Path
import httpx

PROJECT_ROOT = Path(__file__).parent.parent
SUBJECTS_JSON = PROJECT_ROOT / "src/utmelab_bank/adapters/sources/myschool/subjects.json"
UTMELAB_DB = PROJECT_ROOT / ".venv/bin/utmelab-db"

HEADERS = {
    "User-Agent": "utmelab-bank/2.0 (+https://utmelab.com)",
    "Accept": "application/json",
}

async def load_prod_subjects():
    """Query prod DB for WAEC subjects."""
    cmd = [
        str(UTMELAB_DB), "--database", "prod", "query",
        "SELECT slug, name FROM subjects WHERE exam='WAEC' ORDER BY slug"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"DB query failed: {result.stderr}")
    
    subjects = []
    for line in result.stdout.strip().split("\n")[2:]:  # skip header
        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2 and parts[0]:
                subjects.append({"slug": parts[0], "name": parts[1]})
    return subjects

def load_mappings():
    """Load current WAEC source slug mappings from subjects.json."""
    with open(SUBJECTS_JSON) as f:
        data = json.load(f)
    mappings = {}
    for s in data["exams"]["waec"]["subjects"]:
        mappings[s["slug"]] = s["source"]
    return mappings

async def probe_subject(client, source_slug, year):
    """Probe MySchool for one subject/year."""
    url = f"https://myschool.ng/api/web/v1/classroom/{source_slug}?exam_type=waec&exam_year={year}&page=1"
    try:
        resp = await client.get(url, timeout=30.0)
        if resp.status_code == 404:
            return {"status": "404", "total": 0, "pages": 0, "has_data": False}
        data = resp.json()
        pq = (data.get("data") or {}).get("practice_questions") if isinstance(data.get("data"), dict) else None
        if pq:
            total = pq.get("total", 0)
            pages = pq.get("last_page", 1)
            has_data = len(pq.get("data", [])) > 0
            return {"status": str(resp.status_code), "total": total, "pages": pages, "has_data": has_data}
        return {"status": str(resp.status_code), "total": 0, "pages": 0, "has_data": False}
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "total": 0, "pages": 0, "has_data": False}

async def main():
    print("Loading prod WAEC subjects...")
    subjects = await load_prod_subjects()
    print(f"Found {len(subjects)} WAEC subjects in prod")
    
    mappings = load_mappings()
    print(f"Loaded {len(mappings)} WAEC source mappings")
    
    # Check for unmapped subjects
    unmapped = [s for s in subjects if s["slug"] not in mappings]
    if unmapped:
        print(f"WARNING: {len(unmapped)} subjects have no mapping:", [s["slug"] for s in unmapped])
    
    results = []
    async with httpx.AsyncClient(headers=HEADERS, timeout=httpx.Timeout(30.0, connect=15.0), follow_redirects=True) as client:
        for subj in subjects:
            catalog_slug = subj["slug"]
            prod_name = subj["name"]
            source_slug = mappings.get(catalog_slug)
            
            if not source_slug:
                results.append({
                    "prod_slug": catalog_slug,
                    "prod_name": prod_name,
                    "source_slug": None,
                    "years": {str(y): {"status": "UNMAPPED"} for y in range(2022, 2026)}
                })
                continue
            
            year_results = {}
            for year in range(2022, 2026):
                probe = await probe_subject(client, source_slug, year)
                year_results[str(year)] = probe
                print(f"  {catalog_slug:35} src={source_slug:35} year={year} status={probe['status']} total={probe.get('total',0)} pages={probe.get('pages',0)}")
            
            results.append({
                "prod_slug": catalog_slug,
                "prod_name": prod_name,
                "source_slug": source_slug,
                "years": year_results
            })
    
    # Output CSV
    print("\n=== CSV ===")
    header = ["prod_slug", "prod_name", "source_slug"] + [f"{y}_status" for y in range(2022,2026)] + [f"{y}_total" for y in range(2022,2026)] + [f"{y}_pages" for y in range(2022,2026)]
    print(",".join(header))
    for r in results:
        row = [r["prod_slug"], r["prod_name"], r["source_slug"] or ""]
        for y in range(2022, 2026):
            yr = r["years"][str(y)]
            row.append(yr.get("status", ""))
            row.append(str(yr.get("total", 0)))
            row.append(str(yr.get("pages", 0)))
        print(",".join(row))
    
    # Output JSON
    out_file = PROJECT_ROOT / "waec_source_check_results.json"
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nJSON written to {out_file}")

if __name__ == "__main__":
    asyncio.run(main())