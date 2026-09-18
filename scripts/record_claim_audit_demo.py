#!/usr/bin/env python3
"""Render a small animated GIF using real output from ``audit_claims``.

Run from the repository root:
    python scripts/record_claim_audit_demo.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from textwrap import wrap

from PIL import Image, ImageDraw, ImageFont

# Running a file in ``scripts/`` does not put the repository root on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_module import audit_claims


WIDTH, HEIGHT = 1200, 720
BACKGROUND = "#111827"
PANEL = "#1f2937"
TEXT = "#e5e7eb"
MUTED = "#9ca3af"
STATUS_COLOURS = {
    "supported": "#22c55e",
    "needs_review": "#f59e0b",
    "contradicted": "#ef4444",
}


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"
    return ImageFont.truetype(name, size)


def _draw_wrapped(draw: ImageDraw.ImageDraw, text: str, x: int, y: int, *, width: int,
                  font: ImageFont.FreeTypeFont, fill: str, line_height: int = 28) -> int:
    for line in wrap(text, width=width, break_long_words=False):
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return y


def _frame(report: dict, visible_claims: int) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((28, 24, WIDTH - 28, HEIGHT - 24), radius=18, fill=PANEL)
    draw.text((58, 54), "Research Assistant  /  Grounded Claim Audit", font=_font(28, True), fill=TEXT)
    draw.text((58, 98), "$ audit_claims(manuscript, analysis)", font=_font(19), fill="#93c5fd")
    draw.line((58, 132, WIDTH - 58, 132), fill="#374151", width=2)

    summary = report["summary"]
    x = 58
    for label in ("supported", "needs_review", "contradicted"):
        colour = STATUS_COLOURS[label]
        draw.rounded_rectangle((x, 151, x + 216, 193), radius=10, fill="#111827", outline=colour, width=2)
        draw.text((x + 14, 162), f"{label}: {summary[label]}", font=_font(16, True), fill=colour)
        x += 234

    y = 224
    for claim in report["claims"][:visible_claims]:
        colour = STATUS_COLOURS[claim["status"]]
        draw.rounded_rectangle((58, y, WIDTH - 58, y + 132), radius=10, fill="#111827")
        draw.text((76, y + 16), claim["status"].upper(), font=_font(16, True), fill=colour)
        y = _draw_wrapped(draw, claim["claim"], 254, y + 15, width=78, font=_font(17), fill=TEXT)
        evidence_y = y + 7
        draw.text((76, evidence_y), "evidence", font=_font(15, True), fill=MUTED)
        _draw_wrapped(draw, claim["evidence"] or "No matching analysis sentence.", 254, evidence_y,
                      width=78, font=_font(16), fill=MUTED, line_height=24)
        y = max(y + 81, evidence_y + 54) + 16

    draw.text((58, HEIGHT - 62), "Human review required — matching evidence is not a proof of scientific truth.",
              font=_font(15), fill=MUTED)
    return image


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the grounded-claim-audit GIF demo.")
    parser.add_argument("--output", type=Path, required=True,
                        help="Destination for the generated GIF (for example /tmp/claim-audit-demo.gif).")
    args = parser.parse_args()

    report = audit_claims(
        "The analysis recorded 120 neurons across 12 sessions. "
        "The intervention eliminated all adverse events. "
        "We recorded 15 sessions.",
        "The underlying analysis recorded 120 neurons across 12 sessions. "
        "3 adverse events occurred during the intervention.",
    )
    frames = [_frame(report, visible) for visible in (0, 1, 2, 3)]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(args.output, save_all=True, append_images=frames[1:], duration=[850, 1100, 1100, 2200], loop=0)
    print(f"Wrote {args.output} using {report['claim_count']} audited claims.")


if __name__ == "__main__":
    main()
