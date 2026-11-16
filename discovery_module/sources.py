"""Thin, rate-limit aware clients for public scholarly APIs.

Every function returns a list of *candidate* dicts with a common schema::

    {"title", "authors" (list[str]), "year" (str), "abstract", "doi",
     "arxiv_id", "venue", "url", "pdf_url", "citation_count", "source"}

Missing fields are empty strings / lists. No API key is needed; set
``S2_API_KEY`` (Semantic Scholar) or ``OPENALEX_API_KEY`` to get higher limits.
"""

from __future__ import annotations

import html
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

USER_AGENT = "research-assistant/1.0 (+https://github.com/jobellet/research-assistant)"
TIMEOUT = 30
ARXIV_ID_RE = re.compile(r"(?<![\d.])(\d{4}\.\d{4,5})(v\d+)?(?![\d])")
OLD_ARXIV_ID_RE = re.compile(r"\b([a-z\-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?\b")

_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT


def _get(url: str, params: Optional[dict] = None, headers: Optional[dict] = None,
         retries: int = 3, backoff: float = 3.0) -> Optional[requests.Response]:
    """GET with retry on 429/5xx; returns None when the service stays unavailable."""
    for attempt in range(retries):
        try:
            resp = _session.get(url, params=params, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as exc:
            logger.warning("Request to %s failed: %s", url, exc)
            resp = None
        if resp is not None and resp.status_code == 200:
            return resp
        if resp is not None and resp.status_code not in (429, 500, 502, 503, 504):
            logger.info("%s returned HTTP %s", url, resp.status_code)
            return None
        wait = backoff * (attempt + 1)
        if resp is not None and resp.headers.get("Retry-After", "").isdigit():
            wait = min(int(resp.headers["Retry-After"]), 30)
        if attempt < retries - 1:
            time.sleep(wait)
    logger.warning("Giving up on %s after %d attempts", url, retries)
    return None


def empty_candidate(source: str) -> Dict:
    return {"title": "", "authors": [], "year": "", "abstract": "", "doi": "",
            "arxiv_id": "", "venue": "", "url": "", "pdf_url": "",
            "citation_count": None, "source": source}


def normalize_arxiv_id(value: str) -> str:
    """Return a bare arXiv id ("2308.08708") from an id, URL or DOI, or ''."""
    if not value:
        return ""
    value = value.strip()
    m = re.search(r"10\.48550/arxiv\.(\S+)", value, re.I)
    if m:
        value = m.group(1)
    m = ARXIV_ID_RE.search(value)
    if m:
        return m.group(1)
    m = OLD_ARXIV_ID_RE.search(value)
    return m.group(1) if m else ""


def find_arxiv_id(text: str, filename: str = "") -> str:
    """Find an arXiv identifier in a filename or in the first page of a paper."""
    if filename:
        m = re.match(r"^(\d{4}\.\d{4,5})(v\d+)?", Path_stem(filename))
        if m:
            return m.group(1)
    head = (text or "")[:6000]
    m = re.search(r"arXiv:\s*(\d{4}\.\d{4,5})(v\d+)?", head, re.I)
    if m:
        return m.group(1)
    m = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", head, re.I)
    return m.group(1) if m else ""


def Path_stem(name: str) -> str:
    return os.path.splitext(os.path.basename(name))[0]


# ---------------------------------------------------------------------------
# arXiv
# ---------------------------------------------------------------------------

_ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def _parse_arxiv_feed(xml_text: str) -> List[Dict]:
    out = []
    root = ET.fromstring(xml_text)
    for e in root.findall("a:entry", _ATOM):
        c = empty_candidate("arxiv")
        abs_url = (e.findtext("a:id", default="", namespaces=_ATOM) or "").strip()
        c["arxiv_id"] = normalize_arxiv_id(abs_url)
        c["title"] = " ".join((e.findtext("a:title", default="", namespaces=_ATOM) or "").split())
        c["abstract"] = " ".join((e.findtext("a:summary", default="", namespaces=_ATOM) or "").split())
        c["authors"] = [a.findtext("a:name", default="", namespaces=_ATOM) for a in e.findall("a:author", _ATOM)]
        c["year"] = (e.findtext("a:published", default="", namespaces=_ATOM) or "")[:4]
        c["doi"] = (e.findtext("arxiv:doi", default="", namespaces=_ATOM) or "").strip()
        c["venue"] = (e.findtext("arxiv:journal_ref", default="", namespaces=_ATOM) or "arXiv").strip()
        c["url"] = f"https://arxiv.org/abs/{c['arxiv_id']}" if c["arxiv_id"] else abs_url
        c["pdf_url"] = f"https://arxiv.org/pdf/{c['arxiv_id']}" if c["arxiv_id"] else ""
        if c["title"]:
            out.append(c)
    return out


def arxiv_search(query: str, max_results: int = 20, sort_by: str = "relevance") -> List[Dict]:
    """Full-text search on arXiv. ``query`` may use arXiv syntax (ti:, abs:, au:, AND/OR)."""
    if not re.search(r"\b(ti|abs|au|all|cat):", query):
        terms = [t for t in re.findall(r"[\w\-]+", query) if len(t) > 2]
        query = " AND ".join(f"all:{t}" for t in terms) or query
    resp = _get("https://export.arxiv.org/api/query",
                params={"search_query": query, "max_results": max_results, "sortBy": sort_by},
                retries=3, backoff=5)
    if resp is None:
        return []
    try:
        return _parse_arxiv_feed(resp.text)
    except ET.ParseError as exc:
        logger.warning("Could not parse arXiv feed: %s", exc)
        return []


def arxiv_lookup(arxiv_id: str) -> Optional[Dict]:
    """Metadata for one arXiv id, read from the abstract page (robust to API rate limits)."""
    arxiv_id = normalize_arxiv_id(arxiv_id)
    if not arxiv_id:
        return None
    resp = _get(f"https://arxiv.org/abs/{arxiv_id}")
    if resp is None:
        return None
    page = resp.text

    def meta(name):
        return [html.unescape(v) for v in re.findall(rf'<meta name="{name}" content="([^"]*)"', page)]

    title = (meta("citation_title") or [""])[0]
    if not title:
        return None
    c = empty_candidate("arxiv")
    c["arxiv_id"] = arxiv_id
    c["title"] = " ".join(title.split())
    # citation_author is "Last, First"; store "First Last"
    c["authors"] = [" ".join(reversed([p.strip() for p in a.split(",", 1)])) if "," in a else a
                    for a in meta("citation_author")]
    c["year"] = ((meta("citation_date") or meta("citation_online_date") or [""])[0])[:4]
    c["abstract"] = " ".join((meta("citation_abstract") or [""])[0].split())
    c["doi"] = (meta("citation_doi") or [""])[0]
    c["venue"] = "arXiv"
    c["url"] = f"https://arxiv.org/abs/{arxiv_id}"
    c["pdf_url"] = (meta("citation_pdf_url") or [f"https://arxiv.org/pdf/{arxiv_id}"])[0]
    return c


# ---------------------------------------------------------------------------
# Semantic Scholar
# ---------------------------------------------------------------------------

S2_FIELDS = "title,year,authors,abstract,externalIds,venue,citationCount,openAccessPdf,url"


def _s2_headers() -> dict:
    key = os.getenv("S2_API_KEY")
    return {"x-api-key": key} if key else {}


def _from_s2(p: dict) -> Dict:
    c = empty_candidate("semantic_scholar")
    ext = p.get("externalIds") or {}
    c["title"] = p.get("title") or ""
    c["authors"] = [a.get("name", "") for a in p.get("authors") or []]
    c["year"] = str(p.get("year") or "")
    c["abstract"] = p.get("abstract") or ""
    c["doi"] = ext.get("DOI") or ""
    c["arxiv_id"] = ext.get("ArXiv") or ""
    c["venue"] = p.get("venue") or ""
    c["url"] = p.get("url") or ""
    c["pdf_url"] = ((p.get("openAccessPdf") or {}).get("url") or
                    (f"https://arxiv.org/pdf/{c['arxiv_id']}" if c["arxiv_id"] else ""))
    c["citation_count"] = p.get("citationCount")
    return c


def semantic_scholar_search(query: str, limit: int = 20, year: str = "") -> List[Dict]:
    params = {"query": query, "limit": limit, "fields": S2_FIELDS}
    if year:
        params["year"] = year
    resp = _get("https://api.semanticscholar.org/graph/v1/paper/search", params=params,
                headers=_s2_headers(), retries=4, backoff=4)
    if resp is None:
        return []
    return [_from_s2(p) for p in resp.json().get("data", []) if p.get("title")]


def s2_paper_ref(doi: str = "", arxiv_id: str = "") -> str:
    if arxiv_id:
        return f"arXiv:{normalize_arxiv_id(arxiv_id)}"
    if doi:
        return f"DOI:{doi}"
    return ""


def semantic_scholar_recommendations(doi: str = "", arxiv_id: str = "", limit: int = 20) -> List[Dict]:
    """Papers Semantic Scholar recommends as similar to one seed paper."""
    ref = s2_paper_ref(doi, arxiv_id)
    if not ref:
        return []
    resp = _get(f"https://api.semanticscholar.org/recommendations/v1/papers/forpaper/{ref}",
                params={"limit": limit, "fields": S2_FIELDS}, headers=_s2_headers(), retries=4, backoff=4)
    if resp is None:
        return []
    out = [_from_s2(p) for p in resp.json().get("recommendedPapers", []) if p.get("title")]
    for c in out:
        c["source"] = "semantic_scholar_recommendations"
    return out


def semantic_scholar_links(doi: str = "", arxiv_id: str = "", direction: str = "citations", limit: int = 50) -> List[Dict]:
    """Papers citing (``citations``) or cited by (``references``) a seed paper."""
    ref = s2_paper_ref(doi, arxiv_id)
    if not ref or direction not in ("citations", "references"):
        return []
    resp = _get(f"https://api.semanticscholar.org/graph/v1/paper/{ref}/{direction}",
                params={"limit": limit, "fields": S2_FIELDS}, headers=_s2_headers(), retries=4, backoff=4)
    if resp is None:
        return []
    key = "citingPaper" if direction == "citations" else "citedPaper"
    out = []
    for item in resp.json().get("data", []):
        p = item.get(key) or {}
        if p.get("title"):
            c = _from_s2(p)
            c["source"] = f"semantic_scholar_{direction}"
            out.append(c)
    return out


# ---------------------------------------------------------------------------
# OpenAlex
# ---------------------------------------------------------------------------

def _openalex_params(extra: dict) -> dict:
    key = os.getenv("OPENALEX_API_KEY")
    if key:
        extra["api_key"] = key
    return extra


def _abstract_from_index(inv: Optional[dict]) -> str:
    if not inv:
        return ""
    words = []
    for word, positions in inv.items():
        for pos in positions:
            words.append((pos, word))
    return " ".join(w for _, w in sorted(words))


def _from_openalex(w: dict) -> Dict:
    c = empty_candidate("openalex")
    c["title"] = w.get("display_name") or w.get("title") or ""
    c["authors"] = [(a.get("author") or {}).get("display_name", "") for a in w.get("authorships") or []]
    c["year"] = str(w.get("publication_year") or "")
    c["abstract"] = _abstract_from_index(w.get("abstract_inverted_index"))
    doi = (w.get("doi") or "").replace("https://doi.org/", "")
    c["arxiv_id"] = normalize_arxiv_id(doi) if "arxiv" in doi.lower() else ""
    for loc in w.get("locations") or []:
        if not c["arxiv_id"]:
            c["arxiv_id"] = normalize_arxiv_id(loc.get("landing_page_url") or "") if "arxiv.org" in (loc.get("landing_page_url") or "") else ""
    c["doi"] = doi
    src = ((w.get("primary_location") or {}).get("source") or {})
    c["venue"] = src.get("display_name") or ""
    c["url"] = w.get("id") or ""
    best = w.get("best_oa_location") or {}
    c["pdf_url"] = best.get("pdf_url") or (f"https://arxiv.org/pdf/{c['arxiv_id']}" if c["arxiv_id"] else "")
    c["citation_count"] = w.get("cited_by_count")
    c["openalex_id"] = (w.get("id") or "").rsplit("/", 1)[-1]
    c["related_works"] = [r.rsplit("/", 1)[-1] for r in w.get("related_works") or []]
    return c


def openalex_search(query: str, limit: int = 20, year: str = "") -> List[Dict]:
    params = {"search": query, "per-page": min(limit, 50)}
    if year:
        params["filter"] = f"publication_year:{year}"
    resp = _get("https://api.openalex.org/works", params=_openalex_params(params), retries=3, backoff=4)
    if resp is None:
        return []
    return [_from_openalex(w) for w in resp.json().get("results", []) if w.get("display_name")]


def openalex_lookup(doi: str = "", arxiv_id: str = "") -> Optional[Dict]:
    if arxiv_id and not doi:
        doi = f"10.48550/arXiv.{normalize_arxiv_id(arxiv_id)}"
    if not doi:
        return None
    resp = _get(f"https://api.openalex.org/works/doi:{doi}", params=_openalex_params({}), retries=3, backoff=4)
    return _from_openalex(resp.json()) if resp is not None else None


def openalex_related(doi: str = "", arxiv_id: str = "", limit: int = 20) -> List[Dict]:
    """OpenAlex 'related works' of a seed paper (concept + citation based)."""
    seed = openalex_lookup(doi, arxiv_id)
    if not seed or not seed.get("related_works"):
        return []
    ids = "|".join(seed["related_works"][:limit])
    resp = _get("https://api.openalex.org/works",
                params=_openalex_params({"filter": f"openalex:{ids}", "per-page": limit}), retries=3, backoff=4)
    if resp is None:
        return []
    out = [_from_openalex(w) for w in resp.json().get("results", [])]
    for c in out:
        c["source"] = "openalex_related"
    return out


# ---------------------------------------------------------------------------
# Crossref
# ---------------------------------------------------------------------------

def crossref_search(query: str, limit: int = 20) -> List[Dict]:
    resp = _get("https://api.crossref.org/works", params={"query": query, "rows": limit}, retries=2)
    if resp is None:
        return []
    out = []
    for item in resp.json().get("message", {}).get("items", []):
        c = empty_candidate("crossref")
        c["title"] = html.unescape((item.get("title") or [""])[0])
        c["authors"] = [f"{a.get('given', '')} {a.get('family', '')}".strip() for a in item.get("author", [])]
        parts = (item.get("issued") or {}).get("date-parts") or [[None]]
        c["year"] = str(parts[0][0] or "") if parts and parts[0] else ""
        c["abstract"] = re.sub(r"<[^>]+>", "", item.get("abstract") or "").strip()
        c["doi"] = item.get("DOI") or ""
        c["venue"] = html.unescape((item.get("container-title") or [""])[0])
        c["url"] = f"https://doi.org/{c['doi']}" if c["doi"] else ""
        c["citation_count"] = item.get("is-referenced-by-count")
        for link in item.get("link") or []:
            if link.get("content-type") == "application/pdf":
                c["pdf_url"] = link.get("URL", "")
                break
        if c["title"]:
            out.append(c)
    return out
