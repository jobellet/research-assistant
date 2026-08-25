import hashlib
import os
import shutil
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def calculate_sha256(file_path: str) -> str:
    """Calculate the SHA-256 hash of a file."""
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            # Read the file in chunks to avoid memory issues with large files
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except FileNotFoundError:
        logger.error(f"File not found: {file_path}")
        raise
    except Exception as e:
        logger.error(f"Error calculating hash for {file_path}: {e}")
        raise

def process_file(file_path: str, library_dir: str) -> str:
    """
    Process a single file:
    1. Validate it is a PDF.
    2. Calculate SHA-256 hash.
    3. Create a unique directory at library/<hash>/.
    4. Move the file into that directory.
    """
    file_path = Path(file_path)
    library_dir = Path(library_dir)

    if not file_path.exists():
        logger.error(f"Source file does not exist: {file_path}")
        return None

    if not file_path.suffix.lower() == ".pdf":
        logger.warning(f"Skipping non-PDF file: {file_path}")
        return None

    try:
        file_hash = calculate_sha256(str(file_path))
        dest_dir = library_dir / file_hash
        dest_dir.mkdir(parents=True, exist_ok=True)

        dest_path = dest_dir / file_path.name
        
        # If the file already exists in the destination, shutil.move will overwrite it if it's on the same FS.
        # However, it's safer to handle explicitly if needed. 
        # For now, we move it, effectively "ingesting" it once.
        shutil.move(str(file_path), str(dest_path))
        logger.info(f"Successfully ingested: {file_path.name} -> {dest_path}")
        return file_hash
    except Exception as e:
        logger.error(f"Failed to ingest {file_path}: {e}")
        return None
