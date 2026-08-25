#!/usr/bin/env python3
"""
PDF Comments Extractor Module for My AI Research Assistant.
Pulls reviewer comments out of a PDF document:
1. Real PDF annotation objects (Text, Highlight, Popup) via fitz/pypdf.
2. Comments Word baked into the page margin (recovered by text positioning).
"""
from __future__ import annotations
import os
import re
import subprocess
from typing import Dict, List, Any, Tuple, Optional


def extract_annotations_fitz(pdf_path: str) -> List[Dict[str, Any]]:
    """Extract native PDF annotations using PyMuPDF (fitz)."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return []

    annots = []
    doc = fitz.open(pdf_path)
    for page_num in range(len(doc)):
        page = doc[page_num]
        for annot in page.annots() or []:
            info = annot.info
            content = info.get("content", "").strip()
            title = info.get("title", "").strip()
            subj = info.get("subject", "").strip() or annot.type[1]
            if content:
                annots.append({
                    "page": page_num + 1,
                    "type": subj,
                    "author": title,
                    "text": content
                })
    doc.close()
    return annots


def extract_margin_text(pdf_path: str, split_frac: float = 0.68) -> List[str]:
    """
    Extract comments baked into the right margin using pdftotext or fitz positioning.
    Word writes 'Commented [XY1]:' at the head of each baked-in comment.
    """
    try:
        xml = subprocess.run(['pdftotext', '-bbox-layout', pdf_path, '-'],
                             capture_output=True, text=True, check=True).stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        # Fallback to PyMuPDF text block positioning if pdftotext unavailable
        try:
            import fitz
            doc = fitz.open(pdf_path)
            blocks_out = []
            for page in doc:
                page_w = page.rect.width
                cut = page_w * split_frac
                for b in page.get_text("blocks"):
                    # b: (x0, y0, x1, y1, "text", block_no, block_type)
                    if b[0] >= cut:
                        txt = b[4].strip()
                        if len(txt) > 2:
                            blocks_out.append(txt)
            doc.close()
            return blocks_out
        except Exception:
            return []

    lines = []
    for pm in re.finditer(r'<page width="([\d.]+)".*?>(.*?)</page>', xml, re.S):
        page_w = float(pm.group(1))
        cut = page_w * split_frac
        for lm in re.finditer(r'<line xMin="([\d.]+)"[^>]*>(.*?)</line>', pm.group(2), re.S):
            if float(lm.group(1)) < cut:
                continue
            words = re.findall(r'<word[^>]*>(.*?)</word>', lm.group(2))
            line = ' '.join(words).strip()
            if len(line) > 2:
                lines.append(line)

    head_pat = re.compile(r'^Comment(ed)?\s*\[[^\]]+\]\s*:?|^[A-Z][a-z]+ [A-Z]\w+\s*,')
    blocks, cur = [], []
    for line in lines:
        if head_pat.match(line) and cur:
            blocks.append(' '.join(cur))
            cur = [line]
        else:
            cur.append(line)
    if cur:
        blocks.append(' '.join(cur))
    return blocks


def extract_pdf_comments(pdf_path: str, split_frac: float = 0.68) -> Dict[str, Any]:
    """
    Extract native annotations and baked-in margin comments from PDF.

    Args:
        pdf_path: Path to PDF file.
        split_frac: X fraction where the comment margin starts (default 0.68).

    Returns:
        Dict with "annotations" list and "margin_comments" list.
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    annots = extract_annotations_fitz(pdf_path)
    margin = extract_margin_text(pdf_path, split_frac=split_frac)

    return {
        "pdf_filename": os.path.basename(pdf_path),
        "annotation_count": len(annots),
        "annotations": annots,
        "margin_comment_count": len(margin),
        "margin_comments": margin
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(extract_pdf_comments(sys.argv[1]))
    else:
        print("Provide a PDF path to extract comments.")
