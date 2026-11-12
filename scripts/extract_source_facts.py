#!/usr/bin/env python3
"""Pull the facts a chapter can inherit from its source.

    python3 scripts/extract_source_facts.py [module_id ...]

For every module it reads the CNXML and writes
data/staging/source-facts/<module_id>.json holding the source's own learning
objectives, its section summary and its glossary. A chapter then inherits
these instead of having them written again.
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data/staging/source-facts"
NS = {"c": "http://cnx.rice.edu/cnxml"}
REPO = "osbooks-college-physics-bundle"
HEADERS = {"User-Agent": "utmelab-bank/2.0 (+https://utmelab.com)"}


def text_of(element):
    """The plain text of an element, with the mathematics kept as it is."""
    return " ".join("".join(element.itertext()).split())


def learning_objectives(root):
    for section in root.iter("{http://cnx.rice.edu/cnxml}section"):
        title = section.findtext("c:title", default="", namespaces=NS)
        if title.strip().lower() != "learning objectives":
            continue
        items = []
        for item in section.iter("{http://cnx.rice.edu/cnxml}item"):
            text = text_of(item)
            if text:
                items.append(text)
        return items
    return []


def section_summary(root):
    for section in root.iter("{http://cnx.rice.edu/cnxml}section"):
        title = section.findtext("c:title", default="", namespaces=NS)
        if title.strip().lower() != "section summary":
            continue
        points = []
        for item in section.iter("{http://cnx.rice.edu/cnxml}item"):
            text = text_of(item)
            if text:
                points.append(text)
        if not points:
            for para in section.iter("{http://cnx.rice.edu/cnxml}para"):
                text = text_of(para)
                if len(text) > 40:
                    points.append(text)
        return points[:6]
    return []


def glossary(root):
    entries = []
    for element in root.iter("{http://cnx.rice.edu/cnxml}glossary"):
        for definition in element.iter("{http://cnx.rice.edu/cnxml}definition"):
            term = definition.find("c:term", NS)
            body = definition.find("c:meaning", NS)
            if term is None or body is None:
                continue
            term_text = text_of(term)
            meaning = text_of(body)
            if term_text and meaning:
                entries.append({"term": term_text, "definition": meaning})
    return entries


def main():
    modules = sys.argv[1:]
    if not modules:
        OUT.mkdir(parents=True, exist_ok=True)
        modules = sorted(
            path.stem.replace("phy_", "")
            for path in (ROOT / "data/concepts").glob("phy_m*.json")
        )
    OUT.mkdir(parents=True, exist_ok=True)
    written = 0
    with httpx.Client(headers=HEADERS, timeout=60, follow_redirects=True) as client:
        for module in modules:
            path = OUT / f"{module}.json"
            if path.exists():
                continue
            url = f"https://raw.githubusercontent.com/openstax/{REPO}/main/modules/{module}/index.cnxml"
            try:
                content = client.get(url).content
                root = ET.fromstring(content)
            except Exception as error:
                print(f"{module}: failed, {str(error)[:60]}")
                continue
            title = root.findtext("c:title", default="", namespaces=NS)
            facts = {
                "module": module,
                "title": title,
                "objectives": learning_objectives(root),
                "summary": section_summary(root),
                "glossary": glossary(root),
            }
            path.write_text(json.dumps(facts, ensure_ascii=False, indent=2) + "\n")
            written += 1
            print(f"{module}: {len(facts['objectives'])} objectives, {len(facts['summary'])} summary points, {len(facts['glossary'])} glossary terms")
    print("wrote", written, "fact files")


if __name__ == "__main__":
    main()
