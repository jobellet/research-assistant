#!/usr/bin/env python3
"""
DocxKit Module for My AI Research Assistant.
Provides safe reading and editing of Word documents (.docx):
- Automatic timestamped backups before writing.
- Font override and graphic/image integrity validation.
- Paragraph manipulation, text search/replace across runs, bibliography detection.
"""
from __future__ import annotations
import copy
import os
import re
import shutil
import zipfile
from datetime import datetime
from typing import Dict, List, Any, Tuple, Optional

try:
    from docx import Document
    from docx.shared import Pt, Emu
    HAS_DOCX = True
except ImportError:
    HAS_DOCX = False

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def open_docx(path: str, backup: bool = True):
    """Open a .docx file, creating a timestamped backup first."""
    if not HAS_DOCX:
        raise ImportError("python-docx is not installed. Install with `pip install python-docx`.")
    if backup:
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        bak = f"{os.path.splitext(path)[0]}_BACKUP_{stamp}.docx"
        shutil.copy(path, bak)
    return Document(path)


def n_graphics(el) -> int:
    """Count drawing/pict graphic elements in XML."""
    return len(el.findall(f'.//{W}drawing')) + len(el.findall(f'.//{W}pict'))


def count_graphics(doc) -> int:
    """Total graphics count across all paragraphs."""
    return sum(n_graphics(p._element) for p in doc.paragraphs)


def count_font_overrides(doc, allowed_sizes: tuple = ()) -> int:
    """Runs setting an explicit font name or size."""
    n = 0
    for p in doc.paragraphs:
        for r in p.runs:
            if r.font.name is not None:
                n += 1
            elif r.font.size is not None and r.font.size not in allowed_sizes:
                n += 1
    return n


def compare_integrity(original_path: str, edited_doc, allowed_sizes: tuple = ()) -> Tuple[bool, str]:
    """Compare edited document against original template to verify font overrides didn't grow and graphics weren't lost."""
    o = Document(original_path)
    fo = count_font_overrides(o, allowed_sizes)
    fe = count_font_overrides(edited_doc, allowed_sizes)
    go, ge = count_graphics(o), count_graphics(edited_doc)
    msg = (f"integrity: font overrides {fo} -> {fe} (must not grow); "
           f"graphics {go} -> {ge} (must not shrink)")
    return (fe <= fo and ge >= go), msg


def save_docx(doc, path: str, template_path: Optional[str] = None, allowed_sizes: tuple = ()):
    """Save document after verifying integrity if template_path is provided."""
    if template_path:
        ok, msg = compare_integrity(template_path, doc, allowed_sizes)
        if not ok:
            raise RuntimeError(f"Integrity check failed: {msg}")
    doc.save(path)


def find_bibliography(doc, min_entries: int = 5, prefer: str = 'zotero') -> Tuple[List[int], Optional[int], Optional[int]]:
    """
    Locate numbered bibliography entry paragraphs.
    Returns (idx_list, lo_index, hi_index).
    """
    zot = [i for i, p in enumerate(doc.paragraphs)
           if p.style.name == 'Bibliography' and p.text.strip()]
    man = [i for i, p in enumerate(doc.paragraphs)
           if p.style.name != 'Bibliography' and re.match(r'^\d+\.\s', p.text.strip())
           and ('DOI' in p.text or 'doi:' in p.text or len(p.text) > 90)]

    idx = zot if (prefer == 'zotero' and len(zot) >= min_entries) else man
    if len(idx) < min_entries:
        idx = zot if len(zot) >= min_entries else man
    if len(idx) < min_entries:
        return [], None, None
    return idx, min(idx), max(idx)


def text_area_cm(doc, section: int = 0) -> Tuple[float, float]:
    """Return (width_cm, height_cm) of document text column area."""
    s = doc.sections[section]
    return (Emu(s.page_width - s.left_margin - s.right_margin).cm,
            Emu(s.page_height - s.top_margin - s.bottom_margin).cm)


def describe_docx(path: str) -> Dict[str, Any]:
    """
    Return a summary of document properties, font rules, graphics, and bibliography bounds.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    doc = Document(path)
    idx, lo, hi = find_bibliography(doc)
    x = zipfile.ZipFile(path).read('word/document.xml').decode('utf8')
    w, h = text_area_cm(doc)
    inline_g = x.count('<wp:inline')
    floating_g = x.count('<wp:anchor')

    return {
        "filename": os.path.basename(path),
        "paragraph_count": len(doc.paragraphs),
        "text_area_cm": f"{w:.2f} x {h:.2f}",
        "normal_style_font": getattr(doc.styles['Normal'].font, 'name', 'Default'),
        "normal_is_bold_by_default": '<w:b/>' in doc.styles['Normal'].element.xml,
        "graphics": {
            "total": count_graphics(doc),
            "inline": inline_g,
            "floating": floating_g
        },
        "font_overrides": count_font_overrides(doc),
        "bibliography": {
            "entries_count": len(idx),
            "lower_paragraph_index": lo,
            "upper_paragraph_index": hi
        }
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(describe_docx(sys.argv[1]))
    else:
        print("Provide a .docx path to describe.")
