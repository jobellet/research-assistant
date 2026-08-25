"""
graph_builder.py — Semantic knowledge graph construction.

Responsibilities:
- Pull all embeddings + metadata from ChromaDB
- Run UMAP to get 2D layout coordinates
- Detect communities (Louvain via networkx-community or HDBSCAN)
- Build k-NN semantic edge list
- Cache result to graph_cache.json
- Support dynamic focus: given paper_ids, return per-paper cosine distance to mean
"""

import json
import logging
import math
import time
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

CACHE_PATH = Path("./library/graph_cache.json")
CACHE_TTL_SECONDS = 3600 * 24  # Rebuild at most every 24 hours on server auto-start


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_is_fresh() -> bool:
    if not CACHE_PATH.exists():
        return False
    age = time.time() - CACHE_PATH.stat().st_mtime
    return age < CACHE_TTL_SECONDS


def _load_cache() -> Optional[dict]:
    try:
        with open(CACHE_PATH, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load graph cache: {e}")
        return None


def _save_cache(data: dict):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(data, f)
    logger.info(f"Graph cache saved → {CACHE_PATH}")


# ---------------------------------------------------------------------------
# Core graph builder
# ---------------------------------------------------------------------------

def build_semantic_graph(db_manager, k_neighbors: int = 10, force_rebuild: bool = False) -> dict:
    """
    Build or load a cached semantic graph.

    Returns a dict with:
        nodes: [{id, title, authors, year, x, y, cluster, degree}]
        edges: [{source, target, weight}]
        clusters: [{id, label, color, count}]
        stats: {n_nodes, n_edges, built_at}
    """
    if not force_rebuild and _cache_is_fresh():
        cached = _load_cache()
        if cached:
            logger.info("Returning cached graph.")
            return cached

    logger.info("Building semantic graph from ChromaDB embeddings…")

    # ------------------------------------------------------------------
    # 1. Pull all items from ChromaDB
    # ------------------------------------------------------------------
    collection = db_manager.collection
    try:
        all_ids = collection.get(include=[])["ids"]
        if not all_ids:
            return {"nodes": [], "edges": [], "clusters": [], "stats": {"n_nodes": 0, "n_edges": 0}}
        result = collection.get(ids=all_ids, include=["embeddings", "metadatas", "documents"])
    except Exception as e:
        logger.error(f"Failed to query ChromaDB: {e}")
        return {"nodes": [], "edges": [], "clusters": [], "stats": {"n_nodes": 0, "n_edges": 0}}

    ids = result.get("ids", [])
    embeddings = result.get("embeddings", [])
    metadatas = result.get("metadatas", [])
    documents = result.get("documents", [])

    if len(ids) == 0 or len(embeddings) == 0:
        logger.warning("ChromaDB returned no items.")
        return {"nodes": [], "edges": [], "clusters": [], "stats": {"n_nodes": 0, "n_edges": 0}}

    logger.info(f"Loaded {len(ids)} items from ChromaDB.")

    emb_matrix = np.array(embeddings, dtype=np.float32)
    n = len(ids)

    # ------------------------------------------------------------------
    # 2. UMAP 2D projection
    # ------------------------------------------------------------------
    logger.info("Running UMAP…")
    try:
        import umap
        reducer = umap.UMAP(
            n_components=2,
            n_neighbors=min(15, n - 1),
            min_dist=0.1,
            metric="cosine",
            random_state=42,
            low_memory=True,
        )
        coords_2d = reducer.fit_transform(emb_matrix)
    except Exception as e:
        logger.warning(f"UMAP failed ({e}), using PCA fallback.")
        from sklearn.decomposition import PCA
        pca = PCA(n_components=2)
        coords_2d = pca.fit_transform(emb_matrix)

    # Normalise to [-1, 1]
    for dim in range(2):
        col = coords_2d[:, dim]
        rng = col.max() - col.min()
        if rng > 0:
            coords_2d[:, dim] = 2 * (col - col.min()) / rng - 1

    # ------------------------------------------------------------------
    # 3. Community detection via HDBSCAN
    # ------------------------------------------------------------------
    logger.info("Detecting communities…")
    try:
        import hdbscan
        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=max(3, n // 40),
            min_samples=2,
            metric="euclidean",
        )
        labels = clusterer.fit_predict(coords_2d).tolist()
    except Exception as e:
        logger.warning(f"HDBSCAN failed ({e}), assigning single cluster.")
        labels = [0] * n

    unique_labels = sorted(set(l for l in labels if l >= 0))
    noise_label = -1

    # Assign noise points (label == -1) to nearest cluster by 2D distance
    for i, lbl in enumerate(labels):
        if lbl == noise_label and unique_labels:
            dists = [
                math.sqrt((coords_2d[i, 0] - coords_2d[j, 0]) ** 2 + (coords_2d[i, 1] - coords_2d[j, 1]) ** 2)
                for j in range(n) if labels[j] >= 0
            ]
            if dists:
                # find index of nearest non-noise point
                non_noise_indices = [j for j in range(n) if labels[j] >= 0]
                nearest = non_noise_indices[int(np.argmin(dists))]
                labels[i] = labels[nearest]

    unique_labels = sorted(set(labels))

    # Cluster colour palette (visually distinct)
    PALETTE = [
        "#6366f1", "#ec4899", "#14b8a6", "#f59e0b", "#10b981",
        "#3b82f6", "#ef4444", "#8b5cf6", "#06b6d4", "#f97316",
        "#84cc16", "#e11d48", "#0ea5e9", "#a855f7", "#22c55e",
        "#fb923c", "#38bdf8", "#c084fc", "#4ade80", "#fbbf24",
    ]

    cluster_color = {}
    for i, lbl in enumerate(unique_labels):
        cluster_color[lbl] = PALETTE[i % len(PALETTE)]

    # ------------------------------------------------------------------
    # 4. k-NN semantic edge list (cosine similarity)
    # ------------------------------------------------------------------
    logger.info(f"Building k={k_neighbors} nearest-neighbour edge list…")
    try:
        from sklearn.neighbors import NearestNeighbors
        nbrs = NearestNeighbors(n_neighbors=min(k_neighbors + 1, n), metric="cosine").fit(emb_matrix)
        distances, indices = nbrs.kneighbors(emb_matrix)
    except Exception as e:
        logger.error(f"k-NN failed: {e}")
        distances, indices = None, None

    edge_set = {}  # (min_id, max_id) → weight to avoid duplicates
    if distances is not None:
        for i in range(n):
            for rank in range(1, distances.shape[1]):  # skip self (rank 0)
                j = indices[i, rank]
                sim = float(1.0 - distances[i, rank])
                if sim < 0.3:
                    continue
                key = (min(ids[i], ids[j]), max(ids[i], ids[j]))
                if key not in edge_set or edge_set[key] < sim:
                    edge_set[key] = sim

    edges = [
        {"source": k[0], "target": k[1], "weight": round(v, 4)}
        for k, v in edge_set.items()
    ]

    # ------------------------------------------------------------------
    # 5. Compute node degree
    # ------------------------------------------------------------------
    degree = {id_: 0 for id_ in ids}
    for e in edges:
        degree[e["source"]] += 1
        degree[e["target"]] += 1

    # ------------------------------------------------------------------
    # 6. Assemble node list
    # ------------------------------------------------------------------
    nodes = []
    stats_authors = 0
    stats_year = 0
    stats_doi = 0
    stats_summary = 0
    
    for i, paper_id in enumerate(ids):
        meta = metadatas[i] or {}
        
        # Check presence of key attributes
        has_authors = bool(meta.get("authors"))
        has_year = bool(meta.get("year"))
        has_doi = bool(meta.get("doi") or meta.get("DOI"))
        # Summary comes from documents field in Chroma (usually full text or abstract)
        has_summary = bool(documents[i]) if documents else False
        
        if has_authors: stats_authors += 1
        if has_year: stats_year += 1
        if has_doi: stats_doi += 1
        if has_summary: stats_summary += 1

        nodes.append({
            "id": paper_id,
            "title": meta.get("title", "Untitled"),
            "authors": meta.get("authors", ""),
            "year": meta.get("year", ""),
            "doi": meta.get("doi") or meta.get("DOI", ""),
            "keywords": meta.get("keywords", ""),
            "x": round(float(coords_2d[i, 0]), 5),
            "y": round(float(coords_2d[i, 1]), 5),
            "cluster": labels[i],
            "cluster_color": cluster_color.get(labels[i], "#888"),
            "degree": degree[paper_id],
            "summary": (documents[i] or "")[:400] if documents else "",
            "pdf_filename": meta.get("pdf_filename", ""),
        })

    # ------------------------------------------------------------------
    # 7. Cluster metadata
    # ------------------------------------------------------------------
    cluster_counts = {}
    for lbl in labels:
        cluster_counts[lbl] = cluster_counts.get(lbl, 0) + 1

    clusters = [
        {
            "id": lbl,
            "color": cluster_color.get(lbl, "#888"),
            "count": cluster_counts[lbl],
            "label": f"Cluster {lbl}",
        }
        for lbl in unique_labels
    ]

    # ------------------------------------------------------------------
    # 8. Structural hole detection
    # ------------------------------------------------------------------
    gaps = _detect_structural_holes(nodes, edges, unique_labels, emb_matrix, ids)

    # ------------------------------------------------------------------
    # 9. Serialise & cache
    # ------------------------------------------------------------------
    graph = {
        "nodes": nodes,
        "edges": edges,
        "clusters": clusters,
        "gaps": gaps,
        "stats": {
            "n_nodes": len(nodes),
            "n_edges": len(edges),
            "n_clusters": len(unique_labels),
            "n_with_authors": stats_authors,
            "n_with_year": stats_year,
            "n_with_doi": stats_doi,
            "n_with_summary": stats_summary,
            "built_at": int(time.time()),
        },
    }
    _save_cache(graph)
    logger.info(f"Graph built: {len(nodes)} nodes, {len(edges)} edges, {len(unique_labels)} clusters.")
    return graph


def _detect_structural_holes(nodes, edges, unique_labels, emb_matrix, ids) -> list:
    """
    Detect cluster pairs that are semantically close but rarely cite each other.
    Since we may not have citation data at this stage, we use the heuristic:
    semantic edge density BETWEEN two clusters vs. WITHIN clusters.
    
    A structural hole = two clusters with high inter-cluster semantic similarity
    but LOW inter-cluster edge count relative to within-cluster edge count.
    """
    if len(unique_labels) < 2:
        return []

    id_to_idx = {id_: i for i, id_ in enumerate(ids)}
    node_cluster = {n["id"]: n["cluster"] for n in nodes}

    # Count edges within and between clusters
    within = {lbl: 0 for lbl in unique_labels}
    between = {}
    for e in edges:
        c1 = node_cluster.get(e["source"], -1)
        c2 = node_cluster.get(e["target"], -1)
        if c1 == c2:
            within[c1] = within.get(c1, 0) + 1
        else:
            key = (min(c1, c2), max(c1, c2))
            between[key] = between.get(key, 0) + 1

    # For each pair of clusters, compute mean semantic similarity
    # between their centroids using mean embedding
    cluster_to_indices = {lbl: [] for lbl in unique_labels}
    for i, node_id in enumerate(ids):
        lbl = node_cluster.get(node_id)
        if lbl is not None:
            cluster_to_indices[lbl].append(i)

    cluster_centroids = {}
    for lbl, indices in cluster_to_indices.items():
        if indices:
            cluster_centroids[lbl] = emb_matrix[indices].mean(axis=0)

    gaps = []
    lbl_list = list(unique_labels)
    for i in range(len(lbl_list)):
        for j in range(i + 1, len(lbl_list)):
            c1, c2 = lbl_list[i], lbl_list[j]
            if c1 not in cluster_centroids or c2 not in cluster_centroids:
                continue

            v1 = cluster_centroids[c1]
            v2 = cluster_centroids[c2]
            norm1 = np.linalg.norm(v1)
            norm2 = np.linalg.norm(v2)
            if norm1 == 0 or norm2 == 0:
                continue
            inter_sim = float(np.dot(v1, v2) / (norm1 * norm2))

            edge_key = (min(c1, c2), max(c1, c2))
            inter_edges = between.get(edge_key, 0)
            n1 = len(cluster_to_indices[c1])
            n2 = len(cluster_to_indices[c2])
            max_possible_inter = n1 * n2
            inter_density = inter_edges / max_possible_inter if max_possible_inter > 0 else 0

            within_density_1 = within.get(c1, 0) / max(n1 * (n1 - 1) / 2, 1)
            within_density_2 = within.get(c2, 0) / max(n2 * (n2 - 1) / 2, 1)
            avg_within_density = (within_density_1 + within_density_2) / 2

            # A structural hole: semantically similar clusters with sparse inter-connections
            if inter_sim > 0.55 and inter_density < avg_within_density * 0.3:
                gaps.append({
                    "cluster_a": c1,
                    "cluster_b": c2,
                    "semantic_similarity": round(inter_sim, 4),
                    "inter_edge_density": round(inter_density, 6),
                    "within_edge_density": round(avg_within_density, 6),
                    "gap_score": round(inter_sim * (1 - inter_density / max(avg_within_density, 0.001)), 4),
                })

    gaps.sort(key=lambda g: g["gap_score"], reverse=True)
    return gaps[:20]  # Top 20 gaps


# ---------------------------------------------------------------------------
# Dynamic focus: compute distances from mean of selected papers
# ---------------------------------------------------------------------------

def compute_focus_distances(paper_ids: list, db_manager) -> list:
    """
    Given a list of paper hash_ids, compute mean embedding and return
    all papers sorted by cosine distance to that mean.
    Returns [{id, distance, similarity}] sorted nearest-first.
    """
    if not paper_ids:
        return []

    try:
        # Get embeddings for selected papers
        selected = db_manager.collection.get(
            ids=paper_ids,
            include=["embeddings"]
        )
        sel_embs = selected.get("embeddings", [])
        if len(sel_embs) == 0:
            return []

        mean_emb = np.array(sel_embs, dtype=np.float32).mean(axis=0)

        # Get all embeddings
        db_all_ids = db_manager.collection.get(include=[])["ids"]
        if not db_all_ids:
            return []

        all_items = db_manager.collection.get(ids=db_all_ids, include=["embeddings"])
        all_ids = all_items.get("ids", [])
        all_embs = np.array(all_items.get("embeddings", []), dtype=np.float32)

        if len(all_ids) == 0:
            return []

        # Cosine similarity to mean
        mean_norm = np.linalg.norm(mean_emb)
        if mean_norm == 0:
            return []
        mean_unit = mean_emb / mean_norm

        norms = np.linalg.norm(all_embs, axis=1, keepdims=True)
        norms[norms == 0] = 1
        unit_embs = all_embs / norms
        similarities = unit_embs @ mean_unit  # shape: (n,)

        results = []
        for i, pid in enumerate(all_ids):
            sim = float(similarities[i])
            results.append({
                "id": pid,
                "similarity": round(sim, 4),
                "distance": round(1.0 - sim, 4),
            })

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results

    except Exception as e:
        logger.error(f"compute_focus_distances failed: {e}")
        return []
