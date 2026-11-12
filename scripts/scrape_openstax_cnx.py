#!/usr/bin/env python3
"""Convert one OpenStax CNXML module file into our concept block JSON shape.

Usage:
    python3 scripts/scrape_openstax_cnx.py <repo> <module_id> <concept_id>

Example:
    python3 scripts/scrape_openstax_cnx.py osbooks-college-algebra-bundle m49363 math_indices_logarithms

Reads https://raw.githubusercontent.com/openstax/<repo>/main/modules/<module>/index.cnxml
plus media files from <repo>/media/. Emits data/concepts/<concept_id>.json
with typed blocks (heading, paragraph, example, exercise+solutions, figure,
table) and downloads media into data/concepts/images/.
Non-commercial staging only (CC BY-NC-SA 4.0 attribution kept in file).
"""
import argparse
import json
import pathlib
import re

import requests
import xml.etree.ElementTree as ET

OUT_DIR = pathlib.Path("data/concepts")
IMG_DIR = OUT_DIR / "images"
HEADERS = {"User-Agent": "Mozilla/5.0"}
NS = {"c": "http://cnx.rice.edu/cnxml", "m": "http://www.w3.org/1998/Math/MathML"}


def rt(t: str):
    return {"text": " ".join(str(t).split()), "inline": []}


def tex(el) -> str:
    """Very small MathML->LaTeX for the elements OpenStax uses (frac, sup, sub, row)."""
    if el is None:
        return ""
    tag = el.tag.split("}")[-1]
    txt = el.text.strip() if el.text and el.text.strip() else ""
    kids = list(el)
    if tag == "math":
        return (txt + "".join(tex(k) for k in kids)).strip()
    if tag == "mi":
        return txt
    if tag == "mn":
        return txt
    if tag == "mo":
        return {"−": "-", "–": "-", "·": "\\cdot ", "⋅": "\\cdot "}.get(txt, txt)
    if tag == "mtext":
        return txt
    if tag == "mfrac":
        a = tex(kids[0]) if len(kids) > 0 else "?"
        b = tex(kids[1]) if len(kids) > 1 else "?"
        return f"\\frac{{{a}}}{{{b}}}"
    if tag == "msup":
        a = tex(kids[0]) if len(kids) > 0 else "?"
        b = tex(kids[1]) if len(kids) > 1 else "?"
        return f"{{{a}}}^{{{b}}}"
    if tag == "msub":
        a = tex(kids[0]) if len(kids) > 0 else "?"
        b = tex(kids[1]) if len(kids) > 1 else "?"
        return f"{{{a}}}_{{{b}}}"
    if tag == "msubsup":
        a = tex(kids[0]) if len(kids) > 0 else "?"
        b = tex(kids[1]) if len(kids) > 1 else "?"
        c = tex(kids[2]) if len(kids) > 2 else "?"
        return f"{{{a}}}_{{{b}}}^{{{c}}}"
    if tag == "msqrt":
        inner = tex(kids[0]) if kids else ""
        return f"\\sqrt{{{inner}}}"
    if tag == "mrow":
        return "".join(tex(k) for k in kids)
    if tag == "mfenced":
        inner = "".join(tex(k) for k in kids)
        ot = el.get("open", "(")
        ct = el.get("close", ")")
        return f"{ot}{inner}{ct}"
    # fallback: concatenate text + children
    return (txt + "".join(tex(k) for k in kids)).strip()


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


