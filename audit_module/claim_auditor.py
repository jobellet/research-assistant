"""Ground manuscript claims in supplied analysis text.

This module is deliberately deterministic and local: it does not ask an LLM to
invent evidence.  It compares each substantive manuscript sentence with the
sentences from an analysis, result report, or other source text supplied by the
caller.  It is therefore useful as a *review queue*, not as proof that a claim
is true.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Set


_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "is", "it", "of", "on", "or", "that", "the", "this", "to", "was", "were",
    "with", "we", "our", "these", "those", "than", "then", "also", "not",
}
_NUMBER = re.compile(r"(?<![\w.])(?:\d+(?:,\d{3})*(?:\.\d+)?)(?:\s*%)?")


def _plain_text(text: str) -> str:
    """Remove the most common LaTeX markup while retaining its prose."""
    # Keep percentage values (``20%``) while discarding ordinary LaTeX comments.
    text = text.replace(r"\%", "PERCENTMARK")
    text = re.sub(r"(?<!\d)%.*$", "", text, flags=re.M)
    text = text.replace("PERCENTMARK", "%")
    text = re.sub(r"\\(?:cite|ref|label)\{[^}]*\}", "", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^]]*\])?", " ", text)
    return text.replace("{", " ").replace("}", " ")


def extract_sentences(text: str) -> List[str]:
    """Return non-empty, prose-like sentences from plain text or LaTeX."""
    cleaned = re.sub(r"\s+", " ", _plain_text(text)).strip()
    return [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", cleaned)
            if len(sentence.strip().split()) >= 3]


def _terms(text: str) -> Set[str]:
    return {
        word.lower() for word in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", text)
        if word.lower() not in _STOP_WORDS
    }


def _numbers(text: str) -> List[str]:
    return [match.group(0).replace(",", "").replace(" ", "")
            for match in _NUMBER.finditer(text)]


def _score(claim: str, evidence: str) -> float:
    claim_terms, evidence_terms = _terms(claim), _terms(evidence)
    if not claim_terms:
        return 0.0
    lexical = len(claim_terms & evidence_terms) / len(claim_terms)
    claim_numbers, evidence_numbers = set(_numbers(claim)), set(_numbers(evidence))
    numeric = 0.35 if claim_numbers and claim_numbers <= evidence_numbers else 0.0
    return min(1.0, lexical + numeric)


def audit_claims(manuscript: str, analysis: str, *, min_support_score: float = 0.45) -> Dict[str, Any]:
    """Compare substantive manuscript claims against the supplied analysis.

    A claim with numeric values is marked ``contradicted`` when its best
    contextually similar evidence sentence contains numbers but none of the
    claimed values.  Claims without sufficient textual evidence are marked
    ``needs_review``.  The result always includes the best evidence candidate
    so a reviewer can make the final judgement.

    Args:
        manuscript: Draft prose (LaTeX is accepted).
        analysis: Underlying analysis, results, notes, or source extract.
        min_support_score: Minimum deterministic lexical/numeric score for a
            sentence to be classified as supported.  Must be in ``[0, 1]``.
    """
    if not 0 <= min_support_score <= 1:
        raise ValueError("min_support_score must be between 0 and 1")

    evidence = extract_sentences(analysis)
    claims = extract_sentences(manuscript)
    results: List[Dict[str, Any]] = []
    for index, claim in enumerate(claims):
        # Short sentences without numbers are usually headings or transitions.
        if len(_terms(claim)) < 2 and not _numbers(claim):
            continue
        scored = [(position, candidate, _score(claim, candidate))
                  for position, candidate in enumerate(evidence)]
        best_position, best_evidence, best_score = max(
            scored, key=lambda item: item[2], default=(None, None, 0.0)
        )
        claim_numbers = set(_numbers(claim))
        evidence_numbers = set(_numbers(best_evidence or ""))
        absolute_claim = bool(re.search(r"\b(all|none|never|no)\b", claim, re.I))
        if claim_numbers and best_score >= 0.2 and evidence_numbers and not (claim_numbers & evidence_numbers):
            status = "contradicted"
        elif absolute_claim and best_score >= min_support_score and evidence_numbers:
            # Lexical overlap alone cannot substantiate an absolute statement.
            status = "needs_review"
        elif best_score >= min_support_score:
            status = "supported"
        else:
            status = "needs_review"
        results.append({
            "claim_index": index,
            "claim": claim,
            "status": status,
            "support_score": round(best_score, 3),
            "claimed_numbers": sorted(claim_numbers),
            "evidence_index": best_position,
            "evidence": best_evidence,
            "evidence_numbers": sorted(evidence_numbers),
        })

    status_counts = Counter(result["status"] for result in results)
    return {
        "claim_count": len(results),
        "evidence_sentence_count": len(evidence),
        "summary": {
            "supported": status_counts["supported"],
            "needs_review": status_counts["needs_review"],
            "contradicted": status_counts["contradicted"],
        },
        "claims": results,
        "disclaimer": (
            "This local lexical and numeric comparison prioritizes claims for human review; "
            "it does not establish scientific truth or replace source checking."
        ),
    }
