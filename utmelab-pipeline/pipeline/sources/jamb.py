"""JAMB harvester implementation for public CBT archives."""

import asyncio
import html
import re
from typing import AsyncIterator, List, Optional
import httpx
from pipeline.sources.base import BaseHarvester, RawOption, RawQuestionPayload

BASE_URL = "https://myschool.ng"
DEFAULT_UA = "utmelab-pipeline/2.0 (educational data factory; research project)"

DETAIL_RE = re.compile(r"/classroom/[^/\"']+/(\d+)\?exam_type=([a-z]+)&(?:amp;)?exam_year=(\d+)")
STEM_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
STEM_P_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.S)
ROW_RE = re.compile(
    r'<div class="(flex gap-6 items-center rounded-lg[^"]*)">\s*'
    r'<div class="flex items-center gap-6">\s*'
    r'<span class="uppercase font-medium">([a-e])</span>\s*'
    r'<p class="font-medium">(.*?)</p>',
    re.S,
)
CORRECT_HEX = "DFFFEC"
IMAGE_SRC_RE = re.compile(r'<img[^>]+src="([^"]+)"')
AD_FILTER_RE = re.compile(r"/storage/serve/|no_image_placeholder|/members/cache/|/ads?/|logo", re.I)
OPTION_ROW_START = 'class="flex gap-6 items-center rounded-lg'


class JambHarvester(BaseHarvester):
    """CBT archive harvester for JAMB UTME papers."""

    def __init__(self, delay_seconds: float = 1.5, user_agent: str = DEFAULT_UA):
        self.delay = delay_seconds
        self.ua = user_agent

    @property
    def source_name(self) -> str:
        return "myschool_jamb"

    @property
    def supported_exams(self) -> List[str]:
        return ["JAMB"]

    @staticmethod
    def _resolve_source_slug(subject: str) -> str:
        # Standard mappings from config/harvest.json
        slug_map = {
            "principles-of-accounts": "accounts-principles-of-accounts",
            "christian-religious-studies": "christian-religious-knowledge-crk",
            "use-of-english": "english-language",
            "art": "fine-arts",
            "islamic-religious-studies": "islamic-religious-knowledge-irk",
        }
        return slug_map.get(subject.lower().strip(), subject.lower().strip())

    async def crawl(
        self,
        subject: str,
        year: Optional[int] = 2025,
        limit: Optional[int] = None,
    ) -> AsyncIterator[RawQuestionPayload]:
        exam_year = year or 2025
        remote_subject = self._resolve_source_slug(subject)
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 utmelab-pipeline/2.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers=headers) as client:
            yielded_count = 0
            page = 1

            while True:
                list_url = f"{BASE_URL}/classroom/{remote_subject}?exam_type=jamb&exam_year={exam_year}&page={page}"
                try:
                    resp = await client.get(list_url)
                    if resp.status_code != 200:
                        break
                    html_content = resp.text
                except Exception:
                    break

                # Find all detail question links on page
                matches = DETAIL_RE.findall(html_content)
                if not matches:
                    break

                # Deduplicate question ids within the page
                seen_on_page = set()
                page_qids = []
                for qid, etype, eyr in matches:
                    if qid not in seen_on_page:
                        seen_on_page.add(qid)
                        page_qids.append((qid, etype, eyr))

                for qid, etype, eyr in page_qids:
                    detail_url = f"{BASE_URL}/classroom/{subject}/{qid}?exam_type={etype}&exam_year={eyr}"
                    await asyncio.sleep(self.delay)

                    try:
                        detail_resp = await client.get(detail_url)
                        if detail_resp.status_code != 200:
                            continue
                        question = self._parse_detail(detail_resp.text, qid, detail_url, subject, int(eyr))
                        if question:
                            yield question
                            yielded_count += 1
                            if limit and yielded_count >= limit:
                                return
                    except Exception:
                        continue

                page += 1

    def _parse_detail(
        self,
        html_text: str,
        qid: str,
        detail_url: str,
        subject: str,
        year: int,
    ) -> Optional[RawQuestionPayload]:
        # Extract stem
        h1_match = STEM_RE.search(html_text)
        if not h1_match:
            return None

        h1_body = h1_match.group(1)
        paragraphs = [html.unescape(p.strip()) for p in STEM_P_RE.findall(h1_body) if p.strip()]
        # Strip trailing &nbsp; padding
        non_empty_p = [p for p in paragraphs if p and p != "&nbsp;" and not p.isspace()]
        stem = " ".join(non_empty_p) if non_empty_p else html.unescape(re.sub(r"<[^>]+>", " ", h1_body).strip())

        # Extract options and correct answer
        options: List[RawOption] = []
        correct_answer = None

        for row_classes, opt_id, opt_text in ROW_RE.findall(html_text):
            clean_text = html.unescape(re.sub(r"<[^>]+>", " ", opt_text).strip())
            clean_id = opt_id.strip().lower()
            options.append(RawOption(id=clean_id, text=clean_text))
            if CORRECT_HEX in row_classes:
                correct_answer = clean_id

        if not options or not correct_answer:
            return None

        # Extract diagram images bounded between h1 and options
        media_url = None
        start = html_text.find("<h1")
        if start >= 0:
            stop = html_text.find(OPTION_ROW_START, start)
            body_region = html_text[start : stop if stop > 0 else start + 8000]
            for img_src in IMAGE_SRC_RE.findall(body_region):
                if not AD_FILTER_RE.search(img_src):
                    media_url = img_src
                    break

        return RawQuestionPayload(
            source_name=self.source_name,
            source_url=detail_url,
            source_item_id=qid,
            exam="JAMB",
            subject=subject,
            year=year,
            stem=stem,
            options=options,
            reported_answer=correct_answer,
            media_url=media_url,
        )
