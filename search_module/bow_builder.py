"""Build the bag-of-words (word frequency) index used by the 'Word Frequency'
search mode and the Quick Graph, and derive per-paper keywords (TF-IDF).

Used by the background processor after each batch of new papers and by
``scripts/generate_bow.py``.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

STOPWORDS = {
    'the', 'and', 'for', 'with', 'from', 'this', 'that', 'which', 'was', 'were',
    'been', 'have', 'has', 'are', 'not', 'but', 'also', 'their', 'they', 'our',
    'your', 'will', 'can', 'should', 'would', 'could', 'about', 'than', 'then',
    'them', 'these', 'those', 'such', 'into', 'only', 'other', 'some', 'more',
    'most', 'very', 'both', 'each', 'any', 'all', 'anywhere', 'another', 'while',
    'where', 'when', 'who', 'how', 'why', 'what', 'after', 'before', 'during',
    'between', 'under', 'over', 'through', 'above', 'below', 'once', 'here',
    'there', 'mean', 'means', 'using', 'used', 'use', 'study', 'research',
    'results', 'analysis', 'data', 'methods', 'method', 'paper', 'article',
    'system', 'based', 'approach', 'model', 'provide', 'shown', 'figure', 'table',
}

# Extra words that are frequent in papers but useless as keywords.
KEYWORD_STOPWORDS = STOPWORDS | {
    'however', 'therefore', 'thus', 'may', 'might', 'one', 'two', 'three', 'first',
    'second', 'new', 'work', 'well', 'many', 'much', 'different', 'example', 'see',
    'show', 'shows', 'given', 'within', 'without', 'whether', 'like', 'even', 'way',
    'make', 'made', 'take', 'number', 'case', 'cases', 'section', 'appendix', 'fig',
    'et', 'al', 'arxiv', 'preprint', 'doi', 'http', 'https', 'org', 'www', 'com',
    'pages', 'vol', 'proceedings', 'conference', 'journal', 'university', 'press',
    'author', 'authors', 'abstract', 'introduction', 'conclusion', 'references',
    'his', 'her', 'its', 'she', 'him', 'does', 'did', 'being', 'had', 'there',
    'because', 'since', 'still', 'just', 'rather', 'often', 'less', 'among',
    'models', 'systems', 'theory', 'theories', 'neural', 'large', 'learning',
    'issn', 'isbn', 'cogn', 'sci', 'proc', 'res', 'rev', 'lett', 'phys', 'trans', 'ieee', 'acm',
    'preprint', 'licence', 'license', 'copyright', 'creative', 'commons', 'elsevier', 'springer',
    'neurips', 'iclr', 'icml', 'nips', 'aaai', 'emnlp', 'acl', 'naacl', 'cvpr', 'openreview',
}

WORD_RE = re.compile(r"\b[a-z]{3,}\b")


def process_text(text: str) -> Dict[str, float]:
    """Relative term frequencies (stopwords removed, rare words pruned)."""
    words = WORD_RE.findall((text or "").lower())
    if not words:
        return {}
    filtered = [w for w in words if w not in STOPWORDS]
    if not filtered:
        return {}
    total = len(words)
    counts = Counter(filtered)
    return {w: round(c / total, 6) for w, c in counts.items() if c / total >= 0.0005 or c >= 2}


def _text_path(doc_dir: Path) -> Optional[Path]:
    for name in ("preprocessed_text.txt", "full_text.txt"):
        p = doc_dir / name
        if p.exists():
            return p
    return None


def _name_tokens(meta: dict) -> set:
    authors = meta.get("authors") or []
    if isinstance(authors, str):
        authors = authors.split(",")
    tokens = set()
    for a in authors:
        tokens.update(t.lower() for t in WORD_RE.findall(str(a).lower()))
    return tokens


def top_keywords(bow: Dict[str, float], df: Counter, n_docs: int, k: int = 5,
                 exclude: Optional[set] = None) -> list:
    """TF-IDF keywords. Words found in a single paper of a large library (often
    names, places or OCR noise) are down-weighted; author names are excluded."""
    exclude = exclude or set()
    scored = []
    for word, tf in bow.items():
        if word in KEYWORD_STOPWORDS or word in exclude or len(word) < 4:
            continue
        d = df.get(word, 1)
        if n_docs > 2 and d > 0.6 * n_docs:   # too common in this library
            continue
        weight = 0.35 if (d == 1 and n_docs >= 10) else 1.0
        scored.append((weight * tf * math.log((1 + n_docs) / d), word))
    scored.sort(reverse=True)
    return [w for _, w in scored[:k]]


def build_bow_index(library_dir: Path, index_path: Optional[Path] = None,
                    write_keywords: bool = True, max_per_word: int = 100) -> Dict:
    """(Re)build ``bow.json`` for every paper and the global inverted index.

    When ``write_keywords`` is true, papers whose metadata has no keywords (or
    keywords previously generated here) get TF-IDF keywords written to
    ``metadata.json`` (``keywords_source: "tfidf"``).

    Returns ``{"papers": n, "terms": n, "keywords_updated": {hash: [kw...]}}``.
    """
    library_dir = Path(library_dir)
    index_path = Path(index_path) if index_path else library_dir / "global_bow_index.json"
    bows: Dict[str, Dict[str, float]] = {}
    for doc_dir in sorted(p for p in library_dir.iterdir() if p.is_dir()):
        tp = _text_path(doc_dir)
        if not tp:
            continue
        try:
            bow = process_text(tp.read_text(encoding="utf-8", errors="ignore"))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("BOW failed for %s: %s", doc_dir.name, exc)
            continue
        if not bow:
            continue
        (doc_dir / "bow.json").write_text(json.dumps(bow))
        bows[doc_dir.name] = bow

    global_index: Dict[str, list] = {}
    for hash_id, bow in bows.items():
        for word, freq in bow.items():
            global_index.setdefault(word, []).append([hash_id, freq])
    for word, entries in global_index.items():
        entries.sort(key=lambda x: x[1], reverse=True)
        global_index[word] = entries[:max_per_word]

    index_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = index_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(global_index, separators=(",", ":")))
    tmp.replace(index_path)

    updated = {}
    if write_keywords and bows:
        df = Counter()
        for bow in bows.values():
            df.update(bow.keys())
        for hash_id, bow in bows.items():
            meta_path = library_dir / hash_id / "metadata.json"
            if not meta_path.exists():
                continue
            try:
                meta = json.loads(meta_path.read_text())
            except Exception:
                continue
            if meta.get("keywords") and meta.get("keywords_source") != "tfidf":
                continue
            kws = top_keywords(bow, df, len(bows), exclude=_name_tokens(meta))
            if kws and kws != meta.get("keywords"):
                meta["keywords"] = kws
                meta["keywords_source"] = "tfidf"
                meta_path.write_text(json.dumps(meta, indent=4))
                updated[hash_id] = kws

    logger.info("BOW index: %d papers, %d terms, %d keyword sets updated",
                len(bows), len(global_index), len(updated))
    return {"papers": len(bows), "terms": len(global_index), "keywords_updated": updated}
