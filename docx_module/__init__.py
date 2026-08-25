"""Docx Module for My AI Research Assistant.

Provides safe Word document (.docx) reading/writing, backups, paragraph surgery,
font/graphics integrity enforcement, and Zotero field code migration.
"""

from .docxkit import open_docx, save_docx, describe_docx, find_bibliography
from .zotero_fields import build_ref_map, inject_zotero_fields

__all__ = [
    "open_docx",
    "save_docx",
    "describe_docx",
    "find_bibliography",
    "build_ref_map",
    "inject_zotero_fields",
]
