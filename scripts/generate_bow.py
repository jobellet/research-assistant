"""Rebuild the word-frequency (BOW) index and TF-IDF keywords for the library.

The server's background processor does this automatically after new papers are
processed; run this script after importing papers by other means.

    python scripts/generate_bow.py [--library PATH] [--no-keywords] [--update-db]
"""
import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import BOW_INDEX_PATH, LIBRARY_DIR  # noqa: E402
from search_module.bow_builder import build_bow_index, process_text  # noqa: E402,F401

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("generate_bow")


def push_keywords_to_db(keywords_updated):
    """Copy regenerated keywords into ChromaDB metadata (no re-embedding needed)."""
    if not keywords_updated:
        return
    import chromadb
    from config import CHROMA_DB_PATH
    collection = chromadb.PersistentClient(path=CHROMA_DB_PATH).get_collection("research_library")
    existing = collection.get(ids=list(keywords_updated), include=["metadatas"])
    metas = []
    for doc_id, meta in zip(existing["ids"], existing["metadatas"]):
        meta = dict(meta or {})
        meta["keywords"] = ", ".join(keywords_updated[doc_id])
        metas.append(meta)
    if metas:
        collection.update(ids=existing["ids"], metadatas=metas)
    logger.info(f"Updated keywords of {len(metas)} papers in ChromaDB")


def main(library_dir=None, write_keywords=True, update_db=False):
    lib_path = Path(library_dir) if library_dir else LIBRARY_DIR
    if not lib_path.exists():
        logger.error(f"Library directory not found: {lib_path}")
        return None
    index_path = BOW_INDEX_PATH if not library_dir else lib_path / "global_bow_index.json"
    stats = build_bow_index(lib_path, index_path, write_keywords=write_keywords)
    logger.info(f"Indexed {stats['papers']} papers ({stats['terms']} terms) -> {index_path}")
    if update_db:
        push_keywords_to_db(stats.get("keywords_updated"))
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--library", default=None, help="Library directory (default: DATA_DIR/library)")
    parser.add_argument("--no-keywords", action="store_true", help="Do not write TF-IDF keywords to metadata.json")
    parser.add_argument("--update-db", action="store_true",
                        help="Also copy new keywords into ChromaDB (stop the server first)")
    args = parser.parse_args()
    os.chdir(Path(__file__).resolve().parent.parent)
    main(args.library, write_keywords=not args.no_keywords, update_db=args.update_db)
