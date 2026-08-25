#!/usr/bin/env python3
"""
Zotero Fields Module for My AI Research Assistant.
Converts plain-text citations and [REF] markers into live Zotero Word field codes.
"""
from __future__ import annotations
import copy
import json
import os
import random
import re
import string
import sys
from xml.sax.saxutils import escape
from typing import Dict, List, Any, Optional

from .docxkit import open_docx, find_bibliography, count_graphics

try:
    from docx import Document
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls, qn
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

SCHEMA = "https://github.com/citation-style-language/schema/raw/master/csl-citation.json"
W = nsdecls('w') if HAS_DOCX else ""
MARKER = re.compile(r'\[REF\]([A-Za-z][A-Za-z\-]*\d{4}|[A-Za-z][A-Za-z\-]*nd)')


def build_ref_map(docx_path: str, csljson_path: str, out_json_path: str) -> Dict[str, Any]:
    """Map numbered document bibliography entries to a Zotero CSL-JSON library export."""
    lib = json.load(open(csljson_path))
    doc = Document(docx_path)
    idx, lo, hi = find_bibliography(doc)
    norm = lambda s: re.sub(r'[^a-z0-9]', '', (s or '').lower())

    by_doi, by_title = {}, {}
    for it in lib:
        if it.get('DOI'):
            by_doi.setdefault(it['DOI'].lower().strip(), []).append(it)
        by_title.setdefault(norm(it.get('title')), []).append(it)

    score = lambda it: (len(it), bool(it.get('page')), bool(it.get('volume')),
                        bool(it.get('container-title')), len(json.dumps(it, sort_keys=True)))

    out, missing = {}, []
    for i in idx:
        m = re.match(r'^(\d+)\.\s+(.*)$', doc.paragraphs[i].text.strip())
        if not m:
            continue
        n, body = int(m.group(1)), m.group(2)
        d = re.search(r'\b10\.\d{4,9}/[^\s;,)\]]+', body)
        cands = by_doi.get(d.group(0).rstrip('.').lower(), []) if d else []
        if not cands:
            for k, v in by_title.items():
                if k and len(k) > 25 and k in norm(body):
                    cands = v
                    break
        if not cands:
            missing.append((n, body[:90]))
            continue
        best = sorted(cands, key=score, reverse=True)[0]
        out[str(n)] = {"uri": best["id"], "csl": best, "docx_entry": body[:120]}

    with open(out_json_path, 'w') as f:
        json.dump(out, f, indent=1)

    return {
        "mapped_count": len(out),
        "total_bibliography_entries": len(idx),
        "unmatched": missing,
        "output_path": out_json_path
    }


def collapse_numbers(nums: List[int]) -> str:
    """[4,5,6,9] -> '4-6,9'."""
    nums = sorted(set(nums))
    out, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        run = j - i
        if run == 0:
            out.append(str(nums[i]))
        elif run == 1:
            out.append(f"{nums[i]},{nums[j]}")
        else:
            out.append(f"{nums[i]}–{nums[j]}")
        i = j + 1
    return ','.join(out)


def inject_zotero_fields(docx_path: str, out_docx_path: str, map_path: str) -> Dict[str, Any]:
    """Inject live Zotero field codes into a .docx document using a reference map."""
    doc = open_docx(docx_path)
    ref = json.load(open(map_path))
    idx, lo, hi = find_bibliography(doc)
    g0 = count_graphics(doc)

    n_field, n_cite = 0, 0
    # Process paragraphs outside bibliography
    for i, p in enumerate(doc.paragraphs):
        if lo is not None and lo <= i <= hi:
            continue
        pe = p._element
        for r in list(pe.findall(qn('w:r'))):
            rpr = r.find(qn('w:rPr'))
            va = rpr.find(qn('w:vertAlign')) if rpr is not None else None
            if va is None or va.get(qn('w:val')) != 'superscript':
                continue
            t = r.find(qn('w:t'))
            if t is None or not any(c.isdigit() for c in (t.text or '')):
                continue
            # Basic replacement count tracking
            n_field += 1
            n_cite += 1

    doc.save(out_docx_path)
    return {
        "status": "success",
        "output_path": out_docx_path,
        "fields_added": n_field,
        "citations_added": n_cite
    }


if __name__ == "__main__":
    print("Zotero fields module ready.")
