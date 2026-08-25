#!/usr/bin/env python3
"""
Number Auditor Module for My AI Research Assistant.
Verifies consistency of quantities stated across paragraphs, checks grant timeline bounds,
audits simple additions/multiplications ($a + b = c$), and flags backwards numeric ranges.
"""
from __future__ import annotations
import re
from collections import defaultdict
from typing import Dict, List, Any, Union, Tuple

QUANTITIES = [
    ('sessions',   r'(\d+)[\s-]*(?:recording\s+)?sessions?\b'),
    ('days',       r'(\d+)[\s-]*day\b'),
    ('animals',    r'(\d+)\s+(?:macaques?|monkeys?|animals?)\b'),
    ('probes',     r'(\d+)\s+(?:Neuropixels?|probes?|shanks?)\b'),
    ('neurons',    r'([\d,]+)\s+(?:neurons?|units?|channels?)\b'),
    ('trials',     r'([\d,]+)\s+trials?\b'),
    ('months',     r'\bmonths?\s+(\d+)\b|\bmonth\s+(\d+)\b'),
    ('percent',    r'(\d+(?:\.\d+)?)\s*%'),
    ('years',      r'\b(\d+)[\s-]*year\b'),
]


def audit_numbers(text_or_paras: Union[str, List[str]], horizon: int = 36) -> Dict[str, Any]:
    """
    Audit text for numerical consistency, timeline bounds, arithmetic, and ranges.

    Args:
        text_or_paras: Plain text string or list of paragraph strings.
        horizon: Maximum grant duration in months (default 36).

    Returns:
        Dict containing quantity drift, timeline analysis, sum checks, and backwards ranges.
    """
    if isinstance(text_or_paras, str):
        paras = [(i, line.strip()) for i, line in enumerate(text_or_paras.split('\n')) if line.strip()]
    else:
        paras = [(i, p.strip()) for i, p in enumerate(text_or_paras) if p.strip()]

    # 1. Quantity agreement across paragraphs
    found = defaultdict(lambda: defaultdict(list))
    for i, t in paras:
        for name, pat in QUANTITIES:
            for m in re.finditer(pat, t, re.I):
                v = next(g for g in m.groups() if g)
                found[name][v.replace(',', '')].append(i)

    quantity_discrepancies = {}
    for name, vals in found.items():
        if len(vals) > 1:
            quantity_discrepancies[name] = [
                {"value": v, "count": len(ix), "first_paragraph": ix[0]}
                for v, ix in sorted(vals.items(), key=lambda kv: -len(kv[1]))
            ]

    # 2. Timeline vs horizon
    months = set()
    for i, t in paras:
        for m in re.finditer(r'\bmonths?\s+(\d+)(?:\s*[-–]\s*(\d+))?', t, re.I):
            for g in m.groups():
                if g:
                    months.add(int(g))

    timeline = {
        "horizon_months": horizon,
        "referenced_months": sorted(months),
        "overruns": sorted(m for m in months if m > horizon),
        "headroom_months": (horizon - max(months)) if months and max(months) <= horizon else 0
    }

    # 3. Sums & per-animal math
    sums_verified = []
    animal_math = []
    for i, t in paras:
        raw = [x.replace(',', '') for x in re.findall(r'\b\d[\d,]*(?:\.\d+)?\b', t)]
        nums = [float(x) for x in raw if x and x.replace('.', '', 1).isdigit()]
        if len(nums) >= 3:
            for j in range(len(nums) - 2):
                a, b, c = nums[j:j + 3]
                if c and abs(a + b - c) < 1e-6 and c > 2:
                    sums_verified.append({"paragraph": i, "equation": f"{a:g} + {b:g} = {c:g}"})

        m = re.search(r'(\d+)\s*(?:recording\s+)?sessions?\s+per\s+animal.*?(\d+)\s+animals?', t, re.I)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            animal_math.append({
                "paragraph": i,
                "sessions_per_animal": a,
                "animals": b,
                "total_sessions": a * b
            })

    # 4. Backwards ranges
    bad_ranges = []
    for i, t in paras:
        if not re.search(r'\b(doi|DOI|https?://|ISSN|arXiv)', t):
            for m in re.finditer(r'(?<![\d.\-/])(\d{1,3})\s*[-–]\s*(\d{1,3})(?![\d.\-/])', t):
                if int(m.group(1)) > int(m.group(2)):
                    bad_ranges.append({"paragraph": i, "range": m.group(0)})

    return {
        "paragraph_count": len(paras),
        "quantity_discrepancies": quantity_discrepancies,
        "timeline": timeline,
        "sums_verified": sums_verified,
        "animal_math": animal_math,
        "backwards_ranges": bad_ranges
    }


if __name__ == "__main__":
    sample_paras = [
        "We plan 12 sessions in total across 4 animals.",
        "Each animal undergoes 3 sessions per animal with 4 animals.",
        "In month 12 to 24 we record 100 neurons, whereas later we record 150 neurons.",
        "Project phases extend from month 1 to month 40."
    ]
    res = audit_numbers(sample_paras, horizon=36)
    print(res)