def text_of(el) -> str:
    """Plain text of a CNXML element including math as LaTeX, no duplication."""
    parts = []
    if el.text and el.text.strip():
        parts.append(el.text.strip())
    for child in el:
        tag = child.tag.split("}")[-1]
        if tag == "math":
            parts.append("$" + clean_math(tex(child)) + "$")
        elif tag == "xref":
            # A cross reference to a figure or a section. The reference text
            # in the source is a number the reader cannot see, so say what it
            # points at instead of leaving a hole in the sentence.
            href = child.get("url", "") or ""
            parts.append("the figure" if "figure" in href else "the section")
        elif tag in ("emphasis", "span", "link"):
            # link text included; emphasis is italic marker in HTML, keep text
            sub = text_of(child)
            if tag == "emphasis" and sub:
                sub = f"*{sub}*"
            parts.append(sub)
        elif tag == "equation":
            inner = text_of(child)
            parts.append(f"\\[{inner}\\]")
        elif tag == "list":
            items = [text_of(it) for it in child if it.tag.split("}")[-1] == "item"]
            items = [i for i in items if i]
            if items:
                parts.append("; ".join(items))
        else:
            parts.append(text_of(child))
        if child.tail and child.tail.strip():
            parts.append(child.tail.strip())
    return " ".join(p for p in parts if p).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("module")
    ap.add_argument("concept_id")
    ap.add_argument("subject_area", nargs="?", default="mathematics",
                    help="broad subject area stored on the concept (default: mathematics)")
    args = ap.parse_args()

    cnxml_url = f"https://raw.githubusercontent.com/openstax/{args.repo}/main/modules/{args.module}/index.cnxml"
    r = requests.get(cnxml_url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    root = ET.fromstring(r.content)

    title = root.findtext("c:title", default=args.concept_id, namespaces=NS)
    blocks = []
    figures = []
    IMG_DIR.mkdir(parents=True, exist_ok=True)

    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag == "section":
            t = el.findtext("c:title", default="", namespaces=NS)
            if t:
                blocks.append({"id": f"sec-{len(blocks)}", "type": "heading", "level": "core", "text": rt(t)})
        elif tag == "para":
            txt = text_of(el)
            if len(txt) < 20:
                continue
            blocks.append({"id": f"p-{len(blocks)}", "type": "paragraph", "content": rt(txt), "level": "core"})
        elif tag == "example":
            t = el.findtext("c:title", default="", namespaces=NS)
            prob = el.findtext("c:problem", default="", namespaces=NS)
            prob_el = el.find("c:problem", NS)
            prob_txt = text_of(prob_el) if prob_el is not None else prob
            sol_el = el.find("c:solution", NS)
            sol_txt = text_of(sol_el) if sol_el is not None else ""
            blocks.append({"id": f"ex-{len(blocks)}", "type": "example", "kind": "worked", "title": rt(t or "Example"), "problem": rt(prob_txt), "answer": rt(sol_txt) if sol_txt else None, "level": "core"})
        elif tag == "exercise":
            prob_el = el.find("c:problem", NS)
            sol_el = el.find("c:solution", NS)
            prob_txt = text_of(prob_el) if prob_el is not None else ""
            sol_txt = text_of(sol_el) if sol_el is not None else ""
            if prob_txt:
                b = {"id": f"exr-{len(blocks)}", "type": "exercise", "category": "section", "prompt": rt(prob_txt), "level": "core", "solution": rt(sol_txt) if sol_txt else None,
                     "solution_provenance": "OpenStax CNXML solution element (in file)" if sol_txt else "no solution element in CNXML"}
                blocks.append(b)
        elif tag == "figure":
            media = el.find("c:media", NS)
            img = media.find("c:image", NS) if media is not None else None
            src = img.get("src") if img is not None else ""
            alt = media.get("alt", "") if media is not None else ""
            cap_el = el.find("c:caption", NS)
            cap = text_of(cap_el) if cap_el is not None else alt
            # download media file
            if src:
                fname = pathlib.Path(src).name
                # Asset names travel in URLs and file names, so they carry no
                # spaces or other shell-unfriendly characters.
                slug = re.sub(r"[^A-Za-z0-9._-]+", "_", fname).strip("_")
                fpath = IMG_DIR / f"{args.concept_id}_{slug}"
                if not fpath.exists():
                    mr = requests.get(f"https://raw.githubusercontent.com/openstax/{args.repo}/main/media/{fname}", headers=HEADERS, timeout=30)
                    if mr.status_code == 200:
                        fpath.write_bytes(mr.content)
                if fpath.exists():
                    # The asset path is the local one, whether this run
                    # downloaded the file or an earlier run already had it.
                    src = f"images/{fpath.name}"  # keep relative src
            figures.append(src)
            blocks.append({"id": f"fig-{len(figures)}", "type": "figure", "asset_url": src, "caption": rt(cap), "alt": alt, "licence": "CC BY-NC-SA 4.0", "credit": "OpenStax", "level": "core"})
        elif tag == "table":
            rows = []
            for row in el.findall(".//c:row", NS):
                cells = [text_of(e) for e in row.findall("c:entry", NS)]
                if cells:
                    rows.append(cells)
            if rows:
                blocks.append({"id": f"tbl-{len(blocks)}", "type": "table", "title": rt("Table"), "rows": rows, "alt": f"Table with {len(rows)} rows", "level": "core"})

    doc = {
        "concept_id": args.concept_id,
        "schema_version": 4,
        "updated_at": __import__("datetime").date.today().isoformat(),
        "title": title,
        "subject_area": args.subject_area,
        "source_attribution": {"publisher": "OpenStax", "book": args.repo, "section": args.module, "url": f"https://github.com/openstax/{args.repo}/blob/main/modules/{args.module}/index.cnxml", "licence": "CC BY-NC-SA 4.0 (non-commercial staging; attribution required)", "locator": "CNXML module index.cnxml (typed elements, solutions present)"},
        "revision_summary": {"read_time_minutes": 4, "key_takeaway": rt("See deep_context.blocks for the full sourced section."), "sections": [], "worked_examples": [], "formulas": [], "active_recall_checks": [], "examiner_traps": [], "sources": [{"title": f"{args.repo} {args.module} (CNXML)", "url": cnxml_url, "locator": "CNXML index.cnxml"}]},
        "deep_context": {"blocks": blocks},
        "placements": [],
    }
    out = OUT_DIR / f"{args.concept_id}.json"
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out} with {len(blocks)} blocks ({len(figures)} figures). title={title}")
    kinds = {}
    for b in blocks:
        kinds[b["type"]] = kinds.get(b["type"], 0) + 1
    print(kinds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
