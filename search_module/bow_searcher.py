import json
import logging
from pathlib import Path

logger = logging.getLogger("bow_searcher")

class BowSearcher:
    def __init__(self, index_path="library/global_bow_index.json"):
        self.index_path = Path(index_path)
        self.index = {}
        self.load_index()

    def load_index(self):
        if not self.index_path.exists():
            logger.warning(f"BOW index not found at {self.index_path}")
            return
        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                self.index = json.load(f)
            logger.info(f"Loaded BOW index with {len(self.index)} terms.")
        except Exception as e:
            logger.error(f"Failed to load BOW index: {e}")

    def search(self, query, top_k=10):
        """
        Search for papers based on relative frequency of terms.
        Supports single or multiple terms.
        """
        if not self.index:
            return []

        search_terms = [q.lower().strip() for q in query.split()]
        paper_scores = {} # {hash: total_freq}

        for term in search_terms:
            if term in self.index:
                for entry in self.index[term]:
                    # Compact format is [hash, freq]
                    hash_id = entry[0]
                    freq = entry[1]
                    if hash_id not in paper_scores:
                        paper_scores[hash_id] = 0
                    paper_scores[hash_id] += freq

        if not paper_scores:
            return []

        # Sort by total relative frequency
        sorted_papers = sorted(paper_scores.items(), key=lambda x: x[1], reverse=True)
        
        results = []
        for hash_id, score in sorted_papers[:top_k]:
            results.append({
                "hash_id": hash_id,
                "score": round(score * 100, 4), # Score as percentage
                "method": "bow"
            })
            
        return results
