"""WAEC harvester implementation for public CBT archives."""

import asyncio
import html
import re
from typing import AsyncIterator, List, Optional
import httpx
from pipeline.sources.base import BaseHarvester, RawOption, RawQuestionPayload
from pipeline.sources.jamb import extract_passage_from_html

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


class WaecHarvester(BaseHarvester):
    """CBT archive harvester for WAEC SSCE objective papers."""

    def __init__(self, delay_seconds: float = 1.5, user_agent: str = DEFAULT_UA):
        self.delay = delay_seconds
        self.ua = user_agent

    @property
    def source_name(self) -> str:
        return "myschool_waec"

    @property
    def supported_exams(self) -> List[str]:
        return ["WAEC"]

    async def crawl(
        self,
        subject: str,
        year: Optional[int] = 2024,
        limit: Optional[int] = None,
    ) -> AsyncIterator[RawQuestionPayload]:
        exam_year = year or 2024
        headers = {"User-Agent": self.ua, "Accept": "text/html,application/xhtml+xml"}

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, headers=headers) as client:
            yielded_count = 0
            page = 1

            while True:
                list_url = f"{BASE_URL}/classroom/{subject}?exam_type=waec&exam_year={exam_year}&page={page}"
                try:
                    resp = await client.get(list_url)
                    if resp.status_code != 200:
                        break
                    html_content = resp.text
                except Exception:
                    break

                matches = DETAIL_RE.findall(html_content)
                if not matches:
                    break

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
        h1_match = STEM_RE.search(html_text)
        if not h1_match:
            return None

        h1_body = h1_match.group(1)
        paragraphs = [html.unescape(p.strip()) for p in STEM_P_RE.findall(h1_body) if p.strip()]
        non_empty_p = [p for p in paragraphs if p and p != "&nbsp;" and not p.isspace()]
        stem = " ".join(non_empty_p) if non_empty_p else html.unescape(re.sub(r"<[^>]+>", " ", h1_body).strip())

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

        media_url = None
        start = html_text.find("<h1")
        if start >= 0:
            stop = html_text.find(OPTION_ROW_START, start)
            body_region = html_text[start : stop if stop > 0 else start + 8000]
            for img_src in IMAGE_SRC_RE.findall(body_region):
                if not AD_FILTER_RE.search(img_src):
                    media_url = img_src
                    break

        if media_url:
            if media_url.startswith("//"):
                media_url = f"https:{media_url}"
            elif media_url.startswith("/"):
                media_url = f"{BASE_URL}{media_url}"
            elif media_url.startswith("http://"):
                media_url = f"https://{media_url[7:]}"

        passage_text = extract_passage_from_html(html_text)

        return RawQuestionPayload(
            source_name=self.source_name,
            source_url=detail_url,
            source_item_id=qid,
            exam="WAEC",
            subject=subject,
            year=year,
            stem=stem,
            options=options,
            reported_answer=correct_answer,
            media_url=media_url,
            passage_text=passage_text,
        )
