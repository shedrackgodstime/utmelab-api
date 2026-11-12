#!/usr/bin/env python3
"""Census of the source: how many questions it actually carries.

Read only. It asks the source what it holds for a subject and a year, so the
question of what is available is answered by the source and not by guesswork.
"""
import json
from pathlib import Path

import httpx

ROOT = Path("/home/kristency/Projects/utmelab-api/utmelab-bank")
OUT = Path("/home/kristency/Projects/utmelab-api/data/coverage/source-census.json")
HEADERS = {"User-Agent": "utmelab-bank/2.0 (+https://utmelab.com)", "Accept": "application/json"}

SUBJECTS = {
    "jamb": ["physics", "mathematics", "english-language", "chemistry", "biology"],
    "waec": ["physics", "mathematics", "english-language", "chemistry", "biology"],
    "neco": ["physics", "mathematics", "english-language"],
}
YEARS = range(2014, 2026)


def main():
    census = {}
    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        for exam, subjects in SUBJECTS.items():
            for subject in subjects:
                total = 0
                years = {}
                for year in YEARS:
                    url = (
                        f"https://myschool.ng/api/web/v1/classroom/{subject}"
                        f"?exam_type={exam}&exam_year={year}&page=1"
                    )
                    try:
                        response = client.get(url)
                        if response.status_code != 200:
                            years[str(year)] = {"status": response.status_code, "total": 0}
                            continue
                        data = response.json().get("data") or {}
                        questions = data.get("practice_questions") or {}
                        count = int(questions.get("total") or 0)
                        years[str(year)] = {"status": 200, "total": count, "pages": questions.get("last_page", 0)}
                        total += count
                    except Exception as error:
                        years[str(year)] = {"status": "error", "total": 0, "error": str(error)[:80]}
                census[f"{exam}/{subject}"] = {"total": total, "years": years}
                print(f"{exam:<6} {subject:<18} {total:>6} questions over {len(YEARS)} years")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(census, ensure_ascii=False, indent=2) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
