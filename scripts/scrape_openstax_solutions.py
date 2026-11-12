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
import re
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
# A concept records the book it came from and the module id, so the modules to
# re-extract are discovered from the corpus rather than listed by hand.
BOOK_RE = re.compile(r"^(osbooks-[a-z0-9-]+)$")


def discover_modules():
    """Map "<repo>:<module_id>" to the concept files that came from it."""
    found = {}
    for path in sorted((ROOT / "data/concepts").glob("*.json")):
        try:
            document = json.loads(path.read_text())
        except Exception:
            continue
        source = document.get("source_attribution") or {}
        book = (source.get("book") or "").strip()
        module = (source.get("section") or "").strip()
        if not module:
            continue
        if BOOK_RE.match(book):
            found.setdefault(f"{book}:{module}", []).append(path)
    return found


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
        # OpenStax sometimes puts a number or a unit inside <mtext> even
        # though it is part of the expression. Prose stays prose; a value
        # that carries a digit, or a short unit such as "m/s", is maths.
        if re.search(r"\d", txt) or (
            len(txt) <= 6 and " " not in txt and re.fullmatch(r"[A-Za-z/°%^0-9]+", txt)
        ):
            return txt
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


def clean_math(text: str) -> str:
    """Repair the way CNXML splits numbers and units across MathML nodes.

    OpenStax writes a value such as 2.64 x 10^7 as separate nodes, so the
    raw conversion yields "2 . 64 x { 10 }^{7}" and the decimal point drifts
    away from its digits. Strip the stray dollar signs the source sometimes
    leaves inside the maths, and pull the spaces back around the separators.
    """
    text = text.replace("$", "")
    text = re.sub(r"(?<!\\)\s*([.,])\s*", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def split_marked(latex):
    """Split marked LaTeX into maths and prose parts, then merge the maths."""
    parts = []
    for index, chunk in enumerate(latex.split(MARK)):
        if not chunk.strip():
            continue
        if index % 2:
            parts.append(("text", " ".join(chunk.split())))
        else:
            parts.append(("math", clean_math(chunk)))
    merged = []
    for kind, value in parts:
        if kind == "math" and merged and merged[-1][0] == "math":
            merged[-1] = ("math", merged[-1][1] + value)
        else:
            merged.append((kind, value))
    return merged


def parts_of(el):
    """Ordered parts of an element: ('text', str) or ('math', latex)."""
    parts = []
    _collect(el, parts)
    # A decimal point or a comma between two maths parts is part of the
    # number, not a sentence. OpenStax writes "2 . 64" that way.
    parts = [
        ("math", part[1])
        if part[0] == "text" and part[1].strip() and not re.search(r"[A-Za-z0-9]", part[1])
        else part
        for part in parts
    ]
    # A number split across parts, such as 2 . 64, belongs together.
    merged = []
    for kind, value in parts:
        if kind == "math" and merged and merged[-1][0] == "math":
            merged[-1] = ("math", merged[-1][1] + value)
        else:
            merged.append((kind, value))
    return merged


def _collect(el, parts):
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
            parts.extend(parts_of(child))
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
    discovered = discover_modules()
    wanted = sys.argv[1:]
    clean = {}
    for key, concept_paths in discovered.items():
        repo, module = key.split(":", 1)
        if wanted and module not in wanted and key not in wanted:
            continue
        url = f"https://raw.githubusercontent.com/openstax/{repo}/main/modules/{module}/index.cnxml"
        blocks = walk(module, url)
        for concept_path in concept_paths:
            concept = json.loads(concept_path.read_text())
            concept_ids = [b["id"] for b in concept["deep_context"]["blocks"]]
            if len(concept_ids) != len(blocks):
                print(f"warning: {key} block count {len(blocks)} != concept {len(concept_ids)}")
                continue
            for block, concept_id in zip(blocks, concept_ids):
                if block["type"] == "exercise" and block["paragraphs"]:
                    clean[f"{key}:{concept_id}"] = [
                        [{"kind": kind, "text": value} for kind, value in paragraph]
                        for paragraph in block["paragraphs"]
                    ]
        print(f"{key}: {len(blocks)} blocks, {len(concept_paths)} concept file(s)")

    out = ROOT / "data/staging/openstax_clean_solutions.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    # Keep the modules that were extracted earlier. This file is the extract
    # for the whole corpus, not for the run.
    if out.exists():
        existing = json.loads(out.read_text())
        existing.update(clean)
        clean = existing
    out.write_text(json.dumps(clean, ensure_ascii=False, indent=2) + "\n")
    print("wrote", out, len(clean), "solutions")


if __name__ == "__main__":
    main()
