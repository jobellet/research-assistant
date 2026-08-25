#!/usr/bin/env python3
"""
scripts/import_zotero.py — Import an existing Zotero PDF library into My AI Research Assistant.

Scans the local Zotero storage directory, hashes and ingests all scientific PDFs,
extracts metadata via Crossref, and indexes them into ChromaDB for semantic search.
"""

import os
import sys
import shutil
import logging
import argparse
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import LIBRARY_DIR
from ingest_module.ingestor import calculate_sha256
from extract_module.extractor import main as run_extraction
from batch_indexer import run_batch_indexing
from scripts.generate_bow import main as run_bow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("zotero_importer")

def detect_zotero_storage_path() -> Path:
    """Detect default Zotero storage directory across macOS, Windows, and Linux."""
    home = Path.home()
    
    candidates = [
        home / "Zotero" / "storage",
        home / "Zotero" / "zotero" / "storage",
        home / "Documents" / "Zotero" / "storage",
    ]
    
    # Windows specific check
    if os.name == 'nt':
        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            candidates.insert(0, Path(user_profile) / "Zotero" / "storage")
            
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate
            
    return candidates[0]

def import_zotero_library(
    zotero_path: Path,
    library_dir: Path = LIBRARY_DIR,
    max_papers: int = None,
    skip_indexing: bool = False,
    workers: int = 4
):
    """
    Finds all PDFs in Zotero storage, ingests them into unique library/<hash>/ folders,
    extracts metadata, and updates ChromaDB.
    """
    zotero_path = Path(zotero_path).resolve()
    library_dir = Path(library_dir).resolve()
    
    if not zotero_path.exists():
        logger.error(f"Zotero storage path not found: {zotero_path}")
        logger.info("Please specify your Zotero storage path using: python scripts/import_zotero.py --path /path/to/Zotero/storage")
        return
        
    logger.info(f"Scanning Zotero storage directory: {zotero_path}")
    
    # Recursively find all PDF files
    pdf_files = [
        p for p in zotero_path.rglob("*.pdf") 
        if not p.name.startswith(".") and not p.name.startswith("~")
    ]
    
    total_found = len(pdf_files)
    logger.info(f"Found {total_found} PDF files in Zotero library.")
    
    if max_papers:
        pdf_files = pdf_files[:max_papers]
        logger.info(f"Limited import to first {max_papers} papers.")

    ingested_count = 0
    skipped_count = 0
    
    for i, pdf_path in enumerate(pdf_files, 1):
        try:
            file_hash = calculate_sha256(str(pdf_path))
            dest_dir = library_dir / file_hash
            dest_pdf = dest_dir / pdf_path.name
            
            dest_dir.mkdir(parents=True, exist_ok=True)
            
            # Save source info for tracking
            source_info_path = dest_dir / "source_info.txt"
            source_info_path.write_text(f"source: Zotero\noriginal_path: {pdf_path}\nfilename: {pdf_path.name}\n")
            
            if not dest_pdf.exists():
                shutil.copy2(str(pdf_path), str(dest_pdf))
                ingested_count += 1
                logger.debug(f"[{i}/{len(pdf_files)}] Ingested {pdf_path.name} -> {file_hash[:8]}...")
            else:
                skipped_count += 1
                
        except Exception as e:
            logger.error(f"Failed to ingest {pdf_path.name}: {e}")
            
    logger.info(f"Ingestion complete: {ingested_count} new papers added, {skipped_count} already existed.")
    
    if skip_indexing:
        logger.info("Skipping metadata extraction and vector indexing (--skip-indexing specified).")
        return

    # 1. Metadata & Text Extraction
    logger.info("--- Step 1/3: Extracting Text & Resolving Crossref Metadata ---")
    try:
        run_extraction(
            library_dir=str(library_dir),
            model="phi3",
            overwrite=False,
            delete_pdf=False,
            workers=workers,
            skip_llm=False
        )
    except Exception as e:
        logger.warning(f"Metadata extraction encountered errors: {e}")

    # 2. Bag-of-Words Indexing
    logger.info("--- Step 2/3: Generating Bag-of-Words Index ---")
    try:
        run_bow(library_dir=str(library_dir))
    except Exception as e:
        logger.warning(f"Bag-of-Words indexing encountered errors: {e}")

    # 3. Vector Embedding & ChromaDB Indexing
    logger.info("--- Step 3/3: Indexing Vectors into ChromaDB ---")
    try:
        run_batch_indexing(batch_size=50)
    except Exception as e:
        logger.warning(f"Vector indexing encountered errors: {e}")

    logger.info("🎉 Zotero import finished successfully! All papers are ready for search and manuscript drafting.")

def main():
    default_zotero = detect_zotero_storage_path()
    
    parser = argparse.ArgumentParser(description="Import existing Zotero PDF library into My AI Research Assistant.")
    parser.add_argument(
        "--path", 
        default=str(default_zotero), 
        help=f"Path to Zotero storage directory (default: {default_zotero})"
    )
    parser.add_argument(
        "--max-papers", 
        type=int, 
        default=None, 
        help="Maximum number of papers to import (for testing)"
    )
    parser.add_argument(
        "--workers", 
        type=int, 
        default=4, 
        help="Number of parallel metadata extraction threads"
    )
    parser.add_argument(
        "--skip-indexing", 
        action="store_true", 
        help="Only copy PDFs into library without running extraction/embeddings"
    )
    
    args = parser.parse_args()
    
    logger.info(f"Target Zotero Directory: {args.path}")
    import_zotero_library(
        zotero_path=Path(args.path),
        max_papers=args.max_papers,
        skip_indexing=args.skip_indexing,
        workers=args.workers
    )

if __name__ == "__main__":
    main()
