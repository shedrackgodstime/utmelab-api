#!/usr/bin/env python3
"""Structural validator for concept documents in data/concepts/*.json.

Checks schema_version 4, required top-level/source/revision fields,
revision_summary size (<16 KiB), placement shape, and basic deep_context
block/RichText structure. Excludes audit-*.json files.
"""
import json
import glob
import sys
from collections import Counter
from pathlib import Path

REQUIRED_TOP = ['concept_id', 'schema_version', 'updated_at', 'title', 'subject_area',
                'source_attribution', 'revision_summary', 'deep_context', 'placements']
REQUIRED_SRC = ['publisher', 'book', 'section', 'url', 'licence', 'locator']
REQUIRED_RS = ['read_time_minutes', 'key_takeaway', 'sections', 'worked_examples',
               'formulas', 'active_recall_checks', 'examiner_traps', 'sources']
KNOWN_BLOCK_TYPES = {'heading', 'paragraph', 'definition', 'theorem', 'proof', 'procedure',
                     'example', 'exercise', 'figure', 'table', 'passage', 'cloze', 'quote',
                     'media', 'formula', 'summary', 'glossary_entry', 'list'}


def is_richtext(x):
    return isinstance(x, dict) and isinstance(x.get('text'), str) and isinstance(x.get('inline'), list)


def check_inline(rt, path, errors):
    if not is_richtext(rt):
        errors.append((path, 'not richtext'))
        return
    text = rt['text']
    n = len(text)
    for it in rt.get('inline', []):
        if not isinstance(it, dict):
            errors.append((path, 'inline item not dict'))
            continue
        s = it.get('start')
        e = it.get('end')
        if not isinstance(s, int) or not isinstance(e, int) or s < 0 or e < s or e > n:
            errors.append((path, f'inline offset invalid {s},{e},len={n}'))


def check_blocks(blocks, path, errors, depth=0):
    if not isinstance(blocks, list):
        errors.append((path, 'blocks not list'))
        return
    seen = set()
    for b in blocks:
        if not isinstance(b, dict):
            errors.append((path, 'block not dict'))
            continue
        bid = b.get('id')
        btype = b.get('type')
        if not isinstance(bid, str) or not bid:
            errors.append((path, 'block missing id'))
            bid_repr = '<none>'
        else:
            bid_repr = bid
            if bid in seen:
                errors.append((path, f'duplicate block id {bid}'))
            else:
                seen.add(bid)
        if btype not in KNOWN_BLOCK_TYPES:
            errors.append((path, f'unknown block type {btype}'))
        if btype == 'heading':
            check_inline(b.get('text'), path + f'[{bid_repr}].text', errors)
        elif btype == 'paragraph':
            check_inline(b.get('content'), path + f'[{bid_repr}].content', errors)
        elif btype == 'definition':
            check_inline(b.get('term', {}), path + f'[{bid_repr}].term', errors)
            check_inline(b.get('definition', {}), path + f'[{bid_repr}].definition', errors)
        elif btype == 'summary':
            pts = b.get('points', [])
            if isinstance(pts, list):
                for j, p in enumerate(pts):
                    check_inline(p, path + f'[{bid_repr}].points[{j}]', errors)
        elif btype == 'list':
            if not isinstance(b.get('items', []), list):
                errors.append((path, f'[{bid_repr}] list items not list'))
        for k in ('steps', 'proof_steps', 'blocks'):
            if k in b and isinstance(b[k], list):
                check_blocks(b[k], path + f'[{bid_repr}].{k}', errors, depth + 1)


def validate(path):
    errors = []
    try:
        d = json.loads(Path(path).read_text())
    except Exception as e:
        return [(path, f'json parse: {e}')]
    for k in REQUIRED_TOP:
        if k not in d:
            errors.append((path, f'missing {k}'))
    if d.get('schema_version') != 4:
        errors.append((path, 'schema_version != 4'))
    src = d.get('source_attribution', {})
    if not isinstance(src, dict):
        errors.append((path, 'source_attribution not dict'))
    else:
        for k in REQUIRED_SRC:
            if not isinstance(src.get(k), str) or not src.get(k).strip():
                errors.append((path, f'source_attribution.{k} missing/empty'))
    rs = d.get('revision_summary', {})
    if not isinstance(rs, dict):
        errors.append((path, 'revision_summary not dict'))
    else:
        for k in REQUIRED_RS:
            if k not in rs:
                errors.append((path, f'revision_summary missing {k}'))
        check_inline(rs.get('key_takeaway', {}), path + '.revision_summary.key_takeaway', errors)
        rs_bytes = len(json.dumps(rs, ensure_ascii=False).encode('utf-8'))
        if rs_bytes >= 16 * 1024:
            errors.append((path, f'revision_summary {rs_bytes} >= 16384'))
        for sec in (rs.get('sections') or []):
            if isinstance(sec, dict) and 'content' in sec:
                check_inline(sec.get('content', {}), path + '.revision_summary.section.content', errors)
    pls = d.get('placements', [])
    if not isinstance(pls, list):
        errors.append((path, 'placements not list'))
    else:
        for i, p in enumerate(pls):
            if not isinstance(p, dict):
                errors.append((path, f'placements[{i}] not dict'))
                continue
            for k in ('exam', 'subject', 'topic_slug'):
                if not isinstance(p.get(k), str) or not p.get(k):
                    errors.append((path, f'placements[{i}].{k}'))
            if p.get('subtopic_slug') is not None and not isinstance(p.get('subtopic_slug'), str):
                errors.append((path, f'placements[{i}].subtopic_slug'))
    dc = d.get('deep_context', {})
    if not isinstance(dc, dict):
        errors.append((path, 'deep_context not dict'))
    else:
        check_blocks(dc.get('blocks', []), path + '.deep_context.blocks', errors)
    return errors


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else 'data/concepts/*.json'
    paths = sorted(glob.glob(base))
    paths = [p for p in paths if not Path(p).name.startswith('audit-')]
    all_errors = []
    for p in paths:
        all_errors.extend(validate(p))
    print('files', len(paths))
    print('errors', len(all_errors))
    msgs = Counter(m for _, m in all_errors)
    for m, c in msgs.most_common(20):
        print(c, m)
    for e in all_errors[:40]:
        print(e[0], '=>', e[1])
    raise SystemExit(1 if all_errors else 0)


if __name__ == '__main__':
    main()
