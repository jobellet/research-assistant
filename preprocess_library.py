import os
import logging
from pathlib import Path
from ingest_module.ingestor import calculate_sha256
from extract_module.extractor import main as run_extraction

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def preprocess_google_drive(gdrive_path, library_repo_dir):
    """
    Scans Google Drive for PDFs, creates hash folders in the repo, 
    and extracts metadata/text WITHOUT computing embeddings.
    """
    gdrive_path = Path(gdrive_path)
    library_repo_dir = Path(library_repo_dir)
    
    if not gdrive_path.exists():
        logger.error(f"Google Drive path not found: {gdrive_path}")
        return

    logger.info(f"Scanning for papers in {gdrive_path}...")
    
    # 1. Hashing and Folder Creation
    count = 0
    for pdf in gdrive_path.glob("*.pdf"):
        try:
            file_hash = calculate_sha256(str(pdf))
            dest_dir = library_repo_dir / file_hash
            
            # Create the folder in the repo if it doesn't exist
            if not dest_dir.exists():
                dest_dir.mkdir(parents=True, exist_ok=True)
            
            # Move/Copy PDF to the hash folder if not already there
            dest_pdf = dest_dir / pdf.name
            if not dest_pdf.exists():
                import shutil
                # We copy instead of move to avoid breaking gdown --continue if it relies on source presence
                shutil.copy(str(pdf), str(dest_pdf))
                logger.debug(f"Copied {pdf.name} to {dest_dir.name}")
                count += 1
            
            # Link the filename in a small text file so extractor knows which PDF to read
            (dest_dir / "source_info.txt").write_text(f"filename: {pdf.name}")
        except Exception as e:
            logger.error(f"Error hashing {pdf.name}: {e}")

    logger.info(f"Prepared {count} new hash directories.")

    # 2. Metadata Extraction
    # We call the existing extractor main, but we don't run the indexer.
    # The extractor reads the PDFs from library folders and writes metadata.json
    # We set delete_pdf=True because we only want to keep the extracted text in the repo.
    logger.info("Starting metadata and text extraction...")
    try:
        run_extraction(library_dir=str(library_repo_dir), model="phi3", overwrite=False, delete_pdf=True, workers=4, skip_llm=False)
    except Exception as e:
        logger.warning(f"Metadata/text extraction skipped or failed: {e}. (Is the LLM worker running?)")
    
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
