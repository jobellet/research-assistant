#!/usr/bin/env python3
"""
Prose Auditor Module for My AI Research Assistant.
Flags formulaic AI connectives, empty negatives, voice imbalance, uniform sentence rhythm,
and mechanical errors (doubled words, double spaces, LaTeX leftovers, US spellings, one-off acronyms).
"""
from __future__ import annotations
import re
from collections import Counter
from typing import Dict, List, Any, Optional, Union, Tuple

# Formulaic connectives. Not wrong, but they cluster in machine-written text.
CONNECTIVES_PATTERN = r'\b(Moreover|Furthermore|Additionally|Importantly|Notably|Crucially|' \
                    r'Together, these|Taken together|In summary|Thus|Therefore|Consequently|Overall)\b'

# Empty negative clauses
EMPTY_NEGATIVES = [
    r'which requires no [^.,;]+',
    r'\bis not always [^.,;]+',
    r'\bis not imposed on [^.,;]+',
    r'\bare never treated as [^.,;]+',
    r'\bwill not have [^.,;]+',
    r'\bis not attributable to [^.,;]+',
    r'\bnot because I (assume|expect|claim)[^.,;]+',
]

FIRST_PERSON = {'I': r'\bI\b', 'my': r'\bmy\b', 'we': r'\bwe\b', 'our': r'\bour\b'}


def extract_sentences(text: str) -> List[str]:
    """Split text into sentence strings with > 3 words."""
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if len(s.split()) > 3]


def audit_prose(text: str, section: Optional[str] = None) -> Dict[str, Any]:
    """
    Perform comprehensive prose audit on input text string.

    Args:
        text: Input draft text.
        section: Optional section heading to restrict analysis (e.g. "2.3").

    Returns:
        Dict containing word count, sentence count, connectives, empty negatives,
        voice counts, sentence rhythm statistics, and mechanical defects.
    """
    if section:
        m = re.search(rf'{re.escape(section)}(.*?)(?=\n\s*\d+\.\d+\s|\Z)', text, re.S)
        if m:
            text = m.group(1)

    words = len(text.split())
    sents = extract_sentences(text)

    # 1. Connectives
    connectives_found = Counter(m.group(1) for m in re.finditer(CONNECTIVES_PATTERN, text))
    total_connectives = sum(connectives_found.values())
    per_1000 = (1000 * total_connectives / max(words, 1)) if words else 0.0

    # 2. Empty negatives
    empty_neg_hits = []
    for pat in EMPTY_NEGATIVES:
        for m in re.finditer(pat, text, re.I):
            s = re.sub(r'\s+', ' ', m.group(0))[:110]
            if s not in empty_neg_hits:
                empty_neg_hits.append(s)

    # 3. Voice
    voice_counts = {k: len(re.findall(pat, text)) for k, pat in FIRST_PERSON.items()}

    # 4. Rhythm
    rhythm = {
        "mean_words": 0.0,
        "std_dev": 0.0,
        "low_variance_warning": False,
        "longest_sentence_words": 0
    }
    if sents:
        lengths = [len(s.split()) for s in sents]
        mean = sum(lengths) / len(lengths)
        sd = (sum((x - mean) ** 2 for x in lengths) / len(lengths)) ** 0.5
        rhythm = {
            "mean_words": round(mean, 1),
            "std_dev": round(sd, 1),
            "low_variance_warning": bool(sd < mean * 0.45 and len(sents) >= 5),
            "longest_sentence_words": max(lengths)
        }

    # 5. Mechanical defects
    doubled_words = sorted({m.group(1) for line in text.split('\n')
                           for m in re.finditer(r'\b(\w+)[ \t]+\1\b', line, re.I)})
    double_spaces = len(re.findall(r'[a-z]\.  +[A-Z]', text))
    latex_leftovers = re.findall(r'\\[a-zA-Z]+|\{|\}', text)
    us_spellings = [w for w in ('optimiz', 'prioritiz', 'analyz', 'characteriz', 'summariz')
                   if re.search(w, text)]
    acronyms = re.findall(r'\b([A-Z]{2,6})\b', text)
    acronyms_once = [a for a, n in Counter(acronyms).items()
                     if n == 1 and a not in ('DFG', 'AI', 'DOI', 'MRI', 'PDF', 'URL', 'API')]

    return {
        "word_count": words,
        "sentence_count": len(sents),
        "connectives": {
            "counts": dict(connectives_found),
            "total": total_connectives,
            "per_1000_words": round(per_1000, 1)
        },
        "empty_negatives": empty_neg_hits,
        "voice": voice_counts,
        "sentence_rhythm": rhythm,
        "mechanical": {
            "doubled_words": doubled_words,
            "double_spaces": double_spaces,
            "latex_leftovers_count": len(latex_leftovers),
            "latex_leftovers_sample": latex_leftovers[:5],
            "us_spellings": us_spellings,
            "acronyms_used_once": acronyms_once[:10]
        }
    }


if __name__ == "__main__":
    sample_text = """
    Moreover, this project requires no special setup. Importantly, we analyze the data carefully.
    Furthermore, the results are not always predictable, but we expect strong progress.
    Thus, our findings will optimize the model.
    """
    res = audit_prose(sample_text)
    print(res)
