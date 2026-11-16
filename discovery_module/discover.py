"""High-level literature discovery built on :mod:`discovery_module.sources`.

* :func:`search_literature` – one query, several databases, merged and ranked.
* :func:`related_to_paper`  – papers similar to one paper of the library.
* :func:`related_to_text`   – literature relevant to a paragraph of a draft.
* :func:`download_to_inbox` – fetch an open-access PDF into ``inbox/`` so the
  normal pipeline (ingest → metadata → embeddings → BOW → graph) picks it up.

Each result carries ``in_library`` / ``hash_id`` so the UI can tell what you
already have.
"""

from __future__ import annotations

import json
import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from discovery_module import sources as S
from search_module.bow_builder import KEYWORD_STOPWORDS, WORD_RE

logger = logging.getLogger(__name__)

SEARCHERS = {
    "arxiv": lambda q, n, year: S.arxiv_search(q, max_results=n),
    "semantic_scholar": lambda q, n, year: S.semantic_scholar_search(q, limit=n, year=year),
    "openalex": lambda q, n, year: S.openalex_search(q, limit=n, year=year),
    "crossref": lambda q, n, year: S.crossref_search(q, limit=n),
}
DEFAULT_SOURCES = ("arxiv", "openalex", "semantic_scholar")


def norm_title(title: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", (title or "").lower()).split())


def norm_doi(doi: str) -> str:
    return (doi or "").lower().replace("https://doi.org/", "").strip()


# ---------------------------------------------------------------------------
# Library index
# ---------------------------------------------------------------------------

def library_index(library_dir: Path) -> Dict[str, Dict[str, str]]:
    """Map DOIs, arXiv ids and normalised titles of the library to hash ids."""
    idx = {"doi": {}, "arxiv": {}, "title": {}, "meta": {}}
    library_dir = Path(library_dir)
    if not library_dir.exists():
        return idx
    for meta_path in library_dir.glob("*/metadata.json"):
        try:
            meta = json.loads(meta_path.read_text())
        except Exception:
            continue
        h = meta_path.parent.name
        idx["meta"][h] = meta
        if meta.get("doi"):
            idx["doi"][norm_doi(meta["doi"])] = h
            ax = S.normalize_arxiv_id(meta["doi"]) if "arxiv" in meta["doi"].lower() else ""
            if ax:
                idx["arxiv"][ax] = h
        ax = S.normalize_arxiv_id(meta.get("arxiv_id", "")) or S.find_arxiv_id("", meta.get("pdf_filename", ""))
        if ax:
            idx["arxiv"][ax] = h
        if meta.get("title"):
            idx["title"][norm_title(meta["title"])] = h
    return idx


def _match_library(c: Dict, idx: Dict) -> Optional[str]:
    if c.get("doi") and norm_doi(c["doi"]) in idx["doi"]:
        return idx["doi"][norm_doi(c["doi"])]
    ax = S.normalize_arxiv_id(c.get("arxiv_id", ""))
    if ax and ax in idx["arxiv"]:
        return idx["arxiv"][ax]
    t = norm_title(c.get("title", ""))
    return idx["title"].get(t) if t else None


# ---------------------------------------------------------------------------
# Merging / ranking
# ---------------------------------------------------------------------------

def _key(c: Dict) -> str:
    ax = S.normalize_arxiv_id(c.get("arxiv_id", ""))
    if ax:
        return f"arxiv:{ax}"
    doi = norm_doi(c.get("doi", ""))
    if doi:
        ax = S.normalize_arxiv_id(doi) if "arxiv" in doi else ""
        return f"arxiv:{ax}" if ax else f"doi:{doi}"
    return f"title:{norm_title(c.get('title', ''))[:120]}"


def merge_ranked(result_lists: Iterable[List[Dict]], k: int = 60) -> List[Dict]:
    """Deduplicate across sources and rank with reciprocal-rank fusion.

    A paper found by several databases gets a higher score; missing fields are
    filled from whichever source has them.
    """
    merged: Dict[str, Dict] = {}
    title_alias: Dict[str, str] = {}
    for results in result_lists:
        for rank, c in enumerate(results or []):
            if not c.get("title"):
                continue
            key = _key(c)
            t = norm_title(c["title"])[:120]
            key = title_alias.get(t, key)
            title_alias.setdefault(t, key)
            if key not in merged:
                m = dict(c)
                m["sources"] = [c.get("source", "")]
                m["score"] = 0.0
                merged[key] = m
            else:
                m = merged[key]
                for f, v in c.items():
                    if f in ("source", "score", "sources"):
                        continue
                    if v and not m.get(f):
                        m[f] = v
                if c.get("source") not in m["sources"]:
                    m["sources"].append(c.get("source", ""))
            merged[key]["score"] += 1.0 / (k + rank + 1)
    out = list(merged.values())
    for m in out:
        cc = m.get("citation_count") or 0
        m["score"] = round(m["score"] * 100 + 0.05 * math.log1p(cc), 4)
        m.pop("related_works", None)
    out.sort(key=lambda m: m["score"], reverse=True)
    return out


def _annotate(results: List[Dict], library_dir: Optional[Path]) -> List[Dict]:
    idx = library_index(library_dir) if library_dir else None
    for c in results:
        h = _match_library(c, idx) if idx else None
        c["in_library"] = bool(h)
        c["hash_id"] = h or ""
        c["downloadable"] = bool(c.get("pdf_url") or c.get("arxiv_id"))
    return results


def _run_parallel(jobs: Dict[str, callable]) -> Dict[str, List[Dict]]:
    out = {}
    with ThreadPoolExecutor(max_workers=max(1, len(jobs))) as pool:
        futures = {name: pool.submit(fn) for name, fn in jobs.items()}
        for name, fut in futures.items():
            try:
                out[name] = fut.result() or []
            except Exception as exc:
                logger.warning("Discovery source %s failed: %s", name, exc)
                out[name] = []
    return out


def search_literature(query: str, sources: Iterable[str] = DEFAULT_SOURCES, limit: int = 20,
                      year: str = "", library_dir: Optional[Path] = None) -> Dict:
    """Search several scholarly databases at once.

    Returns ``{"query", "results": [...], "per_source": {source: n_hits}}``.
    """
    sources = [s for s in sources if s in SEARCHERS] or list(DEFAULT_SOURCES)
    raw = _run_parallel({s: (lambda s=s: SEARCHERS[s](query, limit, year)) for s in sources})
    results = merge_ranked(raw.values())[:limit]
    return {"query": query, "results": _annotate(results, library_dir),
            "per_source": {s: len(v) for s, v in raw.items()}}


# ---------------------------------------------------------------------------
# Related papers
# ---------------------------------------------------------------------------

# Frequent English words that are poor search terms even when rare in the library.
GENERIC_WORDS = {
    "recent", "recently", "suggest", "suggests", "suggested", "maintain", "maintains", "behave",
    "behaves", "small", "large", "work", "works", "set", "sets", "find", "found", "findings",
    "propose", "proposed", "present", "presents", "argue", "argues", "show", "shows", "shown",
    "important", "several", "various", "provide", "provides", "allow", "allows", "remain",
    "remains", "become", "becomes", "approach", "approaches", "current", "currently", "first",
    "whether", "often", "known", "need", "needs", "including", "include", "includes", "possible",
    "able", "high", "higher", "low", "lower", "level", "levels", "kind", "kinds", "like",
    "makes", "making", "seem", "seems", "evidence", "question", "questions", "role", "roles",
}


def extract_query_terms(text: str, n: int = 6, bow_index: Optional[dict] = None,
                        n_docs: int = 0) -> List[str]:
    """Pick the most distinctive words of a text (TF-IDF against the library BOW index when given)."""
    words = [w for w in WORD_RE.findall((text or "").lower())
             if w not in KEYWORD_STOPWORDS and w not in GENERIC_WORDS and len(w) > 3]
    if not words:
        return []
    counts = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1
    def score(w):
        tf = counts[w]
        if bow_index and n_docs:
            df = len(bow_index.get(w, [])) or 1
            return tf * math.log((1 + n_docs) / df)
        return tf
    return sorted(counts, key=lambda w: (score(w), len(w)), reverse=True)[:n]


def arxiv_terms_search(terms: List[str], limit: int) -> List[Dict]:
    """arXiv search requiring the 3 best terms, relaxed to 2 if nothing matches."""
    for n in (3, 2):
        if len(terms) >= n:
            hits = S.arxiv_search(" AND ".join(f"abs:{t}" for t in terms[:n]), max_results=limit)
            if hits:
                return hits
    return S.arxiv_search(" ".join(terms[:1]), max_results=limit) if terms else []


def related_to_text(text: str, sources: Iterable[str] = ("arxiv", "openalex", "semantic_scholar"),
                    limit: int = 15, library_dir: Optional[Path] = None,
                    bow_index: Optional[dict] = None) -> Dict:
    """Find literature for a paragraph of a draft (e.g. the highlighted text)."""
    n_docs = 0
    if bow_index:
        n_docs = len({h for entries in bow_index.values() for h, _ in entries})
    terms = extract_query_terms(text, bow_index=bow_index, n_docs=n_docs)
    if not terms:
        return {"query": "", "terms": [], "results": [], "per_source": {}}
    # Semantic Scholar / OpenAlex handle natural language; arXiv gets the key terms.
    natural = " ".join((text or "").split()[:40])
    jobs = {}
    sources = list(sources)
    if "arxiv" in sources:
        jobs["arxiv"] = lambda: arxiv_terms_search(terms, limit)
    if "semantic_scholar" in sources:
        jobs["semantic_scholar"] = lambda: S.semantic_scholar_search(" ".join(terms), limit=limit)
    if "openalex" in sources:
        jobs["openalex"] = lambda: S.openalex_search(natural, limit=limit)
    if "crossref" in sources:
        jobs["crossref"] = lambda: S.crossref_search(natural, limit=limit)
    raw = _run_parallel(jobs)
    results = merge_ranked(raw.values())[:limit]
    return {"query": " ".join(terms), "terms": terms, "results": _annotate(results, library_dir),
            "per_source": {s: len(v) for s, v in raw.items()}}


def related_to_paper(seed: Dict, limit: int = 20, library_dir: Optional[Path] = None,
                     include_citations: bool = True) -> Dict:
    """Papers related to one seed paper (``{"title", "doi", "arxiv_id"}``).

    Combines Semantic Scholar recommendations, OpenAlex related works, papers
    citing the seed, and a title search on arXiv (works even when the other
    APIs are rate limited).
    """
    doi = norm_doi(seed.get("doi", ""))
    ax = S.normalize_arxiv_id(seed.get("arxiv_id", "")) or (S.normalize_arxiv_id(doi) if "arxiv" in doi else "")
    title = seed.get("title", "")
    jobs = {
        "s2_recommendations": lambda: S.semantic_scholar_recommendations(doi=doi, arxiv_id=ax, limit=limit),
        "openalex_related": lambda: S.openalex_related(doi=doi, arxiv_id=ax, limit=limit),
    }
    if include_citations:
        jobs["s2_citations"] = lambda: S.semantic_scholar_links(doi=doi, arxiv_id=ax, direction="citations", limit=limit)
    if title:
        terms = extract_query_terms(title + " " + " ".join(seed.get("keywords") or []), n=5)
        if terms:
            jobs["arxiv_title"] = lambda: arxiv_terms_search(terms, limit)
    raw = _run_parallel(jobs)
    seed_keys = {f"arxiv:{ax}"} if ax else set()
    if doi:
        seed_keys.add(f"doi:{doi}")
    results = [r for r in merge_ranked(raw.values())
               if _key(r) not in seed_keys and norm_title(r.get("title")) != norm_title(title)][:limit]
    return {"seed": {"title": title, "doi": doi, "arxiv_id": ax},
            "results": _annotate(results, library_dir),
            "per_source": {s: len(v) for s, v in raw.items()}}


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _safe_filename(c: Dict) -> str:
    ax = S.normalize_arxiv_id(c.get("arxiv_id", ""))
    if ax:
        return ax.replace("/", "_") + ".pdf"
    base = re.sub(r"[^A-Za-z0-9]+", "_", c.get("title") or c.get("doi") or "paper").strip("_")[:80]
    return (base or "paper") + ".pdf"


def resolve_identifier(identifier: str) -> Optional[Dict]:
    """Turn an arXiv id / arXiv URL / DOI into a candidate with a PDF URL."""
    identifier = (identifier or "").strip()
    ax = S.normalize_arxiv_id(identifier)
    if ax and ("arxiv" in identifier.lower() or re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?", identifier)):
        return S.arxiv_lookup(ax) or {**S.empty_candidate("arxiv"), "arxiv_id": ax,
                                      "pdf_url": f"https://arxiv.org/pdf/{ax}", "title": ax}
    doi = norm_doi(identifier)
    if doi.startswith("10."):
        c = S.openalex_lookup(doi=doi)
        if c:
            return c
        return {**S.empty_candidate("doi"), "doi": doi, "title": doi}
    return None


def download_to_inbox(candidate: Dict, inbox_dir: Path, library_dir: Optional[Path] = None) -> Dict:
    """Download the candidate's open-access PDF into ``inbox_dir``.

    Returns ``{"status": "downloaded"|"exists"|"in_library"|"no_pdf"|"failed", ...}``.
    """
    inbox_dir = Path(inbox_dir)
    if library_dir:
        h = _match_library(candidate, library_index(library_dir))
        if h:
            return {"status": "in_library", "hash_id": h, "title": candidate.get("title", "")}
    url = candidate.get("pdf_url") or ""
    ax = S.normalize_arxiv_id(candidate.get("arxiv_id", ""))
    if not url and ax:
        url = f"https://arxiv.org/pdf/{ax}"
    if not url:
        return {"status": "no_pdf", "title": candidate.get("title", ""),
                "message": "No open-access PDF known for this paper."}
    inbox_dir.mkdir(parents=True, exist_ok=True)
    target = inbox_dir / _safe_filename(candidate)
    if target.exists():
        return {"status": "exists", "path": str(target), "title": candidate.get("title", "")}
    resp = S._get(url, retries=2)
    if resp is None or not resp.content.startswith(b"%PDF"):
        return {"status": "failed", "url": url, "title": candidate.get("title", ""),
                "message": "The server did not return a PDF (paywall or rate limit?)."}
    tmp = target.with_suffix(".part")
    tmp.write_bytes(resp.content)
    tmp.replace(target)
    return {"status": "downloaded", "path": str(target), "bytes": len(resp.content),
            "title": candidate.get("title", "")}
