#!/usr/bin/env python3
"""
Work Schedule Generator Module for My AI Research Assistant.
Renders DFG-style Work Schedule Gantt tables (project phases over a continuous month timeline
and Aim x Semester task grid) as clean PNG images using matplotlib.
"""
from __future__ import annotations
import os
import json
from typing import Dict, Any, Optional

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

DEFAULT_CONFIG: Dict[str, Any] = {
    "title": "Work schedule",
    "months": 36,
    "cols": 6,                       # semesters
    "year_labels": ["1$^{st}$ year", "2$^{nd}$ year", "3$^{rd}$ year"],
    # (label, first month, last month, colour)
    "phases": [
        ["Preparation and commissioning",            1,  8,  "#9e9e9e"],
        ["Training to criterion",                    4,  9,  "#3d9bd6"],
        ["Surgery and recording series",             10, 12,  "#1f6f9f"],
        ["Data analysis & model comparison",         13, 24,  "#76b043"],
        ["Writing & manuscript release",             25, 36,  "#c0a060"],
    ],
    # (aim, task, marker A col, marker B col) - 1-indexed columns
    "rows": [
        ["1a", "Data preprocessing & curation",  1, 3],
        ["1b", "Feature representation analysis", 2, 4],
        ["2a", "Model training & validation",    3, 5],
        ["2b", "Ablation experiments",          4, 6],
        ["3a", "Drafting manuscript & release", 5, 6],
    ],
    "markers": ["M1", "M2"],
    "marker_colours": ["#3d9bd6", "#76b043"],
    "note": "All data collection is complete by month 24; the final 12 months are for analysis and publication.",
    "col_headers": ["Aim", "Task"],
}


def generate_schedule_chart(config: Optional[Dict[str, Any]] = None, output_path: str = "work_schedule.png") -> Dict[str, Any]:
    """
    Render a work schedule Gantt chart as a PNG image.

    Args:
        config: Configuration dictionary overriding DEFAULT_CONFIG.
        output_path: Path where PNG image will be saved.

    Returns:
        Dict with output_path, image dimensions (width, height), and aspect ratio.
    """
    c = dict(DEFAULT_CONFIG)
    if config:
        c.update(config)

    FS, RULE = 12, "#000000"
    X_L, X_AIM, X_TASK = 0.010, 0.055, 0.245
    X_G0, X_G1 = 0.430, 0.990
    ncol = c["cols"]
    COLW = (X_G1 - X_G0) / ncol
    HDR = 0.055

    rows, phases = c["rows"], c["phases"]
    NROW = len(rows) + len(phases)
    Y_YEAR_TOP = 0.945
    Y_SUB_TOP = Y_YEAR_TOP - HDR
    Y_BODY_TOP = Y_SUB_TOP - HDR
    Y_FLOOR = 0.075
    ROWH = (Y_BODY_TOP - Y_FLOOR) / NROW
    Y_PH_BOT = Y_BODY_TOP - len(phases) * ROWH
    Y_BOT = Y_PH_BOT - len(rows) * ROWH

    fig, ax = plt.subplots(figsize=(11.6, 0.75 + 0.30 * NROW))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')

    def hr(x0, x1, y, lw=0.9):
        ax.plot([x0, x1], [y, y], color=RULE, lw=lw, solid_capstyle='butt')

    def vr(x, y0, y1, lw=0.9):
        ax.plot([x, x], [y0, y1], color=RULE, lw=lw, solid_capstyle='butt')

    ax.text(X_L, 0.975, c["title"], fontsize=FS + 5, style='italic', ha='left', va='center')

    # Year header band
    cpy = max(1, ncol // len(c["year_labels"]))
    hr(X_G0, X_G1, Y_YEAR_TOP)
    for i, lbl in enumerate(c["year_labels"]):
        ax.text(X_G0 + (i * cpy + cpy / 2) * COLW, Y_YEAR_TOP - HDR / 2, lbl,
                fontsize=FS + 1, weight='bold', ha='center', va='center')
    hr(X_G0, X_G1, Y_SUB_TOP)

    # Sub-headers
    ax.text(X_AIM, Y_SUB_TOP - HDR / 2, c["col_headers"][0], fontsize=FS, style='italic', ha='center', va='center')
    ax.text(X_TASK, Y_SUB_TOP - HDR / 2, c["col_headers"][1], fontsize=FS, style='italic', ha='center', va='center')
    per = c["months"] // ncol
    for i in range(ncol):
        lo = 1 + per * i
        ax.text(X_G0 + (i + 0.5) * COLW, Y_SUB_TOP - HDR / 2,
                f"{lo} to {lo + per - 1}", fontsize=FS, style='italic', ha='center', va='center')
    hr(X_L, X_G1, Y_BODY_TOP)

    # Phases Gantt bars
    month_x = lambda mo: X_G0 + (mo / c["months"]) * (X_G1 - X_G0)
    for r, (label, m0, m1, col) in enumerate(phases):
        yc = Y_BODY_TOP - (r + 0.5) * ROWH
        ax.text(X_TASK, yc, label, fontsize=FS - 1.5, ha='center', va='center')
        x0, x1 = month_x(m0 - 1), month_x(m1)
        ax.add_patch(plt.Rectangle((x0, yc - ROWH * 0.26), x1 - x0, ROWH * 0.52,
                                   facecolor=col, edgecolor='none', alpha=0.92, zorder=3))
        hr(X_L, X_G1, Y_BODY_TOP - (r + 1) * ROWH, lw=0.55)
    hr(X_L, X_G1, Y_PH_BOT, lw=1.4)

    # Tasks and semester markers
    for r, row in enumerate(rows):
        aim, task, cols = row[0], row[1], row[2:]
        yc = Y_PH_BOT - (r + 0.5) * ROWH
        ax.text(X_AIM, yc, aim, fontsize=FS, style='italic', ha='center', va='center')
        ax.text(X_TASK, yc, task, fontsize=FS, ha='center', va='center')
        for k, cc in enumerate(cols):
            if cc and k < len(c["markers"]):
                ax.text(X_G0 + (cc - 0.5) * COLW, yc, c["markers"][k], fontsize=FS,
                        color=c["marker_colours"][k % len(c["marker_colours"])], ha='center', va='center')
        hr(X_L, X_G1, Y_PH_BOT - (r + 1) * ROWH, lw=0.7)

    # Vertical rules
    for i in range(ncol + 1):
        vr(X_G0 + i * COLW, Y_BOT, Y_YEAR_TOP if i % cpy == 0 else Y_SUB_TOP)

    if c.get("note"):
        ax.text(X_L, Y_BOT - 0.042, c["note"], fontsize=FS - 2.5, style='italic',
                color="#444444", ha='left', va='center')

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    fig.savefig(output_path, dpi=260, bbox_inches='tight', facecolor='white', pad_inches=0.06)
    plt.close(fig)

    width_px, height_px = 0, 0
    try:
        from PIL import Image
        with Image.open(output_path) as img:
            width_px, height_px = img.size
    except Exception:
        pass

    return {
        "output_path": output_path,
        "width_px": width_px,
        "height_px": height_px,
        "aspect_ratio": round(height_px / max(width_px, 1), 3) if width_px else 0.0
    }


if __name__ == "__main__":
    res = generate_schedule_chart(output_path="test_schedule.png")
    print("Schedule chart rendered:", res)
