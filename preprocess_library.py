import os
import json
import logging
from pathlib import Path
from ingest_module.ingestor import calculate_sha256
from extract_module.extractor import main as run_extraction

# Configure logging to handle Unicode characters on Windows
import sys
# Set console output to UTF-8
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

from config import EXTERNAL_LIBRARY_PATH, LIBRARY_DIR, PROCESSED_REGISTRY_PATH, ensure_data_dirs

def _load_registry() -> dict:
    if PROCESSED_REGISTRY_PATH.exists():
        try:
            with open(PROCESSED_REGISTRY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load file registry: {e}. Starting fresh.")
    return {}

def _save_registry(registry: dict):
    try:
        PROCESSED_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(PROCESSED_REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save file registry: {e}")

def preprocess_google_drive(gdrive_path, library_repo_dir):
    """
    Scans Google Drive for PDFs, creates hash folders in the library directory, 
    and extracts metadata/text WITHOUT computing embeddings.
    
    Uses an O(1) file registry cache (mtime + size) to completely avoid re-hashing
    and re-processing files that have already been handled.
    """
    ensure_data_dirs()
    gdrive_path = Path(gdrive_path)
    library_repo_dir = Path(library_repo_dir)
    
    if not gdrive_path.exists():
        logger.error(f"Google Drive path not found: {gdrive_path}")
        return

    logger.info(f"Scanning for papers in {gdrive_path}...")
    registry = _load_registry()
    registry_updated = False
    
    # 1. Hashing and Folder Creation (Fast Check)
    count = 0
    total_scanned = 0
    skipped_cached = 0
    
    for pdf in gdrive_path.glob("*.pdf"):
        total_scanned += 1
        pdf_name = pdf.name
        
        try:
            stat = pdf.stat()
            mtime = stat.st_mtime
            size = stat.st_size
        except Exception as e:
            logger.warning(f"Could not stat {pdf_name}: {e}")
            continue

        # Fast Check: Has this exact file already been preprocessed?
        cached = registry.get(pdf_name)
        if cached and cached.get("mtime") == mtime and cached.get("size") == size:
            dest_hash = cached.get("hash")
            dest_dir = library_repo_dir / dest_hash if dest_hash else None
            if dest_dir and (dest_dir / "metadata.json").exists() and (dest_dir / "full_text.txt").exists():
                skipped_cached += 1
                continue

        # File is new or modified
        try:
            file_hash = calculate_sha256(str(pdf))
            dest_dir = library_repo_dir / file_hash
            dest_dir.mkdir(parents=True, exist_ok=True)
            
            # Copy PDF if not already there and metadata/text not yet complete
            dest_pdf = dest_dir / pdf.name
            has_complete_extracted_data = (dest_dir / "metadata.json").exists() and (dest_dir / "full_text.txt").exists()
            
            if not has_complete_extracted_data and not dest_pdf.exists():
                import shutil
                shutil.copy(str(pdf), str(dest_pdf))
                logger.debug(f"Copied {repr(pdf.name)} to {dest_dir.name}")
                count += 1
            
            # Link the filename in a small text file so extractor knows which PDF to read
            (dest_dir / "source_info.txt").write_text(f"filename: {pdf.name}", encoding="utf-8")
            
            # Update registry
            registry[pdf_name] = {
                "hash": file_hash,
                "mtime": mtime,
                "size": size,
                "preprocessed": has_complete_extracted_data
            }
            registry_updated = True
        except Exception as e:
            logger.error(f"Error hashing/preparing {repr(pdf.name)}: {e}")

    if registry_updated:
        _save_registry(registry)

    logger.info(f"Scan complete: {total_scanned} files scanned ({skipped_cached} cached & skipped, {count} new folders prepared).")

    # 2. Metadata Extraction
    # Run extraction only if new folders were prepared
    if count > 0:
        logger.info(f"Starting metadata and text extraction for {count} new papers...")
        try:
            run_extraction(library_dir=str(library_repo_dir), model="phi3", overwrite=False, delete_pdf=True, workers=4, skip_llm=False)
            
            # Mark processed in registry
            for pdf_name, info in registry.items():
                if not info.get("preprocessed"):
                    h = info.get("hash")
                    if h and (library_repo_dir / h / "metadata.json").exists():
                        info["preprocessed"] = True
                        registry_updated = True
            if registry_updated:
                _save_registry(registry)
        except Exception as e:
            logger.warning(f"Metadata/text extraction skipped or failed: {e}. (Is the LLM worker running?)")
    else:
        logger.info("No new papers to extract. Skipping extraction step.")
    
    logger.info("Preprocessing step finished.")

if __name__ == "__main__":
    from dotenv import load_dotenv
    # Find .env in the parent directory of this script
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(dotenv_path=env_path)

    # Use the project's config
    from config import EXTERNAL_LIBRARY_PATH, LIBRARY_DIR
    
    # EXTERNAL_LIBRARY_PATH already handles LOCAL_GDRIVE_PATH logic in config.py
    GDRIVE = EXTERNAL_LIBRARY_PATH
    REPO_LIBRARY = LIBRARY_DIR
    
    preprocess_google_drive(GDRIVE, REPO_LIBRARY)
