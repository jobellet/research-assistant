"""
citation_fetcher.py — Fetch citation links via Semantic Scholar API.

Strategy:
1. For each paper in the library that has a DOI, query Semantic Scholar
2. Get its references list (papers it cites)
3. Check if each referenced DOI is also in our local library
4. If yes → add a citation edge
5. Cache to citation_graph.json

Rate limit: Semantic Scholar public API ~100 req/5min (~1/3s). We use
batch requests to minimize round-trips.
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

import requests
from config import CITATION_GRAPH_PATH

logger = logging.getLogger(__name__)

CITATION_CACHE_PATH = CITATION_GRAPH_PATH
SS_BASE = "https://api.semanticscholar.org/v1"
SS_GRAPH = "https://api.semanticscholar.org/graph/v1"
REQUEST_DELAY = 0.35  # seconds between requests to respect rate limit


def _load_citation_cache() -> Optional[dict]:
    if not CITATION_CACHE_PATH.exists():
        return None
    try:
        with open(CITATION_CACHE_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return None


def _save_citation_cache(data: dict):
    CITATION_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CITATION_CACHE_PATH, "w") as f:
        json.dump(data, f)
    logger.info(f"Citation graph saved → {CITATION_CACHE_PATH}")


def _query_ss_paper(doi: str) -> Optional[dict]:
    """
    Query Semantic Scholar for a paper by DOI.
    Returns raw SS response or None on failure.
    """
    url = f"{SS_GRAPH}/paper/DOI:{doi}"
    params = {"fields": "references,title,year,authors,externalIds"}
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 404:
            logger.debug(f"DOI not found in SS: {doi}")
        else:
            logger.warning(f"SS API returned {resp.status_code} for DOI {doi}")
    except requests.exceptions.RequestException as e:
        logger.warning(f"SS request error for {doi}: {e}")
    return None


def build_citation_graph(db_manager, force_rebuild: bool = False) -> dict:
    """
    Build citation edge list using Semantic Scholar API.
    Only builds edges where BOTH papers exist in local library.

    Returns:
        {
            "edges": [{"source": hash_a, "target": hash_b, "type": "cites"}],
            "ss_coverage": float,
            "built_at": int
        }
    """
    if not force_rebuild:
        cached = _load_citation_cache()
        if cached:
            logger.info("Returning cached citation graph.")
            return cached

    logger.info("Building citation graph from Semantic Scholar API…")

    # Pull all metadata from ChromaDB
    db_all_ids = db_manager.collection.get(include=[])["ids"]
    if not db_all_ids:
        return {"nodes": [], "edges": [], "clusters": [], "stats": {}}

    result = db_manager.collection.get(ids=db_all_ids, include=["metadatas"])
    all_ids = result.get("ids", [])
    all_metas = result.get("metadatas", [])

    # Build local DOI → hash_id lookup
    doi_to_hash = {}
    hash_to_doi = {}
    for i, paper_id in enumerate(all_ids):
        meta = all_metas[i] or {}
        doi = (meta.get("doi") or meta.get("DOI") or "").strip().lower()
        if doi:
            doi_to_hash[doi] = paper_id
            hash_to_doi[paper_id] = doi

    doi_list = list(doi_to_hash.keys())
    logger.info(f"Found {len(doi_list)} papers with DOIs out of {len(all_ids)} total.")

    citation_edges = []
    found_count = 0

    for i, doi in enumerate(doi_list):
        source_hash = doi_to_hash[doi]
        logger.debug(f"Querying SS [{i+1}/{len(doi_list)}]: {doi}")

        ss_data = _query_ss_paper(doi)
        time.sleep(REQUEST_DELAY)

        if not ss_data:
            continue

        found_count += 1
        references = ss_data.get("references", []) or []

        for ref in references:
            ext_ids = ref.get("externalIds") or {}
            ref_doi = (ext_ids.get("DOI") or "").strip().lower()
            if not ref_doi:
                continue

            target_hash = doi_to_hash.get(ref_doi)
            if target_hash and target_hash != source_hash:
                citation_edges.append({
                    "source": source_hash,
                    "target": target_hash,
                    "type": "cites",
                })

    # Deduplicate
    seen = set()
    unique_edges = []
    for e in citation_edges:
        key = (e["source"], e["target"])
        if key not in seen:
            seen.add(key)
            unique_edges.append(e)

    ss_coverage = found_count / len(doi_list) if doi_list else 0.0

    result_data = {
        "edges": unique_edges,
        "n_doi_papers": len(doi_list),
        "ss_coverage": round(ss_coverage, 3),
        "built_at": int(time.time()),
    }
    _save_citation_cache(result_data)
    logger.info(
        f"Citation graph: {len(unique_edges)} edges, "
        f"SS coverage {ss_coverage:.1%} ({found_count}/{len(doi_list)} DOIs found)"
    )
    return result_data
