#!/usr/bin/env python3
"""
Figure Fit Calculator Module for My AI Research Assistant.
Computes how much page area an image figure will occupy given text area dimensions (cm)
and image aspect ratio. Recommends maximum width fractions to stay within page budgets.
"""
from __future__ import annotations
import os
from typing import Dict, List, Any, Optional

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def calculate_figure_fit(
    image_paths: List[str],
    text_width_cm: float = 16.0,
    text_height_cm: float = 24.0,
    width_frac: float = 1.0,
    budget_page_frac: float = 0.25
) -> Dict[str, Any]:
    """
    Calculate page consumption for a list of figure images.

    Args:
        image_paths: List of file paths to figure images (PNG, JPG, etc.).
        text_width_cm: Text column width in cm (default 16.0).
        text_height_cm: Text column height in cm (default 24.0).
        width_frac: Target fraction of text width to render figure (default 1.0).
        budget_page_frac: Target max page height fraction per figure (default 0.25).

    Returns:
        Dict with text_area, figures list, and total_page_fraction.
    """
    figures_out = []
    total_page_frac = 0.0

    for img_path in image_paths:
        if not os.path.exists(img_path):
            figures_out.append({
                "filename": os.path.basename(img_path),
                "status": "missing"
            })
            continue

        if not HAS_PIL:
            figures_out.append({
                "filename": os.path.basename(img_path),
                "status": "error_pillow_missing"
            })
            continue

        try:
            with Image.open(img_path) as img:
                w_px, h_px = img.size
        except Exception as e:
            figures_out.append({
                "filename": os.path.basename(img_path),
                "status": f"error: {e}"
            })
            continue

        aspect = h_px / w_px
        w_cm = text_width_cm * width_frac
        h_cm = w_cm * aspect
        page_frac = h_cm / text_height_cm
        total_page_frac += page_frac

        # Max width fraction to keep under target page budget
        w_max_frac = min(1.0, (budget_page_frac * text_height_cm / aspect) / text_width_cm)

        figures_out.append({
            "filename": os.path.basename(img_path),
            "status": "ok",
            "dimensions_px": f"{w_px}x{h_px}",
            "rendered_width_cm": round(w_cm, 2),
            "rendered_height_cm": round(h_cm, 2),
            "page_fraction": round(page_frac, 3),
            "page_percent": f"{page_frac:.1%}",
            "recommended_max_width_fraction": round(w_max_frac, 3),
            "recommended_max_width_percent": f"{w_max_frac:.0%}"
        })

    return {
        "text_area_cm": f"{text_width_cm:.2f} x {text_height_cm:.2f}",
        "target_width_fraction": width_frac,
        "target_budget_page_fraction": budget_page_frac,
        "figures": figures_out,
        "total_page_area_consumed": round(total_page_frac, 3),
        "note": "Caption text lines add roughly 3-5% of additional page height per figure."
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(calculate_figure_fit(sys.argv[1:]))
    else:
        print("Provide image paths to calculate figure fit.")
