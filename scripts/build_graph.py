#!/usr/bin/env python3
"""
scripts/build_graph.py — Standalone CLI to generate the knowledge graph cache.
Use this on a powerful machine to pre-compute the UMAP layout and citation links.
"""

import os
import sys
import argparse
import logging
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db_module.db_manager import DBManager
from graph_module.graph_builder import build_semantic_graph
from graph_module.citation_fetcher import build_citation_graph

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("graph_cli")

def main():
    parser = argparse.ArgumentParser(description="Generate Semantic Knowledge Graph Cache")
    parser.add_argument("--skip-citations", action="store_true", help="Skip fetching citations from Semantic Scholar")
    parser.add_argument("--force", action="store_true", help="Force rebuild even if cache is fresh")
    args = parser.parse_args()

    logger.info("Initializing Database Connection…")
    db_manager = DBManager()
    
    # 1. Build Semantic Graph (UMAP + Clustering)
    logger.info("--- Step 1: Semantic Mapping (UMAP) ---")
    try:
        build_semantic_graph(db_manager, force_rebuild=args.force)
        logger.info("✅ Semantic graph completed.")
    except Exception as e:
        logger.error(f"❌ Failed to build semantic graph: {e}")
        sys.exit(1)

    # 2. Build Citation Graph (Semantic Scholar API)
    if not args.skip_citations:
        logger.info("--- Step 2: Citation Network (Semantic Scholar) ---")
        try:
            build_citation_graph(db_manager, force_rebuild=args.force)
            logger.info("✅ Citation network completed.")
        except Exception as e:
            logger.error(f"❌ Failed to build citation network: {e}")
            # Don't exit here, semantic graph might still be useful
    else:
        logger.info("Skipping citation network as requested.")

    logger.info("--- DONE ---")
    logger.info("The graph cache files are saved in the './library/' folder.")
    logger.info("You can now commit and push these files to sync with other machines:")
    logger.info("  git add library/graph_cache.json library/citation_graph.json")
    logger.info("  git commit -m 'chore: update knowledge graph cache'")
    logger.info("  git push")

if __name__ == "__main__":
    main()
