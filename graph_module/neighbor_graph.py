import json
import logging
from pathlib import Path
import numpy as np
from config import LIBRARY_DIR

logger = logging.getLogger("neighbor_graph")

def build_neighbor_graph_bow(hash_id, bow_searcher, db_manager, top_n=50):
    """
    Build a local graph of papers similar to the target hash_id based on Bag of Words.
    """
    # 1. Get the source paper's BOW
    source_bow_path = LIBRARY_DIR / hash_id / "bow.json"
    if not source_bow_path.exists():
        logger.error(f"BOW file not found for source: {hash_id}")
        return {"nodes": [], "edges": []}
    
    with open(source_bow_path, "r") as f:
        source_bow = json.load(f)
    
    # 2. Find neighbors using BowSearcher
    # We use the top words from the source paper as the query
    sorted_words = sorted(source_bow.items(), key=lambda x: x[1], reverse=True)
    query_terms = " ".join([w for w, f in sorted_words[:50]]) # top 50 words
    
    similar_papers = bow_searcher.search(query_terms, top_k=top_n + 1)
    
    # Filter out the source itself if it's there
    neighbor_hashes = [p["hash_id"] for p in similar_papers if p["hash_id"] != hash_id][:top_n]
    all_hashes = [hash_id] + neighbor_hashes
    
    # 3. Load metadata and full BOW for these papers
    nodes = []
    bow_vectors = {} # hash -> {word: freq}
    
    for h in all_hashes:
        # Metadata from ChromaDB
        res = db_manager.collection.get(ids=[h], include=["metadatas"])
        meta = res["metadatas"][0] if res and res["metadatas"] else {"title": "Unknown"}
        
        file_meta = {}
        meta_path = LIBRARY_DIR / h / "metadata.json"
        if meta_path.exists():
            try:
                file_meta = json.loads(meta_path.read_text())
            except Exception:
                file_meta = {}
        nodes.append({
            "id": h,
            "title": meta.get("title", "Unknown"),
            "authors": meta.get("authors", ""),
            "year": meta.get("year", ""),
            "doi": meta.get("doi", ""),
            "summary": file_meta.get("summary", ""),
            "pdf_filename": meta.get("pdf_filename", ""),
            "is_source": (h == hash_id)
        })
        
        # Load BOW for pairwise comparison
        b_path = LIBRARY_DIR / h / "bow.json"
        if b_path.exists():
            with open(b_path, "r") as f:
                bow_vectors[h] = json.load(f)
        else:
            bow_vectors[h] = {}

    # 4. Compute pairwise edges (Cosine similarity on BOW)
    edges = []
    for i in range(len(all_hashes)):
        for j in range(i + 1, len(all_hashes)):
            h1, h2 = all_hashes[i], all_hashes[j]
            v1, v2 = bow_vectors[h1], bow_vectors[h2]
            
            # Compute cosine similarity
            common_words = set(v1.keys()) & set(v2.keys())
            if not common_words:
                continue
                
            dot_product = sum(v1[w] * v2[w] for w in common_words)
            norm1 = np.sqrt(sum(f**2 for f in v1.values()))
            norm2 = np.sqrt(sum(f**2 for f in v2.values()))
            
            if norm1 > 0 and norm2 > 0:
                similarity = dot_product / (norm1 * norm2)
                if similarity > 0.05: # threshold
                    edges.append({
                        "source": h1,
                        "target": h2,
                        "weight": round(float(similarity), 4)
                    })

    edges = sparsify_edges(edges, k=5)
    return {
        "nodes": nodes,
        "edges": edges,
        "source_id": hash_id
    }


def sparsify_edges(edges, k=5):
    """Keep each paper's k strongest links and rescale weights to [0.3, 1].

    Word-overlap cosine similarities are small (median ~0.25), so with the
    graph page's default similarity threshold almost every edge was hidden and
    the layout fell apart. The raw value is kept in ``similarity``.
    """
    if not edges:
        return edges
    by_node = {}
    for i, e in enumerate(edges):
        by_node.setdefault(e["source"], []).append(i)
        by_node.setdefault(e["target"], []).append(i)
    keep = set()
    for idxs in by_node.values():
        keep.update(sorted(idxs, key=lambda i: edges[i]["weight"], reverse=True)[:k])
    kept = [dict(edges[i]) for i in sorted(keep)]
    lo = min(e["weight"] for e in kept)
    hi = max(e["weight"] for e in kept)
    for e in kept:
        e["similarity"] = e["weight"]
        e["weight"] = round(0.3 + 0.7 * ((e["weight"] - lo) / (hi - lo) if hi > lo else 1.0), 4)
    return kept
