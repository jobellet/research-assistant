#!/usr/bin/env python3
"""
Page Measurement Module for My AI Research Assistant.
Measures actual rendered document page count, section page distribution,
and identifies sparse pages (likely heavy figure/table areas).
"""
from __future__ import annotations
import os
import re
import shutil
import subprocess
import tempfile
from typing import Dict, List, Any, Optional


def to_pdf(docx_path: str, outdir: str) -> str:
    """Convert .docx file to PDF using LibreOffice headless."""
    soffice = shutil.which('soffice') or shutil.which('libreoffice')
    if not soffice:
        raise RuntimeError("LibreOffice ('soffice') is not installed or not found on PATH.")
    subprocess.run([soffice, '--headless', '--convert-to', 'pdf', '--outdir', outdir, docx_path],
                   check=True, capture_output=True, timeout=300)
    pdf_path = os.path.join(outdir, os.path.splitext(os.path.basename(docx_path))[0] + '.pdf')
    if not os.path.exists(pdf_path):
        raise RuntimeError("LibreOffice conversion produced no PDF file.")
    return pdf_path


def get_pdf_page_texts(pdf_path: str) -> List[str]:
    """Extract per-page text strings using pdftotext or PyMuPDF."""
    pdftotext = shutil.which('pdftotext')
    if pdftotext:
        txt = subprocess.run([pdftotext, '-layout', pdf_path, '-'],
                             capture_output=True, text=True, check=True).stdout
        return txt.split('\f')
    else:
        try:
            import fitz
            doc = fitz.open(pdf_path)
            pages = [page.get_text("text") for page in doc]
            doc.close()
            return pages
        except Exception:
            raise RuntimeError("Neither pdftotext nor PyMuPDF (fitz) is available to read PDF text.")


def measure_pages(
    path: str,
    limit: Optional[int] = None,
    heading_pattern: str = r'^[ \t]*\d+(?:\.\d+)*\.?[ \t]+[A-Z][^\n]{3,70}$'
) -> Dict[str, Any]:
    """
    Measure actual rendered page count, headings, and sparse pages for a .docx or .pdf file.

    Args:
        path: Path to .docx or .pdf file.
        limit: Optional page limit to compare against (e.g. 25 pages).
        heading_pattern: Regex matching section headings at line start.

    Returns:
        Dict with total pages, limit status, section start pages, and sparse page analysis.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")

    tmpdir = None
    try:
        if path.lower().endswith('.docx'):
            tmpdir = tempfile.mkdtemp()
            pdf_path = to_pdf(path, tmpdir)
        else:
            pdf_path = path

        pages = get_pdf_page_texts(pdf_path)
        non_empty = [p for p in pages if p.strip()]
        n_pages = len(non_empty)

        # Section start pages
        rx = re.compile(heading_pattern, re.M)
        marks = []
        for pi, ptxt in enumerate(pages, 1):
            for m in rx.finditer(ptxt):
                line = m.group(0).strip()
                if len(line) < 120 and not re.search(r'[;]|DOI|doi:|\bet al\b', line):
                    marks.append({"page": pi, "heading": line})

        sections = []
        if marks:
            prev = None
            for item in marks:
                pi, line = item["page"], item["heading"]
                if prev and prev["heading"] == line:
                    continue
                if prev:
                    sections.append({
                        "heading": prev["heading"],
                        "start_page": prev["page"],
                        "end_page": pi if pi > prev["page"] else prev["page"],
                        "page_span": max(1, pi - prev["page"])
                    })
                prev = {"page": pi, "heading": line}
            if prev:
                sections.append({
                    "heading": prev["heading"],
                    "start_page": prev["page"],
                    "end_page": n_pages,
                    "page_span": max(1, n_pages - prev["page"] + 1)
                })

        # Sparse pages analysis (likely figures/tables)
        lens = [(i + 1, len(p.split())) for i, p in enumerate(pages) if p.strip()]
        word_counts = [w for _, w in lens]
        median_words = sorted(word_counts)[len(word_counts) // 2] if word_counts else 0

        sparse_pages = [
            {"page": pi, "word_count": w, "median_word_count": median_words}
            for pi, w in lens if w < median_words * 0.6
        ]

        limit_status = None
        if limit:
            if n_pages > limit:
                limit_status = f"OVER by {n_pages - limit} page(s)"
            else:
                limit_status = f"UNDER limit with {limit - n_pages} page(s) to spare"

        return {
            "filename": os.path.basename(path),
            "total_pages": n_pages,
            "page_limit": limit,
            "limit_status": limit_status,
            "sections": sections,
            "median_words_per_page": median_words,
            "sparse_pages": sparse_pages
        }
    finally:
        if tmpdir and os.path.exists(tmpdir):
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(measure_pages(sys.argv[1]))
    else:
        print("Provide a .docx or .pdf path to measure pages.")
