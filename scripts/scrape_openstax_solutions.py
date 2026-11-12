#!/usr/bin/env python3
"""Re-extract OpenStax exercise solutions with prose and math kept apart.

Usage:
    python3 scripts/scrape_openstax_solutions.py [module_id ...]

The concept scraper (scripts/scrape_openstax_cnx.py) joins prose and maths
into one string, which mangles a solution into something like
"$\\sqrt{12\\cdot 3}Express the product as a single radical
expression.\\sqrt{36}Simplify.6$". A chapter needs the solution as steps,
with the prose and the mathematics apart, so this walks the same CNXML in the
same order as the concept scraper (the block ids line up) and keeps the two
apart: OpenStax hides the prose of a worked solution inside MathML <mtext>,
and this marks it instead of folding it into the LaTeX.

Writes data/staging/openstax_clean_solutions.json, keyed
"<module_id>:<block_id>".

Non-commercial staging only (CC BY-NC-SA 4.0 attribution kept in file).
"""
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import scrape_openstax_cnx as scraper  # noqa: E402  the same traversal, so ids line up

NS = {"c": "http://cnx.rice.edu/cnxml"}
HEADERS = {"User-Agent": "Mozilla/5.0"}
MARK = "\u0001"
REPO = "osbooks-college-algebra-bundle"
MODULES = {
    "m51241": "data/concepts/math_indices.json",
    "m51242": "data/concepts/math_surds.json",
}


def tex_marked(el) -> str:
    """The scraper's converter, but <mtext> becomes a marked prose run."""
    if el is None:
        return ""
    tag = el.tag.split("}")[-1]
    txt = el.text.strip() if el.text and el.text.strip() else ""
    kids = list(el)
    if tag == "math":
        return (txt + "".join(tex_marked(k) for k in kids)).strip()
    if tag in ("mi", "mn"):
        return txt
    if tag == "mo":
        return {"−": "-", "–": "-", "·": "\\cdot ", "⋅": "\\cdot "}.get(txt, txt)
    if tag == "mtext":
        return f"{MARK}{txt}{MARK}"
    if tag == "mfrac":
        a = tex_marked(kids[0]) if len(kids) > 0 else "?"
        b = tex_marked(kids[1]) if len(kids) > 1 else "?"
        return f"\\frac{{{a}}}{{{b}}}"
    if tag == "msup":
        a = tex_marked(kids[0]) if kids else "?"
        b = tex_marked(kids[1]) if len(kids) > 1 else "?"
        return f"{{{a}}}^{{{b}}}"
    if tag == "msub":
        a = tex_marked(kids[0]) if kids else "?"
        b = tex_marked(kids[1]) if len(kids) > 1 else "?"
        return f"{{{a}}}_{{{b}}}"
    if tag == "msubsup":
        a = tex_marked(kids[0]) if kids else "?"
        b = tex_marked(kids[1]) if len(kids) > 1 else "?"
        c = tex_marked(kids[2]) if len(kids) > 2 else "?"
        return f"{{{a}}}_{{{b}}}^{{{c}}}"
    if tag == "msqrt":
        inner = tex_marked(kids[0]) if kids else ""
        return f"\\sqrt{{{inner}}}"
    if tag == "mrow":
        return "".join(tex_marked(k) for k in kids)
    if tag == "mfenced":
        inner = "".join(tex_marked(k) for k in kids)
        return f"({inner})"
    return (txt + "".join(tex_marked(k) for k in kids)).strip()


def split_marked(latex):
    """Split marked LaTeX into alternating maths and prose parts."""
    parts = []
    for index, chunk in enumerate(latex.split(MARK)):
        if not chunk.strip():
            continue
        parts.append(("text" if index % 2 else "math", " ".join(chunk.split())))
    return parts


def parts_of(el):
    """Ordered parts of an element: ('text', str) or ('math', latex)."""
    parts = []
    if el.text and el.text.strip():
        parts.append(("text", el.text.strip()))
    for child in el:
        tag = child.tag.split("}")[-1]
        if tag == "math":
            parts.extend(split_marked(tex_marked(child)))
        elif tag == "emphasis":
            inner = "".join(p[1] for p in parts_of(child))
            if inner:
                parts.append(("text", f"*{inner}*"))
        elif tag == "equation":
            parts.append(("equation", parts_of(child)))
        elif tag == "list":
            items = []
            for item in child:
                if item.tag.split("}")[-1] == "item":
                    items.append(" ".join(p[1] for p in parts_of(item)))
            if items:
                parts.append(("text", "; ".join(i for i in items if i)))
        else:
            inner = parts_of(child)
            if inner:
                parts.extend(inner)
        if child.tail and child.tail.strip():
            parts.append(("text", child.tail.strip()))
    return parts


def solution_paragraphs(sol_el):
    if sol_el is None:
        return []
    return [parts_of(child) for child in sol_el]


def walk(module, url):
    root = ET.fromstring(requests.get(url, headers=HEADERS, timeout=90).content)
    blocks = []
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag == "section":
            if el.findtext("c:title", default="", namespaces=NS):
                blocks.append({"id": f"sec-{len(blocks)}", "type": "heading"})
        elif tag == "para":
            if len(scraper.text_of(el)) < 20:
                continue
            blocks.append({"id": f"p-{len(blocks)}", "type": "paragraph"})
        elif tag == "example":
            blocks.append({"id": f"ex-{len(blocks)}", "type": "example"})
        elif tag == "exercise":
            prob_el = el.find("c:problem", NS)
            prob_txt = scraper.text_of(prob_el) if prob_el is not None else ""
            if prob_txt:
                sol_el = el.find("c:solution", NS)
                blocks.append({
                    "id": f"exr-{len(blocks)}",
                    "type": "exercise",
                    "paragraphs": solution_paragraphs(sol_el) if sol_el is not None else [],
                })
        elif tag == "figure":
            blocks.append({"id": f"fig-{len(blocks)}", "type": "figure"})
        elif tag == "table":
            blocks.append({"id": f"tbl-{len(blocks)}", "type": "table"})
    return blocks


def main():
    wanted = sys.argv[1:] or list(MODULES)
    clean = {}
    for module in wanted:
        concept_path = MODULES.get(module)
        if concept_path is None:
            print(f"unknown module {module}, skipping")
            continue
        url = f"https://raw.githubusercontent.com/openstax/{REPO}/main/modules/{module}/index.cnxml"
        blocks = walk(module, url)
        concept = json.loads((ROOT / concept_path).read_text())
        concept_ids = [b["id"] for b in concept["deep_context"]["blocks"]]
        if len(concept_ids) != len(blocks):
            print(f"warning: {module} block count {len(blocks)} != concept {len(concept_ids)}")
        for block, concept_id in zip(blocks, concept_ids):
            if block["type"] == "exercise" and block["paragraphs"]:
                clean[f"{module}:{concept_id}"] = [
                    [{"kind": kind, "text": value} for kind, value in paragraph]
                    for paragraph in block["paragraphs"]
                ]
        print(f"{module}: {len(blocks)} blocks")

    out = ROOT / "data/staging/openstax_clean_solutions.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(clean, ensure_ascii=False, indent=2) + "\n")
    print("wrote", out, len(clean), "solutions")


if __name__ == "__main__":
    main()
