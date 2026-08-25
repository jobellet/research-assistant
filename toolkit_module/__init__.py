"""Toolkit Module for My AI Research Assistant.

Provides PDF comment extraction, DFG-style Gantt work schedule rendering,
figure page-consumption fitting, and page length metrics.
"""

from .pdf_comments import extract_pdf_comments
from .schedule_generator import generate_schedule_chart
from .figure_fit import calculate_figure_fit
from .measure_pages import measure_pages

__all__ = [
    "extract_pdf_comments",
    "generate_schedule_chart",
    "calculate_figure_fit",
    "measure_pages",
]
